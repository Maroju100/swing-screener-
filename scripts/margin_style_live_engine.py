"""LIVE margin-style engine for the Agentic-2 cash account (912291820) - real money.

Implements the "Scaled Dip-Buy / Scaled Peak-Sell" strategy reverse-engineered from
the user's margin account (410961445, read-only, never traded) trading behavior,
using the "Winner" parameter set found via a joint random-search + walk-forward
validation on the 9-Way Combo's 5-symbol basket (2026-07-22 session):

  HUGE_DIP_DRAWDOWN = -25.5% cumulative decline from the trailing LOOKBACK_DAYS-day
                      closing high (not a single day's move - a real multi-day break)
  LOOKBACK_DAYS     = 22 trading days (trailing-high reference window)
  TRANCHE_PCT       = 44.6% of available cash per normal down-day, up to MAX_TRANCHES
  MAX_TRANCHES      = 5
  HUGE_DIP_PCT      = 74.3% of available cash deployed on a huge-dip trigger
  INTRADAY_STOP     = -1.51% from prior close -> sell entire position immediately
  PEAK_SELL_PCT     = 74.3% of shares sold on a new closing high since entry
  GAIN_TIERS        = gain >= 20% -> sell 90%; >= 10% -> sell 50%; >= 5% -> sell 20%

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

HUGE_DIP_DRAWDOWN = -0.255
LOOKBACK_DAYS = 22
TRANCHE_PCT = 0.446
MAX_TRANCHES = 5
HUGE_DIP_PCT = 0.743
INTRADAY_STOP = -0.0151
PEAK_SELL_PCT = 0.743
GAIN_TIERS = [(0.20, 0.90), (0.10, 0.50), (0.05, 0.20)]
MIN_NOTIONAL = 25.0

# Added 2026-07-24 after a code review surfaced three gaps versus the backtest:
MAX_SYMBOL_ALLOCATION_PCT = 0.50  # no single symbol may hold more than 50% of this
                                  # system's total equity (available cash + mark-to-market
                                  # of its own open positions) - caps concentration risk from
                                  # a symbol hitting all 5 tranches in a row.
CIRCUIT_BREAKER_STOP_COUNT = 2    # if this many STOP exits fire in the same run (a broad,
                                  # simultaneous selloff across the basket), skip all new
                                  # entries this run - stops/exits still execute normally,
                                  # only fresh buys pause. Re-evaluated fresh next run.

# Added 2026-07-27 per explicit user request after a single-day run put ~90% of the
# $5,000 allocation into 2 trades (44.6%/74.3%-of-cash sizing has no per-trade ceiling
# on its own), leaving no room for further entries and no settled cash for days once
# those positions later stopped out. Backtested trade-off (honest fills, 6 quarters,
# $5k): uncapped totals +$15,647 (6/6 quarters, worst +$502); capped at $1,000 totals
# +$10,110 (5/6, worst -$74) - a real cost in expected return, accepted deliberately in
# exchange for more concurrent positions and faster access to settled cash.
MAX_TRADE_NOTIONAL = 1000.0


def next_business_day(d):
    d2 = d + timedelta(days=1)
    while d2.weekday() >= 5:
        d2 += timedelta(days=1)
    return d2


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

    candidates = []
    if not circuit_breaker_triggered:
        for sym in SYMBOLS:
            if sym in excluded_symbols or sym not in bars_by_sym or sym not in quotes:
                continue
            pos = state['open_positions'].get(sym)
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

            if drawdown <= HUGE_DIP_DRAWDOWN:
                reason = 'HUGE_DIP'
            elif day_return < 0 and (not pos or pos.get('tranches', 0) < MAX_TRANCHES):
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
        pct = HUGE_DIP_PCT if c['reason'] == 'HUGE_DIP' else TRANCHE_PCT
        uncapped_deploy = safe_cash * pct
        deploy = min(uncapped_deploy, MAX_TRADE_NOTIONAL)

        pos = state['open_positions'].get(sym)
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
            if remaining <= 1e-6 or s['reason'] == 'STOP':
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
