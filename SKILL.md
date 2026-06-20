---
name: fg-regime-switcher
description: "Fear & Greed Regime Switcher -- generates a backtestable 1H momentum trading strategy spec by using the CMC Fear & Greed Index as a regime gate across BTC, ETH, BNB, and CAKE. Use this skill whenever the user wants a trading strategy spec, asks about crypto market regime, wants to know whether to go long based on Fear & Greed, or needs position sizing guidance from sentiment data. Trigger: 'trading strategy', 'fear greed regime', 'should I go long', 'market regime', 'position sizing', 'momentum strategy', 'BTC ETH BNB CAKE strategy', '/fg-regime-switcher'"
user-invocable: true
allowed-tools:
  - Bash: Read
---

# Fear & Greed Regime Switcher Skill

This skill uses the CMC Fear & Greed Index to classify the current market regime and outputs a structured, backtestable trading strategy spec for BTC, ETH, BNB, and CAKE.

## What this skill does

1. Fetches the current Fear & Greed score from the CMC API
2. Classifies the regime (Extreme Fear / Fear / Greed / Extreme Greed)
3. Determines position sizing and entry permissions for the regime
4. Scans BTC, ETH, BNB, and CAKE for active 1H EMA crossover entry signals
5. Returns a structured strategy spec with entry rules, exit rules, and position sizing parameters

## When to use this skill

- User asks "should I go long on crypto right now?"
- User wants a data-driven trading strategy based on market sentiment
- User wants to know the current Fear & Greed regime and what it means for positioning
- User needs a backtestable strategy spec for an autonomous trading agent
- User asks about momentum trading across BTC, ETH, BNB, or CAKE

## Authentication

Requires CMC API key with Fear & Greed access.

```
X-CMC_PRO_API_KEY: your-api-key
```

Get your API key at: https://pro.coinmarketcap.com/login

## CMC Endpoints Used

| Endpoint | Purpose |
|---|---|
| GET /v3/fear-and-greed/latest | Live regime classification |
| GET /v3/fear-and-greed/historical | Historical F&G for backtesting |

## Regime Gate Logic

| F&G Score | Zone | Allow Long | Position Size |
|---|---|---|---|
| 0-25 | Extreme Fear | No | 0% (cash only) |
| 26-49 | Fear | Yes | 50% of standard slot |
| 50-74 | Greed | Yes | 100% of standard slot |
| 75-100 | Extreme Greed | Yes | 100%, tighter trail stop |

## Entry Conditions (all required on same 1H bar)

1. EMA(20) crosses above EMA(50)
2. RSI(14) above 50
3. Close above EMA(200)
4. F&G score above 25

## Exit Conditions (first trigger wins)

1. EMA(20) crosses below EMA(50)
2. Trailing stop: close below high-water minus ATR multiplier times ATR(14)
3. F&G drops to Extreme Fear zone

## Token Ranking

When multiple entry signals fire simultaneously, rank by:
`Momentum Score = ROC(10) x Volume_Ratio(20)`
Take top 2 by score.

## Output Format

The skill outputs a `spec.json` with this structure:

```json
{
  "name": "Fear & Greed Regime Switcher -- Momentum Strategy",
  "tokens": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "CAKEUSDT"],
  "max_positions": 2,
  "entry_rules": ["EMA(20) crosses above EMA(50)", "RSI(14) > 50", "Close > EMA(200)", "F&G > 25"],
  "exit_rules": ["EMA(20) crosses below EMA(50)", "Trailing stop", "F&G <= 25"],
  "position_sizing": {
    "fg_fear_multiplier": 0.5,
    "atr_trail_multiplier_normal": 2.0,
    "atr_trail_multiplier_extreme_greed": 1.5
  },
  "backtest_results": {
    "total_return_pct": 371.67,
    "annualised_return_pct": 27.75,
    "max_drawdown_pct": -33.15,
    "sharpe_ratio": 1.163,
    "n_trades": 871
  }
}
```

## Usage

### Live regime + signals
```bash
python skill.py --mode live
```

### Full backtest (Jan 2020 - May 2026)
```bash
python skill.py --mode backtest
```

### Strategy spec only
```bash
python skill.py --mode spec
```

## Installation

```bash
git clone https://github.com/trippleyay/fg-regime-switcher
cd fg-regime-switcher
pip install -r requirements.txt
cp .env.example .env
# Add your CMC API key to .env
```

## Backtest Performance (Jan 2020 - May 2026)

| Metric | Value |
|---|---|
| Total Return | 371.67% |
| Annualised Return | 27.75% |
| Max Drawdown | -33.15% |
| Sharpe Ratio | 1.163 |
| Total Trades | 871 |
| Win Rate | 36.51% |
| Profit Factor | 1.371 |

Benchmark: BTC buy-and-hold returned approximately 960% over the same period with a -77% maximum drawdown. The strategy's edge is risk-adjusted: Sharpe ratio of 1.163 vs approximately 0.65 for buy-and-hold.

## Data Sources

- CoinMarketCap API (live F&G, historical F&G from July 2023)
- Alternative.me (historical F&G, January 2020 to June 2023)
- Binance Public Klines (1H OHLCV, no key required)

## Repository

https://github.com/trippleyay/fg-regime-switcher