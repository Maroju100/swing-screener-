#!/usr/bin/env python3
"""Last six months, month by month: v1, v2 live, equal-weight hold, and every other setup explored so far.
One continuous run each, May 11 -> Nov 11 2026, $15,000, 5 bps/side, official-close data, 17:00 UTC bar.
Setups and engines exactly as margin_style_all_setups_since_sep1.py (+ _pass2): studies that fit the current
engine run on origin/main on both a v2 and a v1 base; the nine older studies run on the engine revision they
were written for. Monthly P&L = change in equity between month-end marks of the same run.
Gates: plain v2 Oct1->Nov5 = 13,370.47; every patch list switched off reproduces its engine's plain run.
HINDSIGHT TABLE: ~170 setups on one window; the top rows are not validated improvements.
MEASURED. Reproduce: python3 scripts/margin_style_6mo_all_setups.py
"""
import csv, json, os, sys
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_17h_backtest as H
import margin_style_all_setups_since_sep1 as A
import margin_style_all_setups_since_sep1_pass2 as P

START, END, CAP = '2026-05-11', '2026-11-11', 15000.0
MONTHS = ['2026-05', '2026-06', '2026-07', '2026-08', '2026-09', '2026-10', '2026-11']


def one(job):
    study, label, base, eng, params, patches, tag, a, b = job
    H.UNIVERSE = list(A.CHIPS)
    try:
        r = R.replay(start=a, end=b, params=dict(params) or None, tag=tag, engine=eng, cost_bps=A.COST, capital=CAP,
                     src_patches=patches or None, daily=A.D, hourly=A.HR)
    except BaseException as e:
        return {'study': study, 'label': label, 'base': base, 'error': repr(e)[:200]}
    eq = r['day_equity']; pk = dd = 0.0
    for d in sorted(eq):
        pk = max(pk, eq[d]); dd = min(dd, eq[d] / pk - 1)
    return {'study': study, 'label': label, 'base': base, 'eng': eng, 'end': eq[max(eq)], 'max_dd': dd * 100,
            'trades': r['trade_count'], 'eq': eq}


def monthly(eq):
    prev, out = CAP, {}
    for m in MONTHS:
        ds = [d for d in sorted(eq) if d.startswith(m)]
        e = eq[ds[-1]]; out[m] = round(e - prev, 2); prev = e
    return out


if __name__ == '__main__':
    studies = A.collect()
    engs = ['origin/main', '1cb91a2', '979412d']
    with Pool(4) as pool:
        g = pool.map(one, [('gate', 'oct', 'v2', 'origin/main', {}, [], 'm6_gate', '2026-10-01', '2026-11-05')])[0]
        assert abs(g['end'] - 13370.47) < 0.01, f"GATE A FAILED {g['end']}"
        plain = {x['eng']: x for x in pool.map(one, [('engine', f'plain {e}', e, e, {}, [], f'm6_plain_{i}', START, END) for i, e in enumerate(engs)])}
        print('gate A PASS; plain', {e: round(x['end'], 2) for e, x in plain.items()}, flush=True)
        gj = [(k, 'gate', '', P.ENG.get(k, 'origin/main'), {}, p, f'm6_g_{k}', START, END) for k, (p, _) in studies.items()]
        bad = set()
        for x in pool.map(one, gj):
            if 'error' in x or abs(x['end'] - plain[x['eng']]['end']) > 0.01:
                bad.add(x['study']); print('PATCH GATE FAIL', x['study'], x.get('error') or x['end'], flush=True)
        jobs, seen, n = [], set(), 0
        for k, (p, vs) in studies.items():
            if k in bad:
                continue
            for lbl, params in vs:
                combos = [(P.NAME[P.ENG[k]], P.ENG[k], dict(params))] if k in P.ENG else \
                         [(b, 'origin/main', {**A.BASES[b], **params}) for b in A.BASES]
                for base, eng, pr in combos:
                    sig = (eng, tuple(id(f) for f in p), json.dumps(pr, sort_keys=True, default=str))
                    if sig in seen or not pr and eng == 'origin/main':
                        continue
                    seen.add(sig); n += 1
                    jobs.append((k, lbl, base, eng, pr, p, f'm6_{n}', START, END))
        print(len(jobs), 'runs', flush=True)
        res = []
        for i, x in enumerate(pool.imap_unordered(one, jobs)):
            res.append(x)
            if 'error' in x:
                print('RUN ERROR', x['study'], x['label'], x['error'], flush=True)
            if (i + 1) % 10 == 0:
                print(f'progress {i + 1}/{len(jobs)}', flush=True)
    rows = [x for x in res if 'error' not in x]
    rows.append({**plain['origin/main'], 'study': 'reference', 'label': 'v2 LIVE (current rules)', 'base': 'v2'})
    rows.append({**plain['1cb91a2'], 'study': 'reference', 'label': 'v1 (old rules)', 'base': 'v1 engine'})
    rows.append({**plain['979412d'], 'study': 'reference', 'label': 'v2 before peak reset', 'base': 'v2 pre-reset engine'})
    days = sorted(plain['origin/main']['eq'])
    hrb = {x['symbol']: {b['begins_at'][:10]: float(b['close_price']) for b in x['bars'] if b['begins_at'].endswith('17:00:00Z')}
           for x in json.load(open(A.HR))['data']['results']}
    heq = {d: sum(CAP / 8 * hrb[s][d] / hrb[s][START] for s in A.CHIPS) for d in days if all(d in hrb[s] for s in A.CHIPS)}
    pk = dd = 0.0
    for d in sorted(heq):
        pk = max(pk, heq[d]); dd = min(dd, heq[d] / pk - 1)
    rows.append({'study': 'reference', 'label': 'HOLD 8 chips equal weight', 'base': '-', 'end': heq[max(heq)], 'max_dd': dd * 100, 'trades': 0, 'eq': heq})
    for x in rows:
        x['monthly'] = monthly(x['eq']); x['pnl'] = round(x['end'] - CAP, 2); x['ret'] = round((x['end'] / CAP - 1) * 100, 2)
    rows.sort(key=lambda x: -x['end'])
    out = os.path.join(A.ROOT, 'data', 'research')
    json.dump({'start': START, 'end': END, 'capital': CAP, 'cost_bps': A.COST, 'gate_failed': sorted(bad),
               'rows': [{k: v for k, v in x.items() if k != 'eq'} for x in rows]}, open(os.path.join(out, '6mo_all_setups.json'), 'w'), indent=1, default=str)
    with open(os.path.join(out, '6mo_all_setups.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['rank', 'setup', 'base', 'study'] + [m + ' P&L $' for m in MONTHS] + ['total P&L $', 'return %', 'max drawdown %', 'trades'])
        for i, x in enumerate(rows):
            w.writerow([i + 1, x['label'], x['base'], x['study']] + [x['monthly'][m] for m in MONTHS] + [x['pnl'], x['ret'], round(x['max_dd'], 2), x['trades']])
    for i, x in enumerate(rows):
        if i < 15 or x['study'] == 'reference' or i >= len(rows) - 3:
            print(f"{i+1:3} {x['pnl']:+10.2f} {x['ret']:+7.2f}% dd {x['max_dd']:+6.1f} | " + ' '.join(f"{x['monthly'][m]:+8.0f}" for m in MONTHS) + f" | [{x['base']}] {x['study']}: {x['label']}")
    print('rows', len(rows))
