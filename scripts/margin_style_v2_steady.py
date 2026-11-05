#!/usr/bin/env python3
"""'Steadier' alternative to v2: $500 minimum + a less twitchy kill-switch (asked 2026-11-05).

Engine = deployed v2 (origin/main). MIN_NOTIONAL stays 500. Grid, fixed before any run:
  KILL_SWITCH_DD in -8, -10, -12, -15 %  x  pause 5, 10, 15, 20 trading days, no SMA-50 lock,
  equity_peak reset at release (stops the re-fire loop).  Plus references:
  v2 live (-8/10, no reset), '$500 only' (kill-switch off), '$500 + v1 switch' (-15/20 + SMA-50 lock).
ROBUSTNESS (the point of 'steadier'): for each grid cell, the worst full return and worst crash
result across the cell and its grid neighbours. A cell whose neighbours collapse is luck.
$15k, 5 bps/side, MEASURED by full engine replay. In-sample; same data that chose v2.
Reproduce: python3 scripts/margin_style_v2_steady.py
"""
import json, os, sys, tempfile
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_instant_settlement as IS
import margin_style_reentry_rules as RR
import margin_style_top5_combined as T

PATCHES = [R.patch_sell_epsilon, IS.patch_instant, T.patch_kslog, RR.patch_reentry]
W = dict(T.W)
DDS, PAUSES = (-0.08, -0.10, -0.12, -0.15), (5, 10, 15, 20)
CONFIGS = {f'K{int(-d*100)}/{p}': {'KILL_SWITCH_DD': d, 'KILL_SWITCH_RESUME_DAYS': p, 'RESET_ON_RELEASE': True}
           for d in DDS for p in PAUSES}
CONFIGS.update({'v2 live (-8/10)': {}, '$500 only (no switch)': {'KILL_SWITCH_DD': -1.0},
                '$500 + v1 switch (-15/20, SMA lock)': {'KILL_SWITCH_DD': -0.15, 'KILL_SWITCH_RESUME_DAYS': 20,
                                                        'KILL_SWITCH_TREND_LOCK': True}})


def job(arg):
    name, w = arg
    a, b = W[w]
    log = tempfile.mktemp(suffix='.ks')
    r = R.replay(start=a, end=b, params={**CONFIGS[name], 'KS_LOG': log}, tag=f'v2s_{abs(hash(name))%10**6}_{w}',
                 engine='origin/main', cost_bps=T.COST, capital=T.CAP, src_patches=PATCHES, daily=T.DAILY, hourly=T.HOURLY)
    eq = [v for _, v in sorted(r['day_equity'].items())]
    pk = dd = 0
    for v in eq:
        pk = max(pk, v); dd = min(dd, v / pk - 1)
    ks = open(log).read().split('\n')[:-1] if os.path.exists(log) else []
    rets = [eq[i] / eq[i-1] - 1 for i in range(1, len(eq))]
    return name, w, {'ret': (eq[-1] / T.CAP - 1) * 100, 'dd': dd * 100, 'trades': r['trade_count'],
                     'fires': sum(1 for x in ks if x.startswith('fire')), 'rets': rets if w == 'full' else None}


def main():
    with Pool(4) as p:
        res = p.map(job, [(n, w) for n in CONFIGS for w in W])
    out = {}
    for n, w, r in res:
        out.setdefault(n, {})[w] = r
    assert abs(out['v2 live (-8/10)']['full']['ret'] - 156.4350191732644) < 1e-6, 'v2 reference did not reproduce'
    base = out['v2 live (-8/10)']['full']['rets']
    for d in DDS:
        for p in PAUSES:
            n = f'K{int(-d*100)}/{p}'
            i, j = DDS.index(d), PAUSES.index(p)
            nb = [f'K{int(-DDS[a]*100)}/{PAUSES[b]}' for a, b in ((i, j), (i-1, j), (i+1, j), (i, j-1), (i, j+1))
                  if 0 <= a < len(DDS) and 0 <= b < len(PAUSES)]
            out[n]['neigh_worst_full'] = min(out[x]['full']['ret'] for x in nb)
            out[n]['neigh_worst_crash'] = min(out[x]['crash']['ret'] for x in nb)
    for n, r in out.items():
        lo, hi, pb = R.block_bootstrap_diff(r['full']['rets'], base)
        r['boot_vs_v2'] = [round(lo * 100, 3), round(hi * 100, 3), round(pb, 2)]
        r['full'].pop('rets'); [r[w].pop('rets', None) for w in W]
        print(f"{n:36}" + ''.join(f" {w[:4]} {r[w]['ret']:+6.1f}" for w in W) + f" | DD {r['full']['dd']:+5.1f}"
              f" fires {r['full']['fires']:2} | nbr-worst full {r.get('neigh_worst_full', float('nan')):+6.1f}"
              f" crash {r.get('neigh_worst_crash', float('nan')):+6.1f} | vs v2 P={r['boot_vs_v2'][2]}", flush=True)
    R.save('v2_steady.json', out)


if __name__ == '__main__':
    main()
