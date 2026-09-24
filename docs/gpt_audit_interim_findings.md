# GPT Research/Audit Findings

Status: evidence review complete; new replay jobs pending an executable repository runtime.

## Production protection

`main` was not modified. All GPT-created artifacts are on `gpt-research-audit`. No production strategy change is approved by this report.

## Findings supported by committed replay evidence

### 1. The engine has a reproducible historical edge in the committed research window, but the headline result is not a live-performance estimate

The committed full-engine research baseline at $80,000 and 5 bps/side reports +155.36% realized, Sharpe 3.834 and -8.84% max drawdown over 132 trading days. The older anchor/research baseline reports are similar. This is evidence that the rule set generated strong results on the tested data; it is not evidence that the same return should be expected live.

### 2. Price/timing basis is a material model risk

The committed price-basis study shows production rules at the previously used ~1 PM CDT basis produced $124,289.71 realized, while the noon-CDT basis produced $100,744.77. On the 64-day 30-minute study, results vary materially by mark. Because entry/stop/peak rules are threshold-driven, quote timing changes the entire path. Live validation should use the closest available quote to the actual decision timestamp, not a later bar close.

### 3. Parameter optimization has demonstrated overfitting

The 500-trial walk-forward candidate failed out-of-sample: fold deltas were +$2,273.90, -$12,839.66 and -$2,565.58; bootstrap P(candidate > baseline)=0.2474 and the CI crosses zero. The optimized candidate also had worse full-window realized P&L and drawdown than baseline. No optimized candidate should be promoted without predeclared out-of-sample evidence.

### 4. The intraday stop is structurally important

Removing the intraday stop produced negative results in committed studies. A tighter -1.0% stop and looser -2.5% stop change ranking depending on timestamp/regime. There is no robust basis yet to change the production -1.51% stop.

### 5. More frequent intraday checking is not an improvement under the tested implementation

The committed intraday-frequency study shows the one-check production schedule positive in the tested 64-day window while tested 2x/3x/4x/7x schedules were negative. This is evidence against simply running the same state machine more often.

### 6. Overnight exposure is both a major source of edge and a major tail risk

The 64-day close-at-bell studies materially reduce or eliminate profitability. The overnight decomposition reports +$28,698.85 net overnight contribution across 295 position-nights, but includes individual overnight losses above $8,000 and gaps as large as -17.57%. Eliminating overnight exposure would change the strategy, not merely reduce risk.

### 7. Daily 1% portfolio stop is not supported by the committed replay

The daily-stop study materially reduced realized results in both hourly and 30-minute bases. It should not be added based on current evidence.

### 8. State/execution integrity is a higher-priority production improvement than parameter tuning

The repository already documents phantom-equity/state divergence after a broker sale was not reflected in engine state, and broker history includes manual user trades mixed with agentic trades. Production hardening should reconcile broker positions/fills to engine state before planning and fail closed on unresolved discrepancies.

### 9. Commission-free does not mean zero implementation friction

Robinhood stock/ETF commissions are $0, so the audit should use 0 bps as the commission reference. BPS scenarios should represent implementation shortfall/spread/slippage, not commission. Actual broker fills should eventually replace arbitrary BPS assumptions where signal/reference timestamps are available.

## Changes NOT supported at this point

- Do not replace the production stop with -1.0% or -2.5%.
- Do not adopt the rejected grid-search candidate.
- Do not add the tested 1% daily stop.
- Do not increase intraday run frequency using the same state machine.
- Do not close all positions before the bell merely to eliminate overnight gaps.
- Do not merge research scripts into the production path.

## Improvements supported for engineering validation

1. Broker-first reconciliation before every plan.
2. Aggregate sell validation so multiple same-symbol sells cannot exceed the live position.
3. Idempotent commit/recovery for interrupted agent sessions.
4. Explicit tagging/separation of manual and agent-generated broker activity.
5. Live decision timestamp + reference quote persisted with every planned action.
6. Fill-vs-reference implementation-shortfall measurement.
7. Fail-closed behavior when state and broker positions cannot be reconciled.
8. Research/live capital parity tests before interpreting $80k backtests for a smaller account.

## Pending replay validations

The branch contains `gpt_capital_sensitivity.py` and `gpt_symbol_attribution.py`, plus a GitHub Actions workflow to execute them at 0 bps. They have not produced results because no Actions run is available for this branch through the connected repository environment. Their outputs must not be invented.

Still required before any strategy-rule change is considered validated:

- full capital sensitivity at live-like account sizes;
- per-symbol realized P&L attribution;
- true leave-one-symbol-out full-engine replays (not arithmetic subtraction);
- fill/reference implementation-shortfall attribution from broker evidence;
- paper/live forward validation after infrastructure hardening.

## Current decision gate

The audit does **not** support changing production trading parameters yet. The evidence does support hardening execution/state integrity and collecting cleaner live evidence. Strategy optimization should resume only after the pending replays and live attribution are available.
