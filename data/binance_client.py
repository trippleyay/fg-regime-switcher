"""
Binance Public Klines Client
Fetches daily OHLCV data for the token basket.
No API key required.
"""

import time
import requests
import pandas as pd
from datetime import datetime, timezone


BASE_URL = "https://api1.binance.com/api/v3/klines"

# Token basket — Binance trading pairs (USDT quoted)
TOKEN_PAIRS = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "BNB": "BNBUSDT",
    "CAKE": "CAKEUSDT",
}

# Binance max candles per request
MAX_LIMIT = 1000


def fetch_ohlcv(
    symbol: str,
    start_date: str,
    end_date: str,
    interval: str = "1d",
) -> pd.DataFrame:
    """
    Fetch daily OHLCV data for a single symbol from Binance.

    Args:
        symbol:     Binance pair e.g. 'BTCUSDT'
        start_date: 'YYYY-MM-DD'
        end_date:   'YYYY-MM-DD'
        interval:   Binance interval string, default '1d'

    Returns:
        DataFrame with columns: date, open, high, low, close, volume
    """
    start_ts = int(
        datetime.strptime(start_date, "%Y-%m-%d")
        .replace(tzinfo=timezone.utc)
        .timestamp()
        * 1000
    )
    end_ts = int(
        datetime.strptime(end_date, "%Y-%m-%d")
        .replace(tzinfo=timezone.utc)
        .timestamp()
        * 1000
    )

    all_candles = []
    current_start = start_ts

    while current_start < end_ts:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": current_start,
            "endTime": end_ts,
            "limit": MAX_LIMIT,
        }

        response = requests.get(BASE_URL, params=params, timeout=10)
        response.raise_for_status()
        candles = response.json()

        if not candles:
            break

        all_candles.extend(candles)

        # Advance start to after the last returned candle
        current_start = candles[-1][0] + 1

        # Respect Binance rate limits
        time.sleep(0.1)

    if not all_candles:
        raise ValueError(f"No data returned for {symbol} between {start_date} and {end_date}")

    df = pd.DataFrame(all_candles, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ])

    df["date"] = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.date
    df = df[["date", "open", "high", "low", "close", "volume"]].copy()

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    df = df.sort_values("date").reset_index(drop=True)

    return df


def fetch_all_tokens(
    start_date: str,
    end_date: str,
    interval: str = "1d",
) -> dict[str, pd.DataFrame]:
    """
    Fetch OHLCV data for all tokens in the basket.

    Returns:
        Dict mapping token name to DataFrame e.g. {"BTC": df, "ETH": df, ...}
    """
    result = {}

    for token, pair in TOKEN_PAIRS.items():
        print(f"Fetching {token} ({pair})...")
        df = fetch_ohlcv(pair, start_date, end_date, interval)
        result[token] = df
        print(f"  {token}: {len(df)} candles from {df['date'].iloc[0]} to {df['date'].iloc[-1]}")

    return result


if __name__ == "__main__":
    # Quick test — fetch last 30 days for all tokens
    from datetime import timedelta

    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=30)

    print(f"Testing Binance client: {start} to {end}\n")

    data = fetch_all_tokens(str(start), str(end))

    for token, df in data.items():
        print(f"\n{token} — {len(df)} rows")
        print(df.tail(3).to_string(index=False))
