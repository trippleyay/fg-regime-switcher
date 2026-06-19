"""
regime_detector.py
------------------
Classifies market regime from Fear & Greed index.
Acts as position-sizing gate and long-entry filter for the 1H momentum strategy.

Zones:
  0-25   Extreme Fear  -> no new longs
  26-49  Fear          -> 0.5x position size
  50-74  Greed         -> 1.0x position size
  75-100 Extreme Greed -> 1.0x size, tighten ATR trail (1.5x instead of 2x)
"""

from dataclasses import dataclass


@dataclass
class RegimeSignal:
    fg_value: int
    zone: str            # extreme_fear | fear | greed | extreme_greed
    allow_long: bool
    size_multiplier: float
    tighten_trail: bool
    label: str


def detect_regime(fg_value: int) -> RegimeSignal:
    if not (0 <= fg_value <= 100):
        raise ValueError(f"fg_value must be 0-100, got {fg_value}")

    if fg_value <= 25:
        return RegimeSignal(fg_value, "extreme_fear", False, 0.0, False,
                            f"Extreme Fear ({fg_value}) — no new longs")
    elif fg_value <= 49:
        return RegimeSignal(fg_value, "fear", True, 0.5, False,
                            f"Fear ({fg_value}) — half size")
    elif fg_value <= 74:
        return RegimeSignal(fg_value, "greed", True, 1.0, False,
                            f"Greed ({fg_value}) — full size")
    else:
        return RegimeSignal(fg_value, "extreme_greed", True, 1.0, True,
                            f"Extreme Greed ({fg_value}) — full size, tight trail")


def detect_regime_series(fg_series):
    """Vectorised: apply detect_regime across a pandas Series of daily F&G values."""
    import pandas as pd
    records = [detect_regime(int(v)) for v in fg_series]
    return pd.DataFrame({
        "fg_value":        [r.fg_value for r in records],
        "zone":            [r.zone for r in records],
        "allow_long":      [r.allow_long for r in records],
        "size_multiplier": [r.size_multiplier for r in records],
        "tighten_trail":   [r.tighten_trail for r in records],
    }, index=fg_series.index)


if __name__ == "__main__":
    for v in [10, 30, 60, 80]:
        s = detect_regime(v)
        print(s.label, "| tighten_trail:", s.tighten_trail)
