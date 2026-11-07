#!/usr/bin/env python3
"""v1 vs v2 on stocks OTHER than the 8 semis, last 3 months (asked 2026-11-07).

Window: 2026-08-06 -> 2026-11-05 (Nov 6 bars incomplete at fetch). $15k fresh start, 5 bps/side,
17:00 UTC hourly bar as the check price (= harness convention; noon CDT / 11 AM CST).
Engine: origin/main (v2 live, incl. peak reset). v1 = same engine with MIN_NOTIONAL 25,
kill-switch -15% / 20 days, permanent SMA-50 lock, no peak reset -> exactly the pre-v2 rules.
Baskets FIXED before any run (no semis):
  BIG TECH       AAPL MSFT AMZN META GOOGL TSLA
  NON-TECH 8     JPM XOM LLY WMT CAT NEE HD KO
  SECTOR ETFs    XLF XLV XLE XLP XLU XLI SPY QQQ
  (reference)    OTHER CHIP NAMES AVGO AMAT KLAC MRVL QCOM ASML ARM SMH; CURRENT 8 SEMIS
Plus every non-semi stock traded ALONE (engine's 50% per-symbol cap -> at most half the money in it).
Buy & hold = equal weight, close before window -> last close, no costs.
Gate: v1 on the 8 semis, $80k, 2026-03-13 -> 2026-09-21 on these files must reproduce
production v1 ($124,289.71 / 771 trades).
Data caveat: XLF, XLV (and the semis) daily closes after 10-16 are the last regular hourly close,
not the official close. MEASURED by full engine replay. Reproduce: python3 scripts/margin_style_v1v2_other_stocks.py
"""
import json, os, sys
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_17h_backtest as H
import margin_style_instant_settlement as IS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY = os.path.join(ROOT, 'data', 'margin_live_daily_ext_2025-11-03_2026-11-05_wide.json')
HOURLY = os.path.join(ROOT, 'data', 'margin_live_hourly_ext_2026-03-06_2026-11-05_wide.json')
A, B, CAP, COST = '2026-08-06', '2026-11-05', 15000.0, 5.0
SEMIS = ['AMD', 'MU', 'WDC', 'SNDK', 'TSM', 'INTC', 'LRCX', 'STX']
BASKETS = {'BIG TECH': ['AAPL', 'MSFT', 'AMZN', 'META', 'GOOGL', 'TSLA'],
           'NON-TECH 8': ['JPM', 'XOM', 'LLY', 'WMT', 'CAT', 'NEE', 'HD', 'KO'],
           'SECTOR ETFs': ['XLF', 'XLV', 'XLE', 'XLP', 'XLU', 'XLI', 'SPY', 'QQQ'],
           'OTHER CHIP NAMES (ref)': ['AVGO', 'AMAT', 'KLAC', 'MRVL', 'QCOM', 'ASML', 'ARM', 'SMH'],
           'CURRENT 8 SEMIS (ref)': SEMIS}
SINGLES = BASKETS['BIG TECH'] + BASKETS['NON-TECH 8'] + BASKETS['SECTOR ETFs']
V = {'v1': {'MIN_NOTIONAL': 25.0, 'KILL_SWITCH_DD': -0.15, 'KILL_SWITCH_RESUME_DAYS': 20,
            'KILL_SWITCH_TREND_LOCK': True, 'KILL_SWITCH_RESET_PEAK_ON_RELEASE': False}, 'v2': {}}
PATCHES = [R.patch_sell_epsilon, IS.patch_instant]
CLOSE = {r['symbol']: {b['begins_at'][:10]: float(b['close_price']) for b in r['bars']}
         for r in json.load(open(DAILY))['data']['results']}


def run(univ, ver, a=A, b=B, cap=CAP, tag=''):
    H.UNIVERSE = list(univ)
    r = R.replay(start=a, end=b, params=dict(V[ver]), tag=f'oth_{ver}_{tag}', engine='origin/main', cost_bps=COST,
                 capital=cap, src_patches=PATCHES, daily=DAILY, hourly=HOURLY)
    eq = [v for _, v in sorted(r['day_equity'].items())]
    pk = dd = 0
    for v in eq:
        pk = max(pk, v); dd = min(dd, v / pk - 1)
    return {'ret': (eq[-1] / cap - 1) * 100, 'end': eq[-1], 'dd': dd * 100, 'trades': r['trade_count'],
            'realized': r.get('realized')}


def hold(univ):
    days = sorted(CLOSE[univ[0]])
    d0 = max(d for d in days if d < A)
    return (sum(CLOSE[s][B] / CLOSE[s][d0] for s in univ) / len(univ) - 1) * 100


def job(a):
    kind, name, ver = a
    univ = BASKETS[name] if kind == 'basket' else [name]
    return kind, name, ver, run(univ, ver, tag=f'{kind}_{name.replace(" ", "")[:10]}')


def main():
    g = run(SEMIS, 'v1', '2026-03-13', '2026-09-21', 80000.0, 'gate')
    if abs(g['realized'] - 124289.71) > 0.005 or g['trades'] != 771:
        raise SystemExit(f"GATE FAILED: {g['realized']} / {g['trades']}")
    print('gate PASS: v1 params on these files reproduce production v1', flush=True)
    jobs = [('basket', n, v) for n in BASKETS for v in V] + [('single', s, v) for s in SINGLES for v in V]
    with Pool(4) as p:
        res = p.map(job, jobs)
    out = {'basket': {}, 'single': {}}
    for kind, name, ver, r in res:
        out[kind].setdefault(name, {})[ver] = r
    for kind in out:
        for name, r in out[kind].items():
            r['hold'] = hold(BASKETS[name] if kind == 'basket' else [name])
            print(f"{kind:6} {name:24} v1 {r['v1']['ret']:+6.1f}% (dd {r['v1']['dd']:+5.1f}, {r['v1']['trades']:3}t)"
                  f"  v2 {r['v2']['ret']:+6.1f}% (dd {r['v2']['dd']:+5.1f}, {r['v2']['trades']:3}t)  hold {r['hold']:+6.1f}%", flush=True)
    R.save('v1v2_other_stocks.json', {'window': [A, B], 'capital': CAP, 'cost_bps': COST, **out})


if __name__ == '__main__':
    main()
