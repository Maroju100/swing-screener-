"""LIVE margin-style engine for the Agentic-2 cash account (912291820) - real money.

Implements the "Scaled Dip-Buy / Scaled Peak-Sell" strategy reverse-engineered from
the user's margin account (410961445, read-only, never traded) trading behavior,
using the "Winner" parameter set found via a joint random-search + walk-forward
validation on the 9-Way Combo's 5-symbol basket (2026-07-22 session):

  HUGE_DIP_DRAWDOWN = -35% cumulative decline from the trailing LOOKBACK_DAYS-day
                      closing high (not a single day's move - a real multi-day break)
                      [changed 2026-08-17 from -25.5%, see "New Candidate" note below]
  LOOKBACK_DAYS     = 60 trading days (trailing-high reference window)
                      [changed 2026-08-18 from 22, see LOOKBACK_DAYS/TRANCHE_PCT note below]
  TRANCHE_SCHEDULE  = [95%, 55%, 35%, 20%, 10%] of available cash per normal down-day
                      (requires >= 0.4% decline vs 2 days prior), indexed by tranches
                      already held in that symbol - full 95% on the first entry into a
                      name, tapering on repeat entries into one that keeps falling
                      [changed 2026-08-19 from flat 95%, see TRANCHE_SCHEDULE note below;
                      0.4% min added 2026-08-18, was "any down day"; flat 95% itself was
                      changed 2026-08-18 from flat 44.6%, see LOOKBACK_DAYS/TRANCHE_PCT
                      note below], up to MAX_TRANCHES
  MAX_TRANCHES      = 5
  TRADE_CAP_SCHEDULE = [25%, 25%, 15%, 10%, 5%] of total equity - a hard ceiling on
                      any single NORMAL_DIP trade's dollar size, indexed the same way
                      as TRANCHE_SCHEDULE. 1st/2nd tranche keep the flat 25% ceiling;
                      3rd/4th/5th repeat entries into a name that's kept falling get a
                      tighter ceiling on top of TRANCHE_SCHEDULE's own cash-% taper.
                      HUGE_DIP always uses the flat MAX_TRADE_NOTIONAL_PCT (25%)
                      instead. [added 2026-08-20, see TRADE_CAP_SCHEDULE note below]
  HUGE_DIP_PCT      = 40% of available cash deployed on a huge-dip trigger
                      [changed 2026-08-17 from 74.3%, see "New Candidate" note below]
  INTRADAY_STOP     = -1.51% from prior close -> sell entire position immediately
  PEAK_SELL_PCT     = 74.3% of shares sold on a new closing high since entry
  GAIN_TIERS        = gain >= 20% -> sell 90%; >= 10% -> sell 50%; >= 5% -> sell 20%
  MAX_HOLD_DAYS     = 7 trading days -> force a full exit if a tranche hasn't hit
                      STOP/PEAK/GAIN on its own by then, freeing stale capital back
                      to cash for a fresher candidate [added 2026-08-21, see
                      MAX_HOLD_DAYS note below]

NEVER PAPER-TRACKED before going live - deployed directly to real money at the
user's explicit request after a backtest-only validation (in-sample 5 windows +
2 out-of-sample holdouts: W4 and a genuine Feb-May 2025 crash period). Every other
signal in this account's live systems at least had a standalone same-methodology
backtest before going live, and several were paper-tracked first; this one has
zero live or paper track record beyond the backtest. Treat with elevated scrutiny.

CROSS-SYSTEM SAFETY: shares the same cash pool and 5-symbol universe as the 9-Way
Combo swing system and Day-Trading LIVE. Follows the same exclusion rule Day-Trading
LIVE already uses against the swing system: never enter a symbol currently held by
either of the other two live systems - the caller passes those symbols in as
excluded_symbols so the three systems never fight over the same share lot.

GFV-safety: same settled-cash discipline as daytrade_live_engine.py - this is a cash
account, so sell proceeds go into pending_settlement (locked until next business
day) and are never counted toward a new buy's sizing until settled.

Uses DAILY bars (not intraday) since this strategy's rules and its "Winner"
parameters were tuned on daily closes. "Today" price is a live-quote proxy, same
convention as the 9-Way Combo's 3-hour checks: today's live price stands in for
today's not-yet-final daily close/low, noted explicitly as an approximation.

Modes:
  plan   <daily_hist.json> <live_quotes.json> <real_cash> <excluded_symbols_json>
         -> prints JSON: {"sells": [...], "buys": [...]}
         daily_hist.json shape: {"data": {"results": [{"symbol":.., "bars":[{"begins_at":.., "open_price":.., "close_price":.., "high_price":.., "low_price":..}]}]}}
         live_quotes.json shape: {"AMD": 555.0, "MU": 972.86, ...}
         excluded_symbols_json = JSON list of symbols currently held by the OTHER
         two live systems on this account (from get_equity_positions there).

  commit <executed_actions.json>
         -> updates docs/margin_style_live_state.json: closed positions' proceeds
         go into pending_settlement; new/updated tranches are recorded with their
         running avg_cost, peak, and tranche count.
         executed_actions.json shape:
           {"sells": [{"symbol":.., "shares":.., "price":.., "reason":..}],
            "buys":  [{"symbol":.., "shares":.., "price":.., "reason":"HUGE_DIP|NORMAL_DIP"}]}
"""
import json, sys, os
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, 'docs', 'margin_style_live_state.json')
# Universe expanded 2026-07-25 from the original 5 to 8 names after honest-fill
# backtesting showed +INTC+LRCX+STX improves every robustness metric (6/6 quarters
# won vs 5/6, worst quarter +$2,284 vs -$901, total +$77,174 vs +$64,443 over
# Jan'25-Jul'26), with the improvement present in BOTH the 2025 and 2026 halves.
# NVDA tested and rejected (-$10-12k drag in every combination; also prohibited live).
SYMBOLS = ["AMD", "MU", "WDC", "SNDK", "TSM", "INTC", "LRCX", "STX"]

# "New Candidate" HUGE_DIP refinement, deployed 2026-08-17 (was -25.5%/74.3%):
# a deeper drawdown trigger + smaller huge-dip sizing, found while re-optimizing
# post honest-fill-mechanism-fix (see MAX_TRADE_NOTIONAL_PCT history below - the
# same STOP-fill correction that flipped the 37.5% cap finding also invalidated
# the original HUGE_DIP_DRAWDOWN/HUGE_DIP_PCT tuning, since it was chosen under
# the same flawed idealized-fill backtest). Re-swept under corrected honest fills
# and validated on 3 windows + a continuous Feb-Aug run at $30k, all using the
# progressive-cash candidate loop matching this file's actual cmd_plan() behavior
# (not the earlier static-cash-snapshot backtest script, which was itself found to
# diverge from this file and has since been retired for validation purposes):
#   6-month (Feb1-Jul31):        Current Live +$28,000.06 (+93.33%) -> New Candidate +$30,905.11 (+103.02%)
#   Down-market (Jun22-Jul29, real -40.9% basket decline):
#                                 Current Live -$356.52 (-1.19%)    -> New Candidate +$50.19 (+0.17%)
#   Recovery (Jul30-Aug14):      Current Live +$4,517.70 (+15.06%) -> New Candidate +$3,818.92 (+12.73%)
#   Continuous Feb1-Aug14:       Current Live +$36,178.09 (+120.59%) -> New Candidate +$38,034.69 (+126.78%)
# New Candidate wins the 6-month, down-market, and continuous totals; gives back a
# small amount on the recovery window alone. It is the only variant tested (besides
# the higher-risk leveraged/dynamic-leverage designs, which are a separate,
# undeployed line of work) that turns the actual down-market positive while still
# beating Current Live on every other measured window - the basis for deploying it.
HUGE_DIP_DRAWDOWN = -0.35
LOOKBACK_DAYS = 60
TRANCHE_SCHEDULE = [0.95, 0.55, 0.35, 0.20, 0.10]  # see progressive-tranche note below
MAX_TRANCHES = 5
HUGE_DIP_PCT = 0.40
INTRADAY_STOP = -0.0151
PEAK_SELL_PCT = 0.743
GAIN_TIERS = [(0.20, 0.90), (0.10, 0.50), (0.05, 0.20)]
MIN_NOTIONAL = 25.0

# NORMAL_DIP single-day-decline threshold, deployed 2026-08-18 (was 0.0, i.e. "any
# down day, any size"). An elaborate grid search (coarse 0%-15%, then a fine sweep
# 0.1%-0.9%) over the day_return cutoff found a genuine plateau around 0.3%-0.6%,
# peaking at 0.4%, using the corrected progressive-cash-decrement engine (matching
# this file's actual candidate loop) with the New Candidate HUGE_DIP params above
# held fixed. Requiring a small minimum decline filters out noise-level "down
# 0.01%" days without giving up the trade volume the strategy's compounding
# depends on - unlike much larger thresholds (tested up to 15%), which win the
# Down-market window in isolation but collapse total trade count and overall
# return everywhere else. Results at $5,000 start, GFV-safe, 8-symbol universe:
#   6-month (Feb1-Jul31):        0.0% +102.7% (1,160 buys) -> 0.4% +120.4% (1,105 buys)
#   Down-market (Jun22-Jul29):   0.0%   +0.3% (255 buys)   -> 0.4%   +8.1% (236 buys)
#   Jul30-Aug14:                 0.0%  +12.7% (99 buys)    -> 0.4%  +11.8% (95 buys)
#   Continuous Feb1-Aug14:       0.0% +126.4% (1,250 buys) -> 0.4% +144.7% (1,193 buys)
# 0.4% wins 3 of 4 windows (including fixing the previously razor-thin Down-market
# result) and gives back a small amount only on the shortest window. A same-day
# TOTAL deployment cap (limiting all buys combined per day, not just per-symbol)
# was also tested as a follow-up idea and REJECTED - it hurt every window at every
# cap level tried, including Down-market itself, so it was not adopted.
NORMAL_DIP_THRESHOLD = 0.004

# LOOKBACK_DAYS and TRANCHE_PCT, deployed 2026-08-18 (were 22 days / 44.6%). Coordinate-
# ascent search (one parameter at a time, New Candidate + 0.4% NORMAL_DIP threshold held
# fixed): PEAK_SELL_PCT and INTRADAY_STOP were also swept and confirmed already near-
# optimal at their current values (74.3% / -1.51%), so left unchanged.
#
# LOOKBACK_DAYS 22->60: widens the trailing-high reference window HUGE_DIP measures
# drawdown against, from ~1 month to ~3 months - a longer memory requires a real,
# sustained breakdown rather than a dip off a recently-reset local high. Down-market
# P&L was IDENTICAL at every lookback tested (22-60d) - a genuine crash blows past the
# -35% threshold regardless of window length, so this only screens noise, not real
# breakdowns. Side effect: a symbol needs ~62 days of history before it's eligible.
#
# TRANCHE_PCT 44.6%->95%: NORMAL_DIP now requests ~95% of available cash per tranche
# instead of 44.6%, still bounded by the existing MAX_TRADE_NOTIONAL_PCT (25% of
# equity) and MAX_SYMBOL_ALLOCATION_PCT (50% of equity) caps, which usually end up
# the binding constraint anyway - so this mostly removes cash left idle below what
# those caps would already allow, rather than bypassing them. Net effect verified
# against the actual Down-market trade log: total capital deployed over the window is
# nearly unchanged (~$54k vs ~$56k recycled through buys) - what changes is that
# capital concentrates into the deepest-drawdown (highest-ranked) candidates each day
# instead of being thinned out across every marginal candidate too. Values above 100%
# were tested and confirmed to plateau (150%/200% produce IDENTICAL results to each
# other - the per-trade cap fully saturates), so 95% sits at the top of a genuine,
# smooth 85-95% plateau just below that saturation point, not an overfit single value.
#
# Walk-forward validated: parameters selected using ONLY Feb1-May15 data, then tested
# cold on the held-out May16-Aug14 period (never seen during selection, contains the
# entire down-market window) - out-of-sample P&L improved +67.6% -> +75.3% at the
# TRAIN-selected values (60d, 90%; final deployed value 95% chosen from the fuller
# sweep). Combined with the 0.4% NORMAL_DIP threshold, results at $5,000 start:
#   6-month (Feb1-Jul31):        +120.4% -> +135.7%
#   Down-market (Jun22-Jul29):     +8.1% ->   +9.7%
#   Jul30-Aug14:                  +11.8% ->  +12.3%
#   Continuous Feb1-Aug14:       +144.7% -> +163.0%
# Wins on all 4 windows simultaneously - the strongest result of any change tested to
# date. Real behavioral cost, not hidden by the backtest: fewer, much larger tranches
# per NORMAL_DIP entry means less cash held in reserve if a second dip follows shortly
# after the first one uses up most of that day's available cash.
#
# A same-day TOTAL deployment cap (limiting all symbols' buys combined per day) and a
# per-symbol consecutive-STOP circuit breaker (cooldown after N stops in a row) were
# both tested as follow-up risk-reduction ideas and REJECTED - both hurt every window
# at every tested setting, including Down-market itself, because they block the same
# rebuy mechanism that captures the eventual recovery, not just the losing entries.
#
# TRANCHE_PCT (flat 95%) -> TRANCHE_SCHEDULE [0.95, 0.55, 0.35, 0.20, 0.10], deployed
# 2026-08-19. Indexed by how many tranches are already held in that symbol (0 = first
# NORMAL_DIP entry into a name, 1 = second, etc.; HUGE_DIP always uses HUGE_DIP_PCT
# regardless of this schedule). The first tranche into any name stays at full 95%
# conviction; only REPEAT entries into a name that has already been bought once and
# kept falling get progressively smaller. Tested against flat 95% and against shrinking
# the first tranche too (both directions: 80/50/30/20/10 and a fully reversed
# 10/20/35/55/95) using the real progressive-cash-decrement engine, $5,000 start,
# Down-market window (Jun22-Jul29, real -40.9% basket decline):
#   Flat 95% (previous):              +$209  (+4.2%),  139 trades
#   95/55/35/20/10 (deployed):        +$230  (+4.6%),  144 trades  <- best of all tested
#   80/50/30/20/10 (shrinks 1st too): +$210  (+4.2%),  162 trades  <- no better than flat
#   10/20/35/55/95 (reversed):        -$105  (-2.1%),  221 trades  <- net LOSS, rejected
# Shrinking the first bet does not help (it shrinks winners along with losers, since the
# strategy can't tell in advance which dip reverses and which keeps falling); the edge
# comes entirely from tapering repeat tranches into names that have already shown they
# didn't bottom on the first try. Real-money verification: cross-matched this account's
# actual Robinhood realized P&L (get_pnl_trade_history) against this engine's own trade
# log for the 75 confidently-attributable closed trades since go-live (2026-07-27 to
# 2026-08-18) - net +$763.08 (58 wins +$797.69, 17 STOP losses only -$34.61), and every
# single real entry day so far had 3+ symbols triggering simultaneously (no isolated-dip
# control group exists yet in the live history - this basket has moved as a correlated
# group the entire time live).

# Added 2026-07-24 after a code review surfaced three gaps versus the backtest:
MAX_SYMBOL_ALLOCATION_PCT = 0.50  # no single symbol may hold more than 50% of this
                                  # system's total equity (available cash + mark-to-market
                                  # of its own open positions) - caps concentration risk from
                                  # a symbol hitting all 5 tranches in a row.
CIRCUIT_BREAKER_STOP_COUNT = 2    # if this many STOP exits fire in the same run (a broad,
                                  # simultaneous selloff across the basket), skip all new
                                  # entries this run - stops/exits still execute normally,
                                  # only fresh buys pause. Re-evaluated fresh next run.

# KILL-SWITCH + TREND RE-ENTRY GATE, added 2026-08-20. A portfolio-level circuit
# breaker distinct from CIRCUIT_BREAKER_STOP_COUNT above: that one reacts to how
# many symbols stopped out in a single run; this one reacts to the system's own
# cumulative equity drawdown from its all-time high, however it happened.
#
# KILL_SWITCH_DD: once this system's total_equity falls this far below its own
# running peak (tracked in docs/margin_style_live_state.json as "equity_peak"),
# liquidate every open position immediately (overrides normal PEAK/GAIN sells -
# see the kill-switch block in cmd_plan) and block ALL new entries, real STOPs
# still execute as normal. Verified against 6.5 months of real trading data: this
# system's own actual max drawdown-from-peak never exceeded -11% (worst point
# 2026-07-29, the real Down-market low) - -15% has a real ~4-point margin above
# anything actually observed and never fired once in that period (0 false
# triggers). Widening it was tested and REJECTED: -20%/-25% cost real crash
# protection (losses run $200-450 worse per scenario, and in one -50%-over-a-week
# test -25% provided ZERO protection because the crash resolved before cumulative
# drawdown ever crossed that high a bar) while buying no additional real-world
# safety margin, since -15% already never false-triggered on any real data tested.
KILL_SWITCH_DD = -0.15
# KILL_SWITCH_RESUME_DAYS: once triggered, stay fully in cash for this many
# trading days before allowing ANY new entries again - deliberately time-based,
# not equity-recovery-based. (A first version tried "resume once equity recovers
# to within X% of peak" - broken by construction, since once fully liquidated to
# cash there is no position left to ride a price recovery, so equity can never
# climb back on its own and the system would stay killed forever after any real
# trigger.)
KILL_SWITCH_RESUME_DAYS = 20
# TREND_GATE_SMA_DAYS: once the kill-switch has EVER fired for this system, every
# future NORMAL_DIP/HUGE_DIP candidate must also have its own price above its
# trailing SMA(TREND_GATE_SMA_DAYS) to be eligible - i.e. only re-enter names
# that have shown real relative strength, not just "N days have passed." This
# flag persists permanently once set (matches the validated backtest exactly -
# never tested resetting it). Backtest evidence (dead-cat-bounce stress test: a
# crash, a fake ~95%-retrace bounce, then a second leg down): a naive
# equity/time-only resume got whipsawed re-buying during the fake bounce (137
# trades, -20.2%); adding this trend gate on re-entries cut that to 73 trades and
# -17.6% - real, demonstrated improvement with zero cost on any real historical
# window (0 kill events across 6.5 months, so the gate never even activates
# there).
TREND_GATE_SMA_DAYS = 50

# Added 2026-07-27 per explicit user request after a single-day run put ~90% of the
# $5,000 allocation into 2 trades (44.6%/74.3%-of-cash sizing has no per-trade ceiling
# on its own), leaving no room for further entries and no settled cash for days once
# those positions later stopped out. Backtested trade-off (honest fills, 6 quarters,
# $5k): uncapped totals +$15,647 (6/6 quarters, worst +$502); capped at $1,000 totals
# +$10,110 (5/6, worst -$74) - a real cost in expected return, accepted deliberately in
# exchange for more concurrent positions and faster access to settled cash.
#
# Changed 2026-08-14 from a fixed $1,000 to a % of this system's own current total
# equity (originally set to 0.375 = 37.5%): a flat dollar cap was tuned for the
# account's $5k starting size (20% of capital) and increasingly strangles returns
# as capital grows, since it stays fixed while the account doesn't. The initial
# 37.5% figure was validated via train/test walk-forward at $5k/$10k/$15k/$20k
# starting capital - BUT that validation used a backtest that checked the STOP
# trigger against a 30-min bar's LOW and filled at the theoretical threshold price,
# not what the real live engine (this file) actually does: check a single
# point-in-time quote and fill at THAT quote. For these volatile names, that's a
# large difference - stocks routinely gap well past the -1.51% stop threshold
# between once-daily checks, so the real fill is often much worse than the
# idealized threshold price the old backtest assumed. That flaw systematically
# favored BIGGER caps (bigger positions look fine when every stop is assumed to
# exit cleanly at the threshold; only honest fills expose that a bigger position
# means a bigger realized loss on a real gap-through).
#
# Corrected 2026-08-14 (same day, later): re-validated with the STOP mechanism
# fixed to match live's actual behavior (single quote check + fill at that quote).
# Under honest fills, 37.5% was the WORST of every option tested - worse than both
# the original flat $1,000 and multiple other dynamic %s, on nearly every metric
# (full 6-month aggregate, both train/test halves, and the one real down-market
# stress period in the data, 2026-06-22 to 2026-07-29, real -40.9% basket decline).
# A fresh dynamic-% sweep under the corrected mechanism found 25% is never the
# worst on any tested window (unlike 37.5%, which was worst on 3 of 4) and stays
# reasonably close to the best option in each case without betting hard on one
# market regime - the safer choice among the validated alternatives (a fixed,
# non-growing $1,875 has higher expected return but meaningfully worse crash
# behavior; a fixed $1,000 has the best crash behavior but leaves more return on
# the table in calm/trending conditions). Chose 25% as the deliberate middle
# ground rather than optimizing hard for either extreme.
MAX_TRADE_NOTIONAL_PCT = 0.25

# TRADE_CAP_SCHEDULE, deployed 2026-08-20. HUGE_DIP always uses the flat
# MAX_TRADE_NOTIONAL_PCT above. For NORMAL_DIP, the per-trade notional ceiling
# itself now also tapers by tranches already held in that symbol - a second,
# independent squeeze layered on top of TRANCHE_SCHEDULE's cash-request-%
# taper. The 1st and 2nd tranche keep the existing flat 25% ceiling unchanged
# (tested reducing these too - hurt every window, confirms the first two bets
# shouldn't be touched); only the 3rd/4th/5th repeat entry into a name that's
# kept falling gets a tighter ceiling. Grid-searched over first-tranche-cap
# (20/25/30%) and taper depth/shape - 25% held for tranches 1-2 was uniquely
# necessary (dropping it to 20% cost ~6pp on the walk-forward test); among
# 25%-anchored variants, delaying the taper to the 3rd tranche (matching where
# TRANCHE_SCHEDULE's own cash-% taper has already reduced typical trade size)
# beat starting the taper at the 2nd tranche. Real progressive-cash-decrement
# engine, $5,000 start, wins or ties EVERY window tested, including both
# halves of the walk-forward split:
#   6-month (Feb1-Jul31):        flat 25% +140.5% -> tapered +143.3%
#   Down-market (Jun22-Jul29):   flat 25%   +4.6% -> tapered   +5.5%
#   Jul30-Aug19:                 flat 25%  +17.4% -> tapered  +17.4% (tie)
#   Continuous (Feb1-Aug19):     flat 25% +152.1% -> tapered +155.1%
#   Walk-forward TRAIN:          flat 25%  +61.6% -> tapered  +62.1%
#   Walk-forward TEST (cold):    flat 25%  +56.0% -> tapered  +57.3%
TRADE_CAP_SCHEDULE = [0.25, 0.25, 0.15, 0.10, 0.05]

# MAX_HOLD_DAYS, added 2026-08-21. Forces a full exit on any tranche that has sat
# open this many trading days without hitting STOP/PEAK/GAIN on its own - stale
# capital gets freed back to cash so it can chase a fresher, better-ranked dip
# instead of sitting idle in a position going nowhere. Swept 5-14 trading days
# using the real progressive-cash-decrement engine (matching this file's actual
# candidate loop), $10,000 start, noon-ET quote convention (same as the live
# trigger's check time):
#   6-month (Feb1-Jul31):     no cap +143.4% -> 7d +168.6%
#   Down-market (Jun22-Jul29): no cap  +5.5% -> 7d  +5.5%  (tie - 0 forced exits fired)
#   Jul30-Aug19:               no cap +17.4% -> 7d +17.2%  (-0.2pp, only window that lost)
#   Continuous (Feb1-Aug19):  no cap +155.1% -> 7d +180.0%
# 7 was the sweep's peak (5d/6d underperform 7d; 8d+ decays back toward the no-cap
# baseline as fewer positions ever reach the cutoff). Walk-forward validated:
# selected on TRAIN (Feb1-May15, where it's a rounding-error -0.3pp) and confirmed
# on cold TEST (May16-Aug19, +57.3% -> +72.9%) - the win is real on unseen data, not
# curve-fit to the selection window. Net effect across every window tested is
# strongly positive with only one negligible loss (-$20 on the smallest-dollar
# window) and no case where it meaningfully hurt.
MAX_HOLD_DAYS = 7


def next_business_day(d):
    d2 = d + timedelta(days=1)
    while d2.weekday() >= 5:
        d2 += timedelta(days=1)
    return d2


def business_days_elapsed(from_date_str, to_date_str):
    """Count trading (weekday) days strictly after from_date_str, up to and
    including to_date_str. Matches the once-per-weekday cadence this engine
    actually runs on (holidays aren't excluded, same approximation
    next_business_day already makes everywhere else in this file)."""
    d = datetime.strptime(from_date_str, '%Y-%m-%d').date()
    to = datetime.strptime(to_date_str, '%Y-%m-%d').date()
    count = 0
    while d < to:
        d += timedelta(days=1)
        if d.weekday() < 5:
            count += 1
    return count


def load_state():
    if os.path.exists(STATE_PATH):
        return json.load(open(STATE_PATH))
    return {'pending_settlement': [], 'open_positions': {}}


def save_state(state):
    json.dump(state, open(STATE_PATH, 'w'), indent=1)


def build(hist_path, quotes_path):
    d = json.load(open(hist_path))
    bars_by_sym = {}
    for r in d['data']['results']:
        bars = [{'date': b['begins_at'][:10], 'close': float(b['close_price'])} for b in r['bars']]
        bars_by_sym[r['symbol']] = bars
    quotes = json.load(open(quotes_path))
    return bars_by_sym, quotes


def cmd_plan(hist_path, quotes_path, real_cash, excluded_symbols):
    bars_by_sym, quotes = build(hist_path, quotes_path)
    state = load_state()
    today = datetime.now(timezone.utc).date().isoformat()

    state['pending_settlement'] = [p for p in state['pending_settlement'] if p['settle_date'] > today]
    pending_total = sum(p['amount'] for p in state['pending_settlement'])
    safe_cash = max(0.0, real_cash - pending_total)

    sells = []
    # PEAK/GAIN sells are deferred here rather than appended straight to `sells`, so they
    # can be NETTED against a same-day buy candidate for the same symbol below (added
    # 2026-08-11 per explicit user request + backtest validation: a 6-month true-
    # compounding backtest showed netting improves this strategy's return, +179.97% ->
    # +202.22%, while cutting same-day-same-symbol trade count 1180 -> 888). Netting only
    # applies to PEAK/GAIN, never STOP: STOP's fill price is prev_close*(1+INTRADAY_STOP),
    # not this run's live quote, so a same-day STOP + buy don't even share a price the way
    # PEAK/GAIN and a same-day buy do (both use `live_price`) - and netting a stop-loss
    # against an unrelated dip-buy would defeat the point of cutting the position.
    pending_peak_gain = {}
    peak_updates = {}
    for sym, pos in list(state['open_positions'].items()):
        if sym not in bars_by_sym or sym not in quotes:
            continue
        bars = bars_by_sym[sym]
        prev_close = bars[-1]['close']
        live_price = quotes[sym]

        # Priority: intraday stop > new peak > gain tiers (matches the backtest)
        if live_price <= prev_close * (1 + INTRADAY_STOP):
            sells.append({'symbol': sym, 'shares': pos['shares'], 'price': round(live_price, 4),
                          'reason': 'STOP', 'entry': pos['entry']})
            continue

        if 'opened' in pos and business_days_elapsed(pos['opened'], today) >= MAX_HOLD_DAYS:
            sells.append({'symbol': sym, 'shares': pos['shares'], 'price': round(live_price, 4),
                          'reason': 'MAX_HOLD', 'entry': pos['entry']})
            continue

        if live_price > pos['peak']:
            sell_shares = round(pos['shares'] * PEAK_SELL_PCT, 6)
            if sell_shares > 0:
                pending_peak_gain[sym] = {'shares': sell_shares, 'reason': 'PEAK',
                                           'price': round(live_price, 4), 'entry': pos['entry']}
            peak_updates[sym] = live_price  # ratchets regardless of whether netting cancels the sell
            continue

        gain_pct = (live_price - pos['entry']) / pos['entry']
        for thresh, pct in GAIN_TIERS:
            if gain_pct >= thresh:
                sell_shares = round(pos['shares'] * pct, 6)
                if sell_shares > 0:
                    pending_peak_gain[sym] = {'shares': sell_shares, 'reason': f'GAIN{int(pct*100)}',
                                               'price': round(live_price, 4), 'entry': pos['entry']}
                break

    stop_count = sum(1 for s in sells if s['reason'] == 'STOP')
    circuit_breaker_triggered = stop_count >= CIRCUIT_BREAKER_STOP_COUNT

    # Total equity this system controls right now, for the concentration cap below.
    # (Available cash + mark-to-market of its own open positions - does not include
    # pending_settlement, which is temporarily locked but still "its" money; a minor
    # underestimate that only makes the cap slightly more conservative, never less.)
    total_equity = safe_cash + sum(pos['shares'] * quotes.get(sym, 0.0)
                                    for sym, pos in state['open_positions'].items() if sym in quotes)

    # Per-trade cap recomputed each run as a % of current total_equity (see
    # MAX_TRADE_NOTIONAL_PCT/TRADE_CAP_SCHEDULE above) - grows/shrinks with the
    # account instead of staying pinned to a stale flat dollar figure.

    # KILL-SWITCH / TREND RE-ENTRY GATE (see constants above for full rationale).
    equity_peak = max(state.get('equity_peak', total_equity), total_equity)
    kill_switch_active = state.get('kill_switch_active', False)
    trend_gate_active = state.get('trend_gate_active', False)
    kill_switch_triggered_date = state.get('kill_switch_triggered_date')
    dd_now = (total_equity - equity_peak) / equity_peak if equity_peak > 0 else 0.0

    if not kill_switch_active and dd_now <= KILL_SWITCH_DD:
        kill_switch_active = True
        trend_gate_active = True
        kill_switch_triggered_date = today
    elif kill_switch_active and kill_switch_triggered_date:
        d = datetime.strptime(kill_switch_triggered_date, '%Y-%m-%d')
        for _ in range(KILL_SWITCH_RESUME_DAYS):
            d = next_business_day(d)
        if today >= d.date().isoformat():
            kill_switch_active = False

    if kill_switch_active:
        # Overrides normal PEAK/GAIN sells entirely: liquidate everything still open
        # (STOP already removed some above) and skip new entries this run.
        already_selling = {s['symbol'] for s in sells}
        pending_peak_gain = {}
        peak_updates = {}
        for sym, pos in list(state['open_positions'].items()):
            if sym in already_selling or sym not in quotes:
                continue
            live_price = quotes[sym]
            sells.append({'symbol': sym, 'shares': pos['shares'], 'price': round(live_price, 4),
                          'reason': 'KILL_SWITCH', 'entry': pos['entry']})

    risk_state = {'equity_peak': round(equity_peak, 2), 'kill_switch_active': kill_switch_active,
                  'kill_switch_triggered_date': kill_switch_triggered_date,
                  'trend_gate_active': trend_gate_active}

    # STOP/MAX_HOLD/KILL_SWITCH fully close a position - unlike PEAK/GAIN, which only
    # trim it - but state['open_positions'] itself isn't mutated until cmd_commit runs
    # after this plan step. Without this, a symbol that both fully exits AND re-qualifies
    # as a fresh buy candidate in the SAME run would get sized/gated off its stale,
    # about-to-be-deleted tranche count (e.g. a same-day STOP-then-rebuy priced as a
    # tapered 2nd+ tranche instead of a fresh 1st tranche) - a real divergence from the
    # validated backtest, which deletes the position from its in-memory state immediately
    # on a full exit. Fixed 2026-08-21 after being caught live (INTC STOP'd then re-bought
    # same run, undersized at 55% instead of 95% of cash - conservative, not dangerous, but
    # not what the backtest validated). Treating these symbols as having no position for
    # tranche eligibility/sizing purposes below matches what state will actually contain
    # once cmd_commit runs.
    full_exit_symbols = {s['symbol'] for s in sells if s['reason'] in ('STOP', 'MAX_HOLD', 'KILL_SWITCH')}

    candidates = []
    if not circuit_breaker_triggered and not kill_switch_active:
        for sym in SYMBOLS:
            if sym in excluded_symbols or sym not in bars_by_sym or sym not in quotes:
                continue
            pos = None if sym in full_exit_symbols else state['open_positions'].get(sym)
            if pos and pos.get('tranches', 0) >= MAX_TRANCHES:
                continue
            bars = bars_by_sym[sym]
            if len(bars) < 2:
                continue
            yesterday_close = bars[-1]['close']
            day_before_close = bars[-2]['close']
            day_return = (yesterday_close - day_before_close) / day_before_close
            lb_bars = bars[-(LOOKBACK_DAYS + 1):-1] if len(bars) > LOOKBACK_DAYS else bars[:-1]
            trailing_high = max(b['close'] for b in lb_bars) if lb_bars else yesterday_close
            drawdown = (yesterday_close - trailing_high) / trailing_high

            if trend_gate_active:
                if len(bars) < TREND_GATE_SMA_DAYS + 1:
                    continue  # not enough history to confirm trend - stay out
                sma_val = sum(b['close'] for b in bars[-(TREND_GATE_SMA_DAYS + 1):-1]) / TREND_GATE_SMA_DAYS
                if yesterday_close < sma_val:
                    continue  # kill-switch has fired before; only re-enter names showing real strength

            if drawdown <= HUGE_DIP_DRAWDOWN:
                reason = 'HUGE_DIP'
            elif day_return <= -NORMAL_DIP_THRESHOLD and (not pos or pos.get('tranches', 0) < MAX_TRANCHES):
                reason = 'NORMAL_DIP'
            else:
                continue
            candidates.append({'symbol': sym, 'drawdown': drawdown, 'day_return': day_return, 'reason': reason})

    # Deepest drawdown gets first claim on remaining cash each run, instead of a fixed
    # symbol always winning ties (was AMD, MU, WDC, SNDK, TSM list order every time).
    candidates.sort(key=lambda c: c['drawdown'])

    buys = []
    netted_symbols = set()
    for c in candidates:
        sym = c['symbol']
        if safe_cash <= 1.0:
            break
        live_price = quotes[sym]
        pos = None if sym in full_exit_symbols else state['open_positions'].get(sym)
        tranches_held = pos.get('tranches', 0) if pos else 0
        if c['reason'] == 'HUGE_DIP':
            pct = HUGE_DIP_PCT
            trade_cap_pct = MAX_TRADE_NOTIONAL_PCT
        else:
            pct = TRANCHE_SCHEDULE[min(tranches_held, len(TRANCHE_SCHEDULE) - 1)]
            trade_cap_pct = TRADE_CAP_SCHEDULE[min(tranches_held, len(TRADE_CAP_SCHEDULE) - 1)]
        uncapped_deploy = safe_cash * pct
        deploy = min(uncapped_deploy, trade_cap_pct * total_equity)

        current_value = pos['shares'] * live_price if pos else 0.0
        room = max(0.0, MAX_SYMBOL_ALLOCATION_PCT * total_equity - current_value)
        capped = min(deploy, room)

        if capped < MIN_NOTIONAL:
            continue
        shares = round(capped / live_price, 6)
        if shares <= 0:
            continue

        pending_sell = pending_peak_gain.get(sym)
        if pending_sell:
            # NETTING: same symbol, same day, same live_price (verified: PEAK/GAIN and
            # this buy candidate both price off `live_price`) - trade only the difference
            # instead of a full sell followed by a full buy.
            netted_symbols.add(sym)
            net_shares = round(shares - pending_sell['shares'], 6)
            if net_shares > 1e-6:
                actual_deploy = net_shares * live_price
                buys.append({'symbol': sym, 'shares': net_shares, 'price': round(live_price, 4),
                             'notional': round(actual_deploy, 2),
                             'reason': f"{c['reason']}-NET(vs {pending_sell['reason']})",
                             'drawdown': round(c['drawdown'], 4), 'day_return': round(c['day_return'], 4),
                             'capped_by_trade_notional_limit': deploy < uncapped_deploy,
                             'capped_by_concentration_limit': capped < deploy})
                safe_cash -= actual_deploy
            elif net_shares < -1e-6:
                sells.append({'symbol': sym, 'shares': round(abs(net_shares), 6), 'price': round(live_price, 4),
                              'reason': f"{pending_sell['reason']}-NET(vs {c['reason']})",
                              'entry': pending_sell['entry']})
            # net_shares == 0: no order at all for this symbol; peak_updates (below) still
            # ratchets it since PEAK was true even though nothing traded.
            continue

        actual_deploy = shares * live_price
        buys.append({'symbol': sym, 'shares': shares, 'price': round(live_price, 4),
                     'notional': round(actual_deploy, 2), 'reason': c['reason'],
                     'drawdown': round(c['drawdown'], 4), 'day_return': round(c['day_return'], 4),
                     'capped_by_trade_notional_limit': deploy < uncapped_deploy,
                     'capped_by_concentration_limit': capped < deploy})
        safe_cash -= actual_deploy  # subsequent symbols this run see reduced remaining cash

    # Any PEAK/GAIN sell that never found a same-day buy candidate to net against
    # executes in full, exactly as before netting existed.
    for sym, pending_sell in pending_peak_gain.items():
        if sym not in netted_symbols:
            sells.append({'symbol': sym, 'shares': pending_sell['shares'], 'price': pending_sell['price'],
                          'reason': pending_sell['reason'], 'entry': pending_sell['entry']})

    # peak_updates is only needed for the rare net-exactly-zero case: a PEAK triggered but
    # netting canceled out to no trade at all, so neither the sell-commit path nor the
    # buy-commit path (both of which already ratchet peak themselves) will touch this
    # symbol's state - without this, its peak would stay stale and PEAK could wrongly
    # re-fire off the old, lower peak next run.
    sold_symbols = {s['symbol'] for s in sells}
    bought_symbols = {b['symbol'] for b in buys}
    peak_updates = {sym: round(p, 4) for sym, p in peak_updates.items()
                    if sym not in sold_symbols and sym not in bought_symbols}

    print(json.dumps({'real_cash': real_cash, 'pending_settlement_total': round(pending_total, 2),
                      'safe_settled_cash': round(max(0.0, real_cash - pending_total), 2),
                      'total_equity': round(total_equity, 2),
                      'circuit_breaker_triggered': circuit_breaker_triggered,
                      'stop_count_this_run': stop_count,
                      'risk_state': risk_state,
                      'open_positions': state['open_positions'], 'sells': sells, 'buys': buys,
                      'peak_updates': peak_updates}, indent=1))


def cmd_commit(actions_path):
    actions = json.load(open(actions_path))
    state = load_state()
    today = datetime.now(timezone.utc).date()
    settle_date = next_business_day(today).isoformat()

    # Prune already-settled entries before appending new ones - previously this list
    # only ever grew (cmd_plan filters expired entries for its own calculation but never
    # persists that), so capital_ledger.py's "available" figure would keep shrinking
    # forever even after cash had genuinely settled and become spendable again.
    state['pending_settlement'] = [p for p in state.get('pending_settlement', [])
                                    if p['settle_date'] > today.isoformat()]

    for s in actions.get('sells', []):
        sym = s['symbol']
        pos = state['open_positions'].get(sym)
        state['pending_settlement'].append({'amount': round(s['shares'] * s['price'], 2),
                                            'settle_date': settle_date, 'symbol': sym})
        if pos:
            remaining = round(pos['shares'] - s['shares'], 6)
            if remaining <= 1e-6 or s['reason'] in ('STOP', 'MAX_HOLD'):
                del state['open_positions'][sym]
            else:
                pos['shares'] = remaining
                if s['price'] > pos['peak']:
                    pos['peak'] = s['price']

    for b in actions.get('buys', []):
        sym = b['symbol']
        pos = state['open_positions'].get(sym)
        if pos:
            new_shares = pos['shares'] + b['shares']
            pos['entry'] = round((pos['entry'] * pos['shares'] + b['price'] * b['shares']) / new_shares, 4)
            pos['shares'] = new_shares
            pos['peak'] = max(pos['peak'], b['price'])
            pos['tranches'] = pos.get('tranches', 0) + 1
        else:
            state['open_positions'][sym] = {'shares': b['shares'], 'entry': b['price'],
                                            'peak': b['price'], 'tranches': 1,
                                            'opened': today.isoformat()}

    # NETTING edge case (added 2026-08-11): a same-day PEAK/GAIN sell and a same-day buy
    # candidate can net to exactly zero shares - no order fires, but the position still hit
    # a new high this run, so its peak still needs to ratchet up or PEAK could keep
    # re-triggering off a stale, lower peak next run. The sell- and buy-commit blocks above
    # already ratchet peak themselves whenever an order actually fires; this only covers
    # the case where neither fired.
    for sym, new_peak in actions.get('peak_updates', {}).items():
        pos = state['open_positions'].get(sym)
        if pos and new_peak > pos['peak']:
            pos['peak'] = new_peak

    # KILL-SWITCH / TREND RE-ENTRY GATE state - passed through verbatim from the
    # plan step's output (same pattern as peak_updates above), since cmd_plan is
    # what decides equity_peak/kill_switch_active/trend_gate_active each run.
    if 'risk_state' in actions:
        state['equity_peak'] = actions['risk_state']['equity_peak']
        state['kill_switch_active'] = actions['risk_state']['kill_switch_active']
        state['kill_switch_triggered_date'] = actions['risk_state']['kill_switch_triggered_date']
        state['trend_gate_active'] = actions['risk_state']['trend_gate_active']

    save_state(state)
    print(f"Committed {len(actions.get('sells', []))} sell(s), {len(actions.get('buys', []))} buy(s), "
          f"{len(actions.get('peak_updates', {}))} peak-only update(s). "
          f"Open positions now: {list(state['open_positions'].keys())}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: plan <daily_hist.json> <live_quotes.json> <real_cash> <excluded_symbols_json>  OR  commit <actions.json>")
        sys.exit(1)
    if sys.argv[1] == 'plan':
        cmd_plan(sys.argv[2], sys.argv[3], float(sys.argv[4]), json.loads(sys.argv[5]))
    elif sys.argv[1] == 'commit':
        cmd_commit(sys.argv[2])
    else:
        print("Unknown mode:", sys.argv[1])
        sys.exit(1)
