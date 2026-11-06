#!/usr/bin/env python3
"""Choppy-market column for the v2 / steadier comparison (asked 2026-11-06).

Choppy windows chosen by a rule fixed before any replay: 21-trading-day windows of the
equal-weight 8-stock basket (daily closes) with the LOWEST efficiency ratio
(|net move| / sum of |daily moves|), non-overlapping, top 3, inside Mar 13 - Nov 4.
Each window is a fresh $15k replay, 5 bps/side, engine origin/main (v2). MEASURED.
Buy & hold = equal-weight basket, close before window to last close, no costs.
Reproduce: python3 scripts/margin_style_choppy.py
"""
import json, os, sys
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_instant_settlement as IS
import margin_style_reentry_rules as RR
import margin_style_top5_combined as T

PATCHES = [R.patch_sell_epsilon, IS.patch_instant, T.patch_kslog, RR.patch_reentry]
CFG = {'v2 live (-8/10)': {},
       '-12%/20d middle': {'KILL_SWITCH_DD': -0.12, 'KILL_SWITCH_RESUME_DAYS': 20, 'RESET_ON_RELEASE': True},
       '-15%/20d steadier': {'KILL_SWITCH_DD': -0.15, 'KILL_SWITCH_RESUME_DAYS': 20, 'RESET_ON_RELEASE': True},
       '$500 no switch': {'KILL_SWITCH_DD': -1.0},
       'v1 old rules': {'MIN_NOTIONAL': 25.0, 'KILL_SWITCH_DD': -0.15, 'KILL_SWITCH_RESUME_DAYS': 20,
                        'KILL_SWITCH_TREND_LOCK': True}}


def windows():
    d = json.load(open(T.DAILY)); d = d.get('data', d); res = d['results']
    bd = {r['symbol']: {b['begins_at'][:10]: float(b['close_price']) for b in (r.get('bars') or r.get('historicals'))} for r in res}
    dates = [x for x in sorted(set.intersection(*(set(v) for v in bd.values()))) if '2026-03-12' <= x <= '2026-11-04']
    ix = [sum(bd[s][x] / bd[s][dates[0]] for s in bd) / len(bd) for x in dates]
    rows = []
    for i in range(len(dates) - 21):
        seg = ix[i:i + 22]
        er = abs(seg[-1] - seg[0]) / sum(abs(seg[k] - seg[k-1]) for k in range(1, 22))
        rows.append((er, dates[i + 1], dates[i + 21], (seg[-1] / seg[0] - 1) * 100))
    rows.sort(); out = []
    for r in rows:
        if all(r[2] < p[1] or r[1] > p[2] for p in out):
            out.append(r)
        if len(out) == 3:
            break
    return out


def job(a):
    name, (a0, b0) = a
    r = R.replay(start=a0, end=b0, params=dict(CFG[name]), tag=f'chop_{abs(hash(name))%10**6}_{a0}', engine='origin/main',
                 cost_bps=T.COST, capital=T.CAP, src_patches=PATCHES, daily=T.DAILY, hourly=T.HOURLY)
    eq = [v for _, v in sorted(r['day_equity'].items())]
    return name, a0, (eq[-1] / T.CAP - 1) * 100


def main():
    W = windows()
    with Pool(4) as p:
        res = p.map(job, [(n, (w[1], w[2])) for n in CFG for w in W])
    out = {'windows': [{'start': w[1], 'end': w[2], 'er': w[0], 'buy_hold': w[3]} for w in W], 'results': {}}
    for n, a0, ret in res:
        out['results'].setdefault(n, {})[a0] = ret
    for w in W:
        print(f"{w[1]}..{w[2]}  ER {w[0]:.3f}  buy&hold {w[3]:+.1f}%  " +
              '  '.join(f"{n}: {out['results'][n][w[1]]:+.1f}%" for n in CFG))
    R.save('choppy.json', out)


if __name__ == '__main__':
    main()
