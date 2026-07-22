"""LIVE day-trading engine for the Agentic-2 cash account (912291820) — real money.

GFV-safety design: a Good Faith Violation only happens when unsettled sale proceeds
are used to fund a NEW purchase that is then sold before the original sale settles
(T+1). This engine tracks its own "pending settlement" ledger and only sizes new
BUYs against cash that is NOT still pending from one of ITS OWN recent sells. It
never uses whole-account cash blindly - it treats real Robinhood cash (passed in
by the caller) as the ceiling and subtracts its own pending-settlement amounts.

This script does NOT place real orders itself (no broker access from plain
Python). It has two modes, meant to be called from a live trading session that
does the actual Robinhood calls:

  plan   <fresh_30min_hist.json> <real_cash> <held_symbols_json>
         -> prints JSON: {"sells": [...recommended exits...], "buys": [...recommended entries, sized in fractional shares...]}
         held_symbols_json = JSON list of symbols currently held in ANY position in
         the account (from get_equity_positions) - used to exclude symbols the LIVE
         swing system already holds, so the two systems never touch the same lot.

  commit <executed_actions.json>
         -> updates docs/daytrade_live_state.json: closed positions' proceeds go into
         pending_settlement (unusable for new buys until next business day); newly
         opened positions are recorded with their stop/target.
         executed_actions.json shape: {"sells": [{"symbol":..,"shares":..,"price":..}],
                                        "buys": [{"symbol":..,"shares":..,"price":.., "signal":.., "stop_dist":.., "target_dist":..}]}
"""
import json, math, sys, os
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, 'docs', 'daytrade_live_state.json')
SYMBOLS = ["AMD", "MU", "WDC", "SNDK", "TSM"]
MAXP = 3
MIN_NOTIONAL = 25.0  # skip a new entry if it would size to a trivially small dollar amount
LOOKBACK_BARS = 3  # ~1.5hrs of 30-min bars — matches the live trigger's hourly cadence


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


def rsi_series(closes, period=14):
    out = [None] * len(closes)
    if len(closes) < period + 1: return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        ch = closes[i] - closes[i-1]
        if ch >= 0: gains += ch
        else: losses -= ch
    avg_g, avg_l = gains / period, losses / period
    out[period] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    for i in range(period + 1, len(closes)):
        ch = closes[i] - closes[i-1]
        g = max(ch, 0); l = max(-ch, 0)
        avg_g = (avg_g * (period - 1) + g) / period
        avg_l = (avg_l * (period - 1) + l) / period
        out[i] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    return out


def ema_series(closes, period):
    k = 2 / (period + 1)
    out = [closes[0]]
    for c in closes[1:]: out.append(c * k + out[-1] * (1 - k))
    return out


def build(raw_path):
    d = json.load(open(raw_path))
    bars_by_sym = {}
    for r in d['data']['results']:
        sym = r['symbol']
        bars = []
        for b in r['bars']:
            bars.append({'dt': b['begins_at'], 'date': b['begins_at'][:10],
                         'open': float(b['open_price']), 'close': float(b['close_price']),
                         'high': float(b['high_price']), 'low': float(b['low_price']),
                         'volume': float(b.get('volume', 0) or 0)})
        bars_by_sym[sym] = bars
    IND = {}
    for sym in SYMBOLS:
        if sym not in bars_by_sym: continue
        closes = [b['close'] for b in bars_by_sym[sym]]
        IND[sym] = {'rsi14': rsi_series(closes, 14), 'ema9': ema_series(closes, 9)}
    DAYIDX = {}
    for sym in SYMBOLS:
        if sym not in bars_by_sym: continue
        bars = bars_by_sym[sym]
        meta = []
        day_start_idx = 0
        prev_close = None
        for gi, b in enumerate(bars):
            is_first = (gi == 0) or (bars[gi-1]['date'] != b['date'])
            if is_first:
                day_start_idx = gi
                prev_close = bars[gi-1]['close'] if gi > 0 else None
            is_last = (gi == len(bars) - 1) or (bars[gi+1]['date'] != b['date'])
            meta.append({'i_in_day': gi - day_start_idx, 'is_first': is_first, 'is_last': is_last, 'prev_day_close': prev_close})
        DAYIDX[sym] = meta
    return bars_by_sym, IND, DAYIDX


def make_signals(bars_by_sym, IND, DAYIDX):
    def sig_swing_pullback(sym, gi):
        bars = bars_by_sym[sym]
        if gi < 15: return None
        e9 = IND[sym]['ema9']
        if e9[gi] <= e9[gi-2]: return None
        touched = bars[gi-1]['low'] <= e9[gi-1] * 1.003
        bounced = bars[gi]['close'] > e9[gi] and bars[gi]['close'] > bars[gi-1]['close']
        if touched and bounced:
            rng = sum(bars[j]['high'] - bars[j]['low'] for j in range(gi-5, gi+1)) / 6
            return ((bars[gi]['close'] - e9[gi]) / e9[gi] + 0.001, rng, rng * 2)
        return None

    def sig_hybrid_scalping(sym, gi):
        bars = bars_by_sym[sym]
        if gi < 20: return None
        r = IND[sym]['rsi14']
        if r[gi] is None or r[gi-1] is None: return None
        vol_avg5 = sum(bars[j]['volume'] for j in range(gi-5, gi)) / 5
        if vol_avg5 <= 0: return None
        vol_surge = bars[gi]['volume'] > 1.5 * vol_avg5
        rsi_ok = 50 <= r[gi] <= 75 and r[gi] > r[gi-1]
        breakout = bars[gi]['close'] > max(bars[j]['high'] for j in range(gi-3, gi))
        if vol_surge and rsi_ok and breakout:
            rng = sum(bars[j]['high'] - bars[j]['low'] for j in range(gi-5, gi+1)) / 6
            return (bars[gi]['volume'] / vol_avg5, rng, rng * 2)
        return None

    def sig_gap_momentum(sym, gi):
        bars = bars_by_sym[sym]
        meta = DAYIDX[sym][gi]
        if meta['i_in_day'] != 1: return None
        pc = meta['prev_day_close']
        if pc is None or pc <= 0: return None
        open_bar = bars[gi - 1]
        gap_pct = (open_bar['open'] - pc) / pc
        if gap_pct < 0.015: return None
        holds_gap = bars[gi]['close'] > open_bar['open'] * 0.995
        confirms = bars[gi]['close'] > open_bar['close'] or bars[gi]['volume'] > open_bar['volume']
        if holds_gap and confirms:
            rng = open_bar['high'] - open_bar['low']
            if rng <= 0: return None
            return (gap_pct, rng, rng * 2)
        return None

    def sig_turtle_soup(sym, gi):
        bars = bars_by_sym[sym]
        if gi < 25: return None
        for back in range(1, 3):
            k = gi - back
            if k - 20 < 0: continue
            prior_low = min(bars[j]['low'] for j in range(k - 20, k))
            if bars[k]['low'] < prior_low and bars[gi]['close'] > prior_low:
                rng = sum(bars[j]['high'] - bars[j]['low'] for j in range(gi-5, gi+1)) / 6
                return ((prior_low - bars[k]['low']) / prior_low, rng, rng * 2)
        return None

    def sig_momentum_breakout(sym, gi):
        bars = bars_by_sym[sym]
        if gi < 15: return None
        prior_high = max(bars[j]['high'] for j in range(gi-5, gi))
        vol_avg10 = sum(bars[j]['volume'] for j in range(gi-10, gi)) / 10
        if vol_avg10 <= 0: return None
        if bars[gi]['close'] > prior_high and bars[gi]['volume'] >= 2.0 * vol_avg10:
            rng = sum(bars[j]['high'] - bars[j]['low'] for j in range(gi-5, gi+1)) / 6
            return ((bars[gi]['close'] - prior_high) / prior_high, rng, rng * 2)
        return None

    def sig_mid_range_reversion(sym, gi):
        bars = bars_by_sym[sym]
        meta = DAYIDX[sym][gi]
        i_in_day = meta['i_in_day']
        if i_in_day != 4: return None
        day_start = gi - i_in_day
        day_open = bars[day_start]['open']
        rng_high = max(bars[j]['high'] for j in range(day_start, gi))
        rng_low = min(bars[j]['low'] for j in range(day_start, gi))
        mid = (rng_high + rng_low) / 2
        full_rng = rng_high - rng_low
        if full_rng <= 0: return None
        below_mid = bars[gi]['close'] <= mid
        uptrend_intact = bars[gi]['close'] > day_open
        if below_mid and uptrend_intact:
            return ((mid - bars[gi]['close']) / mid + 0.001, full_rng / 2, full_rng)
        return None

    def sig_opening_range_breakout(sym, gi):
        bars = bars_by_sym[sym]
        meta = DAYIDX[sym][gi]
        i_in_day = meta['i_in_day']
        if i_in_day != 2: return None
        day_start = gi - i_in_day
        or_high = max(bars[day_start]['high'], bars[day_start + 1]['high'])
        or_low = min(bars[day_start]['low'], bars[day_start + 1]['low'])
        or_range = or_high - or_low
        if or_range <= 0: return None
        vol_avg = sum(bars[j]['volume'] for j in range(max(0, gi-10), gi)) / max(1, gi - max(0, gi-10))
        if vol_avg <= 0: return None
        if bars[gi]['close'] > or_high and bars[gi]['volume'] > vol_avg:
            return ((bars[gi]['close'] - or_high) / or_high, or_range, or_range * 2)
        return None

    def sig_id_nr4_breakout(sym, gi):
        meta = DAYIDX[sym][gi]
        if meta['i_in_day'] != 0: return None
        bars = bars_by_sym[sym]
        j = gi - 1
        days_ranges = {}
        while j >= 0 and len(days_ranges) < 5:
            dt = bars[j]['date']
            days_ranges.setdefault(dt, {'high': -1e18, 'low': 1e18})
            days_ranges[dt]['high'] = max(days_ranges[dt]['high'], bars[j]['high'])
            days_ranges[dt]['low'] = min(days_ranges[dt]['low'], bars[j]['low'])
            j -= 1
        ordered_dates = sorted(days_ranges.keys())
        if len(ordered_dates) < 5: return None
        last5 = ordered_dates[-5:]
        d_yest, d_4prior = last5[-1], last5[:-1]
        yest, prior_days = days_ranges[d_yest], [days_ranges[d] for d in d_4prior]
        yest_range = yest['high'] - yest['low']
        if yest_range <= 0: return None
        is_inside = yest['high'] < prior_days[-1]['high'] and yest['low'] > prior_days[-1]['low']
        is_narrowest = all(yest_range < (p['high'] - p['low']) for p in prior_days)
        if not (is_inside and is_narrowest): return None
        for k in range(gi, min(gi + 13, len(bars))):
            if bars[k]['close'] > yest['high']:
                return (yest_range / yest['high'], yest_range, yest_range * 2)
        return None

    def sig_vwap_reclaim(sym, gi):
        bars = bars_by_sym[sym]
        meta = DAYIDX[sym][gi]
        if meta['i_in_day'] < 3: return None
        day_start = gi - meta['i_in_day']
        def vwap_through(k):
            cum_pv = cum_v = 0.0
            for j in range(day_start, k + 1):
                tp = (bars[j]['high'] + bars[j]['low'] + bars[j]['close']) / 3
                v = bars[j]['volume'] or 1
                cum_pv += tp * v; cum_v += v
            return cum_pv / cum_v if cum_v else bars[k]['close']
        vwap_now = vwap_through(gi)
        vwap_prev = vwap_through(gi - 1)
        if bars[gi - 1]['close'] >= vwap_prev: return None
        if bars[gi]['close'] > vwap_now:
            span = max(1, min(6, gi - day_start + 1))
            rng = sum(bars[j]['high'] - bars[j]['low'] for j in range(gi - span + 1, gi + 1)) / span
            if rng <= 0: return None
            return ((bars[gi]['close'] - vwap_now) / vwap_now, rng, rng * 2)
        return None

    def sig_first_pullback_after_orb(sym, gi):
        bars = bars_by_sym[sym]
        meta = DAYIDX[sym][gi]
        day_start = gi - meta['i_in_day']
        if meta['i_in_day'] < 3: return None
        or_high = max(bars[day_start]['high'], bars[day_start + 1]['high'])
        broke_out = any(bars[j]['close'] > or_high for j in range(day_start + 2, gi))
        if not broke_out: return None
        if bars[gi - 1]['close'] <= or_high: return None
        pulled_back = gi - 2 >= day_start and bars[gi - 1]['low'] <= bars[gi - 2]['high']
        bounced = bars[gi]['close'] > bars[gi - 1]['close'] and bars[gi]['close'] > or_high
        if pulled_back and bounced:
            rng = or_high - min(bars[day_start]['low'], bars[day_start + 1]['low'])
            if rng <= 0: return None
            return ((bars[gi]['close'] - or_high) / or_high, rng * 0.5, rng)
        return None

    return {
        'Swing Pullback / Anti': sig_swing_pullback,
        'Hybrid Disciplined Momentum Scalping': sig_hybrid_scalping,
        'Gap / High Change Momentum': sig_gap_momentum,
        'Turtle Soup Reversal': sig_turtle_soup,
        'Momentum Breakout': sig_momentum_breakout,
        'Mid-Range Reversion Rule': sig_mid_range_reversion,
        'Opening Range Breakout': sig_opening_range_breakout,
        'ID/NR4 Volatility Breakout': sig_id_nr4_breakout,
        'VWAP Reclaim': sig_vwap_reclaim,
        'First Pullback After ORB': sig_first_pullback_after_orb,
    }


def cmd_plan(raw_path, real_cash, held_symbols):
    bars_by_sym, IND, DAYIDX = build(raw_path)
    signals = make_signals(bars_by_sym, IND, DAYIDX)
    state = load_state()
    today = datetime.now(timezone.utc).date().isoformat()

    state['pending_settlement'] = [p for p in state['pending_settlement'] if p['settle_date'] > today]
    pending_total = sum(p['amount'] for p in state['pending_settlement'])
    safe_cash = max(0.0, real_cash - pending_total)

    sells = []
    for sym, pos in list(state['open_positions'].items()):
        if sym not in bars_by_sym: continue
        bars = bars_by_sym[sym]
        gi = len(bars) - 1
        bar = bars[gi]
        meta = DAYIDX[sym][gi]
        reason = None
        if bar['low'] <= pos['stop']: reason = 'STOP'
        elif bar['high'] >= pos['target']: reason = 'TARGET'
        elif meta['is_last']: reason = 'EOD_CLOSE'
        if reason:
            sells.append({'symbol': sym, 'shares': pos['shares'], 'reason': reason,
                          'stop': pos['stop'], 'target': pos['target'], 'entry': pos['entry']})

    open_after_sells = len(state['open_positions']) - len(sells)
    slots_free = MAXP - open_after_sells
    buys = []
    if slots_free > 0:
        cands = []
        for sym in SYMBOLS:
            if sym in held_symbols or sym in state['open_positions']: continue
            if sym not in bars_by_sym: continue
            bars = bars_by_sym[sym]
            last_gi = len(bars) - 1
            # Scan back a few bars (not just the single most recent one) so a
            # signal that fired between two hourly LIVE runs isn't missed just
            # because this engine wasn't called at that exact bar — mirrors how
            # the paper engine catches every bar incrementally. Bounded to
            # LOOKBACK_BARS (matches the live trigger's own ~hourly cadence, so
            # it closes the gap between runs) and never crosses into a prior
            # day. Deliberately NOT a whole-day scan: a signal that fired hours
            # ago (e.g. at the opening bell) would otherwise get "entered" now
            # at a much higher chased price with a stop/target sized off that
            # morning's lower volatility — a different, worse trade than the
            # one the backtest actually validated.
            today_date = bars[last_gi]['date']
            today_start_gi = next(i for i, b in enumerate(bars) if b['date'] == today_date)
            scan_start_gi = max(today_start_gi, last_gi - LOOKBACK_BARS)
            best = None
            for gi in range(scan_start_gi, last_gi + 1):
                meta = DAYIDX[sym][gi]
                if meta['is_last']: continue
                for name, fn in signals.items():
                    r = fn(sym, gi)
                    if r is None: continue
                    score, stop_dist, target_dist = r
                    if best is None or gi > best[0]:
                        best = (gi, score, name, stop_dist, target_dist)
            if best is not None:
                gi, score, name, stop_dist, target_dist = best
                cands.append((score, sym, name, bars[last_gi]['close'], stop_dist, target_dist))
        cands.sort(key=lambda x: -x[0])
        seen_syms = set()
        for score, sym, name, price, stop_dist, target_dist in cands:
            if sym in seen_syms: continue
            if len(buys) >= slots_free: break
            notional = safe_cash / max(1, slots_free)
            if notional < MIN_NOTIONAL: continue
            shares = round(notional / price, 6)
            buys.append({'symbol': sym, 'signal': name, 'shares': shares, 'price': round(price, 2),
                        'notional': round(shares * price, 2), 'stop_dist': round(stop_dist, 4),
                        'target_dist': round(target_dist, 4), 'score': round(score, 4)})
            seen_syms.add(sym)

    print(json.dumps({'real_cash': real_cash, 'pending_settlement_total': round(pending_total, 2),
                      'safe_settled_cash': round(safe_cash, 2), 'open_positions': state['open_positions'],
                      'sells': sells, 'buys': buys}, indent=1))


def cmd_commit(actions_path):
    actions = json.load(open(actions_path))
    state = load_state()
    today = datetime.now(timezone.utc).date()
    settle_date = next_business_day(today).isoformat()

    for s in actions.get('sells', []):
        sym = s['symbol']
        if sym in state['open_positions']:
            del state['open_positions'][sym]
        state['pending_settlement'].append({'amount': round(s['shares'] * s['price'], 2),
                                            'settle_date': settle_date, 'symbol': sym})

    for b in actions.get('buys', []):
        sym = b['symbol']
        state['open_positions'][sym] = {'shares': b['shares'], 'entry': b['price'],
                                        'stop': round(b['price'] - b['stop_dist'], 2),
                                        'target': round(b['price'] + b['target_dist'], 2),
                                        'signal': b.get('signal', ''), 'opened': today.isoformat()}

    save_state(state)
    print(f"Committed {len(actions.get('sells', []))} sell(s), {len(actions.get('buys', []))} buy(s). "
          f"Open positions now: {list(state['open_positions'].keys())}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: plan <hist.json> <real_cash> <held_symbols_json>  OR  commit <actions.json>")
        sys.exit(1)
    if sys.argv[1] == 'plan':
        cmd_plan(sys.argv[2], float(sys.argv[3]), json.loads(sys.argv[4]))
    elif sys.argv[1] == 'commit':
        cmd_commit(sys.argv[2])
    else:
        print("Unknown mode:", sys.argv[1])
        sys.exit(1)
