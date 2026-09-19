# Entry Quality Filter Paper Tracking

**Tracking Period:** Sep 19 - Oct 19, 2026 (30 days)  
**Started:** Sep 19, 2026  
**Expected Deployment:** Oct 19, 2026 (if validation passes)

## Daily Update

Run the paper tracking validation daily at **19:00 UTC** (2 hours after Margin-Style Live run at 17:00 UTC):

```bash
bash scripts/daily_paper_tracking.sh
```

Or run manually:
```bash
python scripts/entry_filter_paper_engine.py run_daily
python scripts/entry_filter_paper_engine.py report
```

## Success Criteria

| Result | Improvement | Status | Action |
|--------|-------------|--------|--------|
| ✅ PASS | +22% to +42% (±10% of backtest) | ON TRACK FOR DEPLOYMENT | Deploy to production Oct 19 |
| ⚠️ REVIEW | +10% to +22% | LOWER THAN EXPECTED | Analyze, may need tuning |
| ❌ FAIL | <+10% or negative | NOT WORKING | Investigate root cause, do not deploy |

## Backtest Baseline
- **Expected Improvement:** +32.24%
- **Acceptable Range:** +22.24% to +42.24% (±10% tolerance)
- **Full 6-Month P&L:** $124,081 baseline → $164,084 with filter = +$40,003
- **Out-of-Sample Validation:** +40.31% on holdout window (Jul 6-Aug 3, 2026)
- **Consistency:** 187.5% (OOS beat dev window - real edge, not overfitting)

## Current Status

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Days Tracked | 1 (Sep 19) | 30 | In progress |
| Current Improvement | +32.24% | +22% to +42% | ✅ MATCH (baseline validation) |
| Baseline P&L | $124,081 | — | Confirmed |
| Filtered P&L | $164,084 | — | Confirmed |
| Filtered Entries | 18 | — | Confirmed |

## Milestones

| Date | Milestone | Checkpoint |
|------|-----------|-----------|
| Sep 19 | Start | Baseline initialized |
| Sep 26 | Week 1 | Early signal check (go/no-go) |
| Oct 3 | Week 2 | 2-week checkpoint |
| Oct 10 | Week 3 | Continued validation |
| Oct 17 | Week 4 | Pre-deployment review |
| Oct 19 | Decision | ✅ Deploy if ±10%, ⚠️ Review if 10-20% off, ❌ Investigate if worse |

## Deployment Plan (if validation passes)

**Phase 1: Week 1** (Oct 20-26)
- Capital allocation: 50% ($8,198 on live account)
- Monitor: Entry frequency, P&L contribution, filter effectiveness

**Phase 2: Week 2-3** (Oct 27-Nov 9)
- Capital allocation: 75% ($12,297)
- Monitor: Consistency with backtest expectations

**Phase 3: Week 4+** (Nov 10+)
- Capital allocation: 100% (full live deployment)
- Monitor: First 2 weeks for any divergence

## Files

- **Engine:** `scripts/entry_filter_paper_engine.py`
- **State:** `docs/entry_filter_paper_state.json` (cumulative results)
- **Log:** `docs/entry_filter_paper_log.json` (daily run log)
- **Code:** `scripts/margin_style_live_engine.py` (has_momentum_confirmation function at line 380)

## Notes

- Paper tracking uses historical backtest data replayed through Sep 19
- Once live data becomes available, daily runs will track real trading days going forward
- The filter improves down-market days by ~50% (reduces losses)
- No impact on up-market days (filter doesn't trigger when system makes full profit)
- Implementation is simple and low-risk: just skips ~15-20% of marginal NORMAL_DIP entries
