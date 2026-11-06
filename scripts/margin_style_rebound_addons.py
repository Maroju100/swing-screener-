#!/usr/bin/env python3
"""Add-ons so the live v2 setup does not miss rebounds (asked 2026-11-06). Settings FIXED before any run:
  E1  REBOUND buy: >=15% below 60-day high AND yesterday closed up >=2%  -> normal tranche sizing
  E2  REBOUND buy: >=15% below 60-day high AND live price >=1% above yesterday's close
  X1  MAX_HOLD only fires on a non-up day (live <= prior close); otherwise waits a day. Stop untouched.
  combos E1+X1, E2+X1.
Engine = live origin/main (v2 + peak reset). Windows: rising, falling, crash, full, choppy2, oct1_nov5.
PASS: beat LIVE in rising, falling, crash, full AND choppy2, plus bootstrap CI excluding zero.
$15k, 5 bps/side. MEASURED by full engine replay. Reproduce: python3 scripts/margin_style_rebound_addons.py
"""
import json, os, sys, tempfile
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_instant_settlement as IS
import margin_style_top5_combined as T


def _sub(s, a, b):
    assert s.count(a) == 1, a[:90]
    return s.replace(a, b)


def patch_rebound(src):
    src = _sub(src, "MAX_HOLD_DAYS = 6\n", "MAX_HOLD_DAYS = 6\nREBOUND_MODE = ''\nMAXHOLD_UPDAY_DEFER = False\n")
    src = _sub(src,
               "                reason = 'NORMAL_DIP'\n            else:\n                continue\n",
               "                reason = 'NORMAL_DIP'\n"
               "            elif REBOUND_MODE == 'E1' and drawdown <= -0.15 and day_return >= 0.02:\n"
               "                reason = 'REBOUND'\n"
               "            elif REBOUND_MODE == 'E2' and drawdown <= -0.15 and quotes[sym] >= yesterday_close * 1.01:\n"
               "                reason = 'REBOUND'\n"
               "            else:\n                continue\n")
    src = _sub(src, "        if 'opened' in pos and business_days_elapsed(pos['opened'], today) >= MAX_HOLD_DAYS:\n",
               "        if 'opened' in pos and business_days_elapsed(pos['opened'], today) >= MAX_HOLD_DAYS \\\n"
               "                and not (MAXHOLD_UPDAY_DEFER and live_price > prev_close):\n")
    return src


PATCHES = [R.patch_sell_epsilon, IS.patch_instant, T.patch_kslog, patch_rebound]
D2 = os.path.join(T.ROOT, 'data', 'margin_live_daily_ext_2025-11-03_2026-11-05.json')
H2 = os.path.join(T.ROOT, 'data', 'margin_live_hourly_ext_2026-03-06_2026-11-05.json')
W = {**T.W, 'choppy2': ('2026-07-16', '2026-08-13'), 'oct1_nov5': ('2026-10-01', '2026-11-05')}
CFG = {'LIVE v2': {}, 'E1 rebound (yday +2%)': {'REBOUND_MODE': 'E1'}, 'E2 rebound (live +1%)': {'REBOUND_MODE': 'E2'},
       'X1 no hold-limit sell on up day': {'MAXHOLD_UPDAY_DEFER': True},
       'E1 + X1': {'REBOUND_MODE': 'E1', 'MAXHOLD_UPDAY_DEFER': True},
       'E2 + X1': {'REBOUND_MODE': 'E2', 'MAXHOLD_UPDAY_DEFER': True}}


def job(a):
    name, w = a
    s, e = W[w]
    d, h = (D2, H2) if w == 'oct1_nov5' else (T.DAILY, T.HOURLY)
    log = tempfile.mktemp(suffix='.ks')
    r = R.replay(start=s, end=e, params={**CFG[name], 'KS_LOG': log}, tag=f'rb_{abs(hash(name))%10**6}_{w}',
                 engine='origin/main', cost_bps=T.COST, capital=T.CAP, src_patches=PATCHES, daily=d, hourly=h)
    eq = [v for _, v in sorted(r['day_equity'].items())]
    pk = dd = 0
    for v in eq:
        pk = max(pk, v); dd = min(dd, v / pk - 1)
    return name, w, {'ret': (eq[-1] / T.CAP - 1) * 100, 'dd': dd * 100, 'trades': r['trade_count'],
                     'rets': [eq[i] / eq[i-1] - 1 for i in range(1, len(eq))] if w == 'full' else None}


def main():
    with Pool(4) as p:
        res = p.map(job, [(n, w) for n in CFG for w in W])
    out = {}
    for n, w, r in res:
        out.setdefault(n, {})[w] = r
    ref = json.load(open(os.path.join(T.ROOT, 'data', 'research', 'v2_reset_verify.json')))['windows']
    for w in ('rising', 'falling', 'crash', 'full'):
        assert abs(out['LIVE v2'][w]['ret'] - ref[w]['ret']) < 1e-6, f'gate {w}'
    print('gate PASS: LIVE reproduces the deployed engine', flush=True)
    base_rets = list(out['LIVE v2']['full']['rets'])
    base = out['LIVE v2']
    for n, r in out.items():
        lo, hi, pb = R.block_bootstrap_diff(r['full']['rets'], base_rets)
        wins = {w: r[w]['ret'] > base[w]['ret'] + 1e-9 for w in ('rising', 'falling', 'crash', 'full', 'choppy2')}
        r['boot'] = [round(lo * 100, 3), round(hi * 100, 3), round(pb, 2)]
        r['wins'] = wins; r['passed'] = all(wins.values()) and lo > 0
    for n, r in out.items():
        for w in W:
            r[w].pop('rets', None)
        print(f"{n:32}" + ''.join(f" {w} {r[w]['ret']:+6.1f}" for w in W) + f" | fullDD {r['full']['dd']:+5.1f}"
              f" trades {r['full']['trades']} | wins {sum(r['wins'].values())}/5 P={r['boot'][2]} pass={r['passed']}", flush=True)
    R.save('rebound_addons.json', out)


if __name__ == '__main__':
    main()
