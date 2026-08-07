"""One-off ad hoc backtest (NOT a live/paper tracker - writes no state): rebuilds the
Margin-Style once-daily check-timing comparison (morning / midday / end-of-day) from
fresh intraday data for the real 8-symbol universe, to verify the conclusion already
documented in margin_style_live_engine.py / the live trigger (midday chosen 2026-08-05
after an earlier, now-unreproducible study found it won 2 of 3 windows).

Methodology: entry-signal decisions (HUGE_DIP/NORMAL_DIP - trailing drawdown, day
return) always use completed PRIOR daily closes, exactly like the real live engine -
check timing doesn't change what information the entry signal sees. What changes is
"today's live price": for INTRADAY_STOP (compared against prior close) and PEAK_SELL
(compared against the position's running peak), this backtest substitutes the actual
intraday quote closest to the target clock time (Morning ~9:35am ET, Midday ~12:00pm
ET, End-of-Day ~3:50pm ET) instead of always using the daily close - reproducing what
"checking once/day at time X" really means for a live-quote-proxy system. New buys are
also sized and filled at that same intraday quote.

GFV-safe (T+1 settlement), $5,000 start, current live config params (stop -1.51%,
peak-sell 74.3%, $1,000/trade cap). Runs March-July 2026 - the only span with real
(non-interpolated) intraday data across all 8 symbols.

Usage: python3 scripts/margin_style_timing_comparison.py <daily_hist_8sym.json> <intraday_8sym.json>
"""
import sys, os
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import margin_style_live_engine as MS
from walkforward_search import load_daily, next_business_day

CAPITAL = 5000.0
WINDOW_START, WINDOW_END = '2026-01-30', '2026-08-06'  # full real (non-interpolated) intraday span

CHECK_TIMES = {
    'Morning (~9:35am ET)': 9 * 60 + 35,
    'Midday (~12:00pm ET)': 12 * 60 + 0,
    'End-of-Day (~3:50pm ET)': 15 * 60 + 50,
}


def load_intraday(path):
    import json
    d = json.load(open(path))
    bars_by_sym = {}
    for r in d['data']['results']:
        sym = r['symbol']
        bars = []
        for b in r['bars']:
            bars.append({'dt': b['begins_at'], 'date': b['begins_at'][:10],
                         'close': float(b['close_price']), 'high': float(b['high_price']),
                         'low': float(b['low_price'])})
        bars_by_sym[sym] = bars
    return bars_by_sym


def et_minutes(dt_iso):
    dt = datetime.strptime(dt_iso[:16], '%Y-%m-%dT%H:%M') - timedelta(hours=4)  # EDT approx
    return dt.hour * 60 + dt.minute


def quote_at(intraday_bars_for_day, target_minutes):
    """Pick the intraday bar closest to target_minutes ET; return its close."""
    best = min(intraday_bars_for_day, key=lambda b: abs(et_minutes(b['dt']) - target_minutes))
    return best['close'], best['low'], best['high']


def backtest_with_intraday_checks(daily_bars_by_sym, intraday_bars_by_sym, target_minutes, window_start, window_end):
    date_idx = {sym: {b['date']: i for i, b in enumerate(daily_bars_by_sym[sym])} for sym in daily_bars_by_sym}
    intraday_by_date = {sym: {} for sym in intraday_bars_by_sym}
    for sym, bars in intraday_bars_by_sym.items():
        for b in bars:
            intraday_by_date[sym].setdefault(b['date'], []).append(b)

    dates = sorted(set(dt for sym in daily_bars_by_sym for dt in date_idx[sym] if window_start <= dt <= window_end))
    cash = CAPITAL
    pending = []
    positions = {}

    def settle(dt_str, amount):
        pending.append([next_business_day(datetime.strptime(dt_str, '%Y-%m-%d')).strftime('%Y-%m-%d'), amount])

    for dt in dates:
        released = [p for p in pending if p[0] <= dt]
        for p in released:
            cash += p[1]
        pending = [p for p in pending if p[0] > dt]

        for sym in MS.SYMBOLS:
            if sym not in daily_bars_by_sym or sym not in intraday_by_date or dt not in intraday_by_date[sym]:
                continue
            gi = date_idx[sym].get(dt)
            if gi is None or gi < 2:
                continue
            daily_bars = daily_bars_by_sym[sym]
            prev_close = daily_bars[gi - 1]['close']
            live_close, live_low, live_high = quote_at(intraday_by_date[sym][dt], target_minutes)

            if sym in positions:
                p = positions[sym]
                if live_low <= prev_close * (1 + MS.INTRADAY_STOP):
                    fill = prev_close * (1 + MS.INTRADAY_STOP)
                    settle(dt, p['shares'] * fill)
                    del positions[sym]
                elif live_close > p['peak']:
                    sell_shares = round(p['shares'] * MS.PEAK_SELL_PCT, 6)
                    if sell_shares > 0:
                        settle(dt, sell_shares * live_close)
                        p['shares'] -= sell_shares
                    p['peak'] = live_close
                    p['last_price'] = live_close
                    if p['shares'] <= 1e-9:
                        del positions[sym]
                else:
                    gain_pct = (live_close - p['avg_cost']) / p['avg_cost']
                    for thresh, pct in MS.GAIN_TIERS:
                        if gain_pct >= thresh:
                            sell_shares = round(p['shares'] * pct, 6)
                            if sell_shares > 0:
                                settle(dt, sell_shares * live_close)
                                p['shares'] -= sell_shares
                                if p['shares'] <= 1e-9:
                                    del positions[sym]
                            break
                    if sym in positions:
                        positions[sym]['last_price'] = live_close

            p = positions.get(sym)
            if p and p.get('tranches', 0) >= MS.MAX_TRANCHES:
                continue
            if gi < MS.LOOKBACK_DAYS + 2:
                continue
            prev_prev_close = daily_bars[gi - 2]['close']
            day_return = (prev_close - prev_prev_close) / prev_prev_close
            lb_start = max(0, gi - 1 - MS.LOOKBACK_DAYS)
            trailing_high = max(daily_bars[j]['close'] for j in range(lb_start, gi - 1))
            drawdown = (prev_close - trailing_high) / trailing_high

            deploy = None
            if drawdown <= MS.HUGE_DIP_DRAWDOWN:
                deploy = min(cash * MS.HUGE_DIP_PCT, MS.MAX_TRADE_NOTIONAL)
            elif day_return < 0 and (not p or p.get('tranches', 0) < MS.MAX_TRANCHES):
                deploy = min(cash * MS.TRANCHE_PCT, MS.MAX_TRADE_NOTIONAL)

            if deploy and deploy >= MS.MIN_NOTIONAL and cash > 1.0:
                posval = sum(positions[s]['shares'] * positions[s].get('last_price', positions[s]['avg_cost']) for s in positions)
                total_equity = cash + posval
                current_value = p['shares'] * live_close if p else 0.0
                room = max(0.0, MS.MAX_SYMBOL_ALLOCATION_PCT * total_equity - current_value)
                deploy = min(deploy, room)
                if deploy >= MS.MIN_NOTIONAL:
                    shares = deploy / live_close
                    if shares > 0 and deploy <= cash:
                        cash -= deploy
                        if p:
                            new_shares = p['shares'] + shares
                            p['avg_cost'] = (p['avg_cost'] * p['shares'] + deploy) / new_shares
                            p['shares'] = new_shares
                            p['peak'] = max(p['peak'], live_close)
                            p['tranches'] = p.get('tranches', 0) + 1
                            p['last_price'] = live_close
                        else:
                            positions[sym] = {'shares': shares, 'avg_cost': live_close, 'peak': live_close,
                                               'tranches': 1, 'last_price': live_close}

    pending_total = sum(p[1] for p in pending)
    posval = sum(pos['shares'] * pos.get('last_price', pos['avg_cost']) for pos in positions.values())
    equity = cash + pending_total + posval
    return round(equity - CAPITAL, 2)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python3 margin_style_timing_comparison.py <daily_hist_8sym.json> <intraday_8sym.json>")
        sys.exit(1)

    daily_bars_by_sym, _ = load_daily(sys.argv[1], universe=MS.SYMBOLS)
    intraday_bars_by_sym = load_intraday(sys.argv[2])

    from walkforward_search import make_windows, backtest_margin_style_window

    all_dates = sorted(set(b['date'] for bars in intraday_bars_by_sym.values() for b in bars
                            if WINDOW_START <= b['date'] <= WINDOW_END))
    windows = make_windows(all_dates, 3)
    print(f"Full real-data span: {WINDOW_START} to {WINDOW_END}, split into 3 windows:")
    for i, w in enumerate(windows, 1):
        print(f"  Window {i}: {w[0]} to {w[1]}")
    print()

    print("=== Margin-Style once-daily check-timing comparison, $5k, GFV-safe, per window ===")
    totals = {label: [] for label in CHECK_TIMES}
    for label, minutes in CHECK_TIMES.items():
        for w in windows:
            pnl = backtest_with_intraday_checks(daily_bars_by_sym, intraday_bars_by_sym, minutes, w[0], w[1])
            totals[label].append(pnl)
        print(f"  {label:28} per_window={totals[label]}  total={sum(totals[label]):>10,.2f}")

    print()
    print("Full continuous span (single run, all 6+ months at once) for reference:")
    for label, minutes in CHECK_TIMES.items():
        pnl = backtest_with_intraday_checks(daily_bars_by_sym, intraday_bars_by_sym, minutes, WINDOW_START, WINDOW_END)
        print(f"  {label:28} P&L={pnl:>10,.2f}")

    print()
    print("Daily-close-only version (no intraday timing at all), same 3 windows, for reference:")
    close_pls = [backtest_margin_style_window(daily_bars_by_sym, w[0], w[1], MS.SYMBOLS, MS.INTRADAY_STOP,
                                               MS.PEAK_SELL_PCT, max_trade_notional=MS.MAX_TRADE_NOTIONAL) for w in windows]
    print(f"  Daily close only                        per_window={close_pls}  total={sum(close_pls):>10,.2f}")
