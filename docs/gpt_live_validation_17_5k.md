# GPT live-scale validation — $17.5K replay and Robinhood reconciliation

Generated 2026-09-24 on `gpt-research-audit`. Research-only; production `main` and the live engine were not modified.

## 1. Capital sensitivity: full research window (2026-03-13..2026-09-21)

Fresh full-engine replay, no P&L scaling.

| Starting capital | Cost | Realized P&L | Realized return | Total return | Sharpe | Max DD | Trades |
|---:|---:|---:|---:|---:|---:|---:|---:|
| $17,500 | 0 bps/side | $27,013.53 | 154.36% | 156.17% | 3.793 | -10.84% | 703 |
| $17,500 | 5 bps/side | $25,235.46 | 144.20% | 145.92% | 3.640 | -11.05% | 701 |
| $80,000 | 5 bps/side | $124,289.71 | 155.36% | 157.15% | 3.834 | -8.84% | 771 |

The $17.5K path retains most of the historical percentage return, but gives up about 11.16 percentage points of realized return versus the $80K replay at 5 bps and experiences a somewhat deeper drawdown.

## 2. Live-period / live-time replay at $17,500

### 2026-07-22..2026-09-21, hourly 17:00 UTC OPEN price
This starts around live activation and uses the noon-CDT price proxy, closer to the live trigger than the historical 18:00 close-price anchor.

| Cost | Realized P&L | Realized return | Total return | Sharpe | Max DD | Trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0 bps/side | $1,100.13 | 6.29% | 7.03% | 1.021 | -10.49% | 225 |
| 5 bps/side | $851.81 | 4.87% | 5.59% | 0.868 | -10.72% | 225 |

### 2026-06-22..2026-09-21, 30-minute 17:00 UTC OPEN cross-check

| Cost | Realized P&L | Realized return | Total return | Sharpe | Max DD | Trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0 bps/side | $4,509.30 | 25.77% | 26.65% | 1.860 | -10.08% | 324 |
| 5 bps/side | $4,076.78 | 23.30% | 24.15% | 1.727 | -10.22% | 324 |

The large difference between the June-start and July-start windows shows strong path/regime sensitivity. The +23.30% figure should not be treated as a generic expected three-month return.

## 3. Robinhood broker reconciliation (2026-09-08..2026-09-21)

Committed broker ground truth contains 43 fills in the linked ~$17.5K Robinhood individual account during this interval. Four fills were explicitly manual/user trades:
- 2026-09-09 MU sell 1.957520 @ 1021.70
- 2026-09-09 WDC sell 4.131460 @ 483.65
- 2026-09-18 STX buy 5.887547 @ 849.2501
- 2026-09-18 WDC buy 2.276165 @ 439.3354

For agentic fills:
- simulated date/symbol/side groups: 53
- broker agentic groups: 38
- overlapping groups: 33
- quantity matches within 1% (or 0.01 shares): only 2
- notional-weighted broker execution versus replay reference on overlapping groups: -2.98 bps (positive defined as better)

Broker realized P&L for the known agentic closing trades in this exact 2026-09-08..2026-09-21 window sums to **+$1,698.42** after excluding the two known manual sells on 2026-09-09. This is broker cost-basis P&L, not a backtest calculation.

## Interpretation

1. Capital size is not the main historical failure mode: the engine remains strongly profitable in the full historical replay at ~$17.5K.
2. More live-accurate timing lowers the result materially. On the actual live-activation window, the 5-bps replay is +4.87% realized, not anything close to the +144% six-month headline.
3. Execution price/slippage does not look like the dominant reconciliation problem. On overlapping groups, the weighted price difference is about -2.98 bps versus the replay proxy.
4. Trade-path and sizing divergence is the dominant problem: only 2 overlapping groups match quantity within tolerance. Manual trades, state/history differences, cash/settlement, exact trigger-time prices, and historical code-version differences can all change subsequent sizing and rules.
5. Therefore the historical edge remains interesting, but exact live reproducibility is **not yet demonstrated**. The next validation should capture exact signal quote + intended quantity + order ID + actual fill for every future agentic order and reconcile state from broker truth before each plan.
