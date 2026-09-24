# GPT Independent Research Audit

Branch: `gpt-research-audit`

This branch is isolated from `main`. The production/live engine must not be modified or merged without explicit human approval.

## Baseline policy

- Treat the current production Margin-Style engine as **B0**.
- Reproduce results with the actual engine; do not infer P&L by scaling an existing series.
- Broker fills and broker P&L are ground truth for live execution attribution.
- Separate account-level manual trades from engine-generated trades.
- Candidate improvements remain research-only until replay, walk-forward, stress, paper validation, and human review are complete.

## Audit phases

1. **Execution/state integrity**
   - Reconcile engine state to broker fills.
   - Quantify phantom equity/state divergence.
   - Identify manual-trade desynchronization and interrupted-commit failure modes.

2. **Live vs backtest attribution**
   - Compare expected B0 actions with actual broker fills on overlapping dates.
   - Attribute differences to capital, settlement, cross-system exclusions, skipped/failed orders, timing, manual trades, and state divergence.

3. **Capital sensitivity**
   - Replay B0 at live-like capital levels as well as the research $80k baseline.
   - Measure return, drawdown, trade count, skipped signals, concentration, and cash utilization.

4. **Symbol concentration / leave-one-out**
   - Attribute realized P&L by symbol.
   - Replay after removing each symbol independently.
   - Flag results dominated by one or two names.

5. **Regime robustness**
   - Split results across market and semiconductor regimes using only information available at the time.
   - Compare return, drawdown, hit rate, and exposure.

6. **Candidate research**
   - Only after B0 is understood.
   - Predeclare candidate rule changes and acceptance criteria.
   - Require out-of-sample/walk-forward evidence and stress testing.

## Initial high-priority findings

- The repository already documents a live state defect in which a sold LRCX position remained in `open_positions`, causing approximately $3,970.69 of phantom equity and contaminating state-derived equity/risk figures.
- Committed broker fills show manual account-owner trades mixed with agentic trades. These can desynchronize engine state even when engine code is behaving as written.
- The first live run was explicitly deployed without prior paper tracking; early live behavior therefore should not be treated as a clean validation sample without reconstructing operational interruptions and exclusions.

## Safety rule

No file used by the live production path on `main` is to be changed as part of the audit. Research scripts/results belong on this branch. Any production proposal should be presented as a separate candidate diff/PR for human approval.