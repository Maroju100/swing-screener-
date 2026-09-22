#!/usr/bin/env python3
"""Intraday re-test of the two claims that were fabricated in September 2026.

WHAT WENT WRONG BEFORE
----------------------
Both of these were "answered" by multiplying a frozen day_pnl series:

  * "close at 2:45 PM CDT vs hold overnight"  -- a *0.60 factor was invented.
    day_pnl is a DAILY series and carries no intraday decomposition, so it
    cannot answer what share of a day's P&L happened before any clock time.
  * "3x/day execution adds +2.69pp"           -- an assumed "extra executions
    capture N% more" multiplier. It returns whatever was typed into it.

Both are re-tested here by REPLAY on real 30-minute bars. Nothing is scaled.

SELF-VALIDATION GATE
--------------------
This file implements its own replay loop (the shared one checks once a day), so
it is not entitled to be believed until it reproduces the shared harness. With
one check at 17:00 and no early exit it must match scripts/margin_style_research
baseline over the same window to the cent. `--validate` asserts exactly that and
every command refuses to run if it fails.

WHAT THE DATA CAN AND CANNOT ANSWER (Evidence Rule 6)
-----------------------------------------------------
Real, non-interpolated 30-minute bars exist for 2026-06-22..2026-09-22 only
(65 trading days; measured, zero interpolated). Finer-grained 1-minute history
reaches back about six weeks, which is too short.

So: 2:45 PM CDT is 19:45 UTC, which falls INSIDE the 19:30-20:00 bar and is NOT
directly priced. This study therefore reports the bracketing marks -- 19:30 UTC
(2:30 PM CDT) and 20:00 UTC (3:00 PM CDT, the close) -- and does not interpolate
between them. The question "does closing early beat holding overnight" IS
answerable; "2:45 exactly" is not, and is reported as such.

USAGE
    python3 scripts/margin_style_intraday_study.py validate
    python3 scripts/margin_style_intraday_study.py exits
    python3 scripts/margin_style_intraday_study.py frequency
"""
import argparse
import bisect
import contextlib
import io
import json
import os
import sys
import time
from datetime import datetime as real_datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_17h_backtest as H  # noqa: E402

ROOT = H.ROOT
DATA = os.path.join(ROOT, 'data')
RESULTS = os.path.join(DATA, 'research')
SCRATCH = H.SCRATCH

DAILY = os.path.join(DATA, 'margin_live_daily_ext_2025-11-03_2026-09-21.json')
MIN30 = os.path.join(DATA, 'margin_live_30min_2026-06-22_2026-09-22.json')
HOURLY = os.path.join(DATA, 'margin_live_hourly_ext_2026-03-06_2026-09-22.json')

UNIVERSE = H.UNIVERSE
ENGINE = 'origin/main'
CAPITAL = 80000.0
COST_BPS = 5.0

# The engine's live check. 17:00 UTC == 12:00 noon CDT.
CHECK = '17:00'
# Every 30-minute mark that exists in the session, left-edge labelled UTC.
MARKS = ['13:30', '14:00', '14:30', '15:00', '15:30', '16:00', '16:30',
         '17:00', '17:30', '18:00', '18:30', '19:00', '19:30']


def utc_to_cdt(hhmm):
    h, m = int(hhmm[:2]), hhmm[3:]
    return f'{(h - 5 - 1) % 12 + 1}:{m} {"AM" if (h - 5) % 24 < 12 else "PM"} CDT'


def load_min30():
    d = json.load(open(MIN30))
    op, cl = {}, {}
    for r in d['data']['results']:
        for b in r['bars']:
            ts = b['begins_at']
            op.setdefault(r['symbol'], {})[ts] = float(b['open_price'])
            cl.setdefault(r['symbol'], {})[ts] = float(b['close_price'])
    return op, cl


def load_daily():
    d = json.load(open(DAILY))
    return {r['symbol']: {b['begins_at'][:10]: float(b['close_price']) for b in r['bars']}
            for r in d['data']['results']}


def load_hourly_1700():
    d = json.load(open(HOURLY))
    return {r['symbol']: {b['begins_at'][:10]: float(b['close_price'])
                          for b in r['bars'] if b['begins_at'][11:19] == '17:00:00'}
            for r in d['data']['results']}


def build_engine(tag, params=None, no_lockup=False):
    os.makedirs(SCRATCH, exist_ok=True)
    state_path = os.path.join(SCRATCH, f'state_intraday_{tag}.json')
    if os.path.exists(state_path):
        os.remove(state_path)
    src = H.load_engine_src(ENGINE)
    if no_lockup:
        src = H.apply_no_settlement_lockup_patch(src)
    ns = {'__file__': os.path.join(ROOT, 'scripts', 'margin_style_live_engine.py')}
    exec(compile(src, 'margin_style_live_engine.py', 'exec'), ns)
    ns['SYMBOLS'] = UNIVERSE
    ns['STATE_PATH'] = state_path
    ns['datetime'] = H.FakeDatetime
    for k, v in (params or {}).items():
        if k not in ns:
            raise SystemExit(f'param {k!r} not a global in {ENGINE}')
        ns[k] = v
    return ns, state_path


def replay_intraday(start, end, check_times=(CHECK,), exit_mark=None,
                    tag='x', params=None, cost_bps=COST_BPS, capital=CAPITAL,
                    use_hourly_at_1700=True, no_lockup=False,
                    exit_frac=1.0, exit_at_bell=False):
    """Replay with N checks/day and an optional forced exit at a 30-minute mark.

    check_times  -- UTC marks at which cmd_plan runs. Quotes are that mark's
                    CLOSE for 17:00 (matching the shared harness, which uses the
                    hourly 17:00 bar close) and that mark's OPEN otherwise --
                    an order placed AT time T fills at T, not 30 minutes later.
    exit_mark    -- UTC mark at which open positions are trimmed, at that mark's
                    OPEN price, booked through the engine's own cmd_commit so
                    settlement/state bookkeeping stays honest.
    exit_at_bell -- price the exit at the 19:30 bar's CLOSE (= 20:00 UTC, the
                    closing bell) instead of a mark's open. This isolates the
                    OVERNIGHT GAP: the position keeps the entire session and gives
                    up only the gap. Exiting at 19:30's open instead also forfeits
                    the last 30 minutes, which is a different question.
    exit_frac    -- fraction of each position sold at the exit. 1.0 removes 100%
                    of overnight exposure, 0.5 halves it, 0.0 is production.
                    Lets the risk/return trade-off be drawn as a curve rather
                    than asserted at the endpoints.
    """
    ns, state_path = build_engine(tag, params, no_lockup=no_lockup)
    cmd_plan, cmd_commit = ns['cmd_plan'], ns['cmd_commit']

    op30, cl30 = load_min30()
    daily = load_daily()
    h1700 = load_hourly_1700()
    all_dates = sorted(next(iter(daily.values())))
    win_days = sorted({ts[:10] for ts in next(iter(cl30.values()))})
    win_days = [d for d in win_days if start <= d <= end]

    hist_path = os.path.join(SCRATCH, f'i_hist_{tag}.json')
    q_path = os.path.join(SCRATCH, f'i_q_{tag}.json')
    act_path = os.path.join(SCRATCH, f'i_act_{tag}.json')

    c = cost_bps / 10000.0
    cash = capital
    realized = 0.0
    trades, day_pnl, day_equity = [], {}, {}
    last_risk = None

    for D in win_days:
        i = bisect.bisect_left(all_dates, D)
        hist = [{'symbol': s,
                 'bars': [{'begins_at': dt + 'T00:00:00Z', 'close_price': str(daily[s][dt])}
                          for dt in all_dates[:i] if dt in daily[s]]}
                for s in UNIVERSE]
        json.dump({'data': {'results': hist}}, open(hist_path, 'w'))
        H.SIM_DAY['value'] = real_datetime.strptime(D, '%Y-%m-%d')
        dr = 0.0

        for T in check_times:
            q = {}
            for s in UNIVERSE:
                ts = f'{D}T{T}:00Z'
                if T == CHECK and use_hourly_at_1700 and D in h1700.get(s, {}):
                    q[s] = h1700[s][D]
                elif ts in op30.get(s, {}):
                    q[s] = op30[s][ts] if T != CHECK else cl30[s][ts]
            if not q:
                continue
            json.dump(q, open(q_path, 'w'))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                cmd_plan(hist_path, q_path, cash, [])
            plan = H.extract_plan(buf.getvalue())
            last_risk = plan['risk_state']
            acts = {'sells': [], 'buys': [],
                    'peak_updates': plan.get('peak_updates', {}),
                    'risk_state': plan['risk_state']}
            for s in plan['sells']:
                acts['sells'].append({k: s[k] for k in ('symbol', 'shares', 'price', 'reason', 'entry')})
                dr += s['shares'] * (s['price'] * (1 - c) - s['entry'] * (1 + c))
                cash += s['shares'] * s['price'] * (1 - c)
                trades.append({'date': D, 'time': T, 'side': 'sell', 'reason': s['reason'],
                               'symbol': s['symbol'], 'shares': s['shares'], 'price': s['price']})
            for b in plan['buys']:
                acts['buys'].append({k: b[k] for k in ('symbol', 'shares', 'price', 'reason')})
                cash -= b['shares'] * b['price'] * (1 + c)
                trades.append({'date': D, 'time': T, 'side': 'buy', 'reason': b['reason'],
                               'symbol': b['symbol'], 'shares': b['shares'], 'price': b['price']})
            json.dump(acts, open(act_path, 'w'))
            with contextlib.redirect_stdout(io.StringIO()):
                cmd_commit(act_path)

        if (exit_mark or exit_at_bell) and exit_frac > 0:
            st = json.load(open(state_path))
            sells = []
            mark = '19:30' if exit_at_bell else exit_mark
            for sym, p in list(st['open_positions'].items()):
                ts = f'{D}T{mark}:00Z'
                px = (cl30 if exit_at_bell else op30).get(sym, {}).get(ts)
                if px is None:
                    continue
                sh = round(p['shares'] * exit_frac, 6)
                if sh <= 1e-6:
                    continue
                sh = min(sh, p['shares'])
                sells.append({'symbol': sym, 'shares': sh, 'price': px,
                              'reason': 'EOD_EXIT', 'entry': p['entry']})
                dr += sh * (px * (1 - c) - p['entry'] * (1 + c))
                cash += sh * px * (1 - c)
                trades.append({'date': D, 'time': mark, 'side': 'sell',
                               'reason': 'EOD_EXIT', 'symbol': sym,
                               'shares': sh, 'price': px})
            if sells:
                json.dump({'sells': sells, 'buys': [], 'peak_updates': {},
                           'risk_state': last_risk}, open(act_path, 'w'))
                with contextlib.redirect_stdout(io.StringIO()):
                    cmd_commit(act_path)

        realized += dr
        day_pnl[D] = dr
        st = json.load(open(state_path))
        mark = {s: cl30.get(s, {}).get(f'{D}T19:30:00Z', daily[s].get(D)) for s in UNIVERSE}
        day_equity[D] = cash + sum(p['shares'] * (mark.get(sym) or p['entry'])
                                   for sym, p in st['open_positions'].items())

    st = json.load(open(state_path))
    last = win_days[-1]
    unreal = 0.0
    for sym, p in st['open_positions'].items():
        px = cl30.get(sym, {}).get(f'{last}T19:30:00Z', daily[sym].get(last, p['entry']))
        unreal += p['shares'] * (px * (1 - c) - p['entry'] * (1 + c))
    return {'start': start, 'end': end, 'checks': list(check_times), 'exit_mark': exit_mark,
            'realized': round(realized, 2), 'unrealized': round(unreal, 2),
            'total': round(realized + unreal, 2),
            'realized_pct': round(realized / capital * 100, 2),
            'total_pct': round((realized + unreal) / capital * 100, 2),
            'trades': len(trades), 'days': len(win_days),
            'day_pnl': day_pnl, 'day_equity': day_equity, 'cost_bps': cost_bps}


def metrics(r):
    eq = [v for _, v in sorted(r['day_equity'].items())]
    rets = [(eq[i] / eq[i - 1] - 1) for i in range(1, len(eq)) if eq[i - 1] > 0]
    n = len(rets)
    m = sum(rets) / n if n else 0
    sd = ((sum((x - m) ** 2 for x in rets) / (n - 1)) ** 0.5) if n > 1 else 0
    peak, dd = -1e18, 0.0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            dd = min(dd, v / peak - 1)
    return {'sharpe': round((m / sd * (252 ** 0.5)) if sd > 0 else 0, 3),
            'max_dd_pct': round(dd * 100, 2),
            'vol_ann_pct': round(sd * (252 ** 0.5) * 100, 2)}


# 2026-09-22 is EXCLUDED: the data was pulled before 17:00 UTC that day, so no
# 17:00 bar exists and the engine's own check could not have happened. Including
# it made this loop trade a 65th day the shared harness correctly skipped
# (MEASURED: $31,355.32/376 trades vs $30,622.59/371). The window is therefore
# 64 trading days ending 2026-09-21.
WIN = ('2026-06-22', '2026-09-21')


def validate(verbose=True):
    """This loop must reproduce the shared harness on the same window."""
    mine = replay_intraday(*WIN, tag='val')
    with contextlib.redirect_stdout(io.StringIO()):
        theirs = H.run(WIN[0], WIN[1], CAPITAL, ENGINE, tag='ivalref',
                       daily_path=DAILY, hourly_path=HOURLY, cost_bps=COST_BPS)
    ok = abs(mine['realized'] - theirs['realized']) < 0.01
    if verbose:
        print('VALIDATION: intraday loop @1 check/17:00, no exit, vs shared harness')
        print(f"  this loop     : ${mine['realized']:>12,.2f}  ({mine['trades']} trades)")
        print(f"  shared harness: ${theirs['realized']:>12,.2f}  ({theirs['trade_count']} trades)")
        print('  PASS' if ok else '  FAIL - the intraday loop is not equivalent; do not trust it')
    return ok


def cmd_validate(_):
    sys.exit(0 if validate() else 1)


def cmd_exits(_):
    if not validate(verbose=False):
        raise SystemExit('intraday loop failed validation; refusing to produce numbers')
    print('=' * 82)
    print('FORCED EARLY EXIT vs HOLD OVERNIGHT  (real 30-minute bars, replay)')
    print(f'  window {WIN[0]}..{WIN[1]}   engine {ENGINE}   cost {COST_BPS} bps/side')
    print('=' * 82)
    base = replay_intraday(*WIN, tag='e_base')
    bm = metrics(base)
    rows = [{'exit': 'none (hold overnight) = PRODUCTION', 'exit_utc': None,
             **{k: base[k] for k in ('realized', 'realized_pct', 'total', 'trades')}, **bm}]
    print(f"\n{'exit at (UTC)':<16}{'= CDT':<12}{'realized':>13}{'return':>9}"
          f"{'sharpe':>8}{'maxDD':>8}{'vol':>8}{'trades':>8}")
    print(f"{'hold overnight':<16}{'--':<12}{base['realized']:>13,.0f}"
          f"{base['realized_pct']:>8.1f}%{bm['sharpe']:>8.2f}{bm['max_dd_pct']:>7.1f}%"
          f"{bm['vol_ann_pct']:>7.1f}%{base['trades']:>8}")
    for mark in ['17:30', '18:00', '18:30', '19:00', '19:30']:
        r = replay_intraday(*WIN, exit_mark=mark, tag=f'e{mark.replace(":","")}')
        m = metrics(r)
        rows.append({'exit': f'close at {mark} UTC', 'exit_utc': mark,
                     **{k: r[k] for k in ('realized', 'realized_pct', 'total', 'trades')}, **m})
        print(f"{mark:<16}{utc_to_cdt(mark):<12}{r['realized']:>13,.0f}"
              f"{r['realized_pct']:>8.1f}%{m['sharpe']:>8.2f}{m['max_dd_pct']:>7.1f}%"
              f"{m['vol_ann_pct']:>7.1f}%{r['trades']:>8}")
    print('\n2:45 PM CDT (19:45 UTC) falls INSIDE the 19:30-20:00 bar and is not priced')
    print('by this data. 19:30 UTC (2:30 PM CDT) is the closest mark and is shown above.')
    print('No interpolation is done to reach 2:45 -- see Evidence Rule 6.')
    save('intraday_exits.json', {'window': list(WIN), 'engine': ENGINE,
                                 'cost_bps': COST_BPS, 'rows': rows,
                                 'unanswerable': '2:45 PM CDT exactly (19:45 UTC is mid-bar)',
                                 'method': 'MEASURED by full engine replay on 30-minute bars'})


def cmd_frequency(_):
    if not validate(verbose=False):
        raise SystemExit('intraday loop failed validation; refusing to produce numbers')
    print('=' * 82)
    print('CHECK FREQUENCY  (real 30-minute bars, replay -- nothing scaled)')
    print(f'  window {WIN[0]}..{WIN[1]}   engine {ENGINE}   cost {COST_BPS} bps/side')
    print('=' * 82)
    scheds = [
        ('1x/day 17:00 (PRODUCTION)', ['17:00']),
        ('2x/day 15:00,19:00', ['15:00', '19:00']),
        ('2x/day 14:00,17:00', ['14:00', '17:00']),
        ('3x/day 14:00,17:00,19:00', ['14:00', '17:00', '19:00']),
        ('3x/day 15:00,17:00,19:30', ['15:00', '17:00', '19:30']),
        ('4x/day 14:00,16:00,18:00,19:30', ['14:00', '16:00', '18:00', '19:30']),
        ('7x/day hourly 13:30-19:30', ['13:30', '14:30', '15:30', '16:30', '17:30', '18:30', '19:30']),
    ]
    rows = []
    print(f"\n{'schedule':<34}{'realized':>13}{'return':>9}{'sharpe':>8}{'maxDD':>8}{'trades':>8}")
    for label, ts in scheds:
        r = replay_intraday(*WIN, check_times=ts, tag='f' + str(len(ts)) + ts[0].replace(':', ''))
        m = metrics(r)
        rows.append({'schedule': label, 'checks': ts,
                     **{k: r[k] for k in ('realized', 'realized_pct', 'total', 'trades')}, **m})
        print(f"{label:<34}{r['realized']:>13,.0f}{r['realized_pct']:>8.1f}%"
              f"{m['sharpe']:>8.2f}{m['max_dd_pct']:>7.1f}%{r['trades']:>8}")
    b = rows[0]['realized']
    print(f"\nvs production 1x/day: " +
          '  '.join(f"{r['schedule'].split()[0]}={r['realized'] - b:+,.0f}" for r in rows[1:]))
    print('\nNOTE: on a CASH account the engine withholds its own unsettled proceeds, so a')
    print('second check the same day cannot respend that morning\'s sale. That is not a')
    print('modelling artifact -- it is the GFV rule, and it is why intraday cadence is')
    print('structurally handicapped here.')
    save('intraday_frequency.json', {'window': list(WIN), 'engine': ENGINE,
                                     'cost_bps': COST_BPS, 'rows': rows,
                                     'method': 'MEASURED by full engine replay; no multiplier used'})


def save(name, obj):
    os.makedirs(RESULTS, exist_ok=True)
    dest = os.path.join(RESULTS, name)
    json.dump(obj, open(dest, 'w'), indent=1)
    print(f'\nwrote {os.path.relpath(dest, ROOT)}')


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('validate').set_defaults(fn=cmd_validate)
    sub.add_parser('exits').set_defaults(fn=cmd_exits)
    sub.add_parser('frequency').set_defaults(fn=cmd_frequency)
    a = ap.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
