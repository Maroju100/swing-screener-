# Transcript-derived setup backtests — first proxy batch

Generated 2026-09-24 on `gpt-research-audit`.

## Scope

Source ideas were extracted from `Maroju100/youtube_transcripts` and translated into mechanical rules only where the transcript gave enough structure to avoid pure guesswork.

This first batch is a **compatibility/proxy test**, not a faithful recreation of each creator's full strategy:

- universe: AMD, MU, WDC, SNDK, TSM, INTC, LRCX, STX
- period: 2026-06-22 .. 2026-09-21
- bars: 30-minute OHLCV
- starting capital: $17,500
- execution friction: 5 bps per side
- risk budget: 0.5% of equity per trade
- max position: 25% of equity
- long side only
- target: 2R, otherwise end-of-day exit
- conservative same-bar ordering: stop assumed before target if both touched

## Transcript rules used

### Ross Cameron — first pullback pattern

Transcript-derived objective elements:
- strong momentum stock
- first pullback
- pullback should not retrace more than 50% of the impulse
- red/pullback volume lighter than impulse volume
- hold above VWAP
- hold above 9 EMA
- creator also emphasizes gap/relative-volume/float/catalyst/Level-2 filters

Proxy approximation:
- first two 30-minute bars form the impulse
- third 30-minute bar is the first pullback
- fourth bar breaks the pullback high
- float, true relative-volume scanner, catalyst, Level 2, tape reading, small-cap price filter, and 1m/5m timing are unavailable and therefore omitted

Result:
- 9 trades
- 44.44% win rate
- realized P&L: -$38.30
- return: -0.22%
- profit factor: 0.797
- max drawdown: -0.87%

Interpretation: the pattern component alone did not show an edge in this universe/sample. This is **not** a valid test of the full Ross Cameron strategy because the stock-selection layer is central to his stated method.

### Humbled Trader — gap/reclaim

Transcript-derived objective elements:
- focus on gappers / high-volume names
- examples include gap-up stocks, premarket/key-level reclaim, and VWAP/EMA confirmation

Proxy approximation:
- >=2% regular-session opening gap vs prior close
- opening bar sells off but recovers above its midpoint
- next bar breaks the 30-minute opening-range high and is above VWAP
- no premarket-high, catalyst, or tape filter

Result:
- 30 trades
- 43.33% win rate
- realized P&L: -$187.26
- return: -1.07%
- profit factor: 0.708
- max drawdown: -1.46%

Interpretation: this simplified large-cap gap/reclaim proxy did not show an edge in the tested semiconductor sample.

### ChartFanatics — opening-range/VWAP reclaim pullback

Transcript-derived objective elements:
- initial flush
- reclaim intraday VWAP / shorter moving averages
- break opening-range high
- volume confirmation
- stop at low of day

Proxy approximation:
- uses a 30-minute opening range rather than the described 5-minute opening range
- entry after close above opening-range high, VWAP and short EMA
- stop at low of day

Result:
- 35 trades
- 45.71% win rate
- realized P&L: -$80.85
- return: -0.46%
- profit factor: 0.896
- max drawdown: -2.15%

Interpretation: close to breakeven but negative. The 30-minute approximation is materially coarser than the source setup and should not be treated as a faithful test.

### Scarface Trades — prior-day-high retest

Transcript-derived objective elements:
- previous-day high/low break
- retest of the level
- strong price action on the retest
- stop beyond the structure
- seek at least 2R

Proxy approximation:
- long side only
- first close above prior-day high
- retest within the next two 30-minute bars
- retest bar trades back to the level and closes green above it
- stop below retest structure
- 2R target / EOD fallback

Result:
- 52 trades
- 40.38% win rate
- realized P&L: +$45.43
- return: +0.26%
- profit factor: 1.039
- max drawdown: -3.47%

Interpretation: slightly positive but far too weak to call validated. It is the only first-batch proxy with profit factor >1.

## Ranking by this proxy sample

1. Scarface prior-day-high retest: +0.26%, PF 1.039
2. Ross first-pullback pattern component: -0.22%, PF 0.797
3. ChartFanatics OR/VWAP reclaim: -0.46%, PF 0.896
4. Humbled Trader gap/reclaim: -1.07%, PF 0.708

This ordering applies only to this proxy specification and semiconductor sample. It is not a ranking of the creators or their actual strategies.

## Main finding

The stock-selection and data-resolution layers matter enormously. Several transcript strategies depend on:
- 1-minute or 5-minute bars
- premarket highs/lows and premarket volume
- true relative volume vs 50-day averages
- float / shares outstanding
- catalyst/news filters
- Level 2 / tape behavior

The existing B0 dataset cannot faithfully represent those inputs. Therefore the next serious test should obtain a small-cap / large-cap intraday dataset with 1m/5m bars plus premarket data and, where possible, float and relative-volume features. Only then should the Ross/Humbled/ChartFanatics setups be judged on their intended universe.
