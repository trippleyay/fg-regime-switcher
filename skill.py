"""
skill.py
--------
CLI orchestrator for the Fear & Greed Regime Switcher.

Usage:
  python skill.py --mode backtest          # Run full historical backtest
  python skill.py --mode live              # Print live regime + signals
  python skill.py --mode spec              # Dump strategy spec JSON
  python skill.py --mode backtest --quick  # Smoke test (30-day window)
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta


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


def mode_backtest(quick: bool = False):
    from backtester import run_backtest, write_spec, write_report, OUTPUT_DIR as BT_OUT
    import pandas as pd

    if quick:
        # Patch constants for a fast smoke test
        import backtester
        from datetime import timezone as _tz
        _now = datetime.now(_tz.utc)
        backtester.START_DATE = (_now - timedelta(days=30)).strftime("%Y-%m-%d")
        backtester.END_DATE   = _now.strftime("%Y-%m-%d")
        print(f"[QUICK MODE] {backtester.START_DATE} → {backtester.END_DATE}")

    metrics, trades_df, equity_df = run_backtest()

    print("\n" + "=" * 50)
    print("  BACKTEST RESULTS")
    print("=" * 50)
    rows = [
        ("Total Return",          f"{metrics['total_return_pct']:.2f}%"),
        ("Annualised Return",     f"{metrics['annualised_return_pct']:.2f}%"),
        ("Max Drawdown",          f"{metrics['max_drawdown_pct']:.2f}%"),
        ("Max DD Duration",       f"{metrics['max_drawdown_days']:.0f} days"),
        ("Sharpe Ratio",          f"{metrics['sharpe_ratio']:.3f}"),
        ("Total Trades",          f"{metrics['n_trades']}"),
        ("Win Rate",              f"{metrics['win_rate_pct']:.2f}%"),
        ("Profit Factor",         f"{metrics['profit_factor']:.3f}"),
        ("Final Equity",          f"${metrics['final_equity']:,.2f}"),
    ]
    for label, val in rows:
        print(f"  {label:<25} {val}")
    print("=" * 50)

    write_spec(metrics)
    write_report(metrics)
    trades_df.to_csv(os.path.join(OUTPUT_DIR, "trades.csv"), index=False)
    equity_df.to_csv(os.path.join(OUTPUT_DIR, "equity.csv"))
    print(f"\nOutputs written to {OUTPUT_DIR}/")


def mode_backtest2():
    """Backtest 2: last 30 days, F&G from CMC API."""
    from backtester import run_backtest2, OUTPUT_DIR
    import os

    metrics, trades_df, equity_df = run_backtest2()

    print("\n" + "=" * 50)
    print("  BACKTEST 2 RESULTS (CMC F&G, 30-day)")
    print("=" * 50)
    rows = [
        ("Period",               f"{metrics['backtest_start']} to {metrics['backtest_end']}"),
        ("F&G Source",           metrics["fg_source"]),
        ("Total Return",         f"{metrics['total_return_pct']:.2f}%"),
        ("Annualised Return",    f"{metrics['annualised_return_pct']:.2f}%"),
        ("Max Drawdown",         f"{metrics['max_drawdown_pct']:.2f}%"),
        ("Sharpe Ratio",         f"{metrics['sharpe_ratio']:.3f}"),
        ("Total Trades",         f"{metrics['n_trades']}"),
        ("Win Rate",             f"{metrics['win_rate_pct']:.2f}%"),
        ("Profit Factor",        f"{metrics['profit_factor']:.3f}"),
        ("Final Equity",         f"${metrics['final_equity']:,.2f}"),
    ]
    for label, val in rows:
        print(f"  {label:<25} {val}")
    print("=" * 50)

    import json, os
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, "bt2_spec.json"), "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    trades_df.to_csv(os.path.join(OUTPUT_DIR, "bt2_trades.csv"), index=False)
    equity_df.to_csv(os.path.join(OUTPUT_DIR, "bt2_equity.csv"))
    print(f"\nOutputs written to {OUTPUT_DIR}/bt2_*")


def mode_live():
    """Fetch current F&G and live 4H bar, print regime + any open signals."""
    print("Fetching live data...\n")

    # F&G via CMC (primary), Alternative.me (fallback)
    try:
        from data.cmc_client import get_fear_greed_latest
        fg_live = get_fear_greed_latest()
        fg_value = int(fg_live["value"])
        fg_label = fg_live.get("classification", "")
    except Exception as e:
        print(f"[WARN] CMC client failed ({e}), falling back to Alternative.me")
        from data.alternative_me_client import get_current_fear_greed
        fg_live = get_current_fear_greed()
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

    # Check latest 4H bar for each token
    from data.binance_client import BinanceClient
    from strategy_selector import add_indicators, entry_signal
    import pandas as pd

    bc = BinanceClient()
    end = datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%d")
    start = (datetime.now(__import__("datetime").timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d")

    print("Scanning tokens for entry signals...\n")
    signals = []
    for sym in ["BTCUSDT", "ETHUSDT", "BNBUSDT", "CAKEUSDT"]:
        try:
            df = bc.get_klines(symbol=sym, interval="4h", start=start, end=end)
            df = df[["open", "high", "low", "close", "volume"]].astype(float)
            df = add_indicators(df)
            last = df.iloc[-1]
            has_signal = entry_signal(last, regime.allow_long)
            score = float(last.get("momentum_score", 0))
            status = "✓ SIGNAL" if has_signal else "  —"
            print(f"  {sym:<12} {status}  | Score: {score:+.2f} | "
                  f"EMA cross: {bool(last['ema_cross_up'])} | "
                  f"RSI: {last['rsi14']:.1f} | "
                  f"Above EMA200: {last['close'] > last['ema200']}")
            if has_signal:
                signals.append({"symbol": sym, "score": score})
        except Exception as e:
            print(f"  {sym:<12} ERROR: {e}")

    if signals:
        best = sorted(signals, key=lambda x: x["score"], reverse=True)
        print(f"\nTop signal(s): {[s['symbol'] for s in best]}")
    else:
        print("\nNo entry signals on current 4H bar.")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fear & Greed Regime Switcher — 4H Momentum Strategy"
    )
    parser.add_argument(
        "--mode", choices=["backtest", "backtest2", "live", "spec"],
        required=True, help="Run mode"
    )
    parser.add_argument(
        "--quick", action="store_true",
        help="Quick smoke test (30-day window, backtest mode only)"
    )
    args = parser.parse_args()

    if args.mode == "spec":
        mode_spec()
    elif args.mode == "backtest":
        mode_backtest(quick=args.quick)
    elif args.mode == "backtest2":
        mode_backtest2()
    elif args.mode == "live":
        mode_live()


if __name__ == "__main__":
    main()