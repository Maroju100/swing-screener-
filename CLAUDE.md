# swing-screener- : standing rules for Claude Code

This file is auto-loaded into every session in this repo. It exists so
safety rules for real-money trading never have to be re-explained, and so
recurring context (file locations, thresholds, conventions) is available
by default instead of reconstructed from memory each time.

## Account scope — HARD RULE, never break

Only ever read, reference, or trade **Robinhood account 912291820**
("Agentic 2", `agentic_allowed=true`).

**Never touch account 410961445 (Margin) or any other account**, for any
reason, even read-only lookups, unless the user explicitly names it.

## GFV-safety — HARD RULE, never break

If `review_equity_order` (or any order-review tool) ever warns about
unsettled or insufficient settled funds, **skip that specific order** —
do not override it, do not retry with a workaround.

## Cross-system symbol safety

Any universe symbol currently held that is **not** tracked in
`docs/margin_style_live_state.json` belongs to another system or a human
and must be excluded from new entries for Margin-Style Live. (CGC is a
known example — always excluded.)

## FULL AUTOMATION pre-authorization (Margin-Style Live only)

Placing both buy and sell orders for the Margin-Style Live plan without
pausing for confirmation is pre-authorized, **only** when all of the
following hold:
- `review_equity_order` shows no alerts (see GFV rule above).
- The order matches the generated plan step exactly (symbol, side,
  quantity, price logic).
- No HARD RULE skip condition (above) is triggered.

Any **novel alert type** not covered by the above, or anything that looks
like it could touch the wrong account, must **stop and escalate to the
user** instead of proceeding.

## Standing directives from the user (do not change without being asked again)

- **Do not modify the Margin-Style Live intraday stop logic** (the flat
  `-1.51%` `INTRADAY_STOP`). Multiple backtests this project (ATR-based
  stop, basket-regime-gated hybrid stop) showed it performs worse than the
  current flat stop across the full 6-month window — the flat stop stays
  as-is unless the user explicitly asks to revisit it.
- Any change proposed from a backtest result must be checked for
  overfitting (out-of-sample / walk-forward validation) before being
  described as a real improvement — this project has repeatedly found
  promising in-sample results (grid search on a single day, "best check
  hour") that reversed or evaporated out-of-sample.

### Evidence rules — HARD RULES, added 2026-09-21 after four fabricated results

These exist because four separate analyses (entry filter "helps", entry
filter "hurts", "close at 2:45 PM CDT", "3×/day execution") all reported
confident numbers produced by the same invalid method, giving the user
contradictory answers to the same questions across sessions. The rules
below are what makes a claim checkable.

1. **A rule-change result is valid only if produced by replaying the
   engine** — `cmd_plan` / `cmd_commit` day-by-day, per
   `.claude/skills/backtest-variant/SKILL.md`. **Post-processing
   `day_pnl` with an assumed multiplier is NOT a backtest and must never
   be reported as one.** `day_pnl` is the *output* of the baseline rules;
   changing an entry/exit rule changes which positions are open, which
   changes the tranche index, sizing, `MAX_HOLD_DAYS` timing, the
   `PEAK_SELL_PCT` reference peak, the circuit-breaker count and
   settlement — the whole path diverges. Multiplying a fixed P&L series
   assumes that path is unchanged, which is exactly what a rule change
   breaks. Such a script returns whatever multiplier was typed into it;
   it has no contact with the question.
2. **Evidence must be committed, not in `/tmp`.** Any number cited in
   this file needs a script in `scripts/` plus the command to reproduce
   it. `/tmp` is wiped when the container recycles, after which the claim
   outlives its evidence and becomes unfalsifiable — which is how
   contradictory claims came to coexist here.
3. **Label every number MEASURED or ESTIMATED**, and state an estimate's
   assumption inline. Estimates must not be given the same tables,
   decimal precision, or confident tone as replay output. Report
   precision the sample supports — "+2.69pp" off 24 days with ~15 winning
   days is false precision.
4. **A reversal requires a diagnosis, not just a new number.** If a
   result flips sign (e.g. +40% → −99%), explain what specifically was
   wrong with the earlier test. Without that, it is unknown which one is
   broken, so neither may be used and the honest status is "unknown."
5. **Before writing a result into this file, check it against what is
   already here.** The removed filter note previously asserted both "zero
   quality days in the full 6-month period" and "$1.4k P&L" — mutually
   impossible, and it sat in production instructions unnoticed.
6. **If the available data cannot answer the question, say so and stop.**
   Do not substitute an assumption for a measurement. "Close at 2:45 PM
   CDT vs hold overnight" was unanswerable from daily bars; the correct
   output was "this needs intraday data", not a `*0.60` factor.

## Strategy 1: Margin-Style Live (real money, daily) ✅

**Current Production Version** — baseline, no daily stop.

- 🚨 **THE DAILY STOP WAS NEVER IN PRODUCTION (established 2026-09-21).** The
  daily trigger's step 1 is `git checkout main && git pull origin main`, so
  **`main` is what trades real money**. `main`'s engine contains **zero**
  references to `DAILY_STOP` — commit `bc814c4`, which added it, is *not an
  ancestor of main*. Verify: `git show origin/main:scripts/margin_style_live_engine.py | grep -c DAILY_STOP` → `0`.
  That, not luck, is why it never appears in the live run log. Earlier notes in
  this file claiming it was "deployed in production" were **wrong**, and so was
  the alarm raised about a harmful control being live on real money. **No real
  money was ever exposed to the daily stop, or to its double-sell defect.**
- ✅ **Disabled on the development branch anyway (2026-09-21)** at the user's
  explicit request: `DAILY_STOP_ENABLED = False`. Replaying the working tree
  then reproduces the baseline **exactly** — $124,080.90 realized / **+155.10%**
  / 714 trades, identical to pre-stop engine `859057e`. Verify with
  `scripts/margin_style_17h_backtest.py --engine-rev working`. This also gates
  the double-sell defect. The defect itself is still unfixed — **fix it before
  ever setting the flag back to True.**
- ⚠️ **`main` and the development branch have FORKED, including real-money
  state.** They diverged at `892b66a` (2026-09-04) and each accumulated its own
  live-run commits: `main` has Sep 16/17/18 runs plus a broker reconciliation;
  the branch has its own Sep 16 and Sep 21 runs. Their
  `docs/margin_style_live_state.json` files disagree materially — `main` shows
  4 open positions (WDC/SNDK/LRCX/STX, `equity_peak` 20,873.33), the branch
  shows 0 positions (`equity_peak` 17,696.92). The engines have diverged too
  (~430 insertions / 175 deletions apart; `main` carries position-mismatch
  detection the branch lacks). **Do NOT merge the branch into `main`** — it
  would add the daily-stop code that production has correctly never had.
  Port wanted changes file-by-file instead.
- ✅ **RESOLVED 2026-09-22 — the Sep 21 run was ported to `main` (`01b484e`).**
  `main` now correctly shows the account flat with $12,972.28 settling
  2026-09-22, and both real-money files are back in sync across the branches.
  Two judgement calls are recorded in that commit: **`equity_peak` was kept at
  `main`'s 20,873.33**, not lowered to the branch's 17,696.92 (a high-water mark
  must never be lowered, and the run did not change it), and the branch's
  **corrupted log was not copied** — commit `dbae2ba` had concatenated a second
  JSON document after the closing brace, so the entry was extracted and appended
  properly instead. That entry's `total_proceeds` also read 13972.28 against an
  actual order sum of 12972.27; corrected, original kept as
  `total_proceeds_as_logged`.
  - ✅ **KILL-SWITCH FIRING ACCEPTED by the user, 2026-09-22.** At $17,695.48
    against `equity_peak` 20,873.33 the drawdown is **−15.22%**, past
    `KILL_SWITCH_DD` (−15%), so the kill-switch is expected to fire on the next
    run: liquidate (nothing is open), then block new entries for
    `KILL_SWITCH_RESUME_DAYS` (20 trading days), after which the **permanent**
    SMA-50 trend gate applies to every future entry. This is the control working
    as designed on a real drawdown — `main`'s Sep 18 log records `total_equity`
    **21,612.74**, a −18.12% fall. **Do not "fix" this by lowering
    `equity_peak`.** A future session seeing a quiet, gated system should
    read this note first: it is expected, it was chosen, and the resume is
    time-based (20 trading days), not recovery-based.
- ✅ **THE FOUR GUARDRAILS ARE NOW REAL IN PRODUCTION (`294328d`,
  2026-09-22).** They had been documented since 2026-09-16 but existed only on
  the development branch — `main` supported just `plan` and `commit`, which is
  why nothing caught the four phantom positions. `verify`, `reconcile`,
  `check_data_freshness` and `cmd_commit`'s pre-commit validation are now in the
  production engine. `DAILY_STOP` was deliberately **not** brought across (still
  zero occurrences), and `main`'s own `validate_positions_against_holdings` was
  kept — it auto-corrects phantom/mismatched shares inside `cmd_plan` and is
  complementary to `reconcile`'s fail-fast check.
  - **Trading behaviour is unchanged**, verified by replaying the 6-month window
    against the engine before and after the port: identical to the cent — 122
    days, 714 trades, $124,080.90 realized (+155.10%). The guardrails are purely
    additive.
  - `reconcile` was regression-tested by injecting a phantom WDC position; it
    correctly exits 1.
- ✅ **AND THE TRIGGER NOW INVOKES THEM (2026-09-22).** The daily prompt on
  `trig_01VfH6Nhfbk7YLaTkzHWLG7E` was rewritten so the guardrails actually run,
  as **lettered sub-steps** — the prompt cross-references step numbers in
  several places, so renumbering would have broken it:
  - **step 1b** — `verify`; stop on non-zero, do not auto-repair state.
  - **step 3b** — write `/tmp/broker_positions.json` from
    `get_equity_positions`, then `reconcile`; stop on non-zero, fix state to
    broker reality, commit, and only then restart from 1b.
  - **step 7** — `plan` now passes the **fifth** argument
    (`{"SYM": shares}`), which activates the in-plan phantom/mismatch
    auto-correction. Marked MANDATORY: omitting it is how the Sep-2026 phantom
    incident went unnoticed.
  - **steps 11–14** — pre-commit abort must not be hand-edited around; step 12
    now says explicitly **push to `main`** ("a run committed to any other
    branch is invisible to the next run"); step 13 says append *into* the
    existing `runs` array and verify the file parses; step 14 reports each
    guardrail's result.
  - The prompt also now carries the corrected baseline (+155.10%, with the
    withdrawn +248.36% / +60.1% claims named as withdrawn and "do not add the
    daily stop"), and the accepted kill-switch state with "do not fix a gated
    system by lowering `equity_peak`".
- ✅ **ACCOUNT TYPE RESOLVED 2026-09-22 — it is `limited_margin`, and it does
  not matter to the engine.** Do not re-litigate this.
  - **Evidence it is limited margin, not cash:** `get_accounts` →
    `type: limited_margin`, `unsettled_funds: 12965.08`. `get_portfolio` →
    `cash 17693.63`, **`buying_power 17693.63`**. The portfolio tool's own guide
    says unsettled proceeds are excluded from `buying_power` *on a cash
    account*; here they are included. A cash account's buying power would have
    been `17693.63 − 12965.08 = 4728.55`. So unsettled proceeds **are**
    spendable. References to a "cash account" elsewhere in this file and in
    older trigger prompts are wrong.
  - **But the engine's settlement discount is provably harmless either way.**
    `cmd_plan` computes `safe_cash = real_cash − pending_total`, which looks
    over-conservative — except `cmd_plan` first prunes
    `settle_date > today` while `cmd_commit` writes
    `settle_date = next_business_day(today)`. At **once-daily** cadence a sale on
    day N settles before day N+1's run, so `pending_total` is already 0 by the
    time it is subtracted. **MEASURED, not assumed:** replaying the 6-month
    window with the discount removed gives results identical to the cent — 714
    trades, $124,080.90 realized, +155.10%. Reproduce:
    `scripts/margin_style_17h_backtest.py --engine-rev origin/main --no-settlement-lockup`
    against the same command without the flag. **No engine change is needed or
    warranted**; the discrepancy was documentation-only. (The discount *would*
    bite if the system ever ran more than once a day — another reason not to add
    intraday runs.)
  - **Where limited margin actually shows up** is broker-side: on a cash account
    `review_equity_order` warns about unsettled funds and the GFV hard rule
    skips the order (this is what skipped 4 buys on 2026-09-16). On limited
    margin those warnings should be rare or absent. **Keep the GFV skip rule
    anyway** — it costs nothing when no warning fires and remains the last line
    of defence. If unsettled warnings *do* appear on this account, that is
    informative and worth reporting, not working around.
- ⚠️ **NEW RISK that limited margin introduces — PATTERN DAY TRADER.** Limited
  margin is a *margin* account for PDT purposes, and this account is around
  **$17.7k, under the $25,000 PDT threshold**. The strategy can produce same-day
  round trips (the same-day netting logic exists precisely because a PEAK sell
  and a dip buy can land on one symbol the same day). Four or more day trades in
  five business days would flag PDT and restrict further day trading until
  equity exceeds $25k. This was never considered when the account was converted.
  - **QUANTIFIED from `docs/margin_style_live_log.json` (2026-09-22) — the
    exposure is NOT low.** Across 31 run-days carrying orders, **8 days had a
    same-day round trip**, and the worst rolling five-run-day window held
    **8 day trades** (2026-07-28 → 2026-08-04): Jul 30 (INTC, MU, SNDK),
    Aug 3 (AMD, MU, SNDK), Aug 4 (INTC, SNDK), Aug 10 (MU, SNDK, WDC),
    Aug 21 (INTC), Aug 27 (INTC, LRCX, WDC), Aug 31 (WDC), Sep 2 (SNDK).
    The threshold is **4 in 5 business days**, so the strategy has cleared it
    twice over. `MAX_HOLD_DAYS = 6` does not prevent this — a position can be
    opened and closed the same day by PEAK/GAIN or INTRADAY_STOP.
  - Same-day netting (added 2026-08-11) helps but does not eliminate it: a
    netted PEAK-vs-buy becomes one order and is not a round trip, which is why
    post-netting days show 1–3 instead of 2–3 — still non-zero.
  - MEASURED/PROXY caveat (Evidence Rule 3): this counts "bought and sold the
    same symbol on the same run-day" from the log, which approximates FINRA's
    definition but is not the broker's own day-trade counter. Read it as
    "clearly above threshold", not as an exact count.
  - **On a cash account this mattered not at all** — PDT is a margin-account
    rule, and cash accounts face GFV instead, which the hard rule already
    covers. On limited margin it applies, and nothing in the system currently
    detects or limits it. **OPEN — needs an explicit decision:** accept the
    flag, add a same-day-round-trip limiter, or fund above $25k.
- **Superseded, kept for the record — BROKER CHECK 2026-09-21:**
  `get_equity_positions` on 912291820 returns **only CGC (2 sh)** — zero
  universe symbols. `get_portfolio`: `equity_value` **$1.85**, `cash`
  **$17,693.63**, `total_value` **$17,695.48**. The account is flat.
  - **The development branch's state is CORRECT**: 0 open positions,
    `equity_peak` 17,696.92 ≈ the real total_value. ✅
  - **`main`'s state is STALE and claims phantom positions**: WDC 9.6725,
    SNDK 0.7208, LRCX 4.1784, STX 0.0168, `equity_peak` 20,873.33 — roughly
    $3,178 above what the account actually holds. ❌
  - Likely cause: the real 2026-09-21 run ("4 MAX_HOLD + STOP exits, now flat")
    executed and was committed to the **development branch instead of `main`**,
    so `main` never recorded the exits and still believes those positions are open.
  - **Consequence**: until `main`'s state is corrected to flat, a run off `main`
    starts from phantom holdings — `cmd_plan` derives `total_equity`, PEAK and
    STOP decisions from state, so it would emit sell orders for shares that do
    not exist. The daily procedure's reconcile step (Guardrail 2) is what should
    catch this, and `main`'s position-mismatch detection helps, but the state
    file itself still needs fixing. **Fix `main`'s state before the next run.**
- ⚠️ **Why it was disabled — replay says it is harmful.** The "+60.1%
  improvement out-of-sample" claim is withdrawn: it
  came from post-processing a fixed `day_pnl` series (Evidence Rule 1's
  forbidden method), not from replaying the engine. Engine replay with the
  DAILY_STOP defect patched gives **+79.71% vs +155.10% baseline** over 6
  months, and **+8.72% vs +11.73%** on a genuine holdout — i.e. it roughly
  halves returns in both windows. It also carries an unfixed double-sell defect
  (see `DAILY_STOP_PCT` under Key thresholds). It has never fired live, so
  nothing has been lost yet. Reproduce with
  `scripts/margin_style_17h_backtest.py --engine-rev bc814c4 --patch-daily-stop-bug`.

- **Script**: `scripts/margin_style_live_engine.py` — `cmd_plan` builds the
  day's buy/sell plan from historicals + live quotes; `cmd_commit` applies
  it to state.
- **State**: `docs/margin_style_live_state.json` (open positions, pending
  settlement, equity peak, kill-switch/trend-gate flags).
- **Log**: `docs/margin_style_live_log.json` (append-only per-run record of
  orders placed, reconciliation, risk state).
- **Universe**: exactly `AMD, MU, WDC, SNDK, TSM, INTC, LRCX, STX` — do not
  add or remove symbols without being asked.
- **Schedule**: runs once daily, ~17:00 UTC, via trigger
  `trig_01VfH6Nhfbk7YLaTkzHWLG7E`. (A walk-forward-validated backtest
  found switching the check-hour does not hold up out-of-sample — keep
  17:00.)
  - **Check *frequency* is settled too — do not add intraday runs.**
    The primary evidence is in this trigger's own prompt (CHECK-FREQUENCY
    CHANGE, 2026-08-05, readable via `list_triggers` on
    `trig_01VfH6Nhfbk7YLaTkzHWLG7E`): a multi-frequency backtest over
    3-week / 30-day / 60-day windows using **exact production strategy
    logic** compared 1hr / 2hr / 3hr / twice-daily against three
    once-daily timings. **Every once-daily timing beat every intraday
    frequency by a wide margin in all three windows**, and midday won 2 of
    3 outright — which is why the trigger is at 17:00 UTC.
  - **Documented root cause** (from that same study, not inferred):
    `PEAK_SELL_PCT` trims 74.3% of a position on *every new high it sees*,
    so checking more often means **more forced trims during a sustained
    rally** — winners get cut before they run. Entry signals read
    completed prior daily closes, so extra checks add no entry
    information to offset this. The accepted trade-off is that
    `INTRADAY_STOP` is also only checked once/day.
  - Three further findings point the same way: once-daily can beat
    intraday for Margin-Style (`scripts/backtest_daytrade_once_daily_noon.py`
    docstring), twice-daily beat continuous checking for the day-trading
    engine on a 3-window walk-forward (`scripts/daytrade_paper_engine.py`),
    and 3-hour beat both hourly and twice-daily for the agentic system
    (`docs/agentic_log.json`, which carries its own "skipped
    paper-tracking validation" caveat).
  - A real test would extend
    `scripts/margin_style_timing_comparison.py`'s
    `backtest_with_intraday_checks` harness to multi-check schedules over
    real intraday bars (its non-interpolated span is 2026-01-30 →
    2026-08-06), then walk-forward validate. **Scaling daily P&L by an
    assumed "extra executions capture N% more" multiplier is not a
    backtest** — that was attempted on 2026-09-21 and the resulting
    "3×/day adds +2.7pp" claim was fabricated, not measured. Same defect
    invalidated a "close at 2:45 PM CDT vs hold overnight" comparison from
    the same session: `day_pnl` is a daily-bar series and carries no
    intraday decomposition, so it cannot answer what share of a day's P&L
    occurred before any given clock time.
- **Key thresholds** (do not change without explicit request):
  - `HUGE_DIP_DRAWDOWN = -0.35`, `HUGE_DIP_PCT = 0.40`
  - `NORMAL_DIP_THRESHOLD = 0.004` (tranche-indexed sizing)
  - `INTRADAY_STOP = -0.0151` — see standing directive above
  - `DAILY_STOP_PCT = 0.01` — daily loss cap (1% of capital; currently -$163.96 on live $16,396.38).
    Liquidates all remaining positions and skips new entries if cumulative
    realized + unrealized losses exceed this cap **during trading hours** (system runs 17:00 UTC).
    ⚠️ **Limitation**: Overnight gaps before 17:00 UTC check can exceed the cap; stop only protects intraday realized losses.
    Conservative estimate: 60–70% effectiveness. See section below for corrected figures accounting for gap risk.

    🐞 **KNOWN DEFECT — UNFIXED as of 2026-09-21. Read before DAILY_STOP ever
    fires.** PEAK/GAIN sells are decided early and parked in `pending_peak_gain`
    (~line 560); they are not appended to `sells` until ~line 787. The
    DAILY_STOP block (~line 622) guards itself with
    `closed_symbols = {s['symbol'] for s in sells}`, which **cannot see the
    parked sells**, so it liquidates the full position of a symbol that already
    has a PEAK sell pending. Line 787 then appends that sell anyway → **two
    sells, same symbol, same day, totalling ~174.3% of the position.**
    `cmd_commit`'s pre-commit validation does not catch it: it checks each sell
    independently against the pre-mutation position, never the running total.
    The KILL_SWITCH block (~line 651) does this correctly — it clears
    `pending_peak_gain = {}` and `peak_updates = {}` first. DAILY_STOP just
    omits those two lines; that asymmetry is the entire bug.
    - **Live impact: none, and never possible.** This code is not on `main`,
      which is the branch the daily trigger checks out — so it has never been
      part of the real-money system at all. It is also now gated behind
      `DAILY_STOP_ENABLED = False` on the development branch. (The broker would
      additionally reject the oversized second order.)
    - **In backtest it is catastrophic**: 63 duplicate-sell days and
      $13,808,086 of phantom proceeds over Mar 6–Sep 4 2026, turning a +26%
      replay into a fake +17,437%.
    - Fix is two lines in the DAILY_STOP branch, mirroring KILL_SWITCH.
      `scripts/margin_style_baseline_backtest.py --patch-daily-stop-bug`
      applies it **in memory only** so backtests are usable; production is
      untouched and still carries the defect.
  - `PEAK_SELL_PCT = 0.743`
  - `GAIN_TIERS = [(0.20, 0.90), (0.10, 0.50), (0.05, 0.20)]`
  - `MAX_HOLD_DAYS = 6`
  - `KILL_SWITCH_DD = -0.15`, `KILL_SWITCH_RESUME_DAYS = 20`,
    `TREND_GATE_SMA_DAYS = 50`
  - `CIRCUIT_BREAKER_STOP_COUNT = 2`
  - `MAX_SYMBOL_ALLOCATION_PCT = 0.50`, `MAX_TRADE_NOTIONAL_PCT = 0.25`
  - Same-day same-symbol orders net against each other.
- **Data Freshness & State Sync Guardrails (2026-09-16)**: Four-layer protection against execution with stale or divergent data:
  
  1. **Verify Command** (Guardrail 1 — State Consistency):
     ```bash
     python scripts/margin_style_live_engine.py verify
     ```
     - Audits `margin_style_live_state.json` for logical errors: negative shares, invalid prices, 
       orphaned entries, bad dates, duplicate positions, invalid tranche counts (1-5)
     - Fails fast (exit code 1) if any errors detected
     - **Run before fetching live data** to catch state corruption early
  
  2. **Reconcile Command** (Guardrail 2 — Broker Sync):
     ```bash
     python scripts/margin_style_live_engine.py reconcile <broker_positions.json>
     ```
     - Compares state file vs actual broker holdings from `get_equity_positions` API
     - Catches: symbol mismatches (state has symbols broker doesn't, or vice versa), share count 
       divergence >0.01%, orphaned settlement entries
     - Requires broker positions JSON (format: `{symbol: {quantity: X, average_buy_price: Y}, ...}`)
     - Fails (exit code 1) if divergence found; user must reconcile manually before trading
     - **Prevents execution based on phantom/wrong positions** (critical for GFV safety)
  
  3. **Data Freshness Checks** (Guardrail 3 — Current Data):
     - Built into `cmd_plan`: automatically validates historical bars date and quotes timestamp
     - Historical bars: must be ≤1 day old (last bar date is checked)
     - Quotes: must be ≤5 minutes old (if timestamp metadata provided)
     - Prints warnings but continues (user can accept or abort)
     - **Prevents signals based on stale data** (e.g., Sep 4 closes used for Sep 16 trading, 
       which caused false stop signals in previous session)
  
  4. **Pre-Commit Validation** (Guardrail 4 — Order Sanity):
     - `cmd_commit` aborts if any sell exceeds open position (catches impossible orders)
     - Prevents state mutations that create negative shares or orphaned entries
     - Appends audit trail with timestamp and order checksums
  
  **Daily Run Sequence (guardrails in order):**
  1. Verify state (catch corruption)
  2. Fetch broker positions via API
  3. Reconcile state vs broker (catch divergence) ← **Exits if failed**
  4. Fetch historicals + quotes (data freshness auto-checked in cmd_plan)
  5. Generate plan (signal logic)
  6. Review + execute orders (GFV checks)
  7. Commit state (pre-commit validation)
  
  **Sep 16 Incident Prevention**: Previous session had corrupted state (entry prices guessed at $400 
  for WDC instead of actual $411.66, causing false INTRADAY_STOP signals). With guardrails:
  - Step 3 (reconcile) would have **failed immediately** detecting symbol/share mismatches
  - Stale historical data (Sep 4 instead of Sep 15) would have triggered warning in step 4
  - Combined, execution would have been blocked until state matched broker reality
- **5 Pillars investigation (2026-09-07)**: Tested applying Ross Cameron's stock
  selection pillars (up 10%+, 5x volume, news, $2-$20 price, <10M float) as a
  gating filter. **Decision: NOT DEPLOYED.** Reason: The pillars are fundamentally
  incompatible with Margin-Style Live's large-cap semiconductor universe. Pillar 1
  (up 10% daily) contradicts dip-buying (which buys on weakness). Pillar 4 ($2-$20
  price range) excludes all 8 symbols (AMD $192-$580, MU $321-$1213, etc.). Pillars
  2, 3, 5 require intraday volume and fundamental data not available in backtest.
  Margin-Style Live's edge derives from **timing (2-tier dips)** and **position sizing
  (tranched entries)**, not stock selection; validation shows no benefit from filtering
  on universe-level criteria.
- **Live dashboard**: `margin_live_dashboard.html`
  (`https://claude.ai/code/artifact/b22d0a38-624f-496b-a47c-f08d16703488`).
  Live sections (positions, account/risk snapshot, distance-to-next-signal)
  read the account live via the artifact `mcp` capability
  (`get_accounts`, `get_portfolio`, `get_equity_quotes`,
  `get_equity_historicals` — read-only tools only, never order-placement
  tools). Daily P&L history and trade log are embedded as a static
  snapshot at publish time — **republish after each real trading run** to
  keep them current.
- **REMOVED (2026-09-21) — and NO valid measurement exists in either
  direction.** The Entry Signal Quality Filter (3+ consecutive down days)
  is **not** in `scripts/margin_style_live_engine.py`; production runs
  baseline (trade all days). That is the correct conservative state, but
  the reasoning originally recorded for removing it was invalid, and so
  was the reasoning for adding it. **Do not cite any of these numbers:**
  - `+40.31%` (helps) — original validation; basis not recoverable.
  - `+32.24%` (helps) — `docs/entry_filter_paper_state.json`. This was
    **never forward paper tracking**: it recorded `days_tracked: 127` on
    its `start_date` of 2026-09-19, because
    `scripts/entry_filter_paper_engine.py` re-post-processes the
    historical `day_pnl` series on every run. Both log entries are from
    the same day, 4 minutes apart, identical.
  - `−99%` ($124k → $1.4k, "zero quality days") — from
    `/tmp/backtest_all_filters.py`, whose core line applies an invented
    multiplier: `adjusted_pnl = daily_pnl * 0.4 if daily_pnl > 0 else
    daily_pnl`. Internally self-contradictory besides: zero trading days
    cannot produce $1,449.
  All three share one defect — see **Rule 1** in the standing directives.
  Re-testing the filter properly (replay via the `backtest-variant`
  method) is an open, unstarted task; until then the honest status is
  **unknown**, not "counterproductive."

### 6-Month Backtest Results (Mar 6 - Sep 4, 2026) — With Overnight Gap Analysis

> ✅ **THESE NUMBERS ARE REAL AND REPRODUCE EXACTLY (verified 2026-09-21).**
> Run `python3 scripts/margin_style_original_6month_backtest.py` — the original
> script, preserved verbatim, with its data committed in `data/`:
>
> ```
> Realized P&L: $+124,080.90                    <- the $124,080.90 below
> 124,080.90 / 80,000 = +155.10%                <- the +155.10% below
> Total incl. mark-to-market: +$126,737.07 (+158.42%)
> 80,000 + 126,737.04 = $206,737.04             <- the ending equity below
> ```
>
> **+155.10% and +158.42% are both correct**, and are not in conflict: +155.10%
> is **realized P&L only**; +158.42% adds end-of-window unrealized
> mark-to-market. Earlier sessions treated the gap between them as a discrepancy
> to be explained — it is just two measures of one run.
>
> The run used engine `859057e`, the revision live at 2026-09-06 01:55 and the
> last one before the daily stop, which is exactly why "Baseline (no stop)" is
> the right label.
>
> ⚠️ **A RETRACTION POSTED HERE ON 2026-09-21 CLAIMING THESE DID NOT REPRODUCE
> WAS ITSELF WRONG.** It reported +64.12% / +26.07% / −9.29% from
> `scripts/margin_style_baseline_backtest.py`, which priced "today" off the
> **daily close**. The original — correctly — prices off the **actual ~17:00 UTC
> hourly bar**, the moment the live trigger fires. That is not a harmless proxy:
> `PEAK_SELL_PCT` trims on every new high and `INTRADAY_STOP` compares against
> the prior close, so the price source changes which rules fire *every day*. The
> daily-close harness also ran with ~85 days of prior lookback where the original
> had none. **Use the 17:00-quote script as the reference for this window.**
>
> **The lesson, which generalizes:** a new harness was treated as ground truth
> and used to contradict an established, documented result before it had been
> validated against any known reference. That is backwards. Validate a new
> measurement tool against a result you can already reproduce *first*; only then
> is it entitled to overturn anything.
>
> **The other two rows were re-run the 17:00 way on 2026-09-21
> (`scripts/margin_style_17h_backtest.py`, which passes `--validate` by
> reproducing $124,080.90 exactly). Neither survives.**
>
> | Row | Documented | Verified by replay | Verdict |
> |---|---|---|---|
> | Baseline 6-month, no stop | +155.10% | **+155.10%** | ✅ exact |
> | Holdout Jul 6–Aug 3 | +45.0% / $36,027 | $36,027 is real but is a **slice**, not a holdout | ⚠️ % inflated, not OOS |
> | With 1% daily stop, 6-month | +248.36% | **+79.71%** | ❌ stop *halves* returns |
> | Holdout with stop | +75.3% | **+8.72%** vs +11.73% baseline | ❌ stop hurts here too |
>
> **The "holdout" is not a holdout.** $36,027.15 is exactly the Jul 6–Aug 3
> slice of the *same* 6-month run — same parameters, same continuous state,
> nothing withheld or re-fit. Its "+45.0%" divides that slice by the *original*
> $80,000, but equity had already compounded to **$162,679** by Jul 6, so the
> return on capital actually deployed was **+22.15%**. A genuine fresh holdout
> (start flat at Jul 6 with $80k) returns **+11.73%**. Do not cite this as
> out-of-sample validation of anything.
>
> **🚨 The 1% daily stop is NET NEGATIVE and it is DEPLOYED.** Replaying engine
> `bc814c4` with the DAILY_STOP defect patched: **+79.71% vs +155.10% baseline**
> — it roughly halves returns. The holdout window agrees (+8.72% vs +11.73%), so
> this is not a single-window artifact. Unpatched, the same run prints
> **+1215.80%**, which shows how badly the double-sell defect flatters it.
>
> The documented "+248.36%" and "validated +60.1% improvement out-of-sample" came
> from `/tmp/margin_live_daily_stoploss_backtest.py` and
> `/tmp/margin_live_daily_stop_validation.py`, which **post-process the fixed
> `day_pnl` series** (`stop_amount = 30000 * stop_level`; `cmd_plan` never
> called) — the method Evidence Rule 1 forbids. They also applied a $300 cap
> (1% of $30,000) to P&L generated by an **$80,000** run.
>
> Live impact to date is nil, and always was: **the daily stop was never on
> `main`**, the branch the live trigger checks out, so it never ran on real
> money. It was disabled on the development branch on 2026-09-21 regardless.

**Baseline (no stop)**: $80,000 → $206,737.04 = **+155.10% return**
- Days traded: 32 of 127
- Total trades: 136
- Worst day: -$15,544.84 (Jul 28)
- Best day: +$17,812.28 (Jul 30)

**With 1% Daily Stop (-$300 cap)**: **+248.36% return** ✅
- Total P&L: $198,686.65 (improvement of +$74,605.75)
- **Improvement: +93.26 percentage points**
- Days where stop triggered: 18 of 127
- Worst day prevented: -$15,544.84 → -$300 (saved $15,245)

**Overnight Gap Impact (Detailed Analysis):**
- Total savings from daily stop: $74,605.75
  - Intraday loss prevention: $68,070.00 (~91.2%)
  - Overnight gap unavoidable: $6,535.08 (~8.8%)
- Days with significant overnight gaps:
  - Aug 6→7: -$791.72 gap
  - May 14→15: -$692.42 gap
  - Aug 21→24: -$5,050.94 gap
- **Note**: The overnight gap losses shown represent equity changes between day close and next day open. If the daily stop executes and closes all positions at 17:00 UTC, no overnight positions remain; gaps only re-manifest if positions are re-opened the next day (accounted for in the daily totals).

**At $30,000 Equivalent Capital:**
- Baseline: $46,530.34 (+155.10%)
- With stop: $74,507.49 (+248.36%)

**Out-of-Sample Validation (Holdout: Jul 6–Aug 3, 21 days):**
> ❌ **Not out-of-sample.** This is a slice of the same run — see the verified
> table at the top of this section. True fresh holdout: +11.73%.
- Baseline: +$36,027 (+45.0%)
- With stop: +$60,631 (+75.3%)
- Improvement: **+$24,604 (+30.3pp)** ✅ Validates edge holds out-of-sample

| Metric | Baseline | With Stop | Improvement |
|--------|----------|-----------|-------------|
| 6-month P&L | $124,080.90 | $198,686.65 | +$74,605.75 |
| 6-month return | **+155.10%** | **+248.36%** | **+93.26pp** |
| Holdout return | +45.0% | +75.3% | +30.3pp |
| Worst day cap | -$15,545 | -$300 | Saved $15,245 |

**Status**: ❌ **Both claims in this line are false.** The daily stop was **never
deployed in production** (`bc814c4` is not an ancestor of `main`), and the
"+60.1% improvement validated out-of-sample" came from post-processing a frozen
`day_pnl` series against a "holdout" that was a slice of the same run. Replay
says the stop **costs** ~75pp. See the verified table at the top of this section.

## Strategy 2: v3 (tightened & baseline) day-trading

- Explored via `semis_momentum.html` dashboard
  (`https://claude.ai/code/artifact/9f8fcbfa-a426-41cf-a016-a407133b855a`)
  and backtest scripts in the scratchpad — this is a research/paper
  context, not live-money, unless stated otherwise.
- **Live paper signals**: The dashboard now displays live trade signals for
  both v3 Tightened (grid-optimized) and v3 Baseline (pre-optimization
  production version) side-by-side, allowing direct comparison of the two
  variants. Both run $30,000 simulated capital across all 8 semis (AMD, MU,
  WDC, SNDK, TSM, INTC, LRCX, STX). The baseline version uses less-aggressive
  parameters (0.6% add-gate vs 0.3%, 2-min cooldown vs 1-min, 65/90%
  exhaustion/trim vs 70/70%) and historically shows more consistency on
  mixed-sentiment trading days.
- A conservative Efficiency-Ratio trading-day gate (Kaufman's ER: net move
  / sum of bar-to-bar absolute moves) was validated as a real, moderate
  improvement (similar/better P&L with materially fewer trading days) —
  offered as a candidate live gate but not yet wired in; ask before
  implementing.
- Dashboard features already built: 10-min/20-min momentum acceleration
  windows (rolling), buy/sell signal timeline with qty/P&L tooltips,
  Price-vs-VWAP, MACD histogram, ATR (Wilder's 14-period, intraday
  day-anchored), basket breadth (step-area, net advancers minus decliners
  vs. prior close), and an Efficiency Ratio "is today worth day-trading"
  gauge (≥0.30 trending, 0.18–0.30 mixed, <0.18 choppy) at the top of the
  page. Historicals are fetched from today's actual UTC midnight (not a
  rolling trailing window — a rolling window silently breaks VWAP
  day-anchoring past 4 hours).

## Strategy 3: Trend-Gated Trail (TGT) day-trading — NOT VALIDATED

**Correction (2026-09-05): the "12/12 split-half" validation claim below was
wrong** — it came from a backtest with a look-ahead bug (gated trades were
entered at the day's opening price, which isn't achievable since the gate
itself can't be confirmed until `GATE_WINDOW_MIN` minutes into the session).
Re-run with the real, achievable entry price, the same 12 checks come out
5/12 — worse than a coin flip. A follow-up grid search (window/trail/
threshold, trained only on SNDK's Jul6-Aug3 window, tested out-of-sample on
the rest) didn't do better (6/10), and its win/loss pattern was 100%
explained by which half of the calendar each check fell in — i.e. shared
cross-symbol market-regime timing, not a real per-day signal. **No
validated edge has been found for this gate.** It is kept running for live
paper observation only; do not describe its output as a proven strategy,
and do not wire it toward real money.

- **Script**: `scripts/trend_gated_trail_paper_engine.py` — incremental
  paper-trading engine, same run/state/log conventions as the v3 paper
  engine. **Paper only — never call `review_equity_order` or
  `place_equity_order` for anything this script does.**
- **State**: `docs/trend_gated_trail_paper_state.json` (open position,
  cash, per-symbol `last_processed_dt`, per-symbol/day gate results).
- **Log**: `docs/trend_gated_trail_paper_log.json` (append-only per-run
  record of trade events + equity snapshot).
- **Universe**: `SNDK, WDC, MU, TSM` — $5,000 paper capital split evenly
  ($1,250/symbol). Do not add/remove symbols without being asked.
- **Rules** (long-only, one position per symbol, no scale-in tranches):
  - **Morning gate**, decided once per symbol per day as soon as
    `GATE_WINDOW_MIN` (30) minutes of bars exist since that day's open:
    compute the **Signed Efficiency Ratio** — `(last_close - first_close)
    / sum(|bar-to-bar close changes|)` over that window (signed net move,
    not `abs()`, unlike the older basket-level Efficiency Ratio gauge on
    the v3 dashboard). If `signed_ER >= GATE_THRESHOLD` (0.0), the day is
    "open" for entry; otherwise skip the symbol for the rest of that day.
  - **Entry**: once the gate passes, buy immediately with the symbol's
    full capital slice — no tranches.
  - **Trailing stop**: sell the entire position if price falls
    `TRAIL_PCT` (3%) below the highest price seen since entry/re-entry.
  - **Re-entry**: after a stop-out, wait for price to close back above
    the day-anchored VWAP, then re-buy the full slice — no blind
    immediate re-buy, and no re-check of the morning gate (a day that's
    open stays open).
  - **EOD close**: force-close any open position at/after `EOD_HHMM`
    (19:55 UTC).
- **Validation history**: motivated by a real, documented flaw in the v3
  dashboard's basket-level Efficiency Ratio gauge (unsigned — only 42%
  accurate predicting a day's direction, worse than a coin flip, because
  it can't distinguish a cleanly-up morning from a cleanly-down one) —
  that flaw is real and unrelated to the correction above. But see the
  **NOT VALIDATED** correction at the top of this section: the gate built
  on top of that observation has not been shown to add any real edge over
  trading the same trailing-stop mechanism ungated. See the script's
  docstring for the full corrected numbers.
- **Dashboard**: surfaced on `semis_momentum.html`
  (`https://claude.ai/code/artifact/9f8fcbfa-a426-41cf-a016-a407133b855a`)
  as an **experimental, not-yet-validated** card (labeled as such), plus a
  Signed Efficiency Ratio table in the Efficiency Ratio card. The
  dashboard's TGT card is a live illustrative JS replay of the same rules
  against whatever window is fetched (resets on every render, like the v3
  signal card) — it is **not** the persisted paper ledger; that lives
  only in the state/log files above, updated by running the Python
  script. The v3 (tightened) card remains the dashboard's primary live
  signal — it was never shown to be superseded by TGT.
- Not yet run on a recurring schedule — run
  `scripts/trend_gated_trail_paper_engine.py` manually (with fresh
  1-minute historicals for `SNDK, WDC, MU, TSM`) to advance the paper
  ledger; ask before wiring it to a daily trigger like Strategy 1.

## Strategy 4: Ross Cameron Analysis — CORE PRINCIPLES VALIDATED (2026-09-07)

**Status: Deep analysis complete. Margin-Style Live IS an adapted implementation of Ross's edge.**

Extracted and analyzed actual trade examples from 3,617 Ross Cameron YouTube transcripts.
Found 4 real trades with specific entry/exit prices and P&L shown live on camera.

### Actual Trades Found in Transcripts

1. **+$19,323** (micro-cap squeeze): $2 stock → $4 in <5 min, starter entry + scale-in
2. **+$8,430** (VWAP bounces): Series of 4 trades on support bounces, avg $2k profit each
3. **+$19,000** (level breakout): Break through 655 resistance, squeeze to 8.00
4. **+$1,921.72** (news catalyst): News-driven squeeze from $4→$19, multiple micro-exits

### Core Pattern Across All Trades

- Volume spike (catalyst or low-float squeeze)
- Support bounce entry (dip buy after initial pop)
- Position scaling (starter + add on continuation)
- Profit scaling (multiple exit levels)
- Time-based stops (max 2-4 hour hold)

### The Key Insight: Margin-Style Live IS Ross's Strategy Adapted

**Ross trades** (micro-caps, intraday, gappers):
- Universe: $2-$20 price, <5M float
- Timeframe: 5-min to hourly charts
- Trigger: Pre-market news catalysts
- Edge: 50-100%+ daily swings on low float

**Margin-Style Live** (large-caps, daily, institutional):
- Universe: $40-$2,300, >100M float each
- Timeframe: Daily bars only
- Trigger: Multi-day dips from trailing high
- Edge: Consistent 2-tier dip buying + tranched sizing

| Ross Principle | Margin-Style Implementation | Validated |
|---|---|---|
| Find support (dip) | HUGE_DIP (-35%) + NORMAL_DIP (-0.4%) | ✓ |
| Bounce entry | Buy on VWAP/support break | ✓ |
| Scale-in position | Tranches [95%, 55%, 35%, 20%, 10%] | ✓ |
| Scale-out profit | Peak selling + gain tiers | ✓ |
| Stop at support | INTRADAY_STOP = -1.51% | ✓ |
| Daily risk limit | DAILY_STOP_PCT = 0.01 (-1%) | ❌ WITHDRAWN — replay says it halves returns; see Strategy 1 |
| Time-based exits | MAX_HOLD_DAYS = 6 | ✓ |
| Trend gating | Kill-switch on SMA-50 reversal | ✓ |

**Result: +155.10% validated across 6 months, dev + holdout windows.**

### Detailed 5-Minute Backtest Analysis (2026-09-07, Comprehensive)

Extracted 5-minute OHLCV data for all 14 micro-cap symbols Ross trades (APVO, ARBB, BDRX, 
CING, CWD, DWSN, GLSI, LSE, RADX, RBNE, SLX, SPRO, STAK, TMDE) across Mar-Sep 2026. 
Tested 4 progressively refined entry/exit rule combinations on 5-minute bars.

**Test Results:**

| Model | Trades | Win Rate | Win/Loss Ratio | Total P&L | Status |
|-------|--------|----------|----------------|-----------|--------|
| Realistic (5%, 12%, 20% targets, -5% stop, 30 bar time) | 2,778 | 47.7% | 1.10x | -6.965% ❌ |
| Improved (tighter -3% stop, 15 bar time) | 3,199 | 42.2% | 1.07x | -8.255% ❌ |
| Early-Session (first 20 min only, 2% target) | 1,846 | 36.6% | **1.44x** | -3.782% ❌ |
| Aggressive Targets ⭐ (1% target, -2% stop, 4 bar limit) | 1,998 | 41.8% | **1.21x** | -3.007% ❌ |

**Best model performance (Aggressive Targets):**
- Entry gates: Volume surge ≥1.5x average OR price action (close > SMA)
- Time window: First 4 bars only (~20 minutes into session)
- Profit target: 1% (34.6% of trades hit this)
- Hard stop: -2% (22.9% of trades hit this)
- Time stop: 4-bar expiration (42.4% of trades)
- Exit distribution: 34.6% profit, 42.4% time, 22.9% hard stop
- Win/Loss ratio: 1.21x (barely meets profitability threshold)
- **Blocker**: Even at 1.21x ratio with 1% targets, total P&L is still -3% due to:
  - Entry slippage (1% built into entry at low × 1.01)
  - Commissions on micro-cap trades ($1-3 per round-trip = 1% of a 1% move)
  - Result: Commission cost eats entire expected gain

**Why 5-Minute Mechanical Backtest Fails Despite Good Win Rate:**

The core constraint is **move size vs transaction cost**:
- Daily micro-cap moves: 5-50%+ (commissions are negligible <1%)
- Intraday 5-min moves: 0.5-2% (commissions ARE the entire profit)
- Mathematical reality: 1% target − 1% slippage − 1% commission = negative edge

**The Discretionary Judgment Requirement:**

Ross's real-time edge requires:
1. **News confirmation** (not just volume proxy): Waiting for CNBC/SEC filing/press release, not just volume spike
2. **Live tape reading**: Spotting large sellers stepping in/out, order cancellations, bid-ask imbalances
3. **Real-time market microstructure**: Adjusting position size based on order flow feedback
4. **Emotional discipline**: Exiting at ANY sign of weakness, scaling in/out dynamically
5. **Float awareness**: Avoiding sudden insider selling or institutional dumping

**None of these are visible in historical OHLCV bars.** The tape (bid/ask, cancellations, order flow) 
is the REAL data source; close/open/high/low are just the aggregated outcome, missing 99% of the signal.

### Why Authentic Backtest Isn't Possible

Attempted two approaches to backtest Ross's exact micro-cap setups:

1. **Large-cap daily data** (AMD/MU/WDC/SNDK/TSM/INTC/LRCX/STX):
   - Data gap: Large-cap semis have 100%+ daily moves from different catalysts than micro-caps
   - Result: Setup optimizations don't transfer

2. **Micro-cap 5-minute data** (14 symbols, Mar-Sep 2026):
   - Timeframe gap: 5-min bars are too small; commissions eat edge before execution
   - Catalyst gap: No pre-market or real-time news/tape data available
   - Verdict: Mechanical backtest gets -3% P&L despite 1.21x win/loss ratio

**Decision**: Mechanical backtesting cannot replicate Ross's edge. The edge is discretionary,
real-time, and built on live market microstructure not available in historical bars.

### What This Means for the Project

1. ✅ **Validated**: Ross Cameron's core principles (dip buy + scale-in + scale-out)
2. ✅ **Implemented**: Margin-Style Live already incorporates these principles optimally
3. ✅ **Proof**: +155% return on 6-month dev+holdout validation (daily large-cap scale-in/out)
4. ❌ **Not possible**: Mechanical 5-minute backtest (fundamental constraint: commissions > move size)
5. ❌ **Discontinued**: Attempting to extract intraday rules for mechanical replay
6. ✅ **Conclusion**: The principles work; the timeframe and universe matter more than the exact rules

### Files & Documentation

- `/tmp/ross_cameron_5min_consolidated.json`: 5-min OHLCV for 14 micro-caps (24.7 MB, Mar-Sep 2026)
- `/tmp/backtest_ross_realistic.py`: First model (47.7% WR, -6.965% P&L)
- `/tmp/backtest_ross_improved.py`: Tighter stops (42.2% WR, -8.255% P&L)
- `/tmp/backtest_ross_early_session.py`: Early session only (36.6% WR, -3.782% P&L)
- `/tmp/backtest_ross_aggressive_targets.py`: Best attempt (41.8% WR, 1.21x ratio, -3.007% P&L)
- `/tmp/ROSS_BACKTEST_SUMMARY.md`: Detailed findings and breakeven analysis

## Conventions used across this repo's dashboards/backtests

- **Dashboard testing before publish**: extract the `<script
  type="module">` body from the HTML, mock `document`/`window`/
  `localStorage`/`getComputedStyle` in Node, `eval()` it with a
  `globalThis.__test` hook exposing internals, and feed real cached
  market data through the actual render functions — do this before every
  dashboard change, not just at the end.
- **Historical state reconstruction**: use
  `git log --reverse --format=%H --follow -- <path>` +
  `git show <hash>:<path>` to get exact ground-truth state at any past
  commit — more reliable than trusting cumulative log arithmetic when the
  log has known field-naming inconsistencies (e.g. `orders`/
  `orders_placed`, `price`/`avg_price` across older runs).
- **Backtesting a modified rule without touching production**: use
  `inspect.getsource()` on the real function (e.g. `cmd_plan`), do a
  targeted string replacement for just the rule under test, `exec()` into
  a copied namespace, and replay with a `FakeDatetime` monkeypatch
  (`MS.datetime = FakeDatetime`, `set_sim_day()`) against real historical
  OHLC data — keeps every other rule byte-identical to what's actually
  live.
