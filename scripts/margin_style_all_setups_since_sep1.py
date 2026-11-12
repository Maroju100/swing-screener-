#!/usr/bin/env python3
"""Every rule setup explored so far, replayed Sep 1 -> Nov 11 2026 at $15,000, 5 bps/side, on the official-close
data used by margin_style_nov_replay_vs_hold.py. Full engine replay of origin/main (v2) with each study's own
source patches and parameters. Each setup is run on two bases: v2 (production) and v1 (old kill-switch/$25 min),
with the setup's own parameters overriding the base.

HINDSIGHT RANKING: picking the best of ~200 runs on one 50-day window is in-sample by construction. The top
row is "what would have done best", not a validated improvement (CLAUDE.md evidence rules).

Gates: (a) plain v2 Oct1->Nov5 = 13,370.47; (b) every study's patch list with no params reproduces plain v2
over Sep1->Nov11 exactly (patches are no-ops when switched off, and still apply to the current engine).
MEASURED. Reproduce: python3 scripts/margin_style_all_setups_since_sep1.py
"""
import json, os, sys
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_17h_backtest as H

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, 'data', 'margin_live_daily_to_2026-11-11.json')
HR = os.path.join(ROOT, 'data', 'margin_live_hourly_to_2026-11-11.json')
CHIPS = ['AMD', 'MU', 'WDC', 'SNDK', 'TSM', 'INTC', 'LRCX', 'STX']
H.UNIVERSE = list(CHIPS)
START, END, CAP, COST = '2026-09-01', '2026-11-11', 15000.0, 5.0
BASES = {'v2': {}, 'v1': {'MIN_NOTIONAL': 25.0, 'KILL_SWITCH_DD': -0.15, 'KILL_SWITCH_RESUME_DAYS': 20,
                          'KILL_SWITCH_TREND_LOCK': True, 'KILL_SWITCH_RESET_PEAK_ON_RELEASE': False}}


def collect():
    import margin_style_after_october as AO, margin_style_candidate_pdf as CP, margin_style_drawdown_rules as DR
    import margin_style_protect_rules as P1, margin_style_protect_rules2 as P2, margin_style_rank_admissible as RA
    import margin_style_rebound_addons as RB, margin_style_reentry_rules as RE, margin_style_rule_ideas as RI
    import margin_style_sizing_rules as SZ, margin_style_top5_combined as T5, margin_style_user_derived as UD
    import margin_style_v2_pause as VP, margin_style_v2_steady as VS, margin_style_ks_throttle as KT
    import margin_style_lower_risk as LR, margin_style_grid_entry_exit as GE, margin_style_crash_grid as CG
    import margin_style_choppy as CH
    out = {}  # patchset name -> (patches, [(label, params)])
    def items(v):
        return list(v.items()) if isinstance(v, dict) else [(x[0], x[1]) for x in v]
    out['after_october'] = (AO.PATCHES, items(AO.VARIANTS))
    out['candidate_pdf'] = (CP.PATCH, items(CP.VARIANTS))
    out['drawdown_rules'] = (DR.PATCH, items(DR.VARIANTS))
    out['protect_rules'] = ([P1.patch_protect, P1.SZ.patch_size], items(P1.VARIANTS))
    out['protect_rules2'] = (P2.PATCHES, items(P2.VARIANTS))
    out['rebound_addons'] = (RB.PATCHES, items(RB.CFG))
    out['reentry_rules'] = (RE.PATCHES, [(f'{b}+{RE.NAMES[m]}', {**RE.BASES[b], **RE.MODS[m]}) for b in RE.BASES for m in RE.MODS])
    out['rule_ideas'] = (RI.PATCH, items(RI.VARIANTS))
    out['sizing_rules'] = (SZ.PATCH, items(SZ.VARIANTS))
    out['top5_combined'] = (T5.PATCHES, items(T5.CONFIGS))
    out['user_derived'] = (UD.PATCHES if hasattr(UD, 'PATCHES') else [UD.patch_user], items(UD.VARIANTS))
    out['v2_pause'] = (VP.PATCHES, items(VP.CONFIGS))
    out['v2_steady'] = (VS.PATCHES, items(VS.CONFIGS))
    out['ks_throttle'] = (KT.PATCHES, items(KT.CFG))
    out['choppy'] = (CH.PATCHES, items(CH.CFG))
    out['lower_risk'] = (LR.PATCH, [('streak pause', dict(LR.STREAK))])
    out['grid_entry_exit'] = ([R.patch_sell_epsilon], [('grid#%d %s' % (i + 1, t['label']), GE.to_params(t['config']))
                                                       for i, t in enumerate(json.load(open(os.path.join(ROOT, 'data', 'research', 'grid_entry_exit.json')))['top10_in_sample'])])
    cg = json.load(open(os.path.join(ROOT, 'data', 'research', 'crash_grid.json')))['results']
    cg = sorted(cg, key=lambda x: -x['full']['ret'])[:5]
    lab = {CG.label(c): c for c in CG.GRID}
    out['crash_grid'] = (CG.P2.PATCHES, [(x['config'], CG.params(lab[x['config']])) for x in cg if x['config'] in lab])
    rp = {}
    for lbl, params, patches in RA.CONFIGS:
        rp.setdefault(tuple(patches or []), []).append((lbl, params))
    for i, (pt, v) in enumerate(rp.items()):
        out[f'rank_admissible{i}'] = (list(pt), v)
    return out


def one(job):
    key, label, base, params, patches, tag = job
    try:
        r = R.replay(start=START, end=END, params={**BASES[base], **params} or None, tag=tag, engine='origin/main',
                     cost_bps=COST, capital=CAP, src_patches=patches or None, daily=D, hourly=HR)
    except BaseException as e:   # patch helpers call sys.exit on a missing anchor; that would hang the pool
        return {'study': key, 'label': label, 'base': base, 'error': repr(e)[:200]}
    eq = r['day_equity']
    pk = dd = 0.0
    for d in sorted(eq):
        pk = max(pk, eq[d]); dd = min(dd, eq[d] / pk - 1)
    e = eq[max(eq)]
    return {'study': key, 'label': label, 'base': base, 'params': params, 'end': e, 'ret': (e / CAP - 1) * 100,
            'max_dd': dd * 100, 'trades': r['trade_count'], 'eq': eq}


if __name__ == '__main__':
    g = R.replay(start='2026-10-01', end='2026-11-05', tag='all_gate', engine='origin/main', cost_bps=COST,
                 capital=CAP, daily=D, hourly=HR)
    ge = g['day_equity'][max(g['day_equity'])]
    assert abs(ge - 13370.47) < 0.01, f'GATE A FAILED {ge}'
    print(f'gate A PASS {ge:,.2f}', flush=True)
    studies = collect()
    plain = one(('plain', 'v2 production', 'v2', {}, [], 'all_plain'))
    print(f"plain v2 Sep1->Nov11 {plain['end']:,.2f}", flush=True)
    gate_jobs = [(k, 'gate', 'v2', {}, p, f'all_g_{k}') for k, (p, _) in studies.items()]
    jobs, n = [], 0
    for k, (p, vs) in studies.items():
        for lbl, params in vs:
            for b in BASES:
                n += 1
                jobs.append((k, lbl, b, dict(params), p, f'all_{n}'))
    print(f'{len(studies)} studies, {len(jobs)} runs', flush=True)
    with Pool(4) as pool:
        gres = pool.map(one, gate_jobs)
        bad = [x for x in gres if 'error' in x or abs(x['end'] - plain['end']) > 0.01]
        for x in bad:
            print('PATCH GATE FAIL', x['study'], x.get('error') or x['end'], flush=True)
        badk = {x['study'] for x in bad}
        res = []
        todo = [j for j in jobs if j[0] not in badk]
        for i, x in enumerate(pool.imap_unordered(one, todo)):
            res.append(x)
            if (i + 1) % 10 == 0:
                print(f'progress {i + 1}/{len(todo)}', flush=True)
    ok = [x for x in res if 'error' not in x]
    for x in res:
        if 'error' in x:
            print('RUN ERROR', x['study'], x['label'], x['error'], flush=True)
    ok.sort(key=lambda x: -x['end'])
    hrb = {x['symbol']: {b['begins_at'][:10]: float(b['close_price']) for b in x['bars'] if b['begins_at'].endswith('17:00:00Z')}
           for x in json.load(open(HR))['data']['results']}
    hold = sum(CAP / 8 * hrb[s][END] / hrb[s][START] for s in CHIPS)
    json.dump({'start': START, 'end': END, 'capital': CAP, 'cost_bps': COST, 'plain_v2': plain['end'], 'hold': hold,
               'gate_failed_studies': sorted(badk), 'n_runs': len(ok), 'results': ok},
              open(os.path.join(ROOT, 'data', 'research', 'all_setups_since_sep1.json'), 'w'), indent=1, default=str)
    print(f'hold {hold:,.2f} ({(hold / CAP - 1) * 100:+.2f}%)')
    for i, x in enumerate(ok[:25]):
        print(f"{i+1:3} {x['end']:10,.2f} {x['ret']:+7.2f}% dd {x['max_dd']:+6.2f}% t{x['trades']:4} [{x['base']}] {x['study']}: {x['label']}")
    print('...')
    for x in ok[-5:]:
        print(f"    {x['end']:10,.2f} {x['ret']:+7.2f}% [{x['base']}] {x['study']}: {x['label']}")
