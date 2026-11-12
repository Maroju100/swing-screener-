#!/usr/bin/env python3
"""Pass 2 of margin_style_all_setups_since_sep1.py: the nine studies whose patches no longer fit the current
engine are replayed on the engine revision they were written against, with their own parameters only:
  v1 engine (1cb91a2, main before v2):       after_october, protect_rules, protect_rules2, reentry_rules,
                                             top5_combined, crash_grid
  v2 engine before peak reset (979412d):     v2_pause, v2_steady, choppy
Gate per study: its patch list with no params reproduces the plain replay of that engine revision exactly.
Same window/data/cost: Sep 1 -> Nov 11 2026, $15,000, 5 bps/side. HINDSIGHT RANKING, not validation.
Merges into data/research/all_setups_since_sep1.json. MEASURED.
Reproduce: python3 scripts/margin_style_all_setups_since_sep1.py && python3 scripts/margin_style_all_setups_since_sep1_pass2.py
"""
import json, os, sys
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_all_setups_since_sep1 as A

ENG = {'after_october': '1cb91a2', 'protect_rules': '1cb91a2', 'protect_rules2': '1cb91a2', 'reentry_rules': '1cb91a2',
       'top5_combined': '1cb91a2', 'crash_grid': '1cb91a2', 'v2_pause': '979412d', 'v2_steady': '979412d', 'choppy': '979412d'}
NAME = {'1cb91a2': 'v1 engine', '979412d': 'v2 pre-reset engine'}


def one(job):
    key, label, params, patches, tag = job
    try:
        r = R.replay(start=A.START, end=A.END, params=dict(params) or None, tag=tag, engine=ENG.get(key, key),
                     cost_bps=A.COST, capital=A.CAP, src_patches=patches or None, daily=A.D, hourly=A.HR)
    except BaseException as e:
        return {'study': key, 'label': label, 'error': repr(e)[:200]}
    eq = r['day_equity']; pk = dd = 0.0
    for d in sorted(eq):
        pk = max(pk, eq[d]); dd = min(dd, eq[d] / pk - 1)
    e = eq[max(eq)]
    return {'study': key, 'label': label, 'base': NAME.get(ENG.get(key, key), key), 'params': params, 'end': e,
            'ret': (e / A.CAP - 1) * 100, 'max_dd': dd * 100, 'trades': r['trade_count'], 'eq': eq}


if __name__ == '__main__':
    studies = {k: v for k, v in A.collect().items() if k in ENG}
    with Pool(4) as pool:
        plain = {x['study']: x for x in pool.map(one, [(e, 'plain', {}, [], f'p2_plain_{e}') for e in NAME])}
        for e, x in plain.items():
            print(f"plain {NAME[e]} ({e}): {x.get('end', x.get('error'))}", flush=True)
        g = pool.map(one, [(k, 'gate', {}, p, f'p2_g_{k}') for k, (p, _) in studies.items()])
        bad = {x['study'] for x in g if 'error' in x or abs(x['end'] - plain[ENG[x['study']]]['end']) > 0.01}
        for x in g:
            print('gate', x['study'], 'FAIL' if x['study'] in bad else 'PASS', x.get('error') or round(x['end'], 2), flush=True)
        jobs = [(k, lbl, params, p, f'p2_{k}_{i}') for k, (p, vs) in studies.items() if k not in bad for i, (lbl, params) in enumerate(vs)]
        res = []
        for i, x in enumerate(pool.imap_unordered(one, jobs)):
            res.append(x)
            if (i + 1) % 10 == 0:
                print(f'progress {i + 1}/{len(jobs)}', flush=True)
    for x in res:
        if 'error' in x:
            print('RUN ERROR', x['study'], x['label'], x['error'])
    ok = [x for x in res if 'error' not in x]
    for e in NAME:
        if 'end' in plain[e]:
            ok.append({**plain[e], 'study': 'engine', 'label': f'plain {NAME[e]} ({e})', 'base': NAME[e]})
    path = os.path.join(A.ROOT, 'data', 'research', 'all_setups_since_sep1.json')
    o = json.load(open(path))
    o['results'] = sorted([x for x in o['results'] if not x.get('pass2')] + [{**x, 'pass2': True} for x in ok], key=lambda x: -x['end'])
    o['pass2_gate_failed'] = sorted(bad); o['n_runs'] = len(o['results'])
    json.dump(o, open(path, 'w'), indent=1, default=str)
    print(f"hold {o['hold']:,.2f}  plain v2 {o['plain_v2']:,.2f}  runs {o['n_runs']}")
    for i, x in enumerate(o['results'][:30]):
        print(f"{i+1:3} {x['end']:10,.2f} {x['ret']:+7.2f}% dd {x['max_dd']:+6.2f}% t{x['trades']:4} [{x['base']}] {x['study']}: {x['label']}")
