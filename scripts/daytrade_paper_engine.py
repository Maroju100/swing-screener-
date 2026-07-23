"""Incremental paper-trading engine for the top 8 backtested day-trading strategies.

Usage: python3 scripts/daytrade_paper_engine.py <fresh_30min_historicals.json>

Reads/writes docs/daytrade_paper_state.json (open paper positions + cash per strategy)
and appends to docs/daytrade_paper_log.json (trade-by-trade + per-run equity snapshot).
Places NO real orders — this only maintains simulated positions in JSON.
"""
import json, math, sys, os
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, 'docs', 'daytrade_paper_state.json')
LOG_PATH = os.path.join(ROOT, 'docs', 'daytrade_paper_log.json')
SYMBOLS = ["AMD", "MU", "WDC", "SNDK", "TSM"]
CAPITAL_PER_STRATEGY = 25000.0
MAXP = 3
MAXNEW_PER_BAR = 1

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

def sig_swing_pullback(bars_by_sym, IND, DAYIDX, sym, gi):
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

def sig_hybrid_scalping(bars_by_sym, IND, DAYIDX, sym, gi):
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

def sig_gap_momentum(bars_by_sym, IND, DAYIDX, sym, gi):
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

def sig_turtle_soup(bars_by_sym, IND, DAYIDX, sym, gi):
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

def sig_momentum_breakout(bars_by_sym, IND, DAYIDX, sym, gi):
    bars = bars_by_sym[sym]
    if gi < 15: return None
    prior_high = max(bars[j]['high'] for j in range(gi-5, gi))
    vol_avg10 = sum(bars[j]['volume'] for j in range(gi-10, gi)) / 10
    if vol_avg10 <= 0: return None
    if bars[gi]['close'] > prior_high and bars[gi]['volume'] >= 2.0 * vol_avg10:
        rng = sum(bars[j]['high'] - bars[j]['low'] for j in range(gi-5, gi+1)) / 6
        return ((bars[gi]['close'] - prior_high) / prior_high, rng, rng * 2)
    return None

def sig_mid_range_reversion(bars_by_sym, IND, DAYIDX, sym, gi):
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

def sig_opening_range_breakout(bars_by_sym, IND, DAYIDX, sym, gi):
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

def sig_id_nr4_breakout(bars_by_sym, IND, DAYIDX, sym, gi):
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

def sig_relative_volume_leader(bars_by_sym, IND, DAYIDX, sym, gi):
    meta = DAYIDX[sym][gi]
    if meta['i_in_day'] < 6: return None
    bars = bars_by_sym[sym]
    ratios = {}
    for s in bars_by_sym:
        b2 = bars_by_sym[s]; m2 = DAYIDX[s]
        if gi >= len(b2) or m2[gi]['i_in_day'] < 6: continue
        avg5 = sum(b2[j]['volume'] for j in range(gi-5, gi)) / 5
        if avg5 <= 0: continue
        ratios[s] = b2[gi]['volume'] / avg5
    if not ratios or sym not in ratios: return None
    if ratios[sym] != max(ratios.values()) or ratios[sym] < 1.5: return None
    if bars[gi]['close'] <= max(bars[j]['high'] for j in range(gi-3, gi)): return None
    rng = sum(bars[j]['high']-bars[j]['low'] for j in range(gi-5, gi+1)) / 6
    if rng <= 0: return None
    return (ratios[sym], rng, rng * 2)

def sig_oversold_snapback(bars_by_sym, IND, DAYIDX, sym, gi):
    meta = DAYIDX[sym][gi]
    if meta['i_in_day'] < 4: return None
    bars = bars_by_sym[sym]
    start_price = bars[gi-3]['close']
    low_price = min(bars[j]['low'] for j in range(gi-3, gi))
    drop = (start_price - low_price) / start_price
    if drop < 0.02: return None
    midpoint = (start_price+low_price)/2
    if bars[gi]['close'] > midpoint and bars[gi]['close'] > bars[gi-1]['close']:
        rng = sum(bars[j]['high']-bars[j]['low'] for j in range(gi-3, gi+1)) / 4
        if rng <= 0: return None
        return (drop, rng, rng * 2)
    return None

def sig_vwap_reclaim(bars_by_sym, IND, DAYIDX, sym, gi):
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

def sig_first_pullback_after_orb(bars_by_sym, IND, DAYIDX, sym, gi):
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

# Relative Volume Leader Momentum and Oversold Snapback Fade are paper-only pending further
# validation; Oversold Snapback Fade backtested negative (-$319.98) and is included here for
# continued observation, not because it looked promising. VWAP Reclaim and First Pullback After
# ORB (added 2026-07-22 to Day-Trading LIVE directly, skipping paper-tracking per explicit user
# request) are added here too so their behavior can also be observed on an isolated $25k paper
# account, same as every other not-yet-fully-vetted signal.
STRATEGIES = {
    'Swing Pullback / Anti': sig_swing_pullback,
    'Hybrid Disciplined Momentum Scalping': sig_hybrid_scalping,
    'Gap / High Change Momentum': sig_gap_momentum,
    'Turtle Soup Reversal': sig_turtle_soup,
    'Momentum Breakout': sig_momentum_breakout,
    'Mid-Range Reversion Rule': sig_mid_range_reversion,
    'Opening Range Breakout': sig_opening_range_breakout,
    'ID/NR4 Volatility Breakout': sig_id_nr4_breakout,
    'Relative Volume Leader Momentum': sig_relative_volume_leader,
    'Oversold Snapback Fade': sig_oversold_snapback,
    'VWAP Reclaim (H2)': sig_vwap_reclaim,
    'First Pullback After ORB (H2)': sig_first_pullback_after_orb,
}

def build_indicators(raw_path):
    d = json.load(open(raw_path))
    bars_by_sym = {}
    for r in d['data']['results']:
        sym = r['symbol']
        bars = []
        for b in r['bars']:
            bars.append({
                'dt': b['begins_at'], 'date': b['begins_at'][:10],
                'open': float(b['open_price']), 'close': float(b['close_price']),
                'high': float(b['high_price']), 'low': float(b['low_price']),
                'volume': float(b.get('volume', 0) or 0),
            })
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

def load_state():
    if os.path.exists(STATE_PATH):
        return json.load(open(STATE_PATH))
    return {name: {'cash': CAPITAL_PER_STRATEGY, 'positions': {}, 'last_processed_dt': {}} for name in STRATEGIES}

def load_log():
    if os.path.exists(LOG_PATH):
        return json.load(open(LOG_PATH))
    return {'capital_per_strategy': CAPITAL_PER_STRATEGY, 'symbols': SYMBOLS,
            'strategies': list(STRATEGIES.keys()), 'note': 'PAPER TRADING ONLY - no real orders placed.', 'runs': []}

def run(raw_path):
    bars_by_sym, IND, DAYIDX = build_indicators(raw_path)
    state = load_state()
    log = load_log()
    run_trades = []
    now = datetime.now(timezone.utc).isoformat()

    for name, sig_fn in STRATEGIES.items():
        st = state.setdefault(name, {'cash': CAPITAL_PER_STRATEGY, 'positions': {}, 'last_processed_dt': {}})
        cash = st['cash']
        positions = st['positions']
        last_processed = st['last_processed_dt']

        for sym in SYMBOLS:
            if sym not in bars_by_sym: continue
            bars = bars_by_sym[sym]
            last_dt = last_processed.get(sym)
            if last_dt is None:
                start_gi = max(0, len(bars) - 2)  # first run: only evaluate the newest bar, don't backfill history as fake paper trades
            else:
                start_gi = next((i for i, b in enumerate(bars) if b['dt'] > last_dt), len(bars))

            for gi in range(start_gi, len(bars)):
                bar = bars[gi]
                meta = DAYIDX[sym][gi]

                if sym in positions:
                    pos = positions[sym]
                    exit_reason = None
                    if bar['low'] <= pos['stop']: exit_reason = 'STOP'
                    elif bar['high'] >= pos['target']: exit_reason = 'TARGET'
                    elif meta['is_last']: exit_reason = 'EOD_CLOSE'
                    if exit_reason:
                        exit_price = pos['stop'] if exit_reason == 'STOP' else (pos['target'] if exit_reason == 'TARGET' else bar['close'])
                        pnl = pos['shares'] * (exit_price - pos['entry'])
                        cash += pos['shares'] * exit_price
                        trade = {'strategy': name, 'date': bar['date'], 'symbol': sym, 'side': 'SELL', 'reason': exit_reason,
                                 'entry': round(pos['entry'], 2), 'exit': round(exit_price, 2), 'shares': pos['shares'], 'pnl': round(pnl, 2)}
                        run_trades.append(trade)
                        del positions[sym]

                if sym not in positions and len(positions) < MAXP and not meta['is_last']:
                    r = sig_fn(bars_by_sym, IND, DAYIDX, sym, gi)
                    if r is not None:
                        score, stop_dist, target_dist = r
                        price = bar['close']
                        tv = cash + sum(positions[s]['shares'] * bars_by_sym[s][min(gi, len(bars_by_sym[s])-1)]['close'] for s in positions)
                        target_notional = tv / MAXP
                        shares = math.floor(target_notional / price)
                        if shares >= 1 and shares * price <= cash:
                            cash -= shares * price
                            positions[sym] = {'entry': price, 'shares': shares, 'stop': price - stop_dist, 'target': price + target_dist}
                            run_trades.append({'strategy': name, 'date': bar['date'], 'symbol': sym, 'side': 'BUY', 'shares': shares, 'price': round(price, 2)})

                last_processed[sym] = bar['dt']

        st['cash'] = cash
        st['positions'] = positions
        st['last_processed_dt'] = last_processed

    snapshot = {}
    for name in STRATEGIES:
        st = state[name]
        hv = 0.0
        for sym, pos in st['positions'].items():
            if sym in bars_by_sym:
                hv += pos['shares'] * bars_by_sym[sym][-1]['close']
        snapshot[name] = round(st['cash'] + hv - CAPITAL_PER_STRATEGY, 2)

    log['runs'].append({'timestamp': now, 'trades': run_trades, 'equity_snapshot': snapshot})
    json.dump(state, open(STATE_PATH, 'w'), indent=1)
    json.dump(log, open(LOG_PATH, 'w'), indent=1)

    print(f"Paper-trading run {now}: {len(run_trades)} new trade event(s)")
    for t in run_trades:
        print(f"  {t}")
    print("\nCumulative paper P&L by strategy (since state was initialized):")
    for name, pl in sorted(snapshot.items(), key=lambda x: -x[1]):
        print(f"  {name:42}{pl:>12,.2f}")

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python3 daytrade_paper_engine.py <fresh_30min_historicals.json>")
        sys.exit(1)
    run(sys.argv[1])
