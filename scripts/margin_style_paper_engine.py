"""Incremental paper-trading engine for the "Scaled Dip-Buy / Scaled Peak-Sell"
strategy (the "Winner" joint-search-optimized config) - the one signal in this
whole project that went straight from backtest to real money (scripts/
margin_style_live_engine.py) without ever being paper-tracked first. This
engine exists so it can ALSO be observed on an isolated $25k paper account,
same as every other not-yet-fully-vetted signal, purely for comparison against
its real-money performance - it does not feed into or affect the live engine.

REWRITTEN 2026-08-11 for full parity with margin_style_live_engine.py's actual
mechanics, after the user asked why this paper tracker didn't model the same
constraints as the real system. Previously this engine processed each symbol's
entire catch-up range independently (symbol-by-symbol, not date-synchronized)
and let a same-day sell's proceeds fund that same day's buy immediately - i.e.
it had NO settlement delay at all, unlike the real cash account. That made its
numbers systematically more optimistic than what the live account could
actually achieve, and it was also missing three other live safeguards
(concentration cap, circuit breaker, deepest-drawdown-first buy ordering).
This rewrite adds all four, restructuring the loop to be date-synchronized
across all 8 symbols (required for settlement to work at all, since it's a
single shared cash pool) instead of per-symbol independent catch-up:
  - GFV-SAFE T+1 SETTLEMENT: sell proceeds go into pending_settlement and are
    not usable for a buy until the next business day, exactly like the live
    engine's real cash-account constraint.
  - CONCENTRATION CAP: no symbol may hold more than 50% of system equity.
  - CIRCUIT BREAKER: 2+ STOP exits in one day pauses new entries that day.
  - DEEPEST-DRAWDOWN-FIRST: when multiple buy candidates compete for the same
    day's limited settled cash, the deepest drawdown gets first claim.
  - SAME-DAY SAME-SYMBOL NETTING (added 2026-08-11, matching the live engine):
    when a PEAK/GAIN sell and a same-day buy fire for the same symbol, only
    the net share difference trades - both legs price off the same day's
    close, so this changes nothing about the final position, just avoids
    needlessly parking cash in a same-day round trip. STOP is never netted
    (different price basis - the stop fill is off the prior close, not
    today's close - and netting a stop-loss against an unrelated dip-buy
    would defeat the point of cutting the position).

Uses DAILY bars. As of 2026-08-11 the trigger that runs this script also
closes the last remaining gap with the live engine: it fetches a live noon
quote for each symbol and appends one synthetic "today" bar (open=high=low=
close=that quote) after the real historicals before calling this script -
this file itself needs no special handling for that, since it already treats
every new date generically (it only ever reads high/low/close off whatever
bar it's given, real or synthetic, exactly like swing_paper_engine.py's own
noon-proxy convention). The result: this tracker and the live engine now
observe "today's price" the same way, at the same time of day, with the same
approximation (a single live quote standing in for the day's full range) -
the only structural difference left is that this script commits its own
paper trades immediately, with no review_equity_order/place_equity_order step,
since there is no real broker to reconcile against.

State reset 2026-08-11 alongside this rewrite: the previous accumulated P&L
was computed under the old, more permissive (no-settlement) mechanics and is
not comparable to results going forward, so docs/margin_style_paper_state.json
and docs/margin_style_paper_log.json were reset to a fresh $25,000.

Usage: python3 scripts/margin_style_paper_engine.py <fresh_daily_historicals.json>

Reads/writes docs/margin_style_paper_state.json (single $25k simulated
account - one strategy, not per-strategy like the other paper trackers) and
appends to docs/margin_style_paper_log.json. Places NO real orders.
"""
import json, sys, os
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, 'docs', 'margin_style_paper_state.json')
LOG_PATH = os.path.join(ROOT, 'docs', 'margin_style_paper_log.json')
# 2026-07-25: expanded to match the live system's 8-name universe so the paper
# mirror stays a valid side-by-side comparison. New symbols initialize fresh in
# state (incremental tracking is per-symbol).
SYMBOLS = ["AMD", "MU", "WDC", "SNDK", "TSM", "INTC", "LRCX", "STX"]
CAPITAL = 5000.0  # 2026-08-11: reduced from $25k to match the live engine's actual $5k
                  # allocation and the 36-strategy compounding-ledger backtest's basis -
                  # this paper tracker is now the same dollar size as the real account,
                  # not a scaled-up mirror of it.

# "Winner" config (joint random-search + walk-forward validated, 2026-07-22)
# HUGE_DIP_DRAWDOWN/HUGE_DIP_PCT updated 2026-08-17 to match margin_style_live_engine.py's
# "New Candidate" deployment (was -25.5%/74.3%) - see that file for the full validation
# writeup (3 windows + a continuous Feb1-Aug14 run at $30k, all under the corrected
# progressive-cash candidate loop). Kept in exact parity so this paper tracker stays a
# valid side-by-side comparison against the live account.
HUGE_DIP_DRAWDOWN = -0.35
LOOKBACK_DAYS = 22
TRANCHE_PCT = 0.446
MAX_TRANCHES = 5
HUGE_DIP_PCT = 0.40
INTRADAY_STOP = -0.0151
PEAK_SELL_PCT = 0.743
GAIN_TIERS = [(0.20, 0.90), (0.10, 0.50), (0.05, 0.20)]
MIN_NOTIONAL = 25.0

# NORMAL_DIP_THRESHOLD updated 2026-08-18 to match margin_style_live_engine.py's
# deployment (was 0.0, "any down day") - see that file for the full grid-search
# writeup (0.4% found optimal, wins 3 of 4 validation windows). Kept in exact
# parity so this paper tracker stays a valid side-by-side comparison against live.
NORMAL_DIP_THRESHOLD = 0.004

# 2026-08-11: now that CAPITAL matches the live engine's $5,000 allocation exactly
# (previously this tracker ran at $25k, 5x live, so this was scaled to $5,000 to
# preserve the same 20%-of-allocation ratio), this cap is set to the live engine's
# actual $1,000 - same dollar cap, not just the same ratio.
#
# Changed 2026-08-14 for parity with the live engine's same-dated change: a fixed
# dollar cap doesn't scale as capital grows. Now a % of this tracker's own current
# total equity, recomputed each run, same as the live engine.
#
# Corrected 2026-08-14 (same day, later, again for parity): the initial 37.5%
# figure was found using a backtest that modeled STOP fills incorrectly (checked
# a bar's low instead of the single live quote the real engine actually uses, and
# filled at the idealized threshold price instead of that quote) - see
# margin_style_live_engine.py's own comment for the full account. Under a
# corrected, honest-fill backtest, 37.5% was the worst of every option tested.
# 25% was never the worst on any tested window - the deliberate middle ground
# between a safer, lower-return fixed $1,000 and a higher-return, more
# crash-exposed fixed $1,875.
MAX_TRADE_NOTIONAL_PCT = 0.25

# Added 2026-08-11 for parity with the live engine's same-named safeguards.
MAX_SYMBOL_ALLOCATION_PCT = 0.50
CIRCUIT_BREAKER_STOP_COUNT = 2


def next_business_day(d):
    d2 = d + timedelta(days=1)
    while d2.weekday() >= 5:
        d2 += timedelta(days=1)
    return d2


def build_context(raw_path):
    d = json.load(open(raw_path))
    bars_by_sym = {}
    for r in d['data']['results']:
        bars = [{'date': b['begins_at'][:10], 'high': float(b['high_price']),
                 'low': float(b['low_price']), 'close': float(b['close_price'])} for b in r['bars']]
        bars_by_sym[r['symbol']] = bars
    return bars_by_sym


def load_state():
    if os.path.exists(STATE_PATH):
        state = json.load(open(STATE_PATH))
        state.setdefault('pending_settlement', [])
        return state
    return {'cash': CAPITAL, 'positions': {}, 'last_processed_date': {}, 'pending_settlement': []}


def load_log():
    if os.path.exists(LOG_PATH):
        return json.load(open(LOG_PATH))
    return {'capital': CAPITAL, 'symbols': SYMBOLS,
            'strategy': 'Scaled Dip-Buy / Scaled Peak-Sell (Winner config)',
            'note': 'PAPER TRADING ONLY - no real orders placed. Daily bars, GFV-safe T+1 settlement, '
                     'full parity with margin_style_live_engine.py\'s safeguards (concentration cap, '
                     'circuit breaker, deepest-drawdown-first, same-day netting) since 2026-08-11. '
                     'This strategy is otherwise LIVE on real money (scripts/margin_style_live_engine.py); '
                     'this paper track is a separate, non-connected comparison only.',
            'runs': []}


def run(raw_path):
    bars_by_sym = build_context(raw_path)
    state = load_state()
    log = load_log()
    run_trades = []
    now = datetime.now(timezone.utc).isoformat()

    cash = state['cash']
    positions = state['positions']
    last_processed = state['last_processed_date']
    pending = state['pending_settlement']

    # Determine each symbol's new-date range (same incremental catch-up rule as
    # before: first run only evaluates the newest 1-2 bars, never backfills
    # fake history), then union into one globally-sorted date sequence so
    # settlement and the shared cash pool advance correctly across symbols.
    date_idx = {}
    new_dates_by_sym = {}
    for sym in SYMBOLS:
        if sym not in bars_by_sym:
            continue
        bars = bars_by_sym[sym]
        date_idx[sym] = {b['date']: i for i, b in enumerate(bars)}
        last_dt = last_processed.get(sym)
        if last_dt is None:
            start_gi = max(2, len(bars) - 2)
        else:
            start_gi = next((i for i, b in enumerate(bars) if b['date'] > last_dt), len(bars))
        start_gi = max(start_gi, 2)
        new_dates_by_sym[sym] = set(bars[gi]['date'] for gi in range(start_gi, len(bars)))

    all_new_dates = sorted(set(dt for dts in new_dates_by_sym.values() for dt in dts))

    for dt in all_new_dates:
        released = [p for p in pending if p['settle_date'] <= dt]
        for p in released:
            cash += p['amount']
        pending = [p for p in pending if p['settle_date'] > dt]

        active_syms = [sym for sym in SYMBOLS if sym in new_dates_by_sym and dt in new_dates_by_sym[sym]]

        # Pass 1: STOP checks only - highest priority, never netted (see module
        # docstring: the stop's fill price is off the PRIOR close, not today's
        # close, so it isn't even the same trade as a same-day buy).
        stop_count = 0
        for sym in active_syms:
            gi = date_idx[sym][dt]
            if gi < 1:
                continue
            bars = bars_by_sym[sym]
            prev_close = bars[gi - 1]['close']
            bar = bars[gi]
            p = positions.get(sym)
            if not p:
                continue
            if bar['low'] <= prev_close * (1 + INTRADAY_STOP):
                fill = prev_close * (1 + INTRADAY_STOP)
                pnl = p['shares'] * (fill - p['avg_cost'])
                settle_date = next_business_day(datetime.strptime(dt, '%Y-%m-%d')).strftime('%Y-%m-%d')
                pending.append({'amount': round(p['shares'] * fill, 2), 'settle_date': settle_date, 'symbol': sym})
                run_trades.append({'symbol': sym, 'date': dt, 'side': 'SELL', 'reason': 'STOP',
                                    'entry': round(p['avg_cost'], 4), 'exit': round(fill, 4),
                                    'shares': p['shares'], 'pnl': round(pnl, 2)})
                del positions[sym]
                stop_count += 1

        circuit_breaker_triggered = stop_count >= CIRCUIT_BREAKER_STOP_COUNT

        # Pass 2: defer PEAK/GAIN sells (don't execute yet - may net against a
        # same-day buy candidate below, since both price off today's close).
        pending_sells = {}
        for sym in active_syms:
            p = positions.get(sym)
            if not p:
                continue
            gi = date_idx[sym][dt]
            close = bars_by_sym[sym][gi]['close']
            if close > p['peak']:
                sell_shares = round(p['shares'] * PEAK_SELL_PCT, 6)
                if sell_shares > 0:
                    pending_sells[sym] = (sell_shares, 'PEAK', close)
                p['peak'] = close  # ratchets regardless of netting outcome
            else:
                gain_pct = (close - p['avg_cost']) / p['avg_cost']
                for thresh, pct in GAIN_TIERS:
                    if gain_pct >= thresh:
                        sell_shares = round(p['shares'] * pct, 6)
                        if sell_shares > 0:
                            pending_sells[sym] = (sell_shares, f'GAIN{int(pct*100)}', close)
                        break

        # Pass 3: buy candidates, deepest-drawdown-first, sized against
        # already-settled cash only (today's pending sells are NOT usable yet -
        # GFV-safe), then netted against any pending PEAK/GAIN sell for the
        # same symbol.
        def mark_price(sym):
            if sym in date_idx and dt in date_idx[sym]:
                return bars_by_sym[sym][date_idx[sym][dt]]['close']
            return bars_by_sym[sym][-1]['close']

        total_equity = cash + sum(p['shares'] * mark_price(sym)
                                   for sym, p in positions.items() if sym in bars_by_sym)

        # Per-trade cap recomputed each run as a % of current total_equity - see
        # MAX_TRADE_NOTIONAL_PCT above, kept in parity with the live engine.
        max_trade_notional = MAX_TRADE_NOTIONAL_PCT * total_equity

        candidates = []
        if not circuit_breaker_triggered:
            for sym in active_syms:
                gi = date_idx[sym][dt]
                bars = bars_by_sym[sym]
                if gi < LOOKBACK_DAYS + 2:
                    continue
                p = positions.get(sym)
                if p and p.get('tranches', 0) >= MAX_TRANCHES:
                    continue
                prev_close = bars[gi - 1]['close']
                prev_prev_close = bars[gi - 2]['close']
                day_return = (prev_close - prev_prev_close) / prev_prev_close
                lb_start = max(0, gi - 1 - LOOKBACK_DAYS)
                trailing_high = max(bars[j]['close'] for j in range(lb_start, gi - 1))
                drawdown = (prev_close - trailing_high) / trailing_high
                reason = None
                if drawdown <= HUGE_DIP_DRAWDOWN:
                    reason = 'HUGE_DIP'
                elif day_return <= -NORMAL_DIP_THRESHOLD and (not p or p.get('tranches', 0) < MAX_TRANCHES):
                    reason = 'NORMAL_DIP'
                if reason:
                    candidates.append({'symbol': sym, 'drawdown': drawdown, 'reason': reason})
        candidates.sort(key=lambda c: c['drawdown'])

        netted_symbols = set()
        for c in candidates:
            sym = c['symbol']
            if cash <= 1.0:
                break
            gi = date_idx[sym][dt]
            close = bars_by_sym[sym][gi]['close']
            pct = HUGE_DIP_PCT if c['reason'] == 'HUGE_DIP' else TRANCHE_PCT
            deploy = min(cash * pct, max_trade_notional)

            p = positions.get(sym)
            current_value = p['shares'] * close if p else 0.0
            room = max(0.0, MAX_SYMBOL_ALLOCATION_PCT * total_equity - current_value)
            capped = min(deploy, room)
            if capped < MIN_NOTIONAL:
                continue
            shares = round(capped / close, 6)
            if shares <= 0:
                continue

            pend = pending_sells.get(sym)
            if pend:
                netted_symbols.add(sym)
                sell_shares, sell_reason, sell_price = pend
                net = round(shares - sell_shares, 6)
                if net > 1e-6:
                    cash -= net * close
                    if p:
                        new_shares = p['shares'] + net
                        p['avg_cost'] = (p['avg_cost'] * p['shares'] + net * close) / new_shares
                        p['shares'] = new_shares
                        p['tranches'] = p.get('tranches', 0) + 1
                    else:
                        positions[sym] = {'shares': net, 'avg_cost': close, 'peak': close, 'tranches': 1}
                    run_trades.append({'symbol': sym, 'date': dt, 'side': 'BUY',
                                        'reason': f'{c["reason"]}-NET(vs {sell_reason})',
                                        'shares': net, 'price': round(close, 4)})
                elif net < -1e-6:
                    sell_net = abs(net)
                    pnl = sell_net * (close - p['avg_cost'])
                    settle_date = next_business_day(datetime.strptime(dt, '%Y-%m-%d')).strftime('%Y-%m-%d')
                    pending.append({'amount': round(sell_net * close, 2), 'settle_date': settle_date, 'symbol': sym})
                    run_trades.append({'symbol': sym, 'date': dt, 'side': 'SELL',
                                        'reason': f'{sell_reason}-NET(vs {c["reason"]})',
                                        'entry': round(p['avg_cost'], 4), 'exit': round(close, 4),
                                        'shares': sell_net, 'pnl': round(pnl, 2)})
                    p['shares'] -= sell_net
                    if p['shares'] <= 1e-9:
                        del positions[sym]
                # net == 0: no order; peak already ratcheted above.
                continue

            cash -= capped
            if p:
                new_shares = p['shares'] + shares
                p['avg_cost'] = (p['avg_cost'] * p['shares'] + capped) / new_shares
                p['shares'] = new_shares
                p['peak'] = max(p['peak'], close)
                p['tranches'] = p.get('tranches', 0) + 1
            else:
                positions[sym] = {'shares': shares, 'avg_cost': close, 'peak': close, 'tranches': 1}
            run_trades.append({'symbol': sym, 'date': dt, 'side': 'BUY', 'reason': c['reason'],
                                'shares': shares, 'price': round(close, 4)})

        # Any PEAK/GAIN sell that never found a same-day buy candidate to net
        # against executes in full, exactly as before netting existed.
        for sym, (sell_shares, sell_reason, sell_price) in pending_sells.items():
            if sym in netted_symbols:
                continue
            p = positions.get(sym)
            if not p:
                continue
            pnl = sell_shares * (sell_price - p['avg_cost'])
            settle_date = next_business_day(datetime.strptime(dt, '%Y-%m-%d')).strftime('%Y-%m-%d')
            pending.append({'amount': round(sell_shares * sell_price, 2), 'settle_date': settle_date, 'symbol': sym})
            run_trades.append({'symbol': sym, 'date': dt, 'side': 'SELL', 'reason': sell_reason,
                                'entry': round(p['avg_cost'], 4), 'exit': round(sell_price, 4),
                                'shares': sell_shares, 'pnl': round(pnl, 2)})
            p['shares'] -= sell_shares
            if p['shares'] <= 1e-9:
                del positions[sym]

        for sym in active_syms:
            last_processed[sym] = dt

    state['cash'] = cash
    state['positions'] = positions
    state['last_processed_date'] = last_processed
    state['pending_settlement'] = pending

    pending_total = sum(p['amount'] for p in pending)
    hv = sum(p['shares'] * bars_by_sym[sym][-1]['close'] for sym, p in positions.items() if sym in bars_by_sym)
    cum_pl = round(cash + pending_total + hv - CAPITAL, 2)

    log['runs'].append({'timestamp': now, 'trades': run_trades, 'cumulative_pl': cum_pl})
    json.dump(state, open(STATE_PATH, 'w'), indent=1)
    json.dump(log, open(LOG_PATH, 'w'), indent=1)

    print(f"Margin-Style paper-trading run {now}: {len(run_trades)} new trade event(s)")
    for t in run_trades:
        print(f"  {t}")
    print(f"\nCumulative paper P&L (Scaled Dip-Buy/Scaled Peak-Sell, Winner config): {cum_pl:,.2f}")
    print(f"Cash: {cash:,.2f}  Pending settlement: {pending_total:,.2f}  Open positions: {list(positions.keys())}")


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python3 margin_style_paper_engine.py <fresh_daily_historicals.json>")
        sys.exit(1)
    run(sys.argv[1])
