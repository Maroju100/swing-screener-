"""Core vs swing vs day-trading mix (asked 2026-10-29). Pure arithmetic on already-measured curves
in data/research/daytrade_setups_6m.json (each a real replay, $15k, Apr 21 -> Oct 21 2026, 5 bps/side):
  core  = 'Buy & hold the 8 stocks' (PROXY: the 8 trading names, not a curated quality core)
  swing = 'Margin-Style Live (production)'
  day   = best day-trading setup ('4 Gap-and-go'), also reported alone with the others.
Each bucket is run separately with no rebalancing (money stays in its bucket), so the blend is the
weighted sum of the three equity curves. Not a new backtest: no rule is changed.
Reproduce: python3 scripts/allocation_mix.py
"""
import json, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = json.load(open(os.path.join(ROOT, 'data', 'research', 'daytrade_setups_6m.json')))['results']
CAP = 15000.0
print('Each strategy alone ($15k, Apr 21 -> Oct 21):')
for k, v in R.items():
    print(f"  {k:38} {v['return_pct']:+7.1f}%   worst drop {(v['max_dd_pct'] or 0):+6.1f}%   2nd half " + (f"{v['second_half_pct']:+6.1f}%" if v.get('second_half_pct') is not None else 'n/a'))
C = {n: R[k]['curve'] for n, k in [('core', 'Buy & hold the 8 stocks'), ('swing', 'Margin-Style Live (production)'),
                                   ('day', '4 Gap-and-go')]}
days = sorted(set.intersection(*(set(c) for c in C.values())))
rows = []
for c in range(0, 11):
    for s in range(0, 11 - c):
        d = 10 - c - s
        w = {'core': c / 10, 'swing': s / 10, 'day': d / 10}
        eq = [sum(w[n] * C[n][t] / CAP for n in C) for t in days]
        pk, dd = 0, 0
        for v in eq:
            pk = max(pk, v); dd = min(dd, v / pk - 1)
        oct_ = [v for t, v in zip(days, eq) if t >= '2026-09-30']
        rows.append((c * 10, s * 10, d * 10, (eq[-1] - 1) * 100, dd * 100, (oct_[-1] / oct_[0] - 1) * 100))
print('\ncore/swing/day   return   worst drop   Oct 1-21   return per 1% of drawdown')
for r in sorted(rows, key=lambda r: -r[3] / max(0.5, -r[4]))[:12] + [r for r in rows if (r[0], r[1], r[2]) in
                                                                     [(100, 0, 0), (0, 100, 0), (0, 0, 100), (50, 50, 0), (40, 40, 20), (34, 33, 33)]]:
    print(f"  {r[0]:3}/{r[1]:3}/{r[2]:3}    {r[3]:+6.1f}%   {r[4]:+6.1f}%    {r[5]:+6.1f}%    {r[3] / max(0.5, -r[4]):5.2f}")
