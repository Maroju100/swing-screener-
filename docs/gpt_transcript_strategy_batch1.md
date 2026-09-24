# Transcript-derived strategy backtest — Batch 1

Generated 2026-09-24 on `gpt-research-audit`. Production `main` unchanged.

## Scope

Source concepts were extracted from `Maroju100/youtube_transcripts`.

Two research harnesses were run:

1. **30-minute proxy suite**, 2026-06-22..2026-09-21, $17,500 starting capital, 5 bps/side, 0.5% equity risk per trade, max 25% notional.
2. **1-minute batch 1**, 2026-08-10..2026-09-21, real regular-session 1-minute bars for MU/SNDK/WDC only, same capital/risk/cost assumptions.

These are mechanical proxies of public transcript descriptions, not claims to reproduce the creators' full discretionary methods.

## 30-minute proxy suite

| Setup | Trades | Win rate | P/L | Return | Profit factor | Sharpe | Max DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| Ross Cameron — first pullback proxy | 9 | 44.44% | -$38.30 | -0.22% | 0.797 | -1.727 | -0.87% |
| Humbled Trader — gap/reclaim proxy | 30 | 43.33% | -$187.26 | -1.07% | 0.708 | -2.496 | -1.46% |
| ChartFanatics — OR high/VWAP reclaim proxy | 35 | 45.71% | -$80.85 | -0.46% | 0.896 | -0.733 | -2.15% |
| Scarface Trades — prior-day-high retest proxy | 52 | 40.38% | +$45.43 | +0.26% | 1.039 | 0.235 | -3.47% |

The small positive Scarface proxy is not strong enough to count as a validated edge: profit factor is barely above 1 and the return is only +0.26%.

## 1-minute batch 1

Data source: real Robinhood regular-session 1-minute bars, 30 trading days, MU/SNDK/WDC.

| Setup | Trades | Win rate | P/L | Return | Profit factor | Sharpe | Max DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| ChartFanatics opening-range/VWAP reclaim, 2R | 18 | 33.33% | -$426.48 | -2.44% | 0.420 | -6.992 | -3.15% |
| ChartFanatics opening-range/VWAP reclaim, EOD exit | 18 | 33.33% | -$451.74 | -2.58% | 0.385 | -7.897 | -3.15% |
| Scarface first-candle break/retest, 2R | 56 | 30.36% | -$1,194.72 | -6.83% | 0.687 | -4.540 | -10.07% |
| Ross first-pullback momentum | — | — | — | — | — | — | — |

The Ross setup was deliberately **not run** in the 1-minute batch because a faithful test requires the creator's intended small-cap universe plus relative-volume, float, gap/catalyst and related scanner data. Applying it only to MU/SNDK/WDC would answer a different question.

## Interpretation

1. None of the first-batch transcript-derived proxies demonstrates a robust edge on the available semiconductor dataset.
2. The 30-minute Scarface retest proxy is approximately flat and should not be promoted.
3. Finer 1-minute testing makes the ChartFanatics and Scarface proxies look worse, not better.
4. The current B0 swing strategy remains materially stronger than these transcript proxies on the evidence tested so far.
5. This does **not** prove the original creators' discretionary strategies do not work. The data lacks several important parts of their stated process, including small-cap universe selection, premarket data, catalysts, float, Level 2/tape reading, and some creator-specific discretion.

## Next research gate

For a fairer second batch, obtain or build a historical small-cap intraday universe with:
- premarket + regular-session minute bars,
- gap percentage,
- relative volume,
- float / shares outstanding,
- catalyst/news flag where possible,
- sufficient breadth to reproduce scanner selection.

Until then, transcript rules should remain a separate research track and should not be merged into production B0.


## Normalized 0-bps vs 5-bps comparison

A second normalized harness was added after the first batch so the same five objective proxies could be tested both before and after execution-cost stress.

| Setup | 0-bps return | 5-bps return | 5-bps Sharpe | Max DD | Win rate | Trades | Profit factor | 5-bps impact |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Ross Cameron — first pullback momentum proxy | -0.42% | -0.55% | -1.725 | -0.66% | 14.3% | 7 | 0.249 | -0.13 pp |
| Humbled Trader — gap/reclaim proxy | -0.79% | -1.64% | -1.041 | -2.97% | 50.0% | 34 | 0.747 | -0.85 pp |
| ChartFanatics/Clement — ORH reclaim continuation | -1.49% | -1.99% | -1.894 | -2.97% | 40.0% | 20 | 0.483 | -0.50 pp |
| Live Traders — relative-strength / ATR breakout | -4.14% | -5.16% | -2.394 | -8.63% | 36.6% | 41 | 0.496 | -1.02 pp |
| Riley Coleman — pullback trend continuation | -0.55% | -2.29% | -1.279 | -4.16% | 35.8% | 95 | 0.824 | -1.74 pp |

The Trading Geek supply/demand/order-block material remains excluded from this normalized batch because its zone construction and multi-timeframe context are too subjective to encode defensibly from the transcript alone.

The normalized result is stricter than the original proxy suite: all five tested setups were negative even at zero transaction cost, and all deteriorated further at 5 bps/side. This supports keeping transcript-derived rules out of production B0 until they can be tested on a dataset matching their intended market/universe.
