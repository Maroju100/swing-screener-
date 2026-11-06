#!/usr/bin/env python3
"""v2 '1+3' vs original v1 over Oct 1 -> Nov 5 2026, $15k fresh start (asked 2026-11-06).

Engine origin/main (v2). v1 = same engine with MIN_NOTIONAL 25, kill-switch -15% / 20 days,
permanent SMA-50 lock (exactly the pre-v2 rules). 5 bps/side. Nov 2-5 priced at the 17:00 UTC
bar (= 11:00 CST, DST). Data: *_ext_..._2026-11-05.json (Nov 5 bars appended 2026-11-06).
Gate: Oct 1 -> Nov 4 on the new files must reproduce the committed crash-window results.
MEASURED by full engine replay. Reproduce: python3 scripts/margin_style_octnov_v1v2.py
"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_instant_settlement as IS
import margin_style_reentry_rules as RR
import margin_style_top5_combined as T

D = os.path.join(T.ROOT, 'data', 'margin_live_daily_ext_2025-11-03_2026-11-05.json')
H = os.path.join(T.ROOT, 'data', 'margin_live_hourly_ext_2026-03-06_2026-11-05.json')
PATCHES = [R.patch_sell_epsilon, IS.patch_instant, T.patch_kslog, RR.patch_reentry]
CFG = {'v2': {}, 'v1': {'MIN_NOTIONAL': 25.0, 'KILL_SWITCH_DD': -0.15, 'KILL_SWITCH_RESUME_DAYS': 20,
                        'KILL_SWITCH_TREND_LOCK': True}}


def run(name, end):
    log = tempfile.mktemp(suffix='.ks')
    r = R.replay(start='2026-10-01', end=end, params={**CFG[name], 'KS_LOG': log}, tag=f'on_{name}_{end}', engine='origin/main',
                 cost_bps=T.COST, capital=T.CAP, src_patches=PATCHES, daily=D, hourly=H)
    de = sorted(r['day_equity'].items())
    ks = open(log).read().split('\n')[:-1] if os.path.exists(log) else []
    return de, r['trade_count'], ks, r


ref = json.load(open(os.path.join(T.ROOT, 'data', 'research', 'top5_combined.json')))
for n, k in (('v2', 'PAIR 1+3'), ('v1', 'CURRENT RULES')):
    de, *_ = run(n, '2026-11-04')
    assert abs(de[-1][1] - ref[k]['crash']['end']) < 0.01, f'{n} gate failed'
print('gate PASS: Oct 1-Nov 4 reproduces committed results on the extended files')
out = {}
for n in CFG:
    de, tc, ks, r = run(n, '2026-11-05')
    pk = dd = 0
    for _, v in de:
        pk = max(pk, v); dd = min(dd, v / pk - 1)
    out[n] = {'equity': de, 'trades': tc, 'ks': ks, 'end': de[-1][1], 'ret': (de[-1][1] / T.CAP - 1) * 100, 'dd': dd * 100}
    print(f"{n}: ${de[-1][1]:,.2f} ({out[n]['ret']:+.1f}%) worst drop {dd*100:+.1f}%  trades {tc}  ks {ks}")
for d0 in ('2026-10-01',):
    pass
R.save('octnov_v1v2.json', out)
