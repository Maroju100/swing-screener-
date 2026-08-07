"""One-off ad hoc backtest (NOT a live/paper tracker - writes no state, touches no
other system's files): every currently-optimized swing and day-trading signal,
run through its REAL production code (swing_paper_engine.make_signals /
daytrade_paper_engine.STRATEGIES - the actual deployed, walk-forward-tuned logic,
not a re-derivation), over just the most recent ~1 calendar month of data, starting
from $5,000 capital, with GFV-safe settlement: sale proceeds (whether from a STOP,
TARGET, or forced EOD close) are held in "pending_settlement" and unusable for a
new buy until the next business day - mirroring the T+1 discipline documented in
daytrade_live_engine.py / margin_style_live_engine.py, so no run here could occur
as a real good-faith violation in a cash account. Position-count caps (MAXP) match
each engine's real production value.

Usage: python3 scripts/backtest_5k_1mo_gfv_safe.py <daily_hist.json> <30min_hist.json>
"""
import sys, os
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import swing_paper_engine as SWE
import daytrade_paper_engine as DT

CAPITAL = 5000.0


def next_business_day(d):
    d2 = d + timedelta(days=1)
    while d2.weekday() >= 5:
        d2 += timedelta(days=1)
    return d2


def last_month_range(dates):
    end = dates[-1]
    end_dt = datetime.strptime(end, '%Y-%m-%d')
    start_dt = end_dt - timedelta(days=31)
    start = start_dt.strftime('%Y-%m-%d')
    return start, end


# ---------------------------------------------------------------------------
# Swing: daily bars, GFV-safe (T+1 settlement), MAXP=SWE.MAXP, min_hold=SWE.MIN_HOLD_FOR_TARGET
# ---------------------------------------------------------------------------

def backtest_swing_1strategy(bars_by_sym, sig_fn, window_start, window_end):
    date_idx = {sym: {b['date']: i for i, b in enumerate(bars_by_sym[sym])} for sym in bars_by_sym}
    dates = sorted(set(dt for sym in bars_by_sym for dt in date_idx[sym] if window_start <= dt <= window_end))
    cash = CAPITAL
    pending = []  # [settle_date, amount] - GFV-safe: unusable until this date
    positions = {}
    trades = []

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
                proceeds = pos['shares'] * exit_price
                settle_date = next_business_day(datetime.strptime(dt, '%Y-%m-%d')).strftime('%Y-%m-%d')
                pending.append([settle_date, proceeds])
                trades.append({'sym': sym, 'date': dt, 'reason': exit_reason, 'pnl': proceeds - pos['shares'] * pos['entry']})
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
                if shares > 0 and cost <= cash:  # GFV-safe: only settled cash funds a buy
                    cash -= cost
                    positions[sym] = {'entry': price, 'shares': shares, 'entry_gi': gi,
                                       'stop': price - stop_dist, 'target': price + target_dist, 'last_price': price}

    pending_total = sum(p[1] for p in pending)
    posval = sum(p['shares'] * p.get('last_price', p['entry']) for p in positions.values())
    equity = cash + pending_total + posval
    return round(equity - CAPITAL, 2), len(trades), len(positions)


# ---------------------------------------------------------------------------
# Day-trading: 30-min bars, GFV-safe (T+1 settlement), MAXP=DT.MAXP, forced EOD close
# ---------------------------------------------------------------------------

def backtest_daytrade_1strategy(bars_by_sym, IND, DAYIDX, sig_fn, window_start, window_end):
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
    trades = []

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
                        proceeds = pos['shares'] * exit_price
                        settle_date = next_business_day(datetime.strptime(date, '%Y-%m-%d')).strftime('%Y-%m-%d')
                        pending.append([settle_date, proceeds])
                        trades.append({'sym': sym, 'date': date, 'reason': exit_reason, 'pnl': proceeds - pos['shares'] * pos['entry']})
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
                        if shares > 0 and cost <= cash:  # GFV-safe: only settled cash funds a buy
                            cash -= cost
                            positions[sym] = {'entry': price, 'shares': shares,
                                               'stop': price - stop_dist, 'target': price + target_dist, 'last_price': price}

    pending_total = sum(p[1] for p in pending)
    posval = sum(p['shares'] * p.get('last_price', p['entry']) for p in positions.values())
    equity = cash + pending_total + posval
    return round(equity - CAPITAL, 2), len(trades), len(positions)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python3 backtest_5k_1mo_gfv_safe.py <daily_hist.json> <30min_hist.json>")
        sys.exit(1)

    daily_path, intraday_path = sys.argv[1], sys.argv[2]

    ctx = SWE.build_context(daily_path)
    bars_by_sym = ctx[0]
    swing_signals = SWE.make_signals(ctx)
    daily_dates = sorted(set(b['date'] for bars in bars_by_sym.values() for b in bars))
    swing_start, swing_end = last_month_range(daily_dates)
    print(f"Swing 1-month window: {swing_start} to {swing_end} ({sum(1 for d in daily_dates if swing_start <= d <= swing_end)} trading days)")
    print()

    swing_results = []
    for name, fn in swing_signals.items():
        pnl, n_trades, open_pos = backtest_swing_1strategy(bars_by_sym, fn, swing_start, swing_end)
        swing_results.append((name, pnl, n_trades, open_pos))
    swing_results.sort(key=lambda r: -r[1])

    print("=== SWING - $5,000 start, GFV-safe (T+1 settlement), last 1 month ===")
    for name, pnl, n_trades, open_pos in swing_results:
        print(f"  {name:42} P&L={pnl:>10,.2f}  closed_trades={n_trades:3}  still_open={open_pos}")
    print()

    dt_bars_by_sym, IND, DAYIDX = DT.build_indicators(intraday_path)
    intraday_dates = sorted(set(b['date'] for bars in dt_bars_by_sym.values() for b in bars))
    dt_start, dt_end = last_month_range(intraday_dates)
    print(f"Day-trading 1-month window: {dt_start} to {dt_end} ({sum(1 for d in intraday_dates if dt_start <= d <= dt_end)} trading days)")
    print()

    dt_results = []
    for name, fn in DT.STRATEGIES.items():
        pnl, n_trades, open_pos = backtest_daytrade_1strategy(dt_bars_by_sym, IND, DAYIDX, fn, dt_start, dt_end)
        dt_results.append((name, pnl, n_trades, open_pos))
    dt_results.sort(key=lambda r: -r[1])

    print("=== DAY-TRADING - $5,000 start, GFV-safe (T+1 settlement), last 1 month ===")
    for name, pnl, n_trades, open_pos in dt_results:
        print(f"  {name:42} P&L={pnl:>10,.2f}  closed_trades={n_trades:3}  still_open={open_pos}")
