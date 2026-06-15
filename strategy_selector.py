"""
strategy_selector.py
--------------------
4H momentum trend-following signal engine.

Entry conditions (all must be true):
  1. 20 EMA crosses above 50 EMA on 4H chart
  2. RSI(14) > 50
  3. Close > 200 EMA (macro trend filter)
  4. Regime allows long (F&G gate from regime_detector)

Exit conditions (first trigger wins):
  A. 20 EMA crosses below 50 EMA
  B. Trailing stop hit (2x ATR from high-water mark; 1.5x if tighten_trail)
  C. F&G drops to Extreme Fear zone

Token ranking (when multiple signals fire same bar):
  Score = ROC(10) x Volume_Ratio
  Volume_Ratio = current_volume / rolling_20_bar_avg_volume
  Take top-N by score, up to max_positions slots available.

Position sizing:
  Slot capital = (equity / max_positions) * size_multiplier
"""

import pandas as pd
import numpy as np


# ── Indicator helpers ──────────────────────────────────────────────────────────

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def roc(series: pd.Series, period: int = 10) -> pd.Series:
    return (series / series.shift(period) - 1) * 100


def volume_ratio(volume: pd.Series, period: int = 20) -> pd.Series:
    return volume / volume.rolling(period).mean()


# ── Signal generation ──────────────────────────────────────────────────────────

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Expects df with columns: open, high, low, close, volume.
    Returns df with indicators added in-place.
    """
    df = df.copy()
    df["ema20"]  = ema(df["close"], 20)
    df["ema50"]  = ema(df["close"], 50)
    df["ema200"] = ema(df["close"], 200)
    df["rsi14"]  = rsi(df["close"], 14)
    df["atr14"]  = atr(df["high"], df["low"], df["close"], 14)
    df["roc10"]  = roc(df["close"], 10)
    df["vol_ratio"] = volume_ratio(df["volume"], 20)
    df["momentum_score"] = df["roc10"] * df["vol_ratio"]

    # Cross signals (previous bar vs current bar)
    df["ema_cross_up"]   = (df["ema20"] > df["ema50"]) & (df["ema20"].shift(1) <= df["ema50"].shift(1))
    df["ema_cross_down"] = (df["ema20"] < df["ema50"]) & (df["ema20"].shift(1) >= df["ema50"].shift(1))

    return df


def entry_signal(row: pd.Series, regime_allow: bool) -> bool:
    """Return True if all entry conditions are met for this bar."""
    if not regime_allow:
        return False
    if not row["ema_cross_up"]:
        return False
    if row["rsi14"] <= 50:
        return False
    if row["close"] <= row["ema200"]:
        return False
    return True


def exit_signal(row: pd.Series, position: dict, regime_allow: bool) -> tuple[bool, str]:
    """
    Check exit conditions for an open position.
    Returns (should_exit: bool, reason: str).

    position dict keys: entry_price, trail_stop, tighten_trail
    """
    # Condition C: regime flipped to no-long
    if not regime_allow:
        return True, "fg_extreme_fear"

    # Condition A: EMA cross down
    if row["ema_cross_down"]:
        return True, "ema_cross_down"

    # Condition B: trailing stop
    if row["close"] <= position["trail_stop"]:
        return True, "trail_stop"

    return False, ""


def update_trail_stop(position: dict, row: pd.Series) -> dict:
    """
    Ratchet trailing stop upward if price has moved higher.
    Uses 2x ATR (or 1.5x if tighten_trail).
    """
    multiplier = 1.5 if position["tighten_trail"] else 2.0
    new_stop = row["close"] - multiplier * row["atr14"]
    position["trail_stop"] = max(position["trail_stop"], new_stop)
    return position


def rank_candidates(signals: list[dict]) -> list[dict]:
    """
    Sort entry candidates by momentum_score descending.
    signals: list of dicts with keys symbol, momentum_score, row.
    """
    return sorted(signals, key=lambda x: x["momentum_score"], reverse=True)


# ── Spec export ────────────────────────────────────────────────────────────────

STRATEGY_SPEC = {
    "name": "Fear & Greed Regime Switcher — 4H Momentum",
    "version": "2.0",
    "timeframe": "4H",
    "tokens": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "CAKEUSDT"],
    "max_positions": 2,
    "indicators": {
        "ema_fast": 20,
        "ema_slow": 50,
        "ema_trend": 200,
        "rsi_period": 14,
        "atr_period": 14,
        "roc_period": 10,
        "vol_ratio_period": 20,
    },
    "entry_rules": [
        "EMA(20) crosses above EMA(50) on 4H bar",
        "RSI(14) > 50",
        "Close > EMA(200)",
        "F&G regime allows long (score > 25)",
    ],
    "exit_rules": [
        "EMA(20) crosses below EMA(50)",
        "Trailing stop: close < (high_water - ATR_mult * ATR14)",
        "F&G drops to Extreme Fear (<= 25)",
    ],
    "position_sizing": {
        "base": "equity / max_positions",
        "fg_fear_multiplier": 0.5,
        "fg_extreme_fear_multiplier": 0.0,
        "atr_trail_multiplier_normal": 2.0,
        "atr_trail_multiplier_extreme_greed": 1.5,
    },
    "token_ranking": "ROC(10) x Volume_Ratio — top N by score",
    "starting_capital": 10000,
    "backtest_period": "2020-01-01 to 2025-06-01",
    "data_sources": {
        "ohlcv": "Binance public klines API (4H)",
        "fg_historical": "Alternative.me (free, 2018-present)",
        "fg_live": "CoinMarketCap Startup plan API",
    },
}


if __name__ == "__main__":
    import json
    print(json.dumps(STRATEGY_SPEC, indent=2))
