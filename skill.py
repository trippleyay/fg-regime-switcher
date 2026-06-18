"""
skill.py
--------
CLI orchestrator for the Fear & Greed Regime Switcher.

Usage:
  python skill.py --mode backtest   # Run full historical backtest
  python skill.py --mode live       # Print live regime + signals
  python skill.py --mode spec       # Dump strategy spec JSON
"""

import argparse
import json
import os
from datetime import datetime, timedelta

from backtester import INTERVAL

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")


# ── Modes ──────────────────────────────────────────────────────────────────────

def mode_spec():
    from strategy_selector import STRATEGY_SPEC
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, "spec.json")
    with open(path, "w") as f:
        json.dump(STRATEGY_SPEC, f, indent=2)
    print(json.dumps(STRATEGY_SPEC, indent=2))
    print(f"\nSpec written to {path}")


def mode_backtest():
    from backtester import run_backtest, write_spec, write_report

    metrics, trades_df, equity_df = run_backtest()

    print("\n" + "=" * 50)
    print("  BACKTEST RESULTS")
    print("=" * 50)
    rows = [
        ("Period",            f"{metrics['backtest_start']} to {metrics['backtest_end']}"),
        ("Interval",          metrics["interval"].upper()),
        ("F&G Source",        metrics["fg_source"]),
        ("Total Return",      f"{metrics['total_return_pct']:.2f}%"),
        ("Annualised Return", f"{metrics['annualised_return_pct']:.2f}%"),
        ("Max Drawdown",      f"{metrics['max_drawdown_pct']:.2f}%"),
        ("Sharpe Ratio",      f"{metrics['sharpe_ratio']:.3f}"),
        ("Total Trades",      f"{metrics['n_trades']}"),
        ("Win Rate",          f"{metrics['win_rate_pct']:.2f}%"),
        ("Profit Factor",     f"{metrics['profit_factor']:.3f}"),
        ("Final Equity",      f"${metrics['final_equity']:,.2f}"),
    ]
    for label, val in rows:
        print(f"  {label:<25} {val}")
    print("=" * 50)

    write_spec(metrics)
    write_report(metrics)
    trades_df.to_csv(os.path.join(OUTPUT_DIR, "trades.csv"), index=False)
    equity_df.to_csv(os.path.join(OUTPUT_DIR, "equity.csv"))
    print(f"\nOutputs written to {OUTPUT_DIR}/")


def mode_live():
    """Fetch current F&G and latest bar, print regime + entry signals."""
    print("Fetching live data...\n")

    from datetime import timezone as _tz

    # F&G via CMC (primary), Alternative.me (fallback)
    try:
        from data.cmc_client import get_fear_greed_latest
        fg_live  = get_fear_greed_latest()
        fg_value = int(fg_live["value"])
        fg_label = fg_live.get("classification", "")
    except Exception as e:
        print(f"[WARN] CMC client failed ({e}), falling back to Alternative.me")
        from data.alternative_me_client import get_current_fear_greed
        fg_live  = get_current_fear_greed()
        fg_value = int(fg_live["value"])
        fg_label = fg_live.get("classification", "")

    from regime_detector import detect_regime
    regime = detect_regime(fg_value)
    print(f"Fear & Greed: {fg_value} ({fg_label})")
    print(f"Regime: {regime.label}")
    print(f"Allow Long: {regime.allow_long} | Size Multiplier: {regime.size_multiplier}x")
    print(f"Tighten Trail: {regime.tighten_trail}\n")

    if not regime.allow_long:
        print("No new longs permitted in current regime.")
        return

    import requests
    import time as time_mod
    import pandas as pd
    from strategy_selector import add_indicators, entry_signal

    end_ts   = int(datetime.now(_tz.utc).timestamp() * 1000)
    start_ts = int((datetime.now(_tz.utc) - timedelta(days=60)).timestamp() * 1000)

    print(f"Scanning tokens for entry signals ({INTERVAL.upper()} bars)...\n")
    signals = []

    for sym in ["BTCUSDT", "ETHUSDT", "BNBUSDT", "CAKEUSDT"]:
        try:
            params = {"symbol": sym, "interval": INTERVAL,
                      "startTime": start_ts, "endTime": end_ts, "limit": 1000}
            resp = requests.get("https://api1.binance.com/api/v3/klines",
                                params=params, timeout=10)
            resp.raise_for_status()
            candles = resp.json()
            df = pd.DataFrame(candles, columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades",
                "taker_buy_base", "taker_buy_quote", "ignore"
            ])
            df = df[["open", "high", "low", "close", "volume"]].astype(float)
            df = add_indicators(df)
            last       = df.iloc[-1]
            has_signal = entry_signal(last, regime.allow_long)
            score      = float(last.get("momentum_score", 0))
            status     = "SIGNAL" if has_signal else "--"
            print(f"  {sym:<12} {status:<8} | Score: {score:+.2f} | "
                  f"EMA cross: {bool(last['ema_cross_up'])} | "
                  f"RSI: {last['rsi14']:.1f} | "
                  f"Above EMA200: {last['close'] > last['ema200']}")
            if has_signal:
                signals.append({"symbol": sym, "score": score})
            time_mod.sleep(0.1)
        except Exception as e:
            print(f"  {sym:<12} ERROR: {e}")

    if signals:
        best = sorted(signals, key=lambda x: x["score"], reverse=True)
        print(f"\nTop signal(s): {[s['symbol'] for s in best]}")
    else:
        print(f"\nNo entry signals on current {INTERVAL.upper()} bar.")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fear & Greed Regime Switcher -- Momentum Strategy"
    )
    parser.add_argument(
        "--mode", choices=["backtest", "live", "spec"],
        required=True, help="Run mode"
    )
    args = parser.parse_args()

    if args.mode == "spec":
        mode_spec()
    elif args.mode == "backtest":
        mode_backtest()
    elif args.mode == "live":
        mode_live()


if __name__ == "__main__":
    main()