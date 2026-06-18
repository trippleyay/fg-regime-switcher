"""
CoinMarketCap API Client
Fetches live Fear & Greed, stablecoin dominance, and global metrics.
Requires CMC API key (Startup plan or above).
"""

import os
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta
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
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    df = df[(df["date"] >= start) & (df["date"] <= end)]

    return df.reset_index(drop=True)


def get_global_metrics() -> dict:
    """
    Fetch current global crypto market metrics.

    Returns:
        Dict with keys:
            total_market_cap_usd
            total_volume_24h_usd
            btc_dominance
            stablecoin_market_cap_usd
            stablecoin_dominance (stablecoin mcap / total mcap * 100)
            defi_market_cap_usd
            last_updated
    """
    url = f"{CMC_BASE_URL}/v1/global-metrics/quotes/latest"

    response = requests.get(url, headers=_get_headers(), timeout=10)
    response.raise_for_status()

    data = response.json().get("data", {})
    quote = data.get("quote", {}).get("USD", {})

    total_mcap = quote.get("total_market_cap", 0)
    stablecoin_mcap = quote.get("stablecoin_market_cap", 0)
    stablecoin_dominance = (
        (stablecoin_mcap / total_mcap * 100) if total_mcap > 0 else 0
    )

    return {
        "total_market_cap_usd": total_mcap,
        "total_volume_24h_usd": quote.get("total_volume_24h", 0),
        "btc_dominance": data.get("btc_dominance", 0),
        "stablecoin_market_cap_usd": stablecoin_mcap,
        "stablecoin_dominance": round(stablecoin_dominance, 4),
        "defi_market_cap_usd": quote.get("defi_market_cap", 0),
        "last_updated": data.get("last_updated", ""),
    }


def get_stablecoin_dominance_trend(days: int = 7) -> str:
    """
    Determine stablecoin dominance trend over the last N days.
    Uses CMC F&G historical as a proxy for date alignment.

    Since stablecoin dominance historical isn't directly available
    on Startup plan, we compute trend from the last available
    global metrics snapshots via the 30-day F&G window.

    For live mode: compares current stablecoin dominance against
    the 7-day average derived from global metrics history.

    Returns:
        'rising'  — stablecoins growing as % of market (fear signal)
        'falling' — stablecoins shrinking as % of market (greed signal)
        'flat'    — no meaningful change
    """
    url = f"{CMC_BASE_URL}/v1/global-metrics/quotes/historical"

    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=days)

    params = {
        "time_start": start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "time_end": end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "interval": "daily",
    }

    response = requests.get(url, headers=_get_headers(), params=params, timeout=10)
    response.raise_for_status()

    quotes = response.json().get("data", {}).get("quotes", [])

    if len(quotes) < 2:
        return "flat"

    def extract_dominance(q):
        usd = q.get("quote", {}).get("USD", {})
        total = usd.get("total_market_cap", 0)
        stable = usd.get("stablecoin_market_cap", 0)
        return (stable / total * 100) if total > 0 else 0

    dominance_series = [extract_dominance(q) for q in quotes]

    first_half_avg = sum(dominance_series[:3]) / 3
    second_half_avg = sum(dominance_series[-3:]) / 3

    diff = second_half_avg - first_half_avg

    if diff > 0.3:
        return "rising"
    elif diff < -0.3:
        return "falling"
    else:
        return "flat"


if __name__ == "__main__":
    print("Testing CMC client...\n")

    # Latest F&G
    fg = get_fear_greed_latest()
    print(f"CMC F&G Latest: {fg['value']} ({fg['classification']})")
    print(f"Timestamp: {fg['timestamp']}")

    # Global metrics
    print("\nGlobal Metrics:")
    metrics = get_global_metrics()
    for k, v in metrics.items():
        if isinstance(v, float) and v > 1_000_000:
            print(f"  {k}: ${v:,.0f}")
        else:
            print(f"  {k}: {v}")

    # Stablecoin dominance trend
    trend = get_stablecoin_dominance_trend(days=7)
    print(f"\nStablecoin dominance trend (7d): {trend}")

    # 30-day F&G history
    from datetime import date
    end = date.today()
    start = end - timedelta(days=30)
    print(f"\nCMC F&G History ({start} to {end}):")
    df = get_fear_greed_history(str(start), str(end))
    print(f"  {len(df)} days returned")
    print(df.tail(5).to_string(index=False))
