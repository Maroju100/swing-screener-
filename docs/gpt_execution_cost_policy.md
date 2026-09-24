# GPT Audit: Robinhood Execution-Cost Policy

## Principle

Robinhood's $0 equity commission does **not** imply zero implementation shortfall.
For the Margin-Style research, separate three concepts:

1. **Broker commission** — $0 for eligible U.S.-listed equities in the Robinhood self-directed account.
2. **Regulatory pass-through fees** — small sell-side SEC/FINRA fees may apply depending on the order/share amount and current fee schedule.
3. **Execution friction** — bid/ask spread, timing between signal and fill, market impact, and adverse price movement. These exist even when commission is $0 and are what the replay's synthetic `cost_bps` is primarily intended to stress.

## Research policy

- Report **0 bps** as the frictionless/commission-free reference case.
- Do **not** call 5 bps a Robinhood fee. It is a conservative execution-friction stress assumption.
- Keep a sensitivity sweep rather than choosing one arbitrary cost assumption.
- Default GPT audit sweep: **0, 1, 2.5, 5, 10 bps per side**.
- Where real broker fills and contemporaneous signal/reference prices exist, estimate empirical implementation shortfall and use that measured distribution to calibrate the synthetic stress levels.
- Regulatory fees should eventually be modeled separately from slippage/spread if they are material at the account's trade sizes.

## Interpretation

A strategy that works only at 0 bps is fragile even at a commission-free broker. A strategy that survives realistic measured implementation shortfall is more credible. Conversely, applying 5 bps mechanically as if Robinhood charges a 5-bps commission would understate performance and misdescribe the cost source.

This policy is research-only and does not modify the production live engine.