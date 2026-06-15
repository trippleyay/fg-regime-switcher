"""
Alternative.me Fear & Greed Index Client
Fetches full historical F&G data going back to 2018.
No API key required.
"""

import requests
import pandas as pd
from datetime import datetime, date


BASE_URL = "https://api.alternative.me/fng/"


def fetch_fear_greed_history(
    start_date: str = None,
    end_date: str = None,
) -> pd.DataFrame:
    """
    Fetch full Fear & Greed history from Alternative.me.

    Args:
        start_date: 'YYYY-MM-DD' — filter from this date (inclusive)
        end_date:   'YYYY-MM-DD' — filter to this date (inclusive)
                    If both are None, returns all available history.

    Returns:
        DataFrame with columns: date, value, classification
        Sorted ascending by date.
    """
    # limit=0 returns all available data
    params = {
        "limit": 0,
        "format": "json",
    }

    response = requests.get(BASE_URL, params=params, timeout=10)
    response.raise_for_status()

    raw = response.json()

    if raw.get("metadata", {}).get("error"):
        raise ValueError(f"Alternative.me API error: {raw['metadata']['error']}")

    records = raw.get("data", [])

    if not records:
        raise ValueError("No data returned from Alternative.me")

    df = pd.DataFrame(records)


    df["date"] = pd.to_datetime(df["timestamp"].astype(int), unit="s", utc=True).dt.date
    df["value"] = df["value"].astype(int)
    df = df.rename(columns={"value_classification": "classification"})
    df = df[["date", "value", "classification"]].copy()
    df = df.sort_values("date").reset_index(drop=True)

    # Apply date filters if provided
    if start_date:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        df = df[df["date"] >= start]

    if end_date:
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
        df = df[df["date"] <= end]

    df = df.reset_index(drop=True)

    return df


def get_current_fear_greed() -> dict:
    """
    Fetch only the latest Fear & Greed value.

    Returns:
        Dict with keys: date, value, classification
    """
    params = {"limit": 1, "format": "json"}

    response = requests.get(BASE_URL, params=params, timeout=10)
    response.raise_for_status()

    raw = response.json()
    latest = raw["data"][0]

    return {
        "date": date.fromtimestamp(int(latest["timestamp"])),
        "value": int(latest["value"]),
        "classification": latest["value_classification"],
    }


def get_seven_day_trend(df: pd.DataFrame = None) -> str:
    """
    Determine the 7-day F&G trend direction.

    Args:
        df: Optional pre-fetched DataFrame. If None, fetches fresh data.

    Returns:
        'rising', 'falling', or 'flat'
    """
    if df is None:
        df = fetch_fear_greed_history()

    recent = df.tail(7)

    if len(recent) < 2:
        return "flat"

    first_half_avg = recent.head(3)["value"].mean()
    second_half_avg = recent.tail(3)["value"].mean()

    diff = second_half_avg - first_half_avg

    if diff > 3:
        return "rising"
    elif diff < -3:
        return "falling"
    else:
        return "flat"


if __name__ == "__main__":
    print("Testing Alternative.me client...\n")

    # Full history
    df = fetch_fear_greed_history(start_date="2020-01-01", end_date="2025-06-30")
    print(f"Full history: {len(df)} days")
    print(f"Range: {df['date'].iloc[0]} to {df['date'].iloc[-1]}")
    print(f"\nSample (last 5 rows):")
    print(df.tail(5).to_string(index=False))

    # Current value
    current = get_current_fear_greed()
    print(f"\nCurrent F&G: {current['value']} ({current['classification']}) on {current['date']}")

    # 7-day trend
    trend = get_seven_day_trend(df)
    print(f"7-day trend: {trend}")

    # Regime distribution
    print(f"\nRegime distribution (2020-2025):")
    greed = len(df[df["value"] > 65])
    fear = len(df[df["value"] < 35])
    neutral = len(df[(df["value"] >= 35) & (df["value"] <= 65)])
    total = len(df)
    print(f"  Greed (>65):   {greed} days ({greed/total*100:.1f}%)")
    print(f"  Neutral (35-65): {neutral} days ({neutral/total*100:.1f}%)")
    print(f"  Fear (<35):    {fear} days ({fear/total*100:.1f}%)")
