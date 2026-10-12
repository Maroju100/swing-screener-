#!/usr/bin/env python3
"""Sensitivity of rule D (volatility sizing) to its one setting, VOL_TARGET.

D was pre-registered at 3% (margin_style_sizing_rules.py). This is NOT a search
for a better value: it reports neighbours to check the 3% result is not a
knife-edge. A rule whose result flips between 2.5% and 3.5% would not be usable.

Reproduce:
    python3 scripts/margin_style_vol_sizing_sensitivity.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_sizing_rules as S

OUT = os.path.join(S.I.RESULTS, 'vol_sizing_sensitivity.json')
TARGETS = (0.02, 0.025, 0.03, 0.035, 0.04, 0.05)


def main():
    base = R.replay(tag='vs_base', cost_bps=S.COST)
    rows = []
    for t in TARGETS:
        p = {'VOL_SIZE': True, 'VOL_TARGET': t}
        f = S.hourly(S.FULL[0], S.FULL[1], p, f'vs_f{int(t*1000)}')
        n = {m: S.fine(m, p, f'vs_m{int(t*1000)}{m[:2]}{m[3:]}') for m in S.MARKS}
        h = {k: S.hourly(a, b, p, f'vs_h{int(t*1000)}{k[:4]}') for k, (a, b) in S.HALVES.items()}
        row = {'vol_target': t, 'full_pct': S.pct(f), 'full_dd': S.dd(f), 'sharpe': R.summarize(f)['sharpe'],
               'halves': {k: [S.pct(r), S.dd(r)] for k, r in h.items()},
               'fine': {m: [S.pct(r), S.dd(r)] for m, r in n.items()}}
        rows.append(row)
        print(f"target {t:.1%}: 6mo {row['full_pct']:+6.1f}% dd {row['full_dd']:5.1f}% sharpe {row['sharpe']:.2f}  "
              + '  '.join(f"{k[:4]} {v[0]:+.1f}/{v[1]:.1f}" for k, v in row['halves'].items()) + '  '
              + '  '.join(f"{m} {v[0]:+.1f}/{v[1]:.1f}" for m, v in row['fine'].items()))
    s = R.summarize(base)
    print(f"production:   6mo {S.pct(base):+6.1f}% dd {s['max_dd_pct']:5.1f}% sharpe {s['sharpe']:.2f}")
    json.dump({'generated': '2026-10-12', 'rows': rows,
               'production': {'full_pct': S.pct(base), 'full_dd': s['max_dd_pct'], 'sharpe': s['sharpe']}},
              open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
