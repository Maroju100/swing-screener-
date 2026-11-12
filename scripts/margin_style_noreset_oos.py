#!/usr/bin/env python3
"""Out-of-sample test of "v2 before peak reset" (asked 2026-11-12, after it beat live v2 on Sep 1 -> Nov 11).

C = v2 without the peak reset (KILL_SWITCH_RESET_PEAK_ON_RELEASE False; v2 as deployed 2026-11-05).
B = v2 live (reset on, since 2026-11-06).  Engine origin/main for both, $15,000, 5 bps/side.

The two differ ONLY after a kill-switch fire and release, so many cells tie; ties are counted and excluded.
The reset was adopted on Nov 6 from semis data to Nov 5, so on the semis only Nov 6 -> Nov 11 is unseen
(reported, not scored). Other stocks were never used for this decision. Pass marks FIXED BEFORE ANY RUN:

 T1 other stocks, 4 baskets, Mar 13 -> Nov 5: pass = C wins every basket where the two differ (at least 2 differ)
 T2 same baskets x rising/falling/crash flat-start windows: pass = C wins >= 75% of differing cells (at least 4 differ)
 T3 22 single stocks/ETFs, full window: pass = C wins >= 2/3 of differing names (at least 6 differ)
 T4 semis, continuous runs to Nov 11 from 8 different start dates (consistency, NOT out-of-sample):
      pass = C wins >= 6 of 8
 T5 semis, continuous Mar 13 -> Nov 11, block bootstrap on daily return difference: pass = 95% CI above zero
 VERDICT: validated only if all five pass. Too few differing cells = INCONCLUSIVE for that check (counts as not passed).

Gates: Sep 1 -> Nov 11 semis, B = 14,533.45 and C = 15,691.40 (committed ranking; C must equal engine 979412d).
MEASURED by full engine replay. Reproduce: python3 scripts/margin_style_noreset_oos.py
"""
import json, os, sys
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_17h_backtest as H
import margin_style_v1v2_other_stocks as O

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, 'data', 'margin_live_daily_to_2026-11-11.json')
HR = os.path.join(ROOT, 'data', 'margin_live_hourly_to_2026-11-11.json')
WD, WH = O.DAILY, O.HOURLY
CAP, COST = 15000.0, 5.0
SEMIS = O.SEMIS
CFG = {'B': {}, 'C': {'KILL_SWITCH_RESET_PEAK_ON_RELEASE': False}}
BASKETS = {k: v for k, v in O.BASKETS.items() if 'CURRENT' not in k}
SUB = {'rising': ('2026-03-13', '2026-06-19'), 'falling': ('2026-06-22', '2026-09-30'), 'crash': ('2026-10-01', '2026-11-05')}
STARTS = ['2026-03-13', '2026-04-01', '2026-05-01', '2026-06-01', '2026-07-01', '2026-08-03', '2026-09-01', '2026-10-01']


def one(job):
    key, cfg, univ, a, b, daily, hourly = job
    H.UNIVERSE = list(univ)
    try:
        r = R.replay(start=a, end=b, params=dict(CFG[cfg]) or None, tag='nr_' + ''.join(ch if ch.isalnum() else '_' for ch in key),
                     engine='origin/main', cost_bps=COST, capital=CAP, daily=daily, hourly=hourly)
    except BaseException as e:
        return key, {'error': repr(e)[:200]}
    eq = r['day_equity']; pk = dd = 0.0
    for d in sorted(eq):
        pk = max(pk, eq[d]); dd = min(dd, eq[d] / pk - 1)
    e = eq[max(eq)]
    return key, {'end': e, 'ret': (e / CAP - 1) * 100, 'dd': dd * 100, 'trades': r['trade_count'], 'eq': eq}


def main():
    jobs = []
    for c in CFG:
        for bk, u in BASKETS.items():
            jobs.append((f'T1|{bk}|{c}', c, u, '2026-03-13', '2026-11-05', WD, WH))
            for w, (a, b) in SUB.items():
                jobs.append((f'T2|{bk}|{w}|{c}', c, u, a, b, WD, WH))
        for s in O.SINGLES:
            jobs.append((f'T3|{s}|{c}', c, [s], '2026-03-13', '2026-11-05', WD, WH))
        for a in STARTS:
            jobs.append((f'T4|{a}|{c}', c, SEMIS, a, '2026-11-11', D, HR))
        jobs.append((f'FWD|{c}', c, SEMIS, '2026-11-06', '2026-11-11', D, HR))
    print(len(jobs), 'runs', flush=True)
    res = {}
    with Pool(4) as pool:
        for i, (k, v) in enumerate(pool.imap_unordered(one, jobs)):
            res[k] = v
            if 'error' in v:
                print('RUN ERROR', k, v['error'], flush=True)
            if (i + 1) % 20 == 0:
                print(f'progress {i + 1}/{len(jobs)}', flush=True)
    json.dump(res, open(os.path.join(ROOT, 'data', 'research', 'noreset_oos_raw.json'), 'w'), default=str)
    gb, gc = res['T4|2026-09-01|B']['end'], res['T4|2026-09-01|C']['end']
    assert abs(gb - 14533.45) < 0.01 and abs(gc - 15691.40) < 0.01, f'GATE FAILED {gb} {gc}'
    print(f'gates PASS  B {gb:,.2f}  C {gc:,.2f}')

    def pair(prefix):
        b, c = res[f'{prefix}|B'], res[f'{prefix}|C']
        d = c['end'] - b['end']
        return {'B': b['ret'], 'C': c['ret'], 'B_dd': b['dd'], 'C_dd': c['dd'], 'res': 'tie' if abs(d) < 0.005 else ('C' if d > 0 else 'B')}
    t1 = {bk: pair(f'T1|{bk}') for bk in BASKETS}
    t2 = {f'{bk}|{w}': pair(f'T2|{bk}|{w}') for bk in BASKETS for w in SUB}
    t3 = {s: pair(f'T3|{s}') for s in O.SINGLES}
    t4 = {a: pair(f'T4|{a}') for a in STARTS}
    rb, rc = (R.daily_returns({'day_equity': res[f'T4|2026-03-13|{c}']['eq']}) for c in ('B', 'C'))
    lo, hi, p = R.block_bootstrap_diff(rc, rb)
    cnt = lambda t: (sum(v['res'] == 'C' for v in t.values()), sum(v['res'] != 'tie' for v in t.values()), len(t))
    c1, c2, c3, c4 = cnt(t1), cnt(t2), cnt(t3), cnt(t4)
    checks = {'T1 other-stock baskets, full (all differing, >=2 differ)': (c1, c1[1] >= 2 and c1[0] == c1[1]),
              'T2 basket sub-windows (>=75% of differing, >=4 differ)': (c2, c2[1] >= 4 and c2[0] >= 0.75 * c2[1]),
              'T3 single stocks (>=2/3 of differing, >=6 differ)': (c3, c3[1] >= 6 and c3[0] >= c3[1] * 2 / 3),
              'T4 semis start dates (>=6 of 8)': (c4, c4[0] >= 6),
              'T5 bootstrap CI above zero': ((round(lo * 100, 3), round(hi * 100, 3), round(p, 3)), lo > 0)}
    out = {'capital': CAP, 'cost_bps': COST, 'T1': t1, 'T2': t2, 'T3': t3, 'T4': t4,
           'T5': {'ci': [lo, hi], 'p_better': p}, 'forward_nov6_nov11': pair('FWD'),
           'checks': {k: {'score': v[0], 'pass': v[1]} for k, v in checks.items()},
           'passed': sum(v[1] for v in checks.values()),
           'verdict': 'VALIDATED' if all(v[1] for v in checks.values()) else 'NOT VALIDATED'}
    json.dump(out, open(os.path.join(ROOT, 'data', 'research', 'noreset_oos.json'), 'w'), indent=1, default=str)
    f = lambda v: f"live {v['B']:+7.2f}%  no-reset {v['C']:+7.2f}%  dd {v['B_dd']:+6.1f}/{v['C_dd']:+6.1f}  {v['res']}"
    for name, t in (('T1', t1), ('T2', t2), ('T3', t3), ('T4', t4)):
        print(name)
        for k, v in t.items():
            print(f'  {k:34} {f(v)}')
    print(f'T5 CI [{lo*100:+.3f}%, {hi*100:+.3f}%] P(better) {p:.3f}')
    print('FWD Nov6-Nov11', f(out['forward_nov6_nov11']))
    for k, v in checks.items():
        print(f"{'PASS' if v[1] else 'FAIL'}  {k}: {v[0]}  (C wins, differing, total)")
    print(out['verdict'], f"({out['passed']} of 5)")


if __name__ == '__main__':
    main()
