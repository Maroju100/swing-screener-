#!/usr/bin/env python3
"""v1 vs v2 on non-semi baskets and single stocks, 6 months, walk-forward (asked 2026-11-07).

Windows (fixed before running):
  FULL   2026-03-13 -> 2026-09-21  (6 months, same window as the production anchor)
  TRAIN  2026-03-13 -> 2026-06-19  (first half: the 'rising' stretch)
  TEST   2026-06-22 -> 2026-09-21  (second half, held out: the 'falling' stretch)
Walk-forward rule, fixed before running: for each basket/stock, choose the version with the higher
TRAIN return; report that choice's TEST return vs the other version and buy & hold.
Count the choices that also won TEST.  Both versions are FIXED configs (no parameters fit), so the
only "selection" is the v1-or-v2 choice on TRAIN. A second reverse split (train on the second half,
test on the first) is also reported as a robustness check.
Engine origin/main; v1 = pre-v2 rules; $15k; 5 bps/side; 17:00 UTC hourly check price.
Gate: v1 on the 8 semis, $80k, 2026-03-13 -> 2026-09-21 reproduces production ($124,289.71 / 771 trades).
MEASURED by full engine replay. Reproduce: python3 scripts/margin_style_6mo_walkforward_other.py
"""
import json, os, sys
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_17h_backtest as H
import margin_style_instant_settlement as IS
import margin_style_v1v2_other_stocks as O

W = {'FULL': ('2026-03-13', '2026-09-21'), 'TRAIN': ('2026-03-13', '2026-06-19'),
     'TEST': ('2026-06-22', '2026-09-21'), 'REV_TRAIN': ('2026-06-22', '2026-09-21'),
     'REV_TEST': ('2026-03-13', '2026-06-19')}
CAP, COST = 15000.0, 5.0
PATCHES = [R.patch_sell_epsilon, IS.patch_instant]


def run(univ, ver, a, b, cap=CAP, tag='x'):
    H.UNIVERSE = list(univ)
    r = R.replay(start=a, end=b, params=dict(O.V[ver]), tag=f'wf_{ver}_{tag}_{a}', engine='origin/main', cost_bps=COST,
                 capital=cap, src_patches=PATCHES, daily=O.DAILY, hourly=O.HOURLY)
    eq = [v for _, v in sorted(r['day_equity'].items())]
    pk = dd = 0
    for v in eq:
        pk = max(pk, v); dd = min(dd, v / pk - 1)
    return {'ret': (eq[-1] / cap - 1) * 100, 'dd': dd * 100, 'trades': r['trade_count'], 'realized': r.get('realized')}


def hold(univ, a, b):
    days = sorted(O.CLOSE[univ[0]])
    d0 = max(d for d in days if d < a)
    d1 = max(d for d in days if d <= b)
    return (sum(O.CLOSE[s][d1] / O.CLOSE[s][d0] for s in univ) / len(univ) - 1) * 100


def job(a):
    name, univ, ver, win = a
    s, e = W[win]
    return name, ver, win, run(univ, ver, s, e, tag=name.replace(' ', '')[:12])


def main():
    g = run(O.SEMIS, 'v1', '2026-03-13', '2026-09-21', cap=80000.0, tag='gate')
    if abs(g['realized'] - 124289.71) > 0.005 or g['trades'] != 771:
        raise SystemExit(f"GATE FAILED: {g}")
    print('gate PASS: v1 reproduces production on these files', flush=True)
    units = [(n, u) for n, u in O.BASKETS.items() if n != 'CURRENT 8 SEMIS (ref)'] + [(s, [s]) for s in O.SINGLES]
    jobs = [(n, u, v, w) for n, u in units for v in O.V for w in W]
    with Pool(1) as p:
        res = p.map(job, jobs)
    out = {}
    for n, v, w, r in res:
        out.setdefault(n, {}).setdefault(v, {})[w] = r
    rows = []
    for n, u in units:
        d = out[n]
        pick = 'v1' if d['v1']['TRAIN']['ret'] > d['v2']['TRAIN']['ret'] else 'v2'
        other = 'v2' if pick == 'v1' else 'v1'
        rev_pick = 'v1' if d['v1']['REV_TRAIN']['ret'] > d['v2']['REV_TRAIN']['ret'] else 'v2'
        h_test = hold(u, *W['TEST']); h_full = hold(u, *W['FULL'])
        rows.append({'name': n, 'pick': pick, 'test_pick': d[pick]['TEST']['ret'], 'test_other': d[other]['TEST']['ret'],
                     'test_hold': h_test, 'pick_won_test': d[pick]['TEST']['ret'] > d[other]['TEST']['ret'],
                     'full_v1': d['v1']['FULL']['ret'], 'full_v2': d['v2']['FULL']['ret'], 'full_hold': h_full,
                     'rev_pick': rev_pick,
                     'rev_pick_won': d[rev_pick]['REV_TEST']['ret'] > d['v2' if rev_pick == 'v1' else 'v1']['REV_TEST']['ret']})
        print(f"{n:24} FULL v1 {d['v1']['FULL']['ret']:+6.1f} v2 {d['v2']['FULL']['ret']:+6.1f} hold {h_full:+6.1f} | "
              f"TRAIN pick {pick} | TEST {pick} {d[pick]['TEST']['ret']:+6.1f} vs {other} {d[other]['TEST']['ret']:+6.1f} "
              f"hold {h_test:+6.1f} | won={rows[-1]['pick_won_test']}", flush=True)
    n = len(rows)
    print(f"TRAIN-chosen version also won TEST: {sum(r['pick_won_test'] for r in rows)}/{n}")
    print(f"REVERSE split: train-chosen version won its held-out half: {sum(r['rev_pick_won'] for r in rows)}/{n}")
    R.save('6mo_walkforward_other.json', {'windows': W, 'capital': CAP, 'cost_bps': COST, 'rows': rows, 'raw': out})


if __name__ == '__main__':
    main()
