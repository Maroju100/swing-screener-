---
name: daily-margin-live-run
description: Run (or manually retrigger) the Margin-Style Live real-money trading engine for Robinhood account 912291820 — fetch quotes, build the day's plan, review and place orders, commit state, and republish the dashboard. Use when asked to run/retrigger/check today's margin-live plan, or when the scheduled daily run (trigger trig_01VfH6Nhfbk7YLaTkzHWLG7E) needs to be redone manually.
---

# Daily Margin-Style Live run

Real money. Account 912291820 ("Agentic 2") only. Read
`/home/user/swing-screener-/CLAUDE.md` first if it hasn't already loaded —
it holds the hard rules (account scope, GFV-safety, automation
pre-authorization conditions) this procedure assumes.

## Steps

1. **Pull current state and universe.**
   - Read `docs/margin_style_live_state.json` (open positions, pending
     settlement, equity peak, kill-switch/trend-gate flags).
   - Universe is fixed: `AMD, MU, WDC, SNDK, TSM, INTC, LRCX, STX`. Do not
     add/remove symbols.
   - Cross-check open positions against the state file — any held symbol
     **not** tracked there belongs to another system/human (e.g. CGC) and
     must be excluded from consideration.

2. **Fetch live data.**
   - `get_equity_historicals` for the universe (daily bars, enough history
     for the dip/peak signal logic).
   - `get_equity_quotes` for current live prices.
   - `get_accounts` / `get_portfolio` for account 912291820 to confirm
     current cash and settled/pending funds — **never** touch account
     410961445.

3. **Build the plan.**
   - Run `scripts/margin_style_live_engine.py cmd_plan` with the fetched
     historicals, quotes, and real cash figure.
   - Inspect the resulting buy/sell actions against the live thresholds in
     CLAUDE.md (HUGE_DIP, NORMAL_DIP, INTRADAY_STOP, PEAK_SELL_PCT,
     GAIN_TIERS, MAX_HOLD_DAYS, kill-switch/trend-gate, circuit breaker,
     allocation caps). Do not hand-adjust the plan's logic — if a number
     looks wrong, that's a bug to fix in the script, not to patch around
     here.

4. **Review each order before placing.**
   - Call `review_equity_order` for every planned buy/sell.
   - **GFV-safety hard rule**: if it warns about unsettled/insufficient
     settled funds, skip that specific order — do not override, do not
     retry with a workaround.
   - Any **novel alert type** not covered by the FULL AUTOMATION
     conditions in CLAUDE.md → stop and escalate to the user instead of
     placing the order.

5. **Place orders (FULL AUTOMATION, pre-authorized).**
   - Placing both buys and sells without pausing for confirmation is fine
     **only** when: `review_equity_order` showed no alerts, the order
     matches the plan step exactly (symbol, side, quantity, price logic),
     and no hard-rule skip condition fired.
   - Same-day same-symbol orders net against each other per the engine's
     existing logic — don't double-place.

6. **Commit state and log.**
   - Run `cmd_commit` to apply the executed actions to
     `docs/margin_style_live_state.json`.
   - Append the full run record (orders placed, reconciliation, risk
     state) to `docs/margin_style_live_log.json`.
   - Commit and push both files to `main` with a clear message (date +
     summary of buys/sells/stops).

7. **Republish the dashboard.**
   - Update `margin_live_dashboard.html`'s embedded daily-P&L and
     trade-log snapshots with the new run's data.
   - Test via the Node.js DOM-mock harness (see CLAUDE.md conventions)
     before republishing.
   - Republish to the existing artifact URL
     (`https://claude.ai/code/artifact/b22d0a38-624f-496b-a47c-f08d16703488`)
     so the live sections and the static snapshot stay in sync.

## Do not

- Do not modify `INTRADAY_STOP` or any other live threshold as part of a
  routine run — that requires an explicit user request (see CLAUDE.md
  standing directives).
- Do not read or trade account 410961445 for any reason during this
  procedure.
- Do not skip the `review_equity_order` check for any order, even ones
  that look obviously fine.
