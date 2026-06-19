"""
CoinMarketCap API Client
Fetches live and historical Fear & Greed data.
Requires CMC API key.
"""

import os
import requests
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

# Load .env file from project root
load_dotenv()

CMC_BASE_URL = "https://pro-api.coinmarketcap.com"

API_KEY = os.environ.get("CMC_API_KEY")


def _get_headers() -> dict:
    if not API_KEY:
        raise EnvironmentError(
            "CMC_API_KEY environment variable not set. "
            "Export it with: export CMC_API_KEY='your_key_here'"
        )
    return {
        "Accepts": "application/json",
        "X-CMC_PRO_API_KEY": API_KEY,
    }


def get_fear_greed_latest() -> dict:
    """
    Fetch the latest CMC Fear & Greed value.

    Returns:
        Dict with keys: value, classification, timestamp
    """
    url = f"{CMC_BASE_URL}/v3/fear-and-greed/latest"

    response = requests.get(url, headers=_get_headers(), timeout=10)
    response.raise_for_status()

    data = response.json().get("data", {})

    return {
        "value": int(data.get("value", 0)),
        "classification": data.get("value_classification", ""),
        "timestamp": data.get("timestamp", ""),
    }


def get_fear_greed_history(
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """
    Fetch CMC Fear & Greed history with pagination to bypass the 500-record limit.

    Args:
        start_date: 'YYYY-MM-DD'
        end_date:   'YYYY-MM-DD'

    Returns:
        DataFrame with columns: date, value, classification
    """
    url = f"{CMC_BASE_URL}/v3/fear-and-greed/historical"
    PAGE_SIZE = 500
    all_records = []
    start_offset = 1

    while True:
        params = {
            "limit": PAGE_SIZE,
            "start": start_offset,
        }
        response = requests.get(url, headers=_get_headers(), params=params, timeout=10)
        response.raise_for_status()
        records = response.json().get("data", [])
        if not records:
            break
        all_records.extend(records)
        if len(records) < PAGE_SIZE:
            break
        start_offset += PAGE_SIZE

    if not all_records:
        raise ValueError("No CMC F&G data returned")

    df = pd.DataFrame(all_records)
    df["date"] = pd.to_datetime(df["timestamp"].astype(int), unit="s", utc=True).dt.date
    df["value"] = df["value"].astype(int)
    df = df.rename(columns={"value_classification": "classification"})
    df = df[["date", "value", "classification"]].copy()
    df = df.sort_values("date").reset_index(drop=True)

    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end   = datetime.strptime(end_date,   "%Y-%m-%d").date()
    df = df[(df["date"] >= start) & (df["date"] <= end)]

    return df.reset_index(drop=True)


if __name__ == "__main__":
    from datetime import date, timedelta

    print("Testing CMC client...\n")

    fg = get_fear_greed_latest()
    print(f"CMC F&G Latest: {fg['value']} ({fg['classification']})")
    print(f"Timestamp: {fg['timestamp']}")

    end = date.today()
    start = end - timedelta(days=30)
    print(f"\nCMC F&G History ({start} to {end}):")
    df = get_fear_greed_history(str(start), str(end))
    print(f"  {len(df)} days returned")
    print(df.tail(5).to_string(index=False))