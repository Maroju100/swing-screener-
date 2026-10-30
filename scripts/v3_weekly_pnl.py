#!/usr/bin/env python3
"""Weekly P&L of the v3 day-trading setup on $15k, to sit beside the Margin-Style weekly table.

Replays the real scripts/daytrading_v3_paper_engine.py (its own constants, i.e. the
'baseline' parameter set) through scripts/v3_replay.py's harness -- nothing re-implemented.
5 bps per side applied inside the replay. v3 closes everything by 19:30 UTC each day,
so end-of-day equity is cash and a week's P&L is the change in cash.

DATA LIMIT (Evidence Rule 6): Robinhood serves real 1-minute bars for ~6 trailing weeks
only, and the committed minute data covers MU, SNDK, WDC -- the engine's own universe --
from 2026-08-10. Weeks before that CANNOT be replayed and are reported as missing, not
estimated. Files:
    data/semis_1min_2026-08-10_2026-09-21.json   (committed 2026-10-01)
    data/semis_1min_2026-09-22_2026-10-16.json   (fetched 2026-10-16)

Gate: on the committed window alone, at the engine's own $5,000 and 5 bps, the replay must
reproduce the committed result in data/v3_replay_results.json ($5,018.91, 767 trades)
exactly -- otherwise nothing is reported.

Weekly equity is taken from a fresh replay truncated at each week's last day. The engine
is causal and flat every night, so a truncated replay is exactly the prefix of the full one.

Reproduce:
    python3 scripts/v3_weekly_pnl.py [--capital 15000] [--params tightened] [--start 2026-09-22]

--params tightened uses v3_replay.PARAMS['tightened'] (the grid-optimized set); its gate is
the committed data/v3_replay_results_tightened.json ($4,900.96, 635 trades at 5 bps).
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v3_replay as VR
import daytrading_v3_paper_engine as V3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = [os.path.join(ROOT, 'data', 'semis_1min_2026-08-10_2026-09-21.json'),
         os.path.join(ROOT, 'data', 'semis_1min_2026-09-22_2026-10-16.json'),
         os.path.join(ROOT, 'data', 'semis_1min_2026-10-19_2026-10-29.json')]
COST = 5.0


def load():
    bars = {}
    for f in FILES:
        d = json.load(open(f))
        for sym, days in d['bars'].items():
            for day, rows in days.items():
                if day in bars.get(sym, {}):
                    raise SystemExit(f'overlap {sym} {day} between minute files -- refusing')
                bars.setdefault(sym, {})[day] = rows
    days = sorted(next(iter(bars.values())))
    for sym in bars:
        if sorted(bars[sym]) != days:
            raise SystemExit(f'{sym} day set differs from the others -- refusing')
    return bars, days


def set_capital(cap):
    V3.CAPITAL = cap
    V3.PER_SYMBOL_SLICE = cap / len(V3.SYMBOLS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--capital', type=float, default=15000.0)
    ap.add_argument('--params', choices=sorted(VR.PARAMS), default='baseline')
    ap.add_argument('--start', default=None)
    a = ap.parse_args()
    bars, days = load()
    params = VR.PARAMS[a.params]
    gate_eq, gate_n = {'baseline': (5018.91, 767), 'tightened': (4900.96, 635)}[a.params]

    set_capital(5000.0)
    gdays = [d for d in days if d <= '2026-09-21']
    g = VR.replay(f'wk_gate_{a.params}', params, gdays, bars, cost_bps=COST)
    if abs(g['equity'] - gate_eq) > 0.005 or g['trades'] != gate_n:
        raise SystemExit(f"GATE FAILED: {g['equity']} / {g['trades']}")
    print(f'gate PASS ({a.params}): committed window reproduces ${gate_eq:,.2f} / {gate_n} trades at 5 bps\n')

    set_capital(a.capital)
    if a.start:
        days = [d for d in days if d >= a.start]
    weeks = {}
    for d in days:
        mon = (dt.date.fromisoformat(d) - dt.timedelta(days=dt.date.fromisoformat(d).weekday())).isoformat()
        weeks.setdefault(mon, []).append(d)
    out, prev, peak = [], a.capital, a.capital
    for mon, wd in weeks.items():
        r = VR.replay(f'wk_{a.params}_{int(a.capital)}_{wd[-1]}', params, [d for d in days if d <= wd[-1]], bars, cost_bps=COST)
        eq = r['equity']
        peak = max(peak, eq)
        out.append({'week_of': mon, 'days': len(wd), 'last_day': wd[-1], 'start_equity': round(prev, 2),
                    'end_equity': round(eq, 2), 'pnl': round(eq - prev, 2),
                    'pct': round((eq / prev - 1) * 100, 2), 'below_peak_pct': round((eq / peak - 1) * 100, 2),
                    'cum_trades': r['trades']})
        prev = eq
    print(f"{'week of':11}{'days':>5}{'P&L':>10}{'%':>8}{'equity':>11}{'vs peak':>9}")
    for w in out:
        print(f"{w['week_of']:11}{w['days']:>5}{w['pnl']:>+10,.0f}{w['pct']:>+8.2f}{w['end_equity']:>11,.0f}{w['below_peak_pct']:>+9.2f}")
    tot = out[-1]['end_equity'] - a.capital
    print(f"\ntotal {tot:+,.0f} ({tot / a.capital * 100:+.1f}%) from {days[0]} to {days[-1]}, "
          f"{out[-1]['cum_trades']} trades")
    path = os.path.join(ROOT, 'data', 'research', f'v3_weekly_pnl_{int(a.capital)}' + (f'_from{a.start}' if a.start else '') + ('' if a.params == 'baseline' else f'_{a.params}') + '.json')
    json.dump({'engine': 'scripts/daytrading_v3_paper_engine.py', 'params': a.params,
               'symbols': V3.SYMBOLS, 'capital': a.capital, 'cost_bps': COST, 'start': days[0],
               'through': days[-1], 'weeks': out,
               'not_replayable': 'weeks before 2026-08-10: no real 1-minute bars from the source'},
              open(path, 'w'), indent=1)


if __name__ == '__main__':
    main()
