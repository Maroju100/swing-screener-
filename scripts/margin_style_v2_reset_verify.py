#!/usr/bin/env python3
"""Verify the live engine with KILL_SWITCH_RESET_PEAK_ON_RELEASE=True (deployed 2026-11-06)
reproduces the research variant 'RS (10d + peak reset)' of data/research/v2_pause.json in every
window, with no rule params. Also replays Oct 1 -> Nov 5 to show the post-crash path.
  python3 scripts/margin_style_v2_reset_verify.py [ENGINE_REV]   (default origin/main)
"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_instant_settlement as IS
import margin_style_top5_combined as T

rev = sys.argv[1] if len(sys.argv) > 1 else 'origin/main'
PATCHES = [R.patch_sell_epsilon, IS.patch_instant, T.patch_kslog]
ref = json.load(open(os.path.join(T.ROOT, 'data', 'research', 'v2_pause.json')))['RS (10d + peak reset)']
ok, out = True, {}
for w, (a, b) in T.W.items():
    log = tempfile.mktemp(suffix='.ks')
    r = R.replay(start=a, end=b, params={'KS_LOG': log}, tag=f'rsv_{w}', engine=rev, cost_bps=T.COST, capital=T.CAP,
                 src_patches=PATCHES, daily=T.DAILY, hourly=T.HOURLY)
    eq = [v for _, v in sorted(r['day_equity'].items())]
    ret = (eq[-1] / T.CAP - 1) * 100
    m = abs(ret - ref[w]['ret']) < 1e-6 and r['trade_count'] == ref[w]['trades']
    ok &= m
    ks = open(log).read().split('\n')[:-1] if os.path.exists(log) else []
    out[w] = {'ret': ret, 'trades': r['trade_count'], 'ks': ks, 'match': m}
    print(f"{w:8} {ret:+7.2f}% {r['trade_count']:4} trades ks={ks} {'MATCH' if m else 'MISMATCH vs %+.2f/%d' % (ref[w]['ret'], ref[w]['trades'])}", flush=True)
D = os.path.join(T.ROOT, 'data', 'margin_live_daily_ext_2025-11-03_2026-11-05.json')
H = os.path.join(T.ROOT, 'data', 'margin_live_hourly_ext_2026-03-06_2026-11-05.json')
log = tempfile.mktemp(suffix='.ks')
r = R.replay(start='2026-10-01', end='2026-11-05', params={'KS_LOG': log}, tag='rsv_octnov', engine=rev, cost_bps=T.COST,
             capital=T.CAP, src_patches=PATCHES, daily=D, hourly=H)
de = sorted(r['day_equity'].items())
out['octnov'] = {'end': de[-1][1], 'trades': r['trade_count'], 'ks': open(log).read().split('\n')[:-1] if os.path.exists(log) else []}
print('Oct1-Nov5', round(de[-1][1], 2), out['octnov'])
R.save('v2_reset_verify.json', {'engine': rev, 'all_match': ok, 'windows': out})
print('ALL WINDOWS MATCH' if ok else 'MISMATCH'); sys.exit(0 if ok else 1)
