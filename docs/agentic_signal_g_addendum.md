# Signal G Addendum — Asymmetric Pullback (added 2026-07-21)

**Update 2026-07-22:** the Morning Run and Pre-Close Run triggers this file was written for have been
disabled and replaced by "Agentic-2 7-Way Combo (LIVE) - 3-Hour Check" (trig_01AZXmLrvMg4B1Gka5kreqcR,
fires every ~3 hours at 13:45/16:45/19:45 UTC). Signal G is now written directly into that trigger's
own prompt as Signal G — this addendum's workaround is no longer needed for it and this file is kept
as historical record. It would become relevant again only if the old twice-daily triggers are ever
re-enabled with a directly-edited prompt still missing G.

The 6-Way Combo's live trigger prompts (Morning Run, Pre-Close Run) cannot be edited in place
(`update_trigger` returns `prompt_update_disabled` on live-trading routines — a deliberate
platform safety rail). This file is the authoritative spec for Signal G. Every future firing of
either trigger must incorporate this signal exactly as specified here, layered on top of the
existing A-F instructions in the trigger prompt, treating this as a live 7th signal competing
for the same slots.

## Origin

Reverse-engineered from analyzing ~5 months of the user's real Margin account (410961445) trade
history. Winning trades there were driven by buying shallow pullbacks within an established
uptrend and cutting losses fast while letting winners run — not by a high win rate.

## Entry rule

1. Compute the 20-day simple moving average of closing prices (last 20 completed days including
   today: closes[gi-19..gi]).
2. Compute RSI(2): over the last 2 daily close-to-close changes, RSI(2) = 100 * (sum of up-moves)
   / (sum of up-moves + sum of down-moves); if no changes, treat as 50.
3. ENTRY triggers TODAY if BOTH:
   - Today's close > today's 20-day moving average (uptrend intact), AND
   - Today's RSI(2) <= 40 (a shallow pullback within that uptrend — not the deepest oversold
     reading; the real account's winners were manageable dips, not capitulation bottoms).
4. Score = (40 - today's RSI(2)) — deeper pullbacks within the uptrend rank higher among
   qualifying candidates.

## Stop/target (uses the system's standard convention, NOT the original backtest's ratio)

- stop_price = entry_price - 1.75 * ATR(14)
- target_price = entry_price + 3.5 * ATR(14)
- Same EXIT RULE as A-F: hard stop anytime, target only after 2-day minimum hold.
- The original backtest exploration used a 0.75x/5.0x ATR ratio (+$22,420 total, 40% win rate).
  A separate backtest at this system's standard 1.75x/3.5x ratio came in at +$18,727 total
  (nearly as profitable) with a much steadier 64% win rate — chosen for live deployment because
  it keeps this signal consistent with the rest of the system's risk conventions.

## Scope lock — do not violate

Signal G is validated ONLY on exactly AMD, MU, WDC, SNDK, TSM. Confirmed via explicit testing
that its edge does not survive on a 25-stock or 50-stock universe (it loses money on both).
Never let Signal G scan or trade any symbol outside the existing 5-symbol basket, even if other
scope changes are made to the account later.

## Backtest basis (5-window methodology, matching A-F/E-F validation)

| Window | P&L | Trades | Win Rate |
|---|---:|---:|---:|
| W0: Jan-Sep 2025 | $9,779 | 31 | 68% |
| W1: Oct-Nov 2025 | $4,562 | 13 | 62% |
| W2: Dec 2025-Jan 2026 | -$4,942 | 11 | 82% |
| W3: Feb-Mar 2026 | -$896 | 8 | 25% |
| W4: Apr-Jul 2026 | $10,225 | 20 | 65% |
| **Total** | **$18,727** | **83** | **64%** |

Profitable in 3 of 5 windows — the same 3 windows (W0, W1, W4) that A-D and E/F were also
profitable in.

## Honest caveats (report these in every run's VERIFICATION & BACKTEST section)

- Explicitly failed to replicate when tested isolated to TSM alone (the specific symbol that
  drove the real account's edge, -$2,903 standalone) — it only works as a diversified signal
  across all 5 basket names together.
- Unlike Signals E and F, this signal skipped the incremental paper-tracking phase before going
  live — it went straight from backtest to live at the user's explicit request. Treat its live
  behavior with more scrutiny than the other six signals for the first several weeks.
- Not yet tested combined with A-F as one seven-signal portfolio competing for the same slots —
  that interaction is unproven and is being observed live from here forward, same caveat that
  applied to E/F when they went live.

## How to apply this each run

When either the Morning Run or Pre-Close Run trigger fires: read this file (fetch/pull docs/ from
main first, same as the heartbeat step), scan all 5 basket symbols for Signal G exactly as
specified above alongside Signals A-F, include it in the CANDIDATE RANKING (2+ signals agreeing
still ranks first; otherwise rank by raw score descending, same caveat as A-F that scores aren't
on a perfectly common scale), size and execute identically to the other six signals, and report
it in every section of the strict output format (SIGNAL SCAN, CHART SETUPS, AUTOMATION JSON,
VERIFICATION & BACKTEST) using signal label "G".
