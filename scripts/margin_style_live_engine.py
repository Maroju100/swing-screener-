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
SYMBOLS = ["AMD", "MU", "WDC", "SNDK", "TSM"]

HUGE_DIP_DRAWDOWN = -0.255
LOOKBACK_DAYS = 22
TRANCHE_PCT = 0.446
MAX_TRANCHES = 5
HUGE_DIP_PCT = 0.743
INTRADAY_STOP = -0.0151
PEAK_SELL_PCT = 0.743
GAIN_TIERS = [(0.20, 0.90), (0.10, 0.50), (0.05, 0.20)]
MIN_NOTIONAL = 25.0


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
                sells.append({'symbol': sym, 'shares': sell_shares, 'price': round(live_price, 4),
                              'reason': 'PEAK', 'entry': pos['entry']})
            continue

        gain_pct = (live_price - pos['entry']) / pos['entry']
        for thresh, pct in GAIN_TIERS:
            if gain_pct >= thresh:
                sell_shares = round(pos['shares'] * pct, 6)
                if sell_shares > 0:
                    sells.append({'symbol': sym, 'shares': sell_shares, 'price': round(live_price, 4),
                                  'reason': f'GAIN{int(pct*100)}', 'entry': pos['entry']})
                break

    buys = []
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
        live_price = quotes[sym]
        if safe_cash <= 1.0:
            continue

        if drawdown <= HUGE_DIP_DRAWDOWN:
            deploy = safe_cash * HUGE_DIP_PCT
            reason = 'HUGE_DIP'
        elif day_return < 0 and (not pos or pos.get('tranches', 0) < MAX_TRANCHES):
            deploy = safe_cash * TRANCHE_PCT
            reason = 'NORMAL_DIP'
        else:
            continue

        if deploy < MIN_NOTIONAL:
            continue
        shares = round(deploy / live_price, 6)
        if shares <= 0:
            continue
        buys.append({'symbol': sym, 'shares': shares, 'price': round(live_price, 4),
                     'notional': round(shares * live_price, 2), 'reason': reason,
                     'drawdown': round(drawdown, 4), 'day_return': round(day_return, 4)})
        safe_cash -= deploy  # subsequent symbols this run see reduced remaining cash

    print(json.dumps({'real_cash': real_cash, 'pending_settlement_total': round(pending_total, 2),
                      'safe_settled_cash': round(max(0.0, real_cash - pending_total), 2),
                      'open_positions': state['open_positions'], 'sells': sells, 'buys': buys}, indent=1))


def cmd_commit(actions_path):
    actions = json.load(open(actions_path))
    state = load_state()
    today = datetime.now(timezone.utc).date()
    settle_date = next_business_day(today).isoformat()

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

    save_state(state)
    print(f"Committed {len(actions.get('sells', []))} sell(s), {len(actions.get('buys', []))} buy(s). "
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
