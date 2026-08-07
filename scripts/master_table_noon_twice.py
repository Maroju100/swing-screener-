"""One-off ad hoc backtest (NOT a live/paper tracker - writes no state): rebuilds the
master table under a specific alternate schedule -

SWING: instead of evaluating each signal against the completed daily close (how the
real swing_paper_engine.py runs), build a synthetic "daily" bar per trading day from
just the single 30-min intraday bar closest to 12:00pm ET (noon) - so every swing
signal only ever sees a once-daily noon snapshot, exactly like a live-quote-proxy
system checking once a day at noon would. All 22 REAL production signal functions run
unmodified against this synthetic dataset (only the input data changes, not the logic).

DAY-TRADING: instead of checking continuously every 30-min bar, only check TWICE per
day, at the two checkpoints this project has already used elsewhere for "twice-daily"
day-trading backtests (walkforward_search.py's continuous=False mode): bar index 3
(~11:00am ET) and bar index 10 (~2:30pm ET) into the session. All 12 REAL production
signal functions run unmodified.

MARGIN-STYLE: included for completeness, using the existing once-daily-at-noon
backtest_with_intraday_checks harness from margin_style_timing_comparison.py.

$5,000 start per strategy per month, GFV-safe T+1 settlement throughout. Reports
March-July 2026 individual months, Net P&L (sum), and Net %% Gain (Net P&L / $5,000).

Usage: python3 scripts/master_table_noon_twice.py <daily_hist.json> <intraday_5sym.json> <intraday_8sym.json> <daily_hist_8sym.json>
"""
import sys, os, json
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import swing_paper_engine as SWE
import daytrade_paper_engine as DT
import margin_style_live_engine as MS
from walkforward_search import load_daily as ms_load_daily, next_business_day
from margin_style_timing_comparison import load_intraday as ms_load_intraday, backtest_with_intraday_checks

CAPITAL = 5000.0
MONTHS = [('March', '2026-03-01', '2026-03-31'), ('April', '2026-04-01', '2026-04-30'),
          ('May', '2026-05-01', '2026-05-31'), ('June', '2026-06-01', '2026-06-30'),
          ('July', '2026-07-01', '2026-07-31')]


def next_bday(d):
    d2 = d + timedelta(days=1)
    while d2.weekday() >= 5:
        d2 += timedelta(days=1)
    return d2


def et_minutes(dt_iso):
    dt = datetime.strptime(dt_iso[:16], '%Y-%m-%dT%H:%M') - timedelta(hours=4)  # EDT approx
    return dt.hour * 60 + dt.minute


# ---------------------------------------------------------------------------
# Build synthetic once-daily-at-noon "daily" bars from 30-min data
# ---------------------------------------------------------------------------

def build_noon_daily_json(intraday_path, symbols):
    d = json.load(open(intraday_path))
    out_results = []
    for r in d['data']['results']:
        if r['symbol'] not in symbols:
            continue
        by_date = {}
        for b in r['bars']:
            date = b['begins_at'][:10]
            by_date.setdefault(date, []).append(b)
        bars = []
        for date in sorted(by_date):
            day_bars = by_date[date]
            noon_bar = min(day_bars, key=lambda b: abs(et_minutes(b['begins_at']) - 12 * 60))
            bars.append({'begins_at': date + 'T00:00:00Z', 'open_price': noon_bar['open_price'],
                          'close_price': noon_bar['close_price'], 'high_price': noon_bar['high_price'],
                          'low_price': noon_bar['low_price'], 'volume': noon_bar.get('volume', 0)})
        out_results.append({'symbol': r['symbol'], 'bars': bars})
    return {'data': {'results': out_results}}


# ---------------------------------------------------------------------------
# Swing: run REAL signals against the synthetic noon-only "daily" dataset
# ---------------------------------------------------------------------------

def swing_1strategy_1month(bars_by_sym, sig_fn, window_start, window_end):
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
            elif held >= SWE.MIN_HOLD_FOR_TARGET and bars[gi]['high'] >= pos['target']:
                exit_reason = 'TARGET'
            if exit_reason:
                exit_price = pos['stop'] if exit_reason == 'STOP' else pos['target']
                settle_date = next_bday(datetime.strptime(dt, '%Y-%m-%d')).strftime('%Y-%m-%d')
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

    pending_total = sum(p[1] for p in pending)
    posval = sum(p['shares'] * p.get('last_price', p['entry']) for p in positions.values())
    equity = cash + pending_total + posval
    return round(equity - CAPITAL, 2)


# ---------------------------------------------------------------------------
# Day-trading: twice-daily checkpoints (bar index 3 ~11am, bar index 10 ~2:30pm)
# ---------------------------------------------------------------------------

def daytrade_1strategy_1month_twice(bars_by_sym, IND, DAYIDX, sig_fn, window_start, window_end):
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

    for date in all_dates:
        released = [p for p in pending if p[0] <= date]
        for p in released:
            cash += p[1]
        pending = [p for p in pending if p[0] > date]

        n_bars_today = max((len(day_bars[s][date]) for s in DT.SYMBOLS if s in day_bars and date in day_bars[s]), default=0)
        if n_bars_today == 0:
            continue
        checkpoints = sorted(set(min(t, n_bars_today - 1) for t in (3, 10)))

        for cp_num, i_in_day in enumerate(checkpoints):
            is_final = (cp_num == len(checkpoints) - 1)
            for sym in DT.SYMBOLS:
                if sym not in day_bars or date not in day_bars[sym]:
                    continue
                idxs = day_bars[sym][date]
                gi = idxs[min(i_in_day, len(idxs) - 1)]
                bars = bars_by_sym[sym]

                if sym in positions:
                    pos = positions[sym]
                    exit_reason, exit_price = None, None
                    for j in range(pos['last_checked_gi'] + 1, gi + 1):
                        if bars[j]['low'] <= pos['stop']:
                            exit_reason, exit_price = 'STOP', pos['stop']
                            break
                        if bars[j]['high'] >= pos['target']:
                            exit_reason, exit_price = 'TARGET', pos['target']
                            break
                    if exit_reason is None and is_final:
                        exit_reason, exit_price = 'EOD_CLOSE', bars[gi]['close']
                    if exit_reason:
                        settle_date = next_bday(datetime.strptime(date, '%Y-%m-%d')).strftime('%Y-%m-%d')
                        pending.append([settle_date, pos['shares'] * exit_price])
                        del positions[sym]
                    else:
                        pos['last_checked_gi'] = gi

                if sym not in positions and len(positions) < DT.MAXP:
                    day_start = idxs[0]
                    fired = None
                    for j in range(day_start, gi + 1):
                        r = sig_fn(bars_by_sym, IND, DAYIDX, sym, j)
                        if r is not None:
                            fired = r
                    if fired is not None:
                        _score, stop_dist, target_dist = fired
                        price = bars[gi]['close']
                        pending_total = sum(p[1] for p in pending)
                        posval = sum(p['shares'] * p.get('last_price', p['entry']) for p in positions.values())
                        tv = cash + pending_total + posval
                        shares = (tv / DT.MAXP) / price
                        cost = shares * price
                        if shares > 0 and cost <= cash:
                            cash -= cost
                            positions[sym] = {'entry': price, 'shares': shares, 'last_checked_gi': gi,
                                               'stop': price - stop_dist, 'target': price + target_dist, 'last_price': price}

    pending_total = sum(p[1] for p in pending)
    posval = sum(p['shares'] * p.get('last_price', p['entry']) for p in positions.values())
    equity = cash + pending_total + posval
    return round(equity - CAPITAL, 2)


if __name__ == '__main__':
    if len(sys.argv) != 5:
        print("Usage: python3 master_table_noon_twice.py <daily_hist.json> <intraday_5sym.json> <intraday_8sym.json> <daily_hist_8sym.json>")
        sys.exit(1)

    daily_path, intraday5_path, intraday8_path, daily8_path = sys.argv[1:5]

    # --- SWING: noon-only synthetic daily bars ---
    noon_json = build_noon_daily_json(intraday5_path, set(SWE.SYMBOLS))
    tmp_path = '/tmp/_swing_noon_synthetic.json'
    json.dump(noon_json, open(tmp_path, 'w'))
    ctx = SWE.build_context(tmp_path)
    bars_by_sym = ctx[0]
    swing_signals = SWE.make_signals(ctx)

    print("=== SWING (once/day at noon ET, synthetic noon-only bars) - $5k/month, GFV-safe ===")
    swing_rows = []
    for name, fn in swing_signals.items():
        monthlies = [swing_1strategy_1month(bars_by_sym, fn, ms, me) for _, ms, me in MONTHS]
        net = round(sum(monthlies), 2)
        pct = round(net / CAPITAL * 100, 2)
        swing_rows.append((name, monthlies, net, pct))
    swing_rows.sort(key=lambda r: -r[2])
    for name, monthlies, net, pct in swing_rows:
        mstr = "  ".join(f"{mn}:{v:>9,.2f}" for (mn, _, _), v in zip(MONTHS, monthlies))
        print(f"  {name:42} {mstr}  NET={net:>10,.2f}  NET%={pct:+.2f}%")
    print()

    # --- DAY-TRADING: twice-daily checkpoints ---
    dt_bars_by_sym, IND, DAYIDX = DT.build_indicators(intraday5_path)
    print("=== DAY-TRADING (twice/day: ~11:00am & ~2:30pm ET) - $5k/month, GFV-safe ===")
    dt_rows = []
    for name, fn in DT.STRATEGIES.items():
        monthlies = [daytrade_1strategy_1month_twice(dt_bars_by_sym, IND, DAYIDX, fn, ms, me) for _, ms, me in MONTHS]
        net = round(sum(monthlies), 2)
        pct = round(net / CAPITAL * 100, 2)
        dt_rows.append((name, monthlies, net, pct))
    dt_rows.sort(key=lambda r: -r[2])
    for name, monthlies, net, pct in dt_rows:
        mstr = "  ".join(f"{mn}:{v:>9,.2f}" for (mn, _, _), v in zip(MONTHS, monthlies))
        print(f"  {name:42} {mstr}  NET={net:>10,.2f}  NET%={pct:+.2f}%")
    print()

    # --- MARGIN-STYLE: once/day at noon, using real fresh intraday data ---
    ms_daily_bars, _ = ms_load_daily(daily8_path, universe=MS.SYMBOLS)
    ms_intraday_bars = ms_load_intraday(intraday8_path)
    print("=== MARGIN-STYLE LIVE (current config, once/day at noon ET) - $5k/month, GFV-safe ===")
    monthlies = []
    for _, ms, me in MONTHS:
        pnl = backtest_with_intraday_checks(ms_daily_bars, ms_intraday_bars, 12 * 60, ms, me)
        monthlies.append(pnl)
    net = round(sum(monthlies), 2)
    pct = round(net / CAPITAL * 100, 2)
    mstr = "  ".join(f"{mn}:{v:>9,.2f}" for (mn, _, _), v in zip(MONTHS, monthlies))
    print(f"  Margin-Style Live (current)                {mstr}  NET={net:>10,.2f}  NET%={pct:+.2f}%")
