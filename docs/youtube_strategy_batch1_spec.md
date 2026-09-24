# YouTube transcript strategy extraction — Batch 1

Research-only work on `gpt-research-audit`. No production trading code is modified.

## Method

A setup is admitted to quantitative testing only when the transcript provides rules that can be converted into observable market-data conditions without subjective interpretation. Any missing portfolio convention (capital, risk per trade, transaction cost) is explicitly labeled as a test harness assumption rather than attributed to the creator.

## A. Ross Cameron / Warrior Trading — First Pullback Momentum

**Transcript-derived rules**
- Focus on momentum stocks meeting at least four of five stock-selection pillars.
- Explicit examples/criteria include high relative volume (5x+ discussed), strong percentage gain/gap, high total volume, price generally around $2-$20, catalyst/news, and low float (under 20M shares discussed).
- Entry: after an initial move and pullback/base, buy the **first candle to make a new high**, i.e. the first candle that crosses the prior candle's high.
- Stop / max loss: the **low of the pullback**.
- Time filter: transcript states recent performance was worse after 10:00 a.m. and describes 10:00 a.m. as a practical hard stop for that period.
- Exit indicators include tape/Level-2 behavior and topping-tail/red-candle information.

**Backtest status: NEEDS DIFFERENT DATASET**
The current 1-minute research data contains the fixed semiconductor universe rather than the small-cap scanner universe. It also lacks float, catalyst/news and true market-wide relative-volume ranking. A pattern-only test on semiconductors would not be a faithful test of this strategy. Do not report one as Ross Cameron strategy performance.

## B. ChartFanatics interview — 5-minute Opening-Range Reclaim/Breakout

**Transcript-derived core**
- Example begins with an opening flush / first candle down.
- Price reclaims intraday VWAP and short-term moving averages.
- Entry confirmation when price breaks the **5-minute opening-range high**.
- Stop at the **low of day / prior low of day**.
- Framed as a continuation/pullback setup where a tight stop can earn multiples of risk.

**Objective proxy used for Batch-1 test**
- Fixed semiconductor universe because that is the available 1-minute dataset.
- First 5-minute candle must close below its open.
- Between 09:35 and 10:30 ET, trigger on first 1-minute close above the first-5-minute high while also above cumulative VWAP.
- Enter at the next 1-minute open (prevents same-bar look-ahead).
- Stop = low of day through trigger.
- Compare exits: 2R target vs end-of-day exit.
- Harness assumption: risk 0.50% of current equity per trade; max one trade per symbol/day; 5 bps/side execution stress.

This is a **mechanical proxy** for the transcript setup, not a claim to reproduce every discretionary element.

## C. Scarface Trades — First-Candle Break-and-Retest

**Transcript-derived core**
- Use the first candle / key high-low as a directional reference.
- Wait for a break and then a retest rather than chasing the first break.
- Enter only after confirming price action/candle closure.
- Stop is a break back through the relevant trigger/retest candle or first-candle level depending on example.
- Target **at least 2R** is explicitly described.

**Objective proxy used for Batch-1 test**
- First 5-minute candle direction defines the candidate side: green=long, red=short.
- Require a close beyond the opening 5-minute range.
- Then require a retest of the broken boundary within 0.10% and a close back in the breakout direction within the next 20 minutes.
- Enter next 1-minute open.
- Stop at retest candle extreme.
- Target = 2R.
- Harness assumption: risk 0.50% of current equity per trade; max one trade per symbol/day; 5 bps/side stress.

## D. Humbled Trader / Live Traders / Riley Coleman

The sampled transcripts contain useful ideas—gap scans, premarket-high reclaims, VWAP/EMA bounce logic, ATR context, relative strength, failed breakouts and dynamic risk/reward—but the examples sampled so far contain more discretionary context than the two setups above. They remain candidates for later extraction; no quantitative result should be attributed until the exact objective rule set is frozen.

## Data limits

Current minute data:
- `data/semis_1min_2026-08-10_2026-09-21.json`
- Regular-hours minute bars only.
- 30 trading days / roughly six trailing weeks.
- Fixed semiconductor universe.
- No broad-market small-cap universe, float, catalyst/news, or premarket bars.

Therefore Batch 1 is an **intraday price-action comparison on semiconductors**, not a universal test of the YouTube creators' full strategies.
