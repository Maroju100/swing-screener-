#!/usr/bin/env python3
"""Verify the DEPLOYED Margin-Style Live v2 ('1+3') engine reproduces the research result.

v2 = production rules + MIN_NOTIONAL 500 (#1) + kill-switch -8% / 10-day wait /
no permanent SMA-50 lock-out (#3). Deployed to main 2026-11-05 at the user's request.

This replays the ENGINE REVISION ITSELF with NO rule params, i.e. the rules are
whatever is written in the engine file, and compares every window against the
'PAIR 1+3' row of data/research/top5_combined.json (which got the same rules by
patching v1). Exact match => the deployed file is exactly the measured rule set.

  python3 scripts/margin_style_v2_verify.py [ENGINE_REV]     (default origin/main; deployed as 979412d)

MEASURED by full engine replay; $15k, 5 bps/side. IN-SAMPLE: the rule set was
chosen after seeing this data, so this proves correct deployment, not an edge.
"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_instant_settlement as IS
import margin_style_top5_combined as T

rev = sys.argv[1] if len(sys.argv) > 1 else 'origin/main'
PATCHES = [R.patch_sell_epsilon, IS.patch_instant, T.patch_kslog]   # all inert unless a param turns them on
ref = json.load(open(os.path.join(T.ROOT, 'data', 'research', 'top5_combined.json')))['PAIR 1+3']
ok, out = True, {}
for w, (a, b) in T.W.items():
    log = tempfile.mktemp(suffix='.ks')
    r = R.replay(start=a, end=b, params={'KS_LOG': log}, tag=f'v2_{w}', engine=rev, cost_bps=T.COST,
                 capital=T.CAP, src_patches=PATCHES, daily=T.DAILY, hourly=T.HOURLY)
    eq = [v for _, v in sorted(r['day_equity'].items())]
    ks = open(log).read().split('\n')[:-1] if os.path.exists(log) else []
    match = abs(eq[-1] - ref[w]['end']) < 0.01 and r['trade_count'] == ref[w]['trades'] and ks == ref[w]['ks']
    ok &= match
    out[w] = {'end': eq[-1], 'ret': (eq[-1] / T.CAP - 1) * 100, 'trades': r['trade_count'], 'ks': ks, 'match': match}
    print(f"{w:8} ${eq[-1]:>10,.2f} ({out[w]['ret']:+6.1f}%) {r['trade_count']:4} trades  ks={ks}  "
          f"{'MATCH' if match else 'MISMATCH vs $%.2f/%d' % (ref[w]['end'], ref[w]['trades'])}", flush=True)
R.save('v2_verify.json', {'engine': rev, 'all_match': ok, 'windows': out})
print('ALL WINDOWS MATCH' if ok else 'MISMATCH'); sys.exit(0 if ok else 1)
