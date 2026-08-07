"""One-off ad hoc backtest (NOT a live/paper tracker - writes no state): what if each
day-trading strategy were only evaluated ONCE per day, at the single 30-min bar
closest to 12:00pm ET (noon), instead of checked continuously through the session?

Mirrors the once-daily-check experiment already done for Margin-Style (which found
once-daily checks can beat intraday checks by letting winners run further, at the
cost of the intraday stop losing same-day precision) - this applies the same idea to
the day-trading signals. At that single daily bar per symbol: if in a position, check
stop/target against that one bar's low/high; if neither hit, force-close at that bar's
close (since nothing else gets looked at until tomorrow's noon check - these are
same-day setups, not meant to carry overnight). If flat, evaluate the entry signal at
that same bar.

Many of these signals are structurally tied to a SPECIFIC bar-of-day (e.g. Gap
Momentum requires i_in_day==1, right after the open; Mid-Range Reversion requires
i_in_day==5) - forcing every check to happen at noon means those either never fire
(if noon isn't their required bar) or fire every day trivially (if noon happens to be
their bar). This is expected and reported as-is, not smoothed over.

Uses the same $5,000 start, GFV-safe T+1 settlement mechanics as every other backtest
in this project. Runs March-July 2026, matching the existing monthly breakdown.

Usage: python3 scripts/backtest_daytrade_once_daily_noon.py <30min_hist.json>
"""
import sys, os
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import daytrade_paper_engine as DT

CAPITAL = 5000.0
MONTHS = [('2026-03-01', '2026-03-31'), ('2026-04-01', '2026-04-30'), ('2026-05-01', '2026-05-31'),
          ('2026-06-01', '2026-06-30'), ('2026-07-01', '2026-07-31')]


def next_business_day(d):
    d2 = d + timedelta(days=1)
    while d2.weekday() >= 5:
        d2 += timedelta(days=1)
    return d2


def et_minutes(dt_iso):
    dt = datetime.strptime(dt_iso[:16], '%Y-%m-%dT%H:%M') - timedelta(hours=4)  # EDT approx
    return dt.hour * 60 + dt.minute


def backtest_once_daily_noon(bars_by_sym, IND, DAYIDX, sig_fn, window_start, window_end):
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
    trades = 0

    for date in all_dates:
        released = [p for p in pending if p[0] <= date]
        for p in released:
            cash += p[1]
        pending = [p for p in pending if p[0] > date]

        for sym in DT.SYMBOLS:
            if sym not in day_bars or date not in day_bars[sym]:
                continue
            idxs = day_bars[sym][date]
            bars = bars_by_sym[sym]
            # pick the single bar closest to 12:00pm ET (720 min) for this symbol/day
            noon_gi = min(idxs, key=lambda gi: abs(et_minutes(bars[gi]['dt']) - 12 * 60))

            if sym in positions:
                pos = positions[sym]
                exit_price = None
                if bars[noon_gi]['low'] <= pos['stop']:
                    exit_price = pos['stop']
                elif bars[noon_gi]['high'] >= pos['target']:
                    exit_price = pos['target']
                else:
                    exit_price = bars[noon_gi]['close']  # forced close - nothing else gets checked until tomorrow
                settle_date = next_business_day(datetime.strptime(date, '%Y-%m-%d')).strftime('%Y-%m-%d')
                pending.append([settle_date, pos['shares'] * exit_price])
                del positions[sym]

            if sym not in positions and len(positions) < DT.MAXP:
                r = sig_fn(bars_by_sym, IND, DAYIDX, sym, noon_gi)
                if r is not None:
                    _score, stop_dist, target_dist = r
                    price = bars[noon_gi]['close']
                    pending_total = sum(p[1] for p in pending)
                    posval = sum(p['shares'] * p.get('last_price', p['entry']) for p in positions.values())
                    tv = cash + pending_total + posval
                    shares = (tv / DT.MAXP) / price
                    cost = shares * price
                    if shares > 0 and cost <= cash:
                        cash -= cost
                        positions[sym] = {'entry': price, 'shares': shares,
                                           'stop': price - stop_dist, 'target': price + target_dist, 'last_price': price}
                        trades += 1

    pending_total = sum(p[1] for p in pending)
    posval = sum(p['shares'] * p.get('last_price', p['entry']) for p in positions.values())
    equity = cash + pending_total + posval
    return round(equity - CAPITAL, 2), trades


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python3 backtest_daytrade_once_daily_noon.py <30min_hist.json>")
        sys.exit(1)

    intraday_path = sys.argv[1]
    dt_bars_by_sym, IND, DAYIDX = DT.build_indicators(intraday_path)
    window_start, window_end = MONTHS[0][0], MONTHS[-1][1]

    print(f"=== DAY-TRADING - once/day at noon ET check only, {window_start} to {window_end} ===")
    for name, fn in DT.STRATEGIES.items():
        pnl, n_trades = backtest_once_daily_noon(dt_bars_by_sym, IND, DAYIDX, fn, window_start, window_end)
        print(f"  {name:42} Mar-Jul P&L={pnl:>10,.2f}  trades={n_trades:3}")
