# Transcript-derived setup backtest — batch 1

Generated 2026-09-24 on `gpt-research-audit`.

## Scope and fidelity

This is a first objective comparison of setups extracted from `Maroju100/youtube_transcripts`.

Common test controls:
- universe: AMD, MU, WDC, SNDK, TSM, INTC, LRCX, STX
- data: regular-session 30-minute OHLCV
- window: 2026-06-22 through 2026-09-21
- starting capital: $17,500
- max allocation per trade: 25% of starting capital
- long-only
- one position per symbol
- objective exits: setup stop, 2R target, or end-of-day
- friction: 0 bps and 5 bps per side

These are **proxies**, not claims to reproduce the creators' full strategies. Inputs not present in the dataset — premarket bars, float, breaking-news catalysts, Level II, tape reading, discretionary support/resistance, or subjective supply/demand zones — are not fabricated.

## Extracted / normalized rules

### Ross Cameron — first pullback momentum proxy
Transcript anchors: gap higher, elevated relative volume, first pullback, no more than 50% retracement, hold VWAP and 9 EMA.

Mechanical proxy:
- gap >= 2%
- first-bar relative volume >= 1.5x median recent first-bar volume
- initial thrust during first hour
- first red pullback retraces <= 50% of the thrust
- pullback holds VWAP / EMA9 area
- enter on continuation after the pullback

### Humbled Trader — gap/reclaim proxy
Transcript anchors: large-cap gappers, key-level / high-of-day breakout, VWAP and 8 EMA confirmation.

Mechanical proxy:
- gap >= 2.5%
- reclaim/break first 30-minute high
- close above VWAP and EMA8
- stop at running intraday low

### ChartFanatics / Clement — VWAP-reclaim opening-range continuation
Transcript anchors: first candle down, reclaim VWAP / short moving averages, break opening-range high, stop at low of day.

Mechanical proxy:
- short daily uptrend filter
- first 30-minute bar closes down
- subsequent VWAP reclaim
- break first 30-minute high
- stop at running low of day

### Live Traders — relative-strength / ATR breakout proxy
Transcript anchors: relative strength versus market, ATR direction / remaining range, breakout continuation.

Mechanical proxy:
- first-hour return at least 0.5 percentage points stronger than peer-universe average
- less than 80% of recent average daily range already consumed
- break first-hour high
- stop beneath recent local low

### Riley Coleman — pullback trend continuation proxy
Transcript anchors: identify uptrend via higher highs/higher lows, enter on pullback rather than chase, manage risk beneath swing low.

Mechanical proxy:
- first hour forms higher high and higher low
- later red pullback remains above initial low
- enter on break above pullback high
- stop beneath pullback low

### Not included in the first mechanical table
The Trading Geek's supply/demand/order-block framework was reviewed but not included because the extracted material relies on discretionary zone construction, multi-timeframe context, and lower-timeframe confirmation. A mechanical rule would require inventing definitions not stated clearly enough in the transcripts.

## Side-by-side results

| Setup | Return 0 bps | Return 5 bps | 5-bps sensitivity | Sharpe (5 bps) | Max DD (5 bps) | Win rate (5 bps) | Trades | Profit factor (5 bps) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Ross Cameron — first pullback | -0.42% | **-0.55%** | -0.13 pp | -1.73 | -0.66% | 14.3% | 7 | 0.249 |
| Humbled Trader — gap/reclaim | -0.79% | **-1.64%** | -0.85 pp | -1.04 | -2.97% | 50.0% | 34 | 0.747 |
| ChartFanatics/Clement — ORH reclaim | -1.49% | **-1.99%** | -0.50 pp | -1.89 | -2.97% | 40.0% | 20 | 0.483 |
| Live Traders — relative-strength ATR breakout | -4.14% | **-5.16%** | -1.02 pp | -2.39 | -8.63% | 36.6% | 41 | 0.496 |
| Riley Coleman — pullback trend continuation | -0.55% | **-2.29%** | -1.74 pp | -1.28 | -4.16% | 35.8% | 95 | 0.824 |

## Interpretation

1. None of the five objective transcript proxies produced a positive return in this test.
2. The result does **not** establish that the creators' original strategies fail. The test universe is eight semiconductor stocks and the bars are 30-minute regular-session data, while several source strategies were designed around other universes, premarket information, lower timeframes, catalysts, float, Level II or discretionary chart context.
3. Riley's proxy had the highest profit factor of the five at 0.824 after 5-bps friction, but remained negative.
4. Ross had only seven trades, so its result is too sparse to support a strong conclusion.
5. Humbled's 50% win rate did not translate to profitability because losses outweighed wins; profit factor was 0.747.
6. Five-bps friction reduced every setup. Riley was most sensitive in percentage-point terms (-1.74 pp).
7. This batch provides no evidence to replace or modify B0 using these transcript-derived proxies.

## Next research gate

Before rejecting the source strategies themselves, a higher-fidelity second batch should use:
- 1-minute or 5-minute bars,
- premarket data,
- a broad equity universe including small-cap momentum names,
- historical relative volume,
- float / liquidity filters where explicitly required,
- creator-specific exit rules where they can be made objective.

Until then these results should be interpreted as **"these normalized proxies do not transfer successfully to the current semiconductor 30-minute environment,"** not as verdicts on the original creators or strategies.
