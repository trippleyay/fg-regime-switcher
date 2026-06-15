"""
backtester.py
-------------
4H event-loop backtester for the Fear & Greed Regime Switcher.

Flow per 4H bar:
  1. Merge daily F&G value onto current bar (forward-fill from daily)
  2. Detect regime -> allow_long, size_multiplier, tighten_trail
  3. Update trail stops on open positions
  4. Check exits on open positions
  5. Collect entry signals across all tokens
  6. Rank by momentum_score, fill open slots up to max_positions
  7. Record equity

Outputs:
  - outputs/report.md   (performance summary)
  - outputs/spec.json   (strategy specification)
  - outputs/trades.csv  (full trade log)
  - outputs/equity.csv  (equity curve by bar)
"""

import os
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from regime_detector import detect_regime
from strategy_selector import (
    add_indicators, entry_signal, exit_signal,
    update_trail_stop, rank_candidates, STRATEGY_SPEC,
)


# ── Constants ──────────────────────────────────────────────────────────────────

SYMBOLS       = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "CAKEUSDT"]
MAX_POSITIONS = 2
STARTING_CAP  = 10_000.0
OUTPUT_DIR    = os.path.join(os.path.dirname(__file__), "outputs")

START_DATE = "2020-01-01"
END_DATE   = "2025-06-01"


# ── Data loading ───────────────────────────────────────────────────────────────

def load_ohlcv(symbol: str, start: str, end: str) -> pd.DataFrame:
    """
    Fetch 4H OHLCV from Binance, indexed by full UTC datetime (not date).

    binance_client.fetch_ohlcv returns a 'date' col derived from open_time
    via .dt.date — which loses the time component and causes index collisions
    on sub-daily intervals. We bypass that by calling the Binance API directly
    with the same pagination logic, preserving the full open_time timestamp.
    """
    import time as time_mod
    import requests

    BASE_URL = "https://api1.binance.com/api/v3/klines"
    MAX_LIMIT = 1000

    from datetime import timezone as _tz
    start_ts = int(
        datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=_tz.utc).timestamp() * 1000
    )
    end_ts = int(
        datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=_tz.utc).timestamp() * 1000
    )

    all_candles = []
    current_start = start_ts
    while current_start < end_ts:
        params = {
            "symbol": symbol, "interval": "4h",
            "startTime": current_start, "endTime": end_ts,
            "limit": MAX_LIMIT,
        }
        resp = requests.get(BASE_URL, params=params, timeout=10)
        resp.raise_for_status()
        candles = resp.json()
        if not candles:
            break
        all_candles.extend(candles)
        current_start = candles[-1][0] + 1
        time_mod.sleep(0.1)

    if not all_candles:
        raise ValueError(f"No 4H data for {symbol} between {start} and {end}")

    df = pd.DataFrame(all_candles, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ])
    df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("timestamp")
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    df = df.sort_index()
    return df


def load_fg_daily(start: str, end: str) -> pd.Series:
    """
    Fetch Alternative.me F&G history.
    Returns Series indexed by Python date objects, values are int F&G scores.
    """
    from data.alternative_me_client import fetch_fear_greed_history
    df = fetch_fear_greed_history(start_date=start, end_date=end)
    # df["date"] is already Python date objects (from .dt.date in the client)
    return df.set_index("date")["value"].astype(int)


# ── Merging ────────────────────────────────────────────────────────────────────

def merge_fg_onto_4h(ohlcv_4h: pd.DataFrame, fg_daily: pd.Series) -> pd.DataFrame:
    """
    Forward-fill daily F&G value onto 4H bars.

    fg_daily index: Python date objects (from alternative_me_client.fetch_fear_greed_history)
    ohlcv_4h index: UTC-aware DatetimeIndex (from load_ohlcv)

    Strategy: extract the date portion of each 4H bar timestamp, join on that.
    """
    df = ohlcv_4h.copy()

    # Extract date from UTC-aware DatetimeIndex -> Python date objects
    df["_date"] = df.index.date  # works on UTC DatetimeIndex

    fg_df = fg_daily.rename("fg").reset_index()
    fg_df.columns = ["_date", "fg"]
    # Ensure fg index is also date objects (already guaranteed by load_fg_daily)

    df = df.merge(fg_df, on="_date", how="left")
    df["fg"] = df["fg"].ffill().bfill()
    df = df.drop(columns=["_date"])
    df.index = ohlcv_4h.index
    return df


def load_fg_cmc(start: str, end: str) -> pd.Series:
    """
    Fetch CMC Fear & Greed history for the 30-day live validation backtest.
    Returns Series indexed by Python date objects, values are int F&G scores.
    """
    from data.cmc_client import get_fear_greed_history
    df = get_fear_greed_history(start_date=start, end_date=end)
    return df.set_index("date")["value"].astype(int)


# ── Core backtest loop ─────────────────────────────────────────────────────────

def run_backtest() -> dict:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("Loading data...")

    # Load F&G once (shared across all tokens)
    fg_daily = load_fg_daily(START_DATE, END_DATE)

    # Load & prepare each token
    token_data: dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        print(f"  Fetching {sym} 4H...")
        raw = load_ohlcv(sym, START_DATE, END_DATE)
        merged = merge_fg_onto_4h(raw, fg_daily)
        token_data[sym] = add_indicators(merged)

    # Build a unified sorted list of all 4H timestamps
    all_timestamps = sorted(set().union(*[set(df.index) for df in token_data.values()]))

    # State
    equity        = STARTING_CAP
    cash          = STARTING_CAP
    positions: dict[str, dict] = {}   # symbol -> position dict
    trades        = []
    equity_curve  = []

    print(f"\nRunning backtest: {START_DATE} → {END_DATE}")
    print(f"Tokens: {SYMBOLS} | Max positions: {MAX_POSITIONS} | Capital: ${STARTING_CAP:,.0f}\n")

    for ts in all_timestamps:
        # Per-symbol rows available at this timestamp
        rows = {sym: df.loc[ts] for sym, df in token_data.items() if ts in df.index}
        if not rows:
            continue

        # Use BTC's F&G as the regime signal (same daily value for all tokens)
        btc_row = rows.get("BTCUSDT")
        anchor_row = btc_row if btc_row is not None else next(iter(rows.values()))
        fg_val = int(anchor_row.get("fg", 50))
        regime = detect_regime(fg_val)

        # ── 1. Update trail stops on open positions ───────────────────────────
        for sym, pos in list(positions.items()):
            if sym in rows:
                positions[sym] = update_trail_stop(pos, rows[sym])

        # ── 2. Check exits ────────────────────────────────────────────────────
        for sym, pos in list(positions.items()):
            if sym not in rows:
                continue
            row = rows[sym]
            should_exit, reason = exit_signal(row, pos, regime.allow_long)
            if should_exit:
                exit_price = float(row["close"])
                pnl        = (exit_price - pos["entry_price"]) * pos["qty"]
                pnl_pct    = (exit_price / pos["entry_price"] - 1) * 100
                # Return the original allocated cash + any profit/loss
                cash      += pos["allocated"] + pnl
                trades.append({
                    "symbol":      sym,
                    "entry_time":  pos["entry_time"],
                    "exit_time":   ts,
                    "entry_price": pos["entry_price"],
                    "exit_price":  exit_price,
                    "qty":         pos["qty"],
                    "pnl_usd":     round(pnl, 4),
                    "pnl_pct":     round(pnl_pct, 4),
                    "exit_reason": reason,
                    "fg_at_entry": pos["fg_at_entry"],
                    "fg_at_exit":  fg_val,
                })
                del positions[sym]

        # ── 3. Mark equity (after exits, before entries) ──────────────────────
        # equity = cash on hand + current market value of open positions
        open_value = sum(
            float(rows[sym]["close"]) * pos["qty"]
            for sym, pos in positions.items() if sym in rows
        )
        equity = cash + open_value

        # ── 4. Collect entry signals ──────────────────────────────────────────
        open_slots = MAX_POSITIONS - len(positions)
        candidates = []
        if open_slots > 0 and regime.allow_long:
            for sym, row in rows.items():
                if sym in positions:
                    continue
                if entry_signal(row, regime.allow_long):
                    candidates.append({
                        "symbol":         sym,
                        "momentum_score": float(row.get("momentum_score", 0)),
                        "row":            row,
                    })

        # ── 5. Fill slots by momentum rank ────────────────────────────────────
        if candidates:
            ranked = rank_candidates(candidates)
            for cand in ranked[:open_slots]:
                sym = cand["symbol"]
                row = cand["row"]
                # Allocate equal share of current equity, scaled by F&G multiplier
                slot_cap    = (equity / MAX_POSITIONS) * regime.size_multiplier
                # Guard: never allocate more than available cash
                slot_cap    = min(slot_cap, cash)
                if slot_cap <= 0:
                    continue
                entry_price = float(row["close"])
                qty         = slot_cap / entry_price
                atr_mult    = 1.5 if regime.tighten_trail else 2.0
                trail_stop  = entry_price - atr_mult * float(row["atr14"])
                cash       -= slot_cap

                positions[sym] = {
                    "entry_time":    ts,
                    "entry_price":   entry_price,
                    "qty":           qty,
                    "allocated":     slot_cap,
                    "trail_stop":    trail_stop,
                    "tighten_trail": regime.tighten_trail,
                    "fg_at_entry":   fg_val,
                }

        # ── 6. Final equity mark for this bar ─────────────────────────────────
        open_value = sum(
            float(rows[sym]["close"]) * pos["qty"]
            for sym, pos in positions.items() if sym in rows
        )
        equity = cash + open_value
        equity_curve.append({"timestamp": ts, "equity": equity, "cash": cash,
                              "fg": fg_val, "zone": regime.zone})

    # ── Close any open positions at final bar ──────────────────────────────────
    final_ts = all_timestamps[-1]
    final_rows = {sym: df.loc[final_ts] for sym, df in token_data.items() if final_ts in df.index}
    for sym, pos in list(positions.items()):
        if sym in final_rows:
            exit_price = float(final_rows[sym]["close"])
            pnl = (exit_price - pos["entry_price"]) * pos["qty"]
            pnl_pct = (exit_price / pos["entry_price"] - 1) * 100
            trades.append({
                "symbol": sym, "entry_time": pos["entry_time"],
                "exit_time": final_ts, "entry_price": pos["entry_price"],
                "exit_price": exit_price, "qty": pos["qty"],
                "pnl_usd": round(pnl, 4), "pnl_pct": round(pnl_pct, 4),
                "exit_reason": "end_of_backtest", "fg_at_entry": pos["fg_at_entry"],
                "fg_at_exit": int(anchor_row.get("fg", 50)),
            })

    # ── Metrics ────────────────────────────────────────────────────────────────
    trades_df  = pd.DataFrame(trades)
    equity_df  = pd.DataFrame(equity_curve).set_index("timestamp")
    final_eq   = equity_df["equity"].iloc[-1]
    total_ret  = (final_eq / STARTING_CAP - 1) * 100
    n_days     = (pd.Timestamp(END_DATE) - pd.Timestamp(START_DATE)).days
    ann_ret    = ((final_eq / STARTING_CAP) ** (365 / n_days) - 1) * 100

    rolling_max = equity_df["equity"].cummax()
    drawdown    = (equity_df["equity"] - rolling_max) / rolling_max * 100
    max_dd      = drawdown.min()

    # Max drawdown duration (bars, then convert to days)
    in_dd       = drawdown < 0
    dd_groups   = (in_dd != in_dd.shift()).cumsum()
    dd_lengths  = in_dd[in_dd].groupby(dd_groups[in_dd]).count()
    max_dd_bars = int(dd_lengths.max()) if len(dd_lengths) else 0
    max_dd_days = max_dd_bars * 0.1667  # 4H bars → days

    # Sharpe (annualised, 4H bars → ~2190 bars/year, risk-free = 0)
    returns  = equity_df["equity"].pct_change().dropna()
    sharpe   = (returns.mean() / returns.std()) * np.sqrt(2190) if returns.std() > 0 else 0

    # Trade stats
    n_trades   = len(trades_df)
    if n_trades > 0:
        winners    = trades_df[trades_df["pnl_usd"] > 0]
        losers     = trades_df[trades_df["pnl_usd"] <= 0]
        win_rate   = len(winners) / n_trades * 100
        avg_win    = winners["pnl_pct"].mean() if len(winners) else 0
        avg_loss   = losers["pnl_pct"].mean() if len(losers) else 0
        profit_fac = (winners["pnl_usd"].sum() / abs(losers["pnl_usd"].sum())
                      if len(losers) and losers["pnl_usd"].sum() != 0 else float("inf"))
        exit_reasons = trades_df["exit_reason"].value_counts().to_dict()
    else:
        win_rate = avg_win = avg_loss = profit_fac = 0
        exit_reasons = {}

    metrics = {
        "starting_capital":  STARTING_CAP,
        "final_equity":      round(final_eq, 2),
        "total_return_pct":  round(total_ret, 2),
        "annualised_return_pct": round(ann_ret, 2),
        "max_drawdown_pct":  round(max_dd, 2),
        "max_drawdown_days": round(max_dd_days, 1),
        "sharpe_ratio":      round(sharpe, 3),
        "n_trades":          n_trades,
        "win_rate_pct":      round(win_rate, 2),
        "avg_win_pct":       round(avg_win, 2),
        "avg_loss_pct":      round(avg_loss, 2),
        "profit_factor":     round(profit_fac, 3),
        "exit_reasons":      exit_reasons,
        "backtest_start":    START_DATE,
        "backtest_end":      END_DATE,
    }

    return metrics, trades_df, equity_df


# ── Output writers ─────────────────────────────────────────────────────────────

def write_spec(metrics: dict):
    spec = {**STRATEGY_SPEC, "backtest_results": metrics}
    path = os.path.join(OUTPUT_DIR, "spec.json")
    with open(path, "w") as f:
        json.dump(spec, f, indent=2, default=str)
    print(f"Wrote {path}")


def write_report(metrics: dict):
    m = metrics
    report = f"""# Fear & Greed Regime Switcher — 4H Momentum Strategy
## Backtest Report

**Period:** {m['backtest_start']} → {m['backtest_end']}  
**Timeframe:** 4H | **Tokens:** BTC, ETH, BNB, CAKE | **Max Positions:** {MAX_POSITIONS}

---

## Performance Summary

| Metric | Value |
|---|---|
| Starting Capital | ${m['starting_capital']:,.2f} |
| Final Equity | ${m['final_equity']:,.2f} |
| Total Return | {m['total_return_pct']:.2f}% |
| Annualised Return | {m['annualised_return_pct']:.2f}% |
| Max Drawdown | {m['max_drawdown_pct']:.2f}% |
| Max Drawdown Duration | {m['max_drawdown_days']:.0f} days |
| Sharpe Ratio | {m['sharpe_ratio']:.3f} |

## Trade Statistics

| Metric | Value |
|---|---|
| Total Trades | {m['n_trades']} |
| Win Rate | {m['win_rate_pct']:.2f}% |
| Avg Win | {m['avg_win_pct']:.2f}% |
| Avg Loss | {m['avg_loss_pct']:.2f}% |
| Profit Factor | {m['profit_factor']:.3f} |

## Exit Breakdown

{chr(10).join(f"- **{k}**: {v} trades" for k, v in m['exit_reasons'].items())}

---

## Strategy Rules

### Entry (all must be true)
1. EMA(20) crosses above EMA(50) on 4H bar
2. RSI(14) > 50
3. Close > EMA(200) — macro trend filter
4. Fear & Greed Index > 25 (not Extreme Fear)

### Exit (first trigger wins)
1. EMA(20) crosses below EMA(50)
2. Trailing stop: `close < high_water - ATR_mult × ATR(14)`
   - ATR_mult = 2.0 (normal) / 1.5 (Extreme Greed, F&G > 75)
3. F&G drops to Extreme Fear (≤ 25)

### Position Sizing
- Base slot = `equity / max_positions`
- Fear zone (F&G 26–49): 0.5× multiplier
- Extreme Fear (F&G ≤ 25): no new longs

### Token Ranking
When multiple entry signals fire simultaneously, rank by:  
`momentum_score = ROC(10) × Volume_Ratio(20)`  
Select top {MAX_POSITIONS} scoring tokens.

---

*Generated by fg-regime-switcher/backtester.py*  
*Data: Alternative.me F&G (historical) + Binance 4H klines (public API)*
"""
    path = os.path.join(OUTPUT_DIR, "report.md")
    with open(path, "w") as f:
        f.write(report)
    print(f"Wrote {path}")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    metrics, trades_df, equity_df = run_backtest()

    print("\n=== RESULTS ===")
    for k, v in metrics.items():
        print(f"  {k}: {v}")

    write_spec(metrics)
    write_report(metrics)

    trades_df.to_csv(os.path.join(OUTPUT_DIR, "trades.csv"), index=False)
    equity_df.to_csv(os.path.join(OUTPUT_DIR, "equity.csv"))
    print(f"\nDone. Outputs written to {OUTPUT_DIR}/")


# ── Backtest 2: CMC 30-day live validation ─────────────────────────────────────

def run_backtest2() -> tuple:
    """
    Backtest 2: last 30 days, F&G from CMC API.
    Same strategy logic as run_backtest(), different data source and window.
    Outputs go to outputs/bt2_*.
    """
    from datetime import timezone as _tz
    _now = datetime.now(_tz.utc)
    start = (_now - __import__("datetime").timedelta(days=30)).strftime("%Y-%m-%d")
    end   = _now.strftime("%Y-%m-%d")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"Backtest 2 (CMC): {start} -> {end}")

    fg_daily = load_fg_cmc(start, end)

    token_data: dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        print(f"  Fetching {sym} 4H...")
        raw    = load_ohlcv(sym, start, end)
        merged = merge_fg_onto_4h(raw, fg_daily)
        token_data[sym] = add_indicators(merged)

    all_timestamps = sorted(set().union(*[set(df.index) for df in token_data.values()]))

    equity   = STARTING_CAP
    cash     = STARTING_CAP
    positions: dict[str, dict] = {}
    trades   = []
    equity_curve = []

    for ts in all_timestamps:
        rows = {sym: df.loc[ts] for sym, df in token_data.items() if ts in df.index}
        if not rows:
            continue

        btc_row    = rows.get("BTCUSDT")
        anchor_row = btc_row if btc_row is not None else next(iter(rows.values()))
        fg_val     = int(anchor_row.get("fg", 50))
        regime     = detect_regime(fg_val)

        for sym, pos in list(positions.items()):
            if sym in rows:
                positions[sym] = update_trail_stop(pos, rows[sym])

        for sym, pos in list(positions.items()):
            if sym not in rows:
                continue
            should_exit, reason = exit_signal(rows[sym], pos, regime.allow_long)
            if should_exit:
                exit_price = float(rows[sym]["close"])
                pnl        = (exit_price - pos["entry_price"]) * pos["qty"]
                pnl_pct    = (exit_price / pos["entry_price"] - 1) * 100
                cash      += pos["allocated"] + pnl
                trades.append({
                    "symbol": sym, "entry_time": pos["entry_time"],
                    "exit_time": ts, "entry_price": pos["entry_price"],
                    "exit_price": exit_price, "qty": pos["qty"],
                    "pnl_usd": round(pnl, 4), "pnl_pct": round(pnl_pct, 4),
                    "exit_reason": reason, "fg_at_entry": pos["fg_at_entry"],
                    "fg_at_exit": fg_val,
                })
                del positions[sym]

        open_value = sum(float(rows[sym]["close"]) * pos["qty"]
                         for sym, pos in positions.items() if sym in rows)
        equity = cash + open_value

        open_slots = MAX_POSITIONS - len(positions)
        candidates = []
        if open_slots > 0 and regime.allow_long:
            for sym, row in rows.items():
                if sym in positions:
                    continue
                if entry_signal(row, regime.allow_long):
                    candidates.append({"symbol": sym,
                                       "momentum_score": float(row.get("momentum_score", 0)),
                                       "row": row})

        if candidates:
            for cand in rank_candidates(candidates)[:open_slots]:
                sym         = cand["symbol"]
                row         = cand["row"]
                slot_cap    = min((equity / MAX_POSITIONS) * regime.size_multiplier, cash)
                if slot_cap <= 0:
                    continue
                entry_price = float(row["close"])
                atr_mult    = 1.5 if regime.tighten_trail else 2.0
                cash       -= slot_cap
                positions[sym] = {
                    "entry_time": ts, "entry_price": entry_price,
                    "qty": slot_cap / entry_price, "allocated": slot_cap,
                    "trail_stop": entry_price - atr_mult * float(row["atr14"]),
                    "tighten_trail": regime.tighten_trail, "fg_at_entry": fg_val,
                }

        open_value = sum(float(rows[sym]["close"]) * pos["qty"]
                         for sym, pos in positions.items() if sym in rows)
        equity = cash + open_value
        equity_curve.append({"timestamp": ts, "equity": equity, "cash": cash,
                              "fg": fg_val, "zone": regime.zone})

    # Close open positions at final bar
    final_ts   = all_timestamps[-1]
    final_rows = {sym: df.loc[final_ts] for sym, df in token_data.items() if final_ts in df.index}
    for sym, pos in list(positions.items()):
        if sym in final_rows:
            exit_price = float(final_rows[sym]["close"])
            pnl = (exit_price - pos["entry_price"]) * pos["qty"]
            trades.append({
                "symbol": sym, "entry_time": pos["entry_time"], "exit_time": final_ts,
                "entry_price": pos["entry_price"], "exit_price": exit_price,
                "qty": pos["qty"], "pnl_usd": round(pnl, 4),
                "pnl_pct": round((exit_price / pos["entry_price"] - 1) * 100, 4),
                "exit_reason": "end_of_backtest", "fg_at_entry": pos["fg_at_entry"],
                "fg_at_exit": fg_val,
            })

    trades_df = pd.DataFrame(trades)
    equity_df = pd.DataFrame(equity_curve).set_index("timestamp")
    final_eq  = equity_df["equity"].iloc[-1]
    total_ret = (final_eq / STARTING_CAP - 1) * 100
    n_days    = max((pd.Timestamp(end) - pd.Timestamp(start)).days, 1)
    ann_ret   = ((final_eq / STARTING_CAP) ** (365 / n_days) - 1) * 100

    rolling_max = equity_df["equity"].cummax()
    drawdown    = (equity_df["equity"] - rolling_max) / rolling_max * 100
    max_dd      = drawdown.min()
    in_dd       = drawdown < 0
    dd_groups   = (in_dd != in_dd.shift()).cumsum()
    dd_lengths  = in_dd[in_dd].groupby(dd_groups[in_dd]).count()
    max_dd_bars = int(dd_lengths.max()) if len(dd_lengths) else 0

    returns = equity_df["equity"].pct_change().dropna()
    sharpe  = (returns.mean() / returns.std()) * np.sqrt(2190) if returns.std() > 0 else 0

    n_trades = len(trades_df)
    if n_trades > 0:
        winners    = trades_df[trades_df["pnl_usd"] > 0]
        losers     = trades_df[trades_df["pnl_usd"] <= 0]
        win_rate   = len(winners) / n_trades * 100
        avg_win    = winners["pnl_pct"].mean() if len(winners) else 0
        avg_loss   = losers["pnl_pct"].mean() if len(losers) else 0
        profit_fac = (winners["pnl_usd"].sum() / abs(losers["pnl_usd"].sum())
                      if len(losers) and losers["pnl_usd"].sum() != 0 else float("inf"))
        exit_reasons = trades_df["exit_reason"].value_counts().to_dict()
    else:
        win_rate = avg_win = avg_loss = profit_fac = 0
        exit_reasons = {}

    metrics = {
        "backtest": "Backtest 2 -- CMC F&G, 30-day live validation",
        "starting_capital": STARTING_CAP,
        "final_equity": round(final_eq, 2),
        "total_return_pct": round(total_ret, 2),
        "annualised_return_pct": round(ann_ret, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "max_drawdown_days": round(max_dd_bars * 0.1667, 1),
        "sharpe_ratio": round(sharpe, 3),
        "n_trades": n_trades,
        "win_rate_pct": round(win_rate, 2),
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "profit_factor": round(profit_fac, 3),
        "exit_reasons": exit_reasons,
        "backtest_start": start,
        "backtest_end": end,
        "fg_source": "CoinMarketCap API",
    }

    return metrics, trades_df, equity_df