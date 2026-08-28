---
name: backtest-variant
description: Backtest a modified rule (different stop logic, different check-hour, a new gate/filter, etc.) against a live production trading engine (e.g. scripts/margin_style_live_engine.py) WITHOUT touching the production file. Use whenever asked to test "what if we changed X" for Margin-Style Live or a similar engine in this repo — patches a copy of the real source via inspect.getsource + targeted string replacement, replays it with a FakeDatetime monkeypatch against real historical OHLC data, and reports P&L across multiple windows (full period, a down-market stretch, and the most recent month) plus an overfitting check.
---

# Backtesting a rule variant against a live engine

Goal: answer "what would have happened if we changed X" with a script that
is **byte-identical to production except for the one rule under test**, and
that never edits the real engine file. Every rule-change backtest this
project has done (ATR-based stop sizing, basket-regime hybrid stop,
best-check-hour) follows this same shape.

## The pattern

1. **Import the real module, don't copy it.**
   ```python
   import sys
   sys.path.insert(0, '/home/user/swing-screener-/scripts')
   import margin_style_live_engine as MS
   ```

2. **Monkeypatch time** so the engine's "today" can be replayed day-by-day
   over historical data:
   ```python
   import datetime as _dt
   class FakeDatetime(_dt.datetime):
       _fake_now = None
       @classmethod
       def now(cls, tz=None):
           return cls._fake_now if tz else cls._fake_now.replace(tzinfo=None)
   MS.datetime = FakeDatetime
   def set_sim_day(day_str):
       FakeDatetime._fake_now = _dt.datetime.strptime(day_str, '%Y-%m-%d').replace(tzinfo=_dt.timezone.utc)
   ```

3. **Patch only the rule under test**, via source-string surgery — not a
   hand-rewritten copy of the function:
   ```python
   import inspect
   plan_src = inspect.getsource(MS.cmd_plan)
   old = "        if live_price <= prev_close * (1 + INTRADAY_STOP):"
   new = "        if live_price <= my_variant_stop_price:"
   assert plan_src.count(old) == 1        # fail loudly if the anchor line moved
   plan_src = plan_src.replace(old, new)
   plan_src = plan_src.replace('def cmd_plan(', 'def cmd_plan_variant(', 1)

   ns = dict(MS.__dict__)                 # variant fn resolves module globals via this dict
   exec(compile(plan_src, '<cmd_plan_variant>', 'exec'), ns)
   ```
   If `build()` also needs new fields (e.g. high/low for ATR), patch it the
   same way and point `ns['build']` at the patched version before the
   variant `cmd_plan` runs, since it looks up `build` via its own globals.

4. **Replay day-by-day** over real historical OHLC (fetched once via
   `get_equity_historicals`, cached to a JSON file, loaded once):
   for each date in range: `set_sim_day(day)`, roll forward
   `pending_settlement` → cash, build a hist/quotes JSON slice truncated to
   that day, call the (variant or baseline) `cmd_plan`, then `cmd_commit`
   the resulting actions against a **separate state file per variant** so
   runs never interfere with each other.

5. **Report across multiple windows, not just one**, at minimum:
   - Full available period (e.g. 6 months)
   - A known down-market stretch
   - The most recent month
   A variant that only wins in one window is a red flag, not a finding.

6. **Check for overfitting before calling it a real improvement.** If the
   backtest sweeps a parameter (multiplier, threshold, hour) and picks the
   best-looking value, that value is in-sample by construction. Re-validate
   with a walk-forward split (train on an earlier chunk, test on a later,
   untouched chunk) or a monthly consistency check before recommending it.
   This project has repeatedly seen promising single-window/grid-search
   results (ATR-stop, hybrid-stop, "best check-hour") reverse or evaporate
   once checked this way — see CLAUDE.md's standing directive on this.

## Reference implementations in this repo

- `ms_atr_stop_replay.py`, `ms_hybrid_stop_replay.py`,
  `ms_besthour_replay.py` / `ms_besthour_validate.py` (previously built in
  the session scratchpad) are worked examples of this exact pattern against
  `margin_style_live_engine.py` — reuse their structure rather than
  starting from scratch.

## Do not

- Do not edit `scripts/margin_style_live_engine.py` itself to run an
  experiment — always patch a copy in-memory.
- Do not report a single-window or single-parameter-value result as "an
  improvement" without the multi-window + overfitting check above.
- Do not let a variant script share a state file or STATE_PATH with the
  real live engine or with another variant's run.
