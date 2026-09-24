# YouTube transcript strategy backtests — Batch 1 results

Generated on 2026-09-24 on `gpt-research-audit`. Research-only. Production `main` remains unchanged.

## 1-minute semiconductor test (2026-08-10..2026-09-21)

Common comparison harness:
- Starting capital: $17,500
- Risk per trade: 0.50% of current equity
- Execution stress: 5 bps per side
- Max one trade per symbol/day
- Regular-hours 1-minute bars
- Fixed semiconductor universe only

| Setup proxy | Trades | Win rate | Net P/L | Return | Profit factor | Max DD |
|---|---:|---:|---:|---:|---:|---:|
| ChartFanatics opening-range/VWAP reclaim, 2R | 18 | 33.33% | -$426.48 | -2.44% | 0.420 | -3.15% |
| ChartFanatics opening-range/VWAP reclaim, EOD exit | 18 | 33.33% | -$451.74 | -2.58% | 0.385 | -3.15% |
| Scarface first-candle break/retest, 2R | 56 | 30.36% | -$1,194.72 | -6.83% | 0.687 | -10.07% |
| Ross Cameron first-pullback momentum | — | — | — | — | — | — |

Ross Cameron was deliberately not run in the 1-minute semiconductor batch because his transcript setup depends on a small-cap scanner universe, relative volume, float, gap/catalyst and other selection criteria that are not present in the current research dataset. A semiconductor-only pattern test would not be a faithful strategy test.

## Earlier 30-minute proxy study (2026-06-22..2026-09-21)

These are coarser approximations and should not be treated as creator-strategy performance.

| Setup proxy | Trades | Win rate | Net P/L | Return | Profit factor | Max DD |
|---|---:|---:|---:|---:|---:|---:|
| Ross first-pullback pattern proxy | 9 | 44.44% | -$38.30 | -0.22% | 0.797 | -0.87% |
| Humbled Trader gap/reclaim proxy | 30 | 43.33% | -$187.26 | -1.07% | 0.708 | -1.46% |
| ChartFanatics OR-high/VWAP reclaim proxy | 35 | 45.71% | -$80.85 | -0.46% | 0.896 | -2.15% |
| Scarface prior-day-high retest proxy | 52 | 40.38% | +$45.43 | +0.26% | 1.039 | -3.47% |

## Interpretation

1. None of the first transcript-derived proxies shows a robust edge on the existing semiconductor dataset.
2. The 1-minute tests are more relevant for intraday setups than the earlier 30-minute approximations, and both tested 1-minute proxies are negative.
3. This does **not** establish that the creators' original strategies are unprofitable. Their stock-selection universes and discretionary filters are materially different from the fixed semiconductor universe used here.
4. The Ross Cameron strategy is especially inappropriate to judge from this dataset because the stock-selection edge is part of the strategy itself.
5. The next useful step is to acquire a broad historical small-cap universe with minute bars plus daily volume/relative-volume, gap, float and ideally catalyst/news fields, then freeze the scanner rules before testing entries.

## Deployment gate

No transcript-derived setup should be added to the current B0 production strategy based on these results.
