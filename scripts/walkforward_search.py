"""One-off ad hoc walk-forward parameter search (NOT a live/paper tracker - writes
no state, touches no other system's files) for 5 candidate strategies flagged as
worth deeper investigation after a $5k/30-day backtest sensitivity check:
  - Turtle Soup Reversal (day-trading, 30-min bars)
  - VWAP Reclaim (H2) (day-trading, 30-min bars)
  - Momentum Breakout (day-trading, 30-min bars)
  - Mid-Range Reversion Rule (day-trading, 30-min bars)
  - Pivot Point S1 Bounce (swing, daily bars, 5-symbol basket)

Methodology matches how "Winner" configs were validated elsewhere in this project:
non-overlapping windows (capital reset to $5,000 each window), scored by
(windows_profitable, total_pnl) - prioritizing consistency across regimes over a
single lucky continuous run. 5 windows each, using ~1yr of 30-min bars (day-trading)
and ~1.5yr of daily bars (swing).

Frequency baseline per strategy uses whichever cadence the earlier sensitivity
check favored: continuous (every 30-min bar) for Turtle Soup Reversal and VWAP
Reclaim (both improved under continuous checking); twice-daily for Momentum
Breakout and Mid-Range Reversion Rule (both were hurt by continuous checking).
Pivot Point S1 Bounce is inherently once/day (daily bars).

Usage: python3 scripts/walkforward_search.py <daily_hist.json> <thirty_min_1yr_hist.json>
"""
import json, sys, os, math
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import daytrade_paper_engine as DT

CAPITAL = 5000.0
DT_SYMBOLS = DT.SYMBOLS
SWING_SYMBOLS = ["AMD", "MU", "WDC", "SNDK", "TSM"]
MAXP_DT = 3
MAXP_SWING = 5


def next_business_day(d):
    d2 = d + timedelta(days=1)
    while d2.weekday() >= 5:
        d2 += timedelta(days=1)
    return d2


def make_windows(dates, n=5):
    """Split a sorted date list into n contiguous, roughly-equal, non-overlapping windows."""
    size = len(dates) // n
    windows = []
    for i in range(n):
        start = i * size
        end = (i + 1) * size if i < n - 1 else len(dates)
        windows.append((dates[start], dates[end - 1]))
    return windows


# ---------------------------------------------------------------------------
# Swing (daily bars) generic single-strategy window backtest
# ---------------------------------------------------------------------------

def atr_series(bars, period=14):
    trs = [bars[0]['high'] - bars[0]['low']]
    for i in range(1, len(bars)):
        tr = max(bars[i]['high'] - bars[i]['low'], abs(bars[i]['high'] - bars[i-1]['close']), abs(bars[i]['low'] - bars[i-1]['close']))
        trs.append(tr)
    out = [None] * len(bars)
    if len(trs) < period:
        return out
    atr = sum(trs[:period]) / period
    out[period-1] = atr
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
        out[i] = atr
    return out


def load_daily(daily_path, universe=None):
    universe = universe or SWING_SYMBOLS
    d = json.load(open(daily_path))
    bars_by_sym = {}
    for r in d['data']['results']:
        if r['symbol'] not in universe:
            continue
        bars_by_sym[r['symbol']] = [{'date': b['begins_at'][:10], 'open': float(b['open_price']),
                                       'close': float(b['close_price']), 'high': float(b['high_price']),
                                       'low': float(b['low_price'])} for b in r['bars']]
    atr_by_sym = {s: atr_series(bars_by_sym[s]) for s in bars_by_sym}
    return bars_by_sym, atr_by_sym


def sig_pivot_point_bounce(bars, atr, gi, touch_mult, stop_atr, target_atr):
    if gi < 30 or atr[gi] is None:
        return None
    y = bars[gi - 1]
    P = (y['high'] + y['low'] + y['close']) / 3
    S1 = (P * 2) - y['high']
    touched = y['low'] <= S1 * touch_mult or bars[gi]['low'] <= S1 * touch_mult
    bounced = bars[gi]['close'] > S1 and bars[gi]['close'] > y['close']
    trend_ok = bars[gi]['close'] > P
    if touched and bounced and trend_ok:
        return (atr[gi] * stop_atr, atr[gi] * target_atr)
    return None


def backtest_swing_window(bars_by_sym, atr_by_sym, sig_fn, min_hold, window_start, window_end, universe=None, maxp=None):
    universe = universe or SWING_SYMBOLS
    maxp = maxp or MAXP_SWING
    date_idx = {sym: {b['date']: i for i, b in enumerate(bars_by_sym[sym])} for sym in bars_by_sym}
    dates = sorted(set(dt for sym in bars_by_sym for dt in date_idx[sym] if window_start <= dt <= window_end))
    cash = CAPITAL
    pending = []
    positions = {}
    for dt in dates:
        released = [p for p in pending if p[0] <= dt]
        for p in released:
            cash += p[1]
        pending = [p for p in pending if p[0] > dt]

        for sym in list(positions.keys()):
            gi = date_idx[sym].get(dt)
            if gi is None:
                continue
            bars = bars_by_sym[sym]
            pos = positions[sym]
            held = gi - pos['entry_gi']
            exit_reason = None
            if bars[gi]['low'] <= pos['stop']:
                exit_reason = 'STOP'
            elif held >= min_hold and bars[gi]['high'] >= pos['target']:
                exit_reason = 'TARGET'
            if exit_reason:
                exit_price = pos['stop'] if exit_reason == 'STOP' else pos['target']
                pending.append([next_business_day(datetime.strptime(dt, '%Y-%m-%d')).strftime('%Y-%m-%d'), pos['shares'] * exit_price])
                del positions[sym]
            else:
                pos['last_price'] = bars[gi]['close']

        if len(positions) < maxp:
            for sym in universe:
                if sym in positions or len(positions) >= maxp or sym not in bars_by_sym:
                    continue
                gi = date_idx[sym].get(dt)
                if gi is None:
                    continue
                r = sig_fn(sym, gi)
                if r is None:
                    continue
                stop_dist, target_dist = r
                price = bars_by_sym[sym][gi]['close']
                pending_total = sum(p[1] for p in pending)
                posval = sum(p['shares'] * p.get('last_price', p['entry']) for p in positions.values())
                tv = cash + pending_total + posval
                shares = (tv / maxp) / price
                cost = shares * price
                if shares > 0 and cost <= cash:
                    cash -= cost
                    positions[sym] = {'entry': price, 'shares': shares, 'entry_gi': gi,
                                        'stop': price - stop_dist, 'target': price + target_dist, 'last_price': price}

    pending_total = sum(p[1] for p in pending)
    posval = sum(p['shares'] * p.get('last_price', p['entry']) for p in positions.values())
    equity = cash + pending_total + posval
    return round(equity - CAPITAL, 2)


# ---------------------------------------------------------------------------
# Day-trading (30-min bars) generic single-strategy window backtest
# ---------------------------------------------------------------------------

def load_intraday(path):
    d = json.load(open(path))
    bars_by_sym = {}
    for r in d['data']['results']:
        if r['symbol'] not in DT_SYMBOLS:
            continue
        bars = []
        for b in r['bars']:
            bars.append({'dt': b['begins_at'], 'date': b['begins_at'][:10], 'open': float(b['open_price']),
                          'close': float(b['close_price']), 'high': float(b['high_price']),
                          'low': float(b['low_price']), 'volume': float(b.get('volume', 0) or 0)})
        bars_by_sym[r['symbol']] = bars
    DAYIDX = {}
    for sym, bars in bars_by_sym.items():
        meta = []
        day_start_idx = 0
        prev_close = None
        for gi, b in enumerate(bars):
            is_first = (gi == 0) or (bars[gi-1]['date'] != b['date'])
            if is_first:
                day_start_idx = gi
                prev_close = bars[gi-1]['close'] if gi > 0 else None
            is_last = (gi == len(bars)-1) or (bars[gi+1]['date'] != b['date'])
            meta.append({'i_in_day': gi - day_start_idx, 'is_first': is_first, 'is_last': is_last, 'prev_day_close': prev_close})
        DAYIDX[sym] = meta
    return bars_by_sym, DAYIDX


def backtest_daytrade_window(bars_by_sym, DAYIDX, sig_fn, continuous, window_start, window_end):
    day_bars = {}
    for sym in DT_SYMBOLS:
        if sym not in bars_by_sym:
            continue
        day_bars[sym] = {}
        for gi, b in enumerate(bars_by_sym[sym]):
            if window_start <= b['date'] <= window_end:
                day_bars[sym].setdefault(b['date'], []).append(gi)

    all_dates = sorted(set(dt for sym in day_bars for dt in day_bars[sym]))
    cash = CAPITAL
    pending = []
    positions = {}

    for date in all_dates:
        released = [p for p in pending if p[0] <= date]
        for p in released:
            cash += p[1]
        pending = [p for p in pending if p[0] > date]

        n_bars_today = max((len(day_bars[s][date]) for s in DT_SYMBOLS if s in day_bars and date in day_bars[s]), default=0)
        if n_bars_today == 0:
            continue
        if continuous:
            i_in_day_checkpoints = list(range(n_bars_today))
        else:
            i_in_day_checkpoints = sorted(set(min(t, n_bars_today - 1) for t in (3, 10)))

        for cp_num, i_in_day_target in enumerate(i_in_day_checkpoints):
            is_final_check = (cp_num == len(i_in_day_checkpoints) - 1)
            for sym in DT_SYMBOLS:
                if sym not in day_bars or date not in day_bars[sym]:
                    continue
                idxs = day_bars[sym][date]
                check_gi = idxs[min(i_in_day_target, len(idxs) - 1)]
                bars = bars_by_sym[sym]
                day_start = idxs[0]

                if sym in positions:
                    pos = positions[sym]
                    exit_reason, exit_price = None, None
                    for j in range(pos['last_checked_gi'] + 1, check_gi + 1):
                        if bars[j]['low'] <= pos['stop']:
                            exit_reason, exit_price = 'STOP', pos['stop']
                            break
                        if bars[j]['high'] >= pos['target']:
                            exit_reason, exit_price = 'TARGET', pos['target']
                            break
                    if exit_reason is None and is_final_check:
                        exit_reason, exit_price = 'EOD_CLOSE', bars[check_gi]['close']
                    if exit_reason:
                        pending.append([next_business_day(datetime.strptime(date, '%Y-%m-%d')).strftime('%Y-%m-%d'), pos['shares'] * exit_price])
                        del positions[sym]
                    else:
                        pos['last_checked_gi'] = check_gi

                if sym not in positions and len(positions) < MAXP_DT:
                    fired = None
                    for j in range(day_start, check_gi + 1):
                        r = sig_fn(bars_by_sym, DAYIDX, sym, j)
                        if r is not None:
                            fired = r
                    if fired is not None:
                        stop_dist, target_dist = fired
                        price = bars[check_gi]['close']
                        pending_total = sum(p[1] for p in pending)
                        posval = sum(positions[s]['shares'] * bars_by_sym[s][positions[s]['last_checked_gi']]['close'] for s in positions)
                        tv = cash + pending_total + posval
                        shares = (tv / MAXP_DT) / price
                        cost = shares * price
                        if shares > 0 and cost <= cash:
                            cash -= cost
                            positions[sym] = {'entry': price, 'shares': shares, 'stop': price - stop_dist,
                                                'target': price + target_dist, 'last_checked_gi': check_gi}

    pending_total = sum(p[1] for p in pending)
    posval = sum(positions[s]['shares'] * bars_by_sym[s][positions[s]['last_checked_gi']]['close'] for s in positions)
    equity = cash + pending_total + posval
    return round(equity - CAPITAL, 2)


# ---------------------------------------------------------------------------
# Parameterized signal generators
# ---------------------------------------------------------------------------

def gen_turtle_soup(lookback, rr):
    stop_mult, target_mult = rr
    def sig(bars_by_sym, DAYIDX, sym, gi):
        bars = bars_by_sym[sym]
        if gi < lookback + 5:
            return None
        for back in range(1, 3):
            k = gi - back
            if k - lookback < 0:
                continue
            prior_low = min(bars[j]['low'] for j in range(k - lookback, k))
            if bars[k]['low'] < prior_low and bars[gi]['close'] > prior_low:
                rng = sum(bars[j]['high'] - bars[j]['low'] for j in range(gi-5, gi+1)) / 6
                return (rng * stop_mult, rng * target_mult)
        return None
    return sig


def gen_vwap_reclaim(min_i_in_day, rr):
    stop_mult, target_mult = rr
    def sig(bars_by_sym, DAYIDX, sym, gi):
        bars = bars_by_sym[sym]
        meta = DAYIDX[sym][gi]
        if meta['i_in_day'] < min_i_in_day:
            return None
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
        if bars[gi-1]['close'] >= vwap_prev:
            return None
        if bars[gi]['close'] > vwap_now:
            span = max(1, min(6, gi - day_start + 1))
            rng = sum(bars[j]['high'] - bars[j]['low'] for j in range(gi - span + 1, gi + 1)) / span
            if rng <= 0:
                return None
            return (rng * stop_mult, rng * target_mult)
        return None
    return sig


def gen_momentum_breakout(lookback, vol_mult, rr):
    stop_mult, target_mult = rr
    def sig(bars_by_sym, DAYIDX, sym, gi):
        bars = bars_by_sym[sym]
        if gi < lookback + 10:
            return None
        prior_high = max(bars[j]['high'] for j in range(gi - lookback, gi))
        vol_avg = sum(bars[j]['volume'] for j in range(gi - 10, gi)) / 10
        if vol_avg <= 0:
            return None
        if bars[gi]['close'] > prior_high and bars[gi]['volume'] >= vol_mult * vol_avg:
            rng = sum(bars[j]['high'] - bars[j]['low'] for j in range(gi-5, gi+1)) / 6
            return (rng * stop_mult, rng * target_mult)
        return None
    return sig


def gen_mid_range_reversion(check_bar, rr):
    stop_frac, target_frac = rr
    def sig(bars_by_sym, DAYIDX, sym, gi):
        bars = bars_by_sym[sym]
        meta = DAYIDX[sym][gi]
        if meta['i_in_day'] != check_bar:
            return None
        day_start = gi - meta['i_in_day']
        day_open = bars[day_start]['open']
        rng_high = max(bars[j]['high'] for j in range(day_start, gi))
        rng_low = min(bars[j]['low'] for j in range(day_start, gi))
        mid = (rng_high + rng_low) / 2
        full_rng = rng_high - rng_low
        if full_rng <= 0:
            return None
        if bars[gi]['close'] <= mid and bars[gi]['close'] > day_open:
            return (full_rng * stop_frac, full_rng * target_frac)
        return None
    return sig


# ---------------------------------------------------------------------------
# Search driver
# ---------------------------------------------------------------------------

def search_daytrade(name, gen_fn, param_grid, bars_by_sym, DAYIDX, windows, continuous):
    results = []
    for params in param_grid:
        sig_fn = gen_fn(**params)
        window_pls = [backtest_daytrade_window(bars_by_sym, DAYIDX, sig_fn, continuous, w[0], w[1]) for w in windows]
        n_profit = sum(1 for p in window_pls if p > 0)
        total = round(sum(window_pls), 2)
        results.append({'params': params, 'window_pls': window_pls, 'n_profit': n_profit, 'total': total})
    results.sort(key=lambda r: (-r['n_profit'], -r['total']))
    return results


def search_swing(name, gen_fn, param_grid, bars_by_sym, atr_by_sym, windows, min_hold, universe=None, maxp=None):
    results = []
    for params in param_grid:
        p2 = {k: v for k, v in params.items() if k != 'min_hold'}
        sig_fn = lambda sym, gi, _p=p2: gen_fn(bars_by_sym[sym], atr_by_sym[sym], gi, **_p)
        window_pls = [backtest_swing_window(bars_by_sym, atr_by_sym, sig_fn, params.get('min_hold', min_hold), w[0], w[1], universe=universe, maxp=maxp) for w in windows]
        n_profit = sum(1 for p in window_pls if p > 0)
        total = round(sum(window_pls), 2)
        results.append({'params': params, 'window_pls': window_pls, 'n_profit': n_profit, 'total': total})
    results.sort(key=lambda r: (-r['n_profit'], -r['total']))
    return results


if __name__ == '__main__':
    if len(sys.argv) not in (3, 4):
        print("Usage: python3 walkforward_search.py <daily_hist.json> <thirty_min_1yr_hist.json> [<top50_daily_hist.json>]")
        sys.exit(1)

    daily_bars, atr_by_sym = load_daily(sys.argv[1])
    intraday_bars, DAYIDX = load_intraday(sys.argv[2])

    daily_dates = sorted(set(b['date'] for bars in daily_bars.values() for b in bars))
    intraday_dates = sorted(set(b['date'] for bars in intraday_bars.values() for b in bars))
    daily_windows = make_windows(daily_dates, 5)
    intraday_windows = make_windows(intraday_dates, 5)

    print("Daily windows:", daily_windows)
    print("Intraday windows:", intraday_windows)
    print()

    # --- Turtle Soup Reversal (continuous) ---
    grid = [{'lookback': lb, 'rr': rr} for lb in (10, 15, 20, 25, 30) for rr in ((1, 2), (1.5, 3), (2, 3), (1, 3))]
    res = search_daytrade('Turtle Soup Reversal', gen_turtle_soup, grid, intraday_bars, DAYIDX, intraday_windows, continuous=True)
    print("=== Turtle Soup Reversal (continuous checks) - top 5 ===")
    for r in res[:5]:
        print(f"  {r['params']}  windows_profitable={r['n_profit']}/5  total={r['total']:>10,.2f}  per_window={r['window_pls']}")
    print()

    # --- VWAP Reclaim (continuous) ---
    grid = [{'min_i_in_day': m, 'rr': rr} for m in (2, 3, 4, 5) for rr in ((1, 2), (0.75, 1.5), (1.5, 3), (1, 3))]
    res = search_daytrade('VWAP Reclaim (H2)', gen_vwap_reclaim, grid, intraday_bars, DAYIDX, intraday_windows, continuous=True)
    print("=== VWAP Reclaim (H2) (continuous checks) - top 5 ===")
    for r in res[:5]:
        print(f"  {r['params']}  windows_profitable={r['n_profit']}/5  total={r['total']:>10,.2f}  per_window={r['window_pls']}")
    print()

    # --- Momentum Breakout (twice-daily) ---
    grid = [{'lookback': lb, 'vol_mult': vm, 'rr': (1, 2)} for lb in (3, 5, 8, 10) for vm in (1.5, 2.0, 2.5, 3.0)]
    res = search_daytrade('Momentum Breakout', gen_momentum_breakout, grid, intraday_bars, DAYIDX, intraday_windows, continuous=False)
    print("=== Momentum Breakout (twice-daily checks) - top 5 ===")
    for r in res[:5]:
        print(f"  {r['params']}  windows_profitable={r['n_profit']}/5  total={r['total']:>10,.2f}  per_window={r['window_pls']}")
    print()

    # --- Mid-Range Reversion Rule (twice-daily) ---
    grid = [{'check_bar': cb, 'rr': rr} for cb in (3, 4, 5, 6) for rr in ((0.3, 1), (0.5, 1), (0.5, 1.5), (0.7, 2))]
    res = search_daytrade('Mid-Range Reversion Rule', gen_mid_range_reversion, grid, intraday_bars, DAYIDX, intraday_windows, continuous=False)
    print("=== Mid-Range Reversion Rule (twice-daily checks) - top 5 ===")
    for r in res[:5]:
        print(f"  {r['params']}  windows_profitable={r['n_profit']}/5  total={r['total']:>10,.2f}  per_window={r['window_pls']}")
    print()

    # --- Pivot Point S1 Bounce (swing, daily) ---
    grid = [{'touch_mult': tm, 'stop_atr': sa, 'target_atr': ta, 'min_hold': mh}
            for tm in (1.005, 1.01, 1.02) for sa in (1.0, 1.5, 2.0) for ta in (2.0, 3.0, 4.0) for mh in (1, 2)]
    res = search_swing('Pivot Point S1 Bounce', sig_pivot_point_bounce, grid, daily_bars, atr_by_sym, daily_windows, min_hold=2)
    print("=== Pivot Point S1 Bounce (swing, 5-symbol) - top 5 ===")
    for r in res[:5]:
        print(f"  {r['params']}  windows_profitable={r['n_profit']}/5  total={r['total']:>10,.2f}  per_window={r['window_pls']}")
    print()

    # --- Pivot Point S1 Bounce (Top-50 S&P universe, pivot50_paper_engine.py) ---
    if len(sys.argv) == 4:
        import pivot50_paper_engine as P50
        daily50_bars, atr50_by_sym = load_daily(sys.argv[3], universe=P50.SYMBOLS)
        daily50_dates = sorted(set(b['date'] for bars in daily50_bars.values() for b in bars))
        daily50_windows = make_windows(daily50_dates, 5)
        print("Top-50 windows:", daily50_windows)
        grid = [{'touch_mult': tm, 'stop_atr': sa, 'target_atr': ta, 'min_hold': mh}
                for tm in (1.005, 1.01, 1.02) for sa in (1.0, 1.5, 2.0) for ta in (2.0, 3.0, 4.0) for mh in (1, 2)]
        res = search_swing('Pivot Point S1 Bounce (Top-50)', sig_pivot_point_bounce, grid, daily50_bars, atr50_by_sym,
                            daily50_windows, min_hold=2, universe=P50.SYMBOLS, maxp=P50.MAXP)
        print("=== Pivot Point S1 Bounce (Top-50 S&P universe) - top 5 ===")
        for r in res[:5]:
            print(f"  {r['params']}  windows_profitable={r['n_profit']}/5  total={r['total']:>10,.2f}  per_window={r['window_pls']}")
        # also report the CURRENT baseline config for direct comparison
        base_params = {'touch_mult': 1.01, 'stop_atr': 1.5, 'target_atr': 3.0, 'min_hold': 2}
        base_res = search_swing('Pivot Point S1 Bounce (Top-50) baseline', sig_pivot_point_bounce, [base_params], daily50_bars, atr50_by_sym,
                                 daily50_windows, min_hold=2, universe=P50.SYMBOLS, maxp=P50.MAXP)
        b = base_res[0]
        print(f"  BASELINE (current pivot50_paper_engine.py config) {b['params']}  windows_profitable={b['n_profit']}/5  total={b['total']:>10,.2f}  per_window={b['window_pls']}")
