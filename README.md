# Fear & Greed Regime Switcher
### CMC Skill -- BNB Hack: AI Trading Agent Edition 2026

A CoinMarketCap Skill that uses the Fear & Greed Index to gate a 1H momentum trend-following strategy across BTC, ETH, BNB, and CAKE. Built for Track 2 (Strategy Skills).

**Backtest results (Jan 2020 - May 2026):** 371.67% total return, 27.75% annualised, -33.15% max drawdown, 1.163 Sharpe, 871 trades.

---

## The problem

Most crypto trading strategies apply the same logic regardless of market conditions. A momentum strategy that works in a greed regime bleeds capital in fear. Applying fixed rules across all regimes is one of the most common causes of strategy failure in crypto.

## The solution

Use the Fear & Greed Index as a regime gate, not just a signal. The index determines whether new positions are permitted and at what size. Within permitted regimes, a 1H EMA crossover system handles all entry and exit decisions.

| F&G Zone | Score | Action |
|---|---|---|
| Extreme Fear | 0-25 | No new longs. Cash only. |
| Fear | 26-49 | Longs permitted at 0.5x position size |
| Greed | 50-74 | Longs permitted at full size |
| Extreme Greed | 75-100 | Full size, tighter trailing stop (1.5x ATR vs 2x) |

---

## Strategy rules

**Entry (all conditions required on the same 1H bar)**
1. EMA(20) crosses above EMA(50)
2. RSI(14) above 50
3. Close above EMA(200)
4. F&G score above 25

**Exit (first trigger wins)**
1. EMA(20) crosses below EMA(50)
2. Trailing stop breached: `close < high_water - ATR_mult x ATR(14)`
3. F&G drops to Extreme Fear zone

**Position sizing**
- Base slot = `equity / max_positions` (max 2 concurrent)
- Fear zone multiplier: 0.5x
- Extreme Fear: no new entries

**Token ranking**
When multiple entry signals fire on the same bar, rank by `ROC(10) x Volume_Ratio(20)` and take the top 2.

---

## Backtest results (Jan 2020 - May 2026)

| Metric | This Strategy | BTC Buy & Hold |
|---|---|---|
| Total Return | 371.67% | ~900% |
| Annualised Return | 27.75% | ~50% |
| Max Drawdown | -33.15% | -77% |
| Sharpe Ratio | 1.163 | ~0.65 |
| Total Trades | 871 | 1 |
| Win Rate | 36.51% | -- |
| Profit Factor | 1.371 | -- |

The strategy does not outperform BTC raw returns in a sustained bull market. The edge is risk-adjusted: less than half the drawdown of buy-and-hold, with a Sharpe ratio nearly double. The F&G gate keeps capital in cash during Extreme Fear periods, which historically coincide with the worst drawdown phases (COVID crash March 2020, crypto winter 2022).

F&G data is stitched from two sources: Alternative.me covers January 2020 to June 2023, CoinMarketCap API covers July 2023 to present. CMC is the primary live data source.

*BTC buy-and-hold benchmark calculated from $7,200 (Jan 1 2020) to $76,307 (May 1 2026). Source: CoinMarketCap historical data. Sharpe ratio estimated using daily returns over the same period.*

---

## Architecture

```
fg-regime-switcher/
├── skill.py                     CLI entry point
├── regime_detector.py           F&G gate: zone classification, size multiplier
├── strategy_selector.py         Signal engine: indicators, entry/exit logic
├── backtester.py                Historical simulation loop (calls Binance API directly)
├── data/
│   ├── alternative_me_client.py F&G history 2018-present (free, no key)
│   └── cmc_client.py            Live F&G via CMC API
├── skills/
│   └── fg-regime-switcher/
│       └── SKILL.md             CMC Skills Marketplace discovery file
├── outputs/
│   ├── spec.json                Machine-readable strategy spec
│   ├── report.md                Performance report
│   ├── trades.csv               Full trade log
│   └── equity.csv               Equity curve
├── mcp.json                     Agent Hub MCP configuration
├── strategy_report.pdf          Full strategy report
├── .env.example
└── requirements.txt
```

---

## Data sources

| Source | Used for | Auth |
|---|---|---|
| CoinMarketCap API | Live F&G, historical F&G from Jul 2023 | API key |
| Alternative.me | F&G history Jan 2020 to Jun 2023 | None |
| Binance Public Klines | 1H OHLCV for all tokens | None |

---

## Setup

**Requirements:** Python 3.10 or above, a CoinMarketCap API key

**Step 1: Clone the repository**
```bash
git clone https://github.com/trippleyay/fg-regime-switcher
cd fg-regime-switcher
```

**Step 2: Install dependencies**
```bash
pip install -r requirements.txt
```

**Step 3: Add your CMC API key**

Copy the example environment file:
```bash
cp .env.example .env
```
Open `.env` in any text editor and replace `your_key_here` with your actual CoinMarketCap API key:
```bash
CMC_API_KEY=your_key_here
```

**Step 4: Run the strategy**

Run the full historical backtest:
```bash
python skill.py --mode backtest
```

Check the current live regime signal:
```bash
python skill.py --mode live
```

All outputs are written to the `outputs/` folder automatically.

---

## Usage

```bash
# Full historical backtest (Jan 2020 - May 2026)
python skill.py --mode backtest

# Live regime scan + current entry signals
python skill.py --mode live

# Dump strategy spec JSON only
python skill.py --mode spec
```

---

## Output files

| File | Description |
|---|---|
| `outputs/spec.json` | Machine-readable strategy spec consumable by Autonomous Trading Agents |
| `outputs/report.md` | Human-readable performance report |
| `outputs/trades.csv` | Trade-by-trade log |
| `outputs/equity.csv` | Equity curve by 1H bar |

---

## Agent integration

`spec.json` is structured for direct consumption by Autonomous Trading Agents:

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
    "sharpe_ratio": 1.163
  }
}
```

---

## CoinMarketCap Agent Hub integration

This Skill is built to run within the CoinMarketCap AI Agent Hub ecosystem. The CMC Fear & Greed endpoint is the primary live data source, accessed via the CMC API in REST mode and compatible with the Agent Hub MCP server.

To connect via MCP instead of direct REST, add the following to your MCP client config:

```json
{
  "mcpServers": {
    "cmc-mcp": {
      "url": "https://mcp.coinmarketcap.com/mcp",
      "headers": {
        "X-CMC-MCP-API-KEY": "your-api-key-here"
      }
    }
  }
}
```

The `outputs/spec.json` produced by this Skill follows the Agent Hub Skill output format and is designed to be consumed directly by Autonomous Trading Agents as a strategy payload.
A `SKILL.md` file is included in the `skills/fg-regime-switcher/` directory, structured for indexing in the CMC Skills Marketplace. Agents can read it to understand when to invoke the skill, what triggers it, and what output to expect.

---

## Limitations

- Backtest does not simulate slippage or exchange fees. Live returns will be lower.
- Alternative.me and CMC use different F&G methodologies. The two sources are stitched at July 2023 where CMC data begins. Both indices use comparable input factors and produce consistent directional classifications during overlapping periods.
- 4-token basket limits diversification by design. Interpretability and reproducibility over breadth.
- CAKEUSDT data begins February 2021 (Binance listing date). BTC, ETH, and BNB cover the full January 2020 to May 2026 window. Despite the shorter history, CAKE contributed approximately 23% of total strategy PnL, confirming it is a meaningful participant in the results rather than a cosmetic addition to the basket.

---

## Built with

- CoinMarketCap AI Agent Hub
- Alternative.me Fear & Greed API
- Binance Public API
- Python, pandas, numpy

---

*BNB Hack: AI Trading Agent Edition 2026 -- Track 2: Strategy Skills*
