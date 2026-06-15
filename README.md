# Fear & Greed Regime Switcher
### CMC Skill -- BNB Hack: AI Trading Agent Edition 2026

A CoinMarketCap Skill that uses the Fear & Greed Index to gate a 4H momentum trend-following strategy across BTC, ETH, BNB, and CAKE. Built for Track 2 (Strategy Skills).

**Backtest 1 results (Jan 2020 - Jun 2025):** 284.56% total return, 28.22% annualised, -28.97% max drawdown, 1.131 Sharpe, 181 trades.

---

## The problem

Most crypto trading strategies apply the same logic regardless of market conditions. A momentum strategy that works in a greed regime bleeds capital in fear. Applying fixed rules across all regimes is one of the most common causes of strategy failure in crypto.

## The solution

Use the Fear & Greed Index as a regime gate, not just a signal. The index determines whether new positions are permitted and at what size. Within permitted regimes, a 4H EMA crossover system handles all entry and exit decisions.

| F&G Zone | Score | Action |
|---|---|---|
| Extreme Fear | 0-25 | No new longs. Cash only. |
| Fear | 26-49 | Longs permitted at 0.5x position size |
| Greed | 50-74 | Longs permitted at full size |
| Extreme Greed | 75-100 | Full size, tighter trailing stop (1.5x ATR vs 2x) |

---

## Strategy rules

**Entry (all conditions required on the same 4H bar)**
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

## Backtest results

### Backtest 1 -- Deep historical (Alternative.me F&G + Binance 4H)

| Metric | This Strategy | BTC Buy & Hold |
|---|---|---|
| Period | Jan 2020 - Jun 2025 | Jan 2020 - Jun 2025 |
| Total Return | 284.56% | ~837% |
| Annualised Return | 28.22% | ~51% |
| Max Drawdown | -28.97% | -77% |
| Sharpe Ratio | 1.131 | ~0.65 |
| Total Trades | 181 | 1 |
| Win Rate | 41.44% | -- |
| Profit Factor | 1.735 | -- |

The strategy does not outperform BTC raw returns in a sustained bull market. The edge is risk-adjusted: less than half the drawdown of buy-and-hold, with a Sharpe ratio nearly double. The F&G gate keeps capital in cash during Extreme Fear periods, which historically coincide with the worst drawdown phases (COVID crash March 2020, crypto winter 2022).

### Backtest 2 -- Live validation (CMC F&G + Binance 4H)

| Metric | Value |
|---|---|
| Period | May 15 2026 - Jun 14 2026 |
| F&G Source | CoinMarketCap API |
| Total Return | -1.78% |
| Max Drawdown | -2.91% |
| Total Trades | 3 |
| Win Rate | 33.33% |

30-day window is too short to draw performance conclusions -- crypto trend-following strategies need multiple full cycles to show their edge. Backtest 2 exists to validate that CMC F&G data integrates correctly with the live signal layer and produces consistent regime classifications vs Alternative.me.

---

## Architecture

```
fg-regime-switcher/
├── skill.py                     CLI entry point
├── regime_detector.py           F&G gate: zone classification, size multiplier
├── strategy_selector.py         4H signal engine: indicators, entry/exit logic
├── backtester.py                Historical simulation loop
├── data/
│   ├── binance_client.py        OHLCV (Binance public API, no key required)
│   ├── alternative_me_client.py F&G history 2018-present (free, no key)
│   └── cmc_client.py            Live F&G via CMC API (Startup plan)
├── outputs/
│   ├── spec.json                Strategy spec (Backtest 1)
│   ├── report.md                Performance report
│   ├── trades.csv               Full trade log (Backtest 1)
│   ├── equity.csv               Equity curve (Backtest 1)
│   ├── bt2_spec.json            Strategy spec (Backtest 2)
│   ├── bt2_trades.csv           Trade log (Backtest 2)
│   └── bt2_equity.csv           Equity curve (Backtest 2)
├── .env.example
└── requirements.txt
```

---

## Data sources

| Source | Used for | Auth |
|---|---|---|
| CoinMarketCap API | Live F&G, Backtest 2 | API key (Startup plan) |
| Alternative.me | F&G history 2018-present, Backtest 1 | None |
| Binance Public Klines | 4H OHLCV for all tokens | None |

---

## Setup

**Requirements:** Python 3.10 or above, a CoinMarketCap API key (Startup plan or above)

**Step 1 -- Clone the repository**
```bash
git clone https://github.com/trippleyay/fg-regime-switcher
cd fg-regime-switcher
```

**Step 2 -- Install dependencies**
```bash
pip install -r requirements.txt
```

**Step 3 -- Add your CMC API key**

Copy the example environment file and open it:
```bash
cp .env.example .env
```
Open `.env` in any text editor and replace `your_key_here` with your actual CoinMarketCap API key:
```bash
CMC_API_KEY=your_key_here
```
**Step 4 -- Run the strategy**

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
# Backtest 1: full historical (Jan 2020 - Jun 2025, Alternative.me F&G)
python skill.py --mode backtest

# Backtest 2: last 30 days (CMC F&G)
python skill.py --mode backtest2

# Quick smoke test (30-day window, Alternative.me F&G)
python skill.py --mode backtest --quick

# Live regime scan + current entry signals
python skill.py --mode live

# Dump strategy spec JSON only
python skill.py --mode spec
```

---

## Output files

| File | Description |
|---|---|
| `outputs/spec.json` | Machine-readable strategy spec, consumable by a Track 1 agent |
| `outputs/report.md` | Human-readable performance report |
| `outputs/trades.csv` | Trade-by-trade log (Backtest 1) |
| `outputs/equity.csv` | Equity curve by 4H bar (Backtest 1) |
| `outputs/bt2_*.csv` | Same outputs for Backtest 2 |

---

## Track 1 integration

`spec.json` is structured for direct consumption by a Track 1 autonomous trading agent:

```json
{
  "name": "Fear & Greed Regime Switcher -- 4H Momentum",
  "timeframe": "4H",
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
    "total_return_pct": 284.56,
    "sharpe_ratio": 1.131
  }
}
```

---

## Limitations

- Backtest does not simulate slippage or exchange fees. Live returns will be lower.
- Alternative.me and CMC use different F&G methodologies. Historical backtest uses Alternative.me for data depth (2018-present). Live mode uses CMC as the primary source. The methodology gap is a documented limitation, not a hidden one.
- 4-token basket limits diversification by design. Interpretability and reproducibility over breadth.
- 1,097-day maximum drawdown duration reflects the 2022-2024 crypto winter. The strategy reduced drawdown severity vs buy-and-hold but the recovery period was long.

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

The `outputs/spec.json` produced by this Skill follows the Agent Hub Skill output format and is designed to be consumed directly by a Track 1 autonomous trading agent as a strategy payload.

---

## Built with

- CoinMarketCap AI Agent Hub
- Alternative.me Fear & Greed API
- Binance Public API
- Python, pandas, numpy

---

*BNB Hack: AI Trading Agent Edition 2026 -- Track 2: Strategy Skills*
