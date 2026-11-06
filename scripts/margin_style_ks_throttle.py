#!/usr/bin/env python3
"""Kill-switch as a THROTTLE instead of an off-switch (asked 2026-11-06: "a 10-day stop may miss the
whole bounce -- is there a better way to think of the kill-switch?").

Engine = live origin/main (v2 + peak reset on release). Trigger stays -8% / 10 days. Variants, fixed
before any run:
  LIVE            sell everything, no buys for 10 days (as deployed)
  HOLD-x          do NOT liquidate; existing positions keep their normal exits (stop, 6-day hold,
                  peak/gain); new buys allowed but sized at x of normal, for the 10 days
  SELL+REENTER-x  liquidate as live, but allow new buys at x of normal size during the 10 days
  x in 0.50, 0.25
Windows: rising, falling, crash, full (as all prior studies), choppy-2 (Jul 16-Aug 13), and
Oct 1-Nov 5 (data extended with Nov 5). PASS: beat LIVE in rising, falling, crash, full AND choppy-2,
plus bootstrap CI on full-window daily difference excluding zero. $15k, 5 bps/side. MEASURED.
Reproduce: python3 scripts/margin_style_ks_throttle.py
"""
import json, os, sys, tempfile
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_instant_settlement as IS
import margin_style_top5_combined as T


def _sub(s, a, b):
    assert s.count(a) == 1, a[:80]
    return s.replace(a, b)


def patch_throttle(src):
    src = _sub(src, "MAX_HOLD_DAYS = 6\n", "MAX_HOLD_DAYS = 6\nTHROTTLE_MODE = ''\nTHROTTLE_SIZE = 1.0\n")
    src = _sub(src, "    if kill_switch_active:\n        # Overrides normal PEAK/GAIN",
               "    if kill_switch_active and THROTTLE_MODE != 'hold':\n        # Overrides normal PEAK/GAIN")
    src = _sub(src, "    if not circuit_breaker_triggered and not kill_switch_active:\n",
               "    if not circuit_breaker_triggered and (not kill_switch_active or THROTTLE_MODE):\n")
    src = _sub(src, "        deploy = min(uncapped_deploy, trade_cap_pct * total_equity)\n",
               "        deploy = min(uncapped_deploy, trade_cap_pct * total_equity)\n"
               "        if kill_switch_active and THROTTLE_MODE:\n            deploy *= THROTTLE_SIZE\n")
    return src


PATCHES = [R.patch_sell_epsilon, IS.patch_instant, T.patch_kslog, patch_throttle]
D2 = os.path.join(T.ROOT, 'data', 'margin_live_daily_ext_2025-11-03_2026-11-05.json')
H2 = os.path.join(T.ROOT, 'data', 'margin_live_hourly_ext_2026-03-06_2026-11-05.json')
W = {**T.W, 'choppy2': ('2026-07-16', '2026-08-13'), 'oct1_nov5': ('2026-10-01', '2026-11-05')}
CFG = {'LIVE (sell all, 10d no buys)': {}}
for x in (0.5, 0.25):
    CFG[f'HOLD-{x}'] = {'THROTTLE_MODE': 'hold', 'THROTTLE_SIZE': x}
    CFG[f'SELL+REENTER-{x}'] = {'THROTTLE_MODE': 'liquidate', 'THROTTLE_SIZE': x}


def job(a):
    name, w = a
    s, e = W[w]
    d, h = (D2, H2) if w == 'oct1_nov5' else (T.DAILY, T.HOURLY)
    log = tempfile.mktemp(suffix='.ks')
    r = R.replay(start=s, end=e, params={**CFG[name], 'KS_LOG': log}, tag=f'thr_{abs(hash(name))%10**6}_{w}',
                 engine='origin/main', cost_bps=T.COST, capital=T.CAP, src_patches=PATCHES, daily=d, hourly=h)
    eq = [v for _, v in sorted(r['day_equity'].items())]
    pk = dd = 0
    for v in eq:
        pk = max(pk, v); dd = min(dd, v / pk - 1)
    ks = open(log).read().split('\n')[:-1] if os.path.exists(log) else []
    return name, w, {'ret': (eq[-1] / T.CAP - 1) * 100, 'dd': dd * 100, 'trades': r['trade_count'],
                     'fires': sum(1 for x in ks if x.startswith('fire')),
                     'rets': [eq[i] / eq[i-1] - 1 for i in range(1, len(eq))] if w == 'full' else None}


def main():
    with Pool(4) as p:
        res = p.map(job, [(n, w) for n in CFG for w in W])
    out = {}
    for n, w, r in res:
        out.setdefault(n, {})[w] = r
    ref = json.load(open(os.path.join(T.ROOT, 'data', 'research', 'v2_reset_verify.json')))['windows']
    for w in ('rising', 'falling', 'crash', 'full'):
        assert abs(out['LIVE (sell all, 10d no buys)'][w]['ret'] - ref[w]['ret']) < 1e-6, f'gate {w}'
    print('gate PASS: LIVE reproduces the deployed engine', flush=True)
    base = out['LIVE (sell all, 10d no buys)']
    base_rets = list(base['full']['rets'])
    for n, r in out.items():
        lo, hi, pb = R.block_bootstrap_diff(r['full']['rets'], base_rets)
        wins = {w: r[w]['ret'] > base[w]['ret'] + 1e-9 for w in ('rising', 'falling', 'crash', 'full', 'choppy2')}
        r['boot'] = [round(lo * 100, 3), round(hi * 100, 3), round(pb, 2)]
        r['wins'] = wins; r['passed'] = all(wins.values()) and lo > 0
        for w in W:
            r[w].pop('rets', None)
        print(f"{n:30}" + ''.join(f" {w} {r[w]['ret']:+6.1f}" for w in W) + f" | fullDD {r['full']['dd']:+5.1f}"
              f" crashDD {r['crash']['dd']:+5.1f} | wins {sum(wins.values())}/5 P={pb:.2f} pass={r['passed']}", flush=True)
    R.save('ks_throttle.json', out)


if __name__ == '__main__':
    main()
