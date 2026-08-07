"""One-off ad hoc analysis (NOT a live/paper tracker - writes no state): for every
currently-optimized swing and day-trading signal, over the same March-July 2026
span used in the monthly $5k GFV-safe backtest, report:
  - trades/day (entries taken, averaged over trading days in the span)
  - typical entry time-of-day (day-trading only - swing is daily-bar, so entries
    are always evaluated against the completed daily close, no intraday timing)

Reuses the real production signal code, same $5k-per-month/GFV-safe mechanics as
backtest_5k_monthly_gfv_safe.py, just also logs each entry's bar for timing stats.

Usage: python3 scripts/trade_frequency_timing.py <daily_hist.json> <30min_hist.json>
"""
import sys, os
from collections import Counter
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import swing_paper_engine as SWE
import daytrade_paper_engine as DT

CAPITAL = 5000.0
MONTHS = [('2026-03-01', '2026-03-31'), ('2026-04-01', '2026-04-30'), ('2026-05-01', '2026-05-31'),
          ('2026-06-01', '2026-06-30'), ('2026-07-01', '2026-07-31')]


def next_business_day(d):
    d2 = d + timedelta(days=1)
    while d2.weekday() >= 5:
        d2 += timedelta(days=1)
    return d2


def swing_entries(bars_by_sym, sig_fn, window_start, window_end):
    date_idx = {sym: {b['date']: i for i, b in enumerate(bars_by_sym[sym])} for sym in bars_by_sym}
    dates = sorted(set(dt for sym in bars_by_sym for dt in date_idx[sym] if window_start <= dt <= window_end))
    cash = CAPITAL
    pending = []
    positions = {}
    entries = []

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
            elif held >= SWE.MIN_HOLD_FOR_TARGET and bars[gi]['high'] >= pos['target']:
                exit_reason = 'TARGET'
            if exit_reason:
                exit_price = pos['stop'] if exit_reason == 'STOP' else pos['target']
                settle_date = next_business_day(datetime.strptime(dt, '%Y-%m-%d')).strftime('%Y-%m-%d')
                pending.append([settle_date, pos['shares'] * exit_price])
                del positions[sym]
            else:
                pos['last_price'] = bars[gi]['close']

        if len(positions) < SWE.MAXP:
            for sym in SWE.SYMBOLS:
                if sym in positions or len(positions) >= SWE.MAXP or sym not in bars_by_sym:
                    continue
                gi = date_idx[sym].get(dt)
                if gi is None:
                    continue
                r = sig_fn(sym, gi)
                if r is None:
                    continue
                _score, stop_dist, target_dist = r
                price = bars_by_sym[sym][gi]['close']
                pending_total = sum(p[1] for p in pending)
                posval = sum(p['shares'] * p.get('last_price', p['entry']) for p in positions.values())
                tv = cash + pending_total + posval
                shares = (tv / SWE.MAXP) / price
                cost = shares * price
                if shares > 0 and cost <= cash:
                    cash -= cost
                    positions[sym] = {'entry': price, 'shares': shares, 'entry_gi': gi,
                                       'stop': price - stop_dist, 'target': price + target_dist, 'last_price': price}
                    entries.append(dt)
    return entries


def daytrade_entries(bars_by_sym, IND, DAYIDX, sig_fn, window_start, window_end):
    day_bars = {}
    for sym in DT.SYMBOLS:
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
    entries = []  # (date, dt_iso_string)

    for date in all_dates:
        released = [p for p in pending if p[0] <= date]
        for p in released:
            cash += p[1]
        pending = [p for p in pending if p[0] > date]

        n_bars_today = max((len(day_bars[s][date]) for s in DT.SYMBOLS if s in day_bars and date in day_bars[s]), default=0)
        if n_bars_today == 0:
            continue

        for i_in_day in range(n_bars_today):
            is_final = (i_in_day == n_bars_today - 1)
            for sym in DT.SYMBOLS:
                if sym not in day_bars or date not in day_bars[sym]:
                    continue
                idxs = day_bars[sym][date]
                if i_in_day >= len(idxs):
                    continue
                gi = idxs[i_in_day]
                bars = bars_by_sym[sym]

                if sym in positions:
                    pos = positions[sym]
                    exit_reason, exit_price = None, None
                    if bars[gi]['low'] <= pos['stop']:
                        exit_reason, exit_price = 'STOP', pos['stop']
                    elif bars[gi]['high'] >= pos['target']:
                        exit_reason, exit_price = 'TARGET', pos['target']
                    elif is_final:
                        exit_reason, exit_price = 'EOD_CLOSE', bars[gi]['close']
                    if exit_reason:
                        settle_date = next_business_day(datetime.strptime(date, '%Y-%m-%d')).strftime('%Y-%m-%d')
                        pending.append([settle_date, pos['shares'] * exit_price])
                        del positions[sym]
                    else:
                        pos['last_price'] = bars[gi]['close']

                if sym not in positions and len(positions) < DT.MAXP and not is_final:
                    r = sig_fn(bars_by_sym, IND, DAYIDX, sym, gi)
                    if r is not None:
                        _score, stop_dist, target_dist = r
                        price = bars[gi]['close']
                        pending_total = sum(p[1] for p in pending)
                        posval = sum(p['shares'] * p.get('last_price', p['entry']) for p in positions.values())
                        tv = cash + pending_total + posval
                        shares = (tv / DT.MAXP) / price
                        cost = shares * price
                        if shares > 0 and cost <= cash:
                            cash -= cost
                            positions[sym] = {'entry': price, 'shares': shares,
                                               'stop': price - stop_dist, 'target': price + target_dist, 'last_price': price}
                            entries.append((date, bars[gi]['dt']))
    return entries


def et_time_from_utc_iso(dt_iso):
    # Robinhood 30-min bars are UTC ISO timestamps; regular session is 13:30-20:00 UTC (9:30am-4pm ET)
    dt = datetime.strptime(dt_iso[:16], '%Y-%m-%dT%H:%M')
    et = dt - timedelta(hours=4)  # ET is UTC-4 in summer (EDT); close enough for a descriptive bucket
    return et.strftime('%-I:%M%p ET') if hasattr(et, 'strftime') else str(et)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python3 trade_frequency_timing.py <daily_hist.json> <30min_hist.json>")
        sys.exit(1)

    daily_path, intraday_path = sys.argv[1], sys.argv[2]
    window_start, window_end = MONTHS[0][0], MONTHS[-1][1]

    ctx = SWE.build_context(daily_path)
    bars_by_sym = ctx[0]
    swing_signals = SWE.make_signals(ctx)
    daily_dates = sorted(set(b['date'] for bars in bars_by_sym.values() for b in bars))
    n_trading_days = sum(1 for d in daily_dates if window_start <= d <= window_end)

    print(f"=== SWING - trades/day and timing, {window_start} to {window_end} ({n_trading_days} trading days) ===")
    for name, fn in swing_signals.items():
        entries = swing_entries(bars_by_sym, fn, window_start, window_end)
        per_day = len(entries) / n_trading_days if n_trading_days else 0
        print(f"  {name:42} entries={len(entries):3}  trades/day={per_day:.3f}  timing=at completed daily close (no intraday timing - daily bars)")
    print()

    dt_bars_by_sym, IND, DAYIDX = DT.build_indicators(intraday_path)
    intraday_dates = sorted(set(b['date'] for bars in dt_bars_by_sym.values() for b in bars))
    n_dt_days = sum(1 for d in intraday_dates if window_start <= d <= window_end)

    print(f"=== DAY-TRADING - trades/day and typical entry time, {window_start} to {window_end} ({n_dt_days} trading days) ===")
    for name, fn in DT.STRATEGIES.items():
        entries = daytrade_entries(dt_bars_by_sym, IND, DAYIDX, fn, window_start, window_end)
        per_day = len(entries) / n_dt_days if n_dt_days else 0
        times = Counter(et_time_from_utc_iso(dt_iso) for _, dt_iso in entries)
        top_times = ", ".join(f"{t}({c})" for t, c in times.most_common(3))
        print(f"  {name:42} entries={len(entries):3}  trades/day={per_day:.3f}  top entry times={top_times or 'n/a'}")
