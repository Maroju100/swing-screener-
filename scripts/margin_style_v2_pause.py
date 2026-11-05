#!/usr/bin/env python3
"""v2 '1+3': is the 10-day kill-switch pause the right length, or should re-entry follow a bounce? (2026-11-05)

Engine = deployed v2 (origin/main), no rule params except the ones varied below.
Variants, fixed before any run:
  PAUSE_n   cool-off of n trading days, n in 2, 3, 5, 7, 10 (live), 15, 20
  R1/R2/R3  early release on a basket bounce (2 up closes / above 5-day avg / +5% off low),
            10-day backstop, equity_peak reset at release (see margin_style_reentry_rules.py)
  RS        10-day pause + equity_peak reset at release (fixes the re-fire loop)
PASS: beat live v2 (PAUSE_10) in rising, falling, crash AND full, plus a bootstrap CI on the
full-window daily difference excluding zero. $15k, 5 bps/side. MEASURED by full engine replay.
Reproduce: python3 scripts/margin_style_v2_pause.py
"""
import json, os, sys, tempfile
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_instant_settlement as IS
import margin_style_reentry_rules as RR
import margin_style_top5_combined as T

PATCHES = [R.patch_sell_epsilon, IS.patch_instant, T.patch_kslog, RR.patch_reentry]
W = {k: v for k, v in T.W.items()}
CONFIGS = {f'PAUSE_{n}': {'KILL_SWITCH_RESUME_DAYS': n} for n in (2, 3, 5, 7, 10, 15, 20)}
CONFIGS.update({'RS (10d + peak reset)': {'RESET_ON_RELEASE': True},
                'R1 bounce: 2 up days': {'REENTRY_MODE': 'R1', 'RESET_ON_RELEASE': True},
                'R2 bounce: above 5d avg': {'REENTRY_MODE': 'R2', 'RESET_ON_RELEASE': True},
                'R3 bounce: +5% off low': {'REENTRY_MODE': 'R3', 'RESET_ON_RELEASE': True}})


def job(arg):
    name, w = arg
    a, b = W[w]
    log = tempfile.mktemp(suffix='.ks')
    r = R.replay(start=a, end=b, params={**CONFIGS[name], 'KS_LOG': log}, tag=f'v2p_{abs(hash(name))%10**6}_{w}',
                 engine='origin/main', cost_bps=T.COST, capital=T.CAP, src_patches=PATCHES, daily=T.DAILY, hourly=T.HOURLY)
    de = sorted(r['day_equity'].items()); eq = [v for _, v in de]
    pk = dd = 0
    for v in eq:
        pk = max(pk, v); dd = min(dd, v / pk - 1)
    ks = open(log).read().split('\n')[:-1] if os.path.exists(log) else []
    return name, w, {'ret': (eq[-1] / T.CAP - 1) * 100, 'dd': dd * 100, 'trades': r['trade_count'], 'ks': ks, 'eq': de}


def main():
    with Pool(4) as p:
        res = p.map(job, [(n, w) for n in CONFIGS for w in W])
    out = {}
    for n, w, r in res:
        out.setdefault(n, {})[w] = r
    ref = json.load(open(os.path.join(T.ROOT, 'data', 'research', 'top5_combined.json')))['PAIR 1+3']['full']
    assert abs(out['PAUSE_10']['full']['eq'][-1][1] - ref['end']) < 0.01, 'PAUSE_10 does not reproduce live v2'
    base = out['PAUSE_10']
    for n, r in out.items():
        e0 = [v for _, v in base['full']['eq']]; e1 = [v for _, v in r['full']['eq']]
        lo, hi, pb = R.block_bootstrap_diff([e1[i] / e1[i-1] - 1 for i in range(1, len(e1))],
                                            [e0[i] / e0[i-1] - 1 for i in range(1, len(e0))])
        r['boot'] = [round(lo * 100, 3), round(hi * 100, 3), round(pb, 2)]
        r['passed'] = all(r.get('wins', {}).values()) if False else None
        r['wins'] = {w: r[w]['ret'] > base[w]['ret'] + 1e-9 for w in ('rising', 'falling', 'crash', 'full')}
        r['passed'] = all(r['wins'].values()) and lo > 0
        for w in W:
            if w != 'full':
                r[w].pop('eq', None)
        print(f"{n:24}" + ''.join(f" {w} {r[w]['ret']:+6.1f}%" for w in W) + f"  fullDD {r['full']['dd']:+5.1f}"
              f"  trades {r['full']['trades']}  fires {sum(1 for x in r['full']['ks'] if x.startswith('fire'))}"
              f"  wins {sum(r['wins'].values())}/4  boot {r['boot']}", flush=True)
    for r in out.values():
        r['full'].pop('eq', None)
    R.save('v2_pause.json', out)


if __name__ == '__main__':
    main()
