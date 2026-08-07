"""One-off ad hoc analysis (NOT a live/paper tracker - writes no state): extends
trade_frequency_timing.py's per-trade logging to also capture:
  - each closed trade's % gain (exit vs entry price)
  - for day-trading only: entry time bucket (Open <10:30am, Midday 10:30am-1:30pm,
    Close >1:30pm ET, approximate EDT), and net P&L split by that bucket vs the rest,
    to see whether midday-triggered entries perform differently from open/close ones
  - average triggers/month (total entries / 5 months, same Mar-Jul 2026 span)

Reuses the real production signal code and the same $5k/GFV-safe mechanics as the
other backtest scripts in this project.

Usage: python3 scripts/trade_bucket_gain_analysis.py <daily_hist.json> <30min_hist.json>
"""
import sys, os
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import swing_paper_engine as SWE
import daytrade_paper_engine as DT

CAPITAL = 5000.0
MONTHS = [('2026-03-01', '2026-03-31'), ('2026-04-01', '2026-04-30'), ('2026-05-01', '2026-05-31'),
          ('2026-06-01', '2026-06-30'), ('2026-07-01', '2026-07-31')]
N_MONTHS = len(MONTHS)


def next_business_day(d):
    d2 = d + timedelta(days=1)
    while d2.weekday() >= 5:
        d2 += timedelta(days=1)
    return d2


def et_hour_min(dt_iso):
    dt = datetime.strptime(dt_iso[:16], '%Y-%m-%dT%H:%M') - timedelta(hours=4)  # EDT approx
    return dt.hour, dt.minute


def bucket_for(dt_iso):
    h, m = et_hour_min(dt_iso)
    mins = h * 60 + m
    if mins < 10 * 60 + 30:
        return 'Open'
    if mins < 13 * 60 + 30:
        return 'Midday'
    return 'Close'


def swing_trades(bars_by_sym, sig_fn, window_start, window_end):
    date_idx = {sym: {b['date']: i for i, b in enumerate(bars_by_sym[sym])} for sym in bars_by_sym}
    dates = sorted(set(dt for sym in bars_by_sym for dt in date_idx[sym] if window_start <= dt <= window_end))
    cash = CAPITAL
    pending = []
    positions = {}
    trades = []  # dicts: pct_gain

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
                trades.append({'pct_gain': (exit_price - pos['entry']) / pos['entry']})
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
    return trades


def daytrade_trades(bars_by_sym, IND, DAYIDX, sig_fn, window_start, window_end):
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
    trades = []  # dicts: pct_gain, pnl, bucket (entry bucket)

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
                        pnl = pos['shares'] * (exit_price - pos['entry'])
                        trades.append({'pct_gain': (exit_price - pos['entry']) / pos['entry'], 'pnl': pnl, 'bucket': pos['bucket']})
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
                            positions[sym] = {'entry': price, 'shares': shares, 'bucket': bucket_for(bars[gi]['dt']),
                                               'stop': price - stop_dist, 'target': price + target_dist, 'last_price': price}
    return trades


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python3 trade_bucket_gain_analysis.py <daily_hist.json> <30min_hist.json>")
        sys.exit(1)

    daily_path, intraday_path = sys.argv[1], sys.argv[2]
    window_start, window_end = MONTHS[0][0], MONTHS[-1][1]

    ctx = SWE.build_context(daily_path)
    bars_by_sym = ctx[0]
    swing_signals = SWE.make_signals(ctx)

    print(f"=== SWING - avg triggers/month, avg %% gain per trade, {window_start} to {window_end} ===")
    for name, fn in swing_signals.items():
        trades = swing_trades(bars_by_sym, fn, window_start, window_end)
        n = len(trades)
        avg_pct = (sum(t['pct_gain'] for t in trades) / n * 100) if n else 0.0
        print(f"  {name:42} closed_trades={n:3}  avg_triggers/mo={n/N_MONTHS:5.2f}  avg_%_gain={avg_pct:+.2f}%  midday_net_pl=N/A (no intraday timing)")
    print()

    dt_bars_by_sym, IND, DAYIDX = DT.build_indicators(intraday_path)
    print(f"=== DAY-TRADING - avg triggers/month, avg %% gain, midday-bucket net P&L vs rest, {window_start} to {window_end} ===")
    for name, fn in DT.STRATEGIES.items():
        trades = daytrade_trades(dt_bars_by_sym, IND, DAYIDX, fn, window_start, window_end)
        n = len(trades)
        avg_pct = (sum(t['pct_gain'] for t in trades) / n * 100) if n else 0.0
        midday = [t for t in trades if t['bucket'] == 'Midday']
        rest = [t for t in trades if t['bucket'] != 'Midday']
        midday_pnl = sum(t['pnl'] for t in midday)
        rest_pnl = sum(t['pnl'] for t in rest)
        total_pnl = midday_pnl + rest_pnl
        print(f"  {name:42} closed_trades={n:3}  avg_triggers/mo={n/N_MONTHS:5.2f}  avg_%_gain={avg_pct:+.2f}%  "
              f"midday_trades={len(midday):3}  midday_net_pl={midday_pnl:>9,.2f}  non_midday_net_pl={rest_pnl:>9,.2f}  total={total_pnl:>9,.2f}")
