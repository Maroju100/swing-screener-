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

## Strategy 1: Margin-Style Live (real money, daily)

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
- **Key thresholds** (do not change without explicit request):
  - `HUGE_DIP_DRAWDOWN = -0.35`, `HUGE_DIP_PCT = 0.40`
  - `NORMAL_DIP_THRESHOLD = 0.004` (tranche-indexed sizing)
  - `INTRADAY_STOP = -0.0151` — see standing directive above
  - `PEAK_SELL_PCT = 0.743`
  - `GAIN_TIERS = [(0.20, 0.90), (0.10, 0.50), (0.05, 0.20)]`
  - `MAX_HOLD_DAYS = 6`
  - `KILL_SWITCH_DD = -0.15`, `KILL_SWITCH_RESUME_DAYS = 20`,
    `TREND_GATE_SMA_DAYS = 50`
  - `CIRCUIT_BREAKER_STOP_COUNT = 2`
  - `MAX_SYMBOL_ALLOCATION_PCT = 0.50`, `MAX_TRADE_NOTIONAL_PCT = 0.25`
  - Same-day same-symbol orders net against each other.
- **Live dashboard**: `margin_live_dashboard.html`
  (`https://claude.ai/code/artifact/b22d0a38-624f-496b-a47c-f08d16703488`).
  Live sections (positions, account/risk snapshot, distance-to-next-signal)
  read the account live via the artifact `mcp` capability
  (`get_accounts`, `get_portfolio`, `get_equity_quotes`,
  `get_equity_historicals` — read-only tools only, never order-placement
  tools). Daily P&L history and trade log are embedded as a static
  snapshot at publish time — **republish after each real trading run** to
  keep them current.

## Strategy 2: v3 (tightened) day-trading

- Explored via `semis_momentum.html` dashboard
  (`https://claude.ai/code/artifact/9f8fcbfa-a426-41cf-a016-a407133b855a`)
  and backtest scripts in the scratchpad — this is a research/paper
  context, not live-money, unless stated otherwise.
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
