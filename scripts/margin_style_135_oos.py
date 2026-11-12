#!/usr/bin/env python3
"""Out-of-sample test of "1+3+5" (asked 2026-11-12, after it topped the Sep 1 -> Nov 11 hindsight ranking).

C  = 1+3+5: MIN_NOTIONAL 500, kill -8%/10d, no trend gate, tranches 50/30/20/10/5, 100% sell on a new high.
B  = 1+3  : the same without the last two (v2 as deployed 2026-11-05, before peak reset).
Both on engine 1cb91a2 with top5_combined's patches (the code 1+3+5 was defined on), $15,000, 5 bps/side.

What is genuinely unseen: 1+3+5 was assembled on 2026-11-05 from semis data Mar 13 -> Nov 4, so on the semis
only Nov 5 -> Nov 11 is unseen (5 sessions: reported, not scored). The real out-of-sample material is OTHER
STOCKS, which were never used to choose it. Checks and pass marks FIXED BEFORE ANY RUN:

 T1 other stocks, 4 baskets (big tech, non-tech 8, sector ETFs, other chip names), Mar 13 -> Nov 5:
      pass = C beats B over the full window in all 4 baskets
 T2 same baskets, 3 flat-start sub-windows each (rising Mar13-Jun19, falling Jun22-Sep30, crash Oct1-Nov5):
      pass = C beats B in at least 9 of 12 cells
 T3 22 single stocks/ETFs outside the semis, full window:  pass = C beats B in at least 15 of 22
 T4 semis, 8 monthly flat-start folds Mar 13 -> Nov 11 (consistency, NOT out-of-sample):
      pass = C beats B in at least 6 of 8
 T5 semis, continuous Mar 13 -> Nov 11, block bootstrap on daily return difference:
      pass = 95% CI excludes zero on the positive side
 T6 with the live peak reset (engine origin/main; C = live + the two changes, B = live v2), semis,
      full + rising/falling/crash to Nov 11:  pass = C beats B in the full window and at least 2 of 3 sub-windows
 VERDICT: validated only if all six pass.

Gates: on Sep 1 -> Nov 11 semis, B = 15,691.40 and C = 17,417.64 (the committed ranking).
MEASURED by full engine replay. Reproduce: python3 scripts/margin_style_135_oos.py
"""
import json, os, sys
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_17h_backtest as H
import margin_style_top5_combined as T5
import margin_style_v1v2_other_stocks as O

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, 'data', 'margin_live_daily_to_2026-11-11.json')
HR = os.path.join(ROOT, 'data', 'margin_live_hourly_to_2026-11-11.json')
WD, WH = O.DAILY, O.HOURLY
CAP, COST = 15000.0, 5.0
SEMIS = O.SEMIS
B13 = {**T5.S1, **T5.S3}
C135 = {**T5.S1, **T5.S3, **T5.S5}
CFG = {'B': ('1cb91a2', B13, T5.PATCHES), 'C': ('1cb91a2', C135, T5.PATCHES),
       'Blive': ('origin/main', {}, [R.patch_sell_epsilon]), 'Clive': ('origin/main', dict(T5.S5), [R.patch_sell_epsilon])}
BASKETS = {k: v for k, v in O.BASKETS.items() if 'CURRENT' not in k}
SUB = {'rising': ('2026-03-13', '2026-06-19'), 'falling': ('2026-06-22', '2026-09-30'), 'crash': ('2026-10-01', None)}
MONTHS = [('2026-03-13', '2026-03-31'), ('2026-04-01', '2026-04-30'), ('2026-05-01', '2026-05-29'), ('2026-06-01', '2026-06-30'),
          ('2026-07-01', '2026-07-31'), ('2026-08-03', '2026-08-31'), ('2026-09-01', '2026-09-30'), ('2026-10-01', '2026-10-30'),
          ('2026-11-02', '2026-11-11')]


def one(job):
    key, cfg, univ, a, b, daily, hourly = job
    eng, params, patches = CFG[cfg]
    H.UNIVERSE = list(univ)
    try:
        r = R.replay(start=a, end=b, params=dict(params) or None, tag='oos_' + ''.join(ch if ch.isalnum() else '_' for ch in key),
                     engine=eng, cost_bps=COST, capital=CAP, src_patches=patches, daily=daily, hourly=hourly)
    except BaseException as e:
        return key, {'error': repr(e)[:200]}
    eq = r['day_equity']; pk = dd = 0.0
    for d in sorted(eq):
        pk = max(pk, eq[d]); dd = min(dd, eq[d] / pk - 1)
    e = eq[max(eq)]
    return key, {'end': e, 'ret': (e / CAP - 1) * 100, 'dd': dd * 100, 'trades': r['trade_count'], 'eq': eq}


def main():
    jobs = []
    for c in ('B', 'C'):
        jobs.append((f'gate|{c}', c, SEMIS, '2026-09-01', '2026-11-11', D, HR))
        for bk, u in BASKETS.items():
            jobs.append((f'T1|{bk}|{c}', c, u, '2026-03-13', '2026-11-05', WD, WH))
            for w, (a, b) in SUB.items():
                jobs.append((f'T2|{bk}|{w}|{c}', c, u, a, b or '2026-11-05', WD, WH))
        for s in O.SINGLES:
            jobs.append((f'T3|{s}|{c}', c, [s], '2026-03-13', '2026-11-05', WD, WH))
        for a, b in MONTHS:
            jobs.append((f'T4|{a[:7]}|{c}', c, SEMIS, a, b, D, HR))
        jobs.append((f'T5|{c}', c, SEMIS, '2026-03-13', '2026-11-11', D, HR))
        jobs.append((f'FWD|{c}', c, SEMIS, '2026-11-05', '2026-11-11', D, HR))
    for c in ('Blive', 'Clive'):
        jobs.append((f'T6|full|{c}', c, SEMIS, '2026-03-13', '2026-11-11', D, HR))
        for w, (a, b) in SUB.items():
            jobs.append((f'T6|{w}|{c}', c, SEMIS, a, b or '2026-11-11', D, HR))
    print(len(jobs), 'runs', flush=True)
    res = {}
    with Pool(4) as pool:
        for i, (k, v) in enumerate(pool.imap_unordered(one, jobs)):
            res[k] = v
            if 'error' in v:
                print('RUN ERROR', k, v['error'], flush=True)
            if (i + 1) % 20 == 0:
                print(f'progress {i + 1}/{len(jobs)}', flush=True)
    gb, gc = res['gate|B']['end'], res['gate|C']['end']
    assert abs(gb - 15691.40) < 0.01 and abs(gc - 17417.64) < 0.01, f'GATE FAILED {gb} {gc}'
    print(f'gates PASS  B {gb:,.2f}  C {gc:,.2f}')

    def pair(prefix, bn='B', cn='C'):
        b, c = res[f'{prefix}|{bn}'], res[f'{prefix}|{cn}']
        return {'B': b['ret'], 'C': c['ret'], 'B_dd': b['dd'], 'C_dd': c['dd'], 'win': c['end'] > b['end'] + 0.005}
    out = {'capital': CAP, 'cost_bps': COST, 'B': B13, 'C': C135}
    t1 = {bk: pair(f'T1|{bk}') for bk in BASKETS}
    t2 = {f'{bk}|{w}': pair(f'T2|{bk}|{w}') for bk in BASKETS for w in SUB}
    t3 = {s: pair(f'T3|{s}') for s in O.SINGLES}
    t4 = {a[:7]: pair(f'T4|{a[:7]}') for a, _ in MONTHS[:-1]}      # 8 scored months; Nov (partial) reported only
    nov = pair('T4|2026-11')
    rb, rc = (R.daily_returns({'day_equity': res[f'T5|{c}']['eq']}) for c in ('B', 'C'))
    lo, hi, p = R.block_bootstrap_diff(rc, rb)
    t5 = {**pair('T5'), 'ci': [lo, hi], 'p_better': p}
    t6 = {w: pair(f'T6|{w}', 'Blive', 'Clive') for w in ['full'] + list(SUB)}
    n = lambda d: sum(1 for v in d.values() if v['win'])
    checks = {'T1 other-stock baskets, full (need 4/4)': (n(t1), 4, n(t1) == 4),
              'T2 basket sub-windows (need 9/12)': (n(t2), 12, n(t2) >= 9),
              'T3 single stocks (need 15/22)': (n(t3), 22, n(t3) >= 15),
              'T4 semis monthly folds (need 6/8)': (n(t4), 8, n(t4) >= 6),
              'T5 bootstrap CI > 0': (round(p, 3), 1, lo > 0),
              'T6 with peak reset (full + 2 of 3)': (n(t6), 4, t6['full']['win'] and sum(t6[w]['win'] for w in SUB) >= 2)}
    out.update({'T1': t1, 'T2': t2, 'T3': t3, 'T4': t4, 'T4_nov_partial': nov, 'T5': t5, 'T6': t6,
                'forward_nov5_nov11': pair('FWD'), 'checks': {k: {'score': v[0], 'of': v[1], 'pass': v[2]} for k, v in checks.items()},
                'passed': sum(1 for v in checks.values() if v[2]),
                'verdict': 'VALIDATED' if all(v[2] for v in checks.values()) else 'NOT VALIDATED'})
    json.dump(out, open(os.path.join(ROOT, 'data', 'research', '135_oos.json'), 'w'), indent=1, default=str)
    f = lambda v: f"B {v['B']:+7.2f}%  C {v['C']:+7.2f}%  dd {v['B_dd']:+6.1f}/{v['C_dd']:+6.1f}  {'C' if v['win'] else 'B'}"
    for name, t in (('T1', t1), ('T2', t2), ('T3', t3), ('T4', t4), ('T6', t6)):
        print(name)
        for k, v in t.items():
            print(f'  {k:38} {f(v)}')
    print('  2026-11 (partial, not scored)          ', f(nov))
    print('T5 full semis', f(t5), f'CI [{lo*100:+.3f}%, {hi*100:+.3f}%] P(better) {p:.3f}')
    print('FWD Nov5-Nov11', f(out['forward_nov5_nov11']))
    for k, v in checks.items():
        print(f"{'PASS' if v[2] else 'FAIL'}  {k}: {v[0]}/{v[1]}")
    print(out['verdict'], f"({out['passed']} of 6)")


if __name__ == '__main__':
    main()
