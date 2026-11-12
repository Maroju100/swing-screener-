#!/usr/bin/env python3
"""Last four months, one continuous run: v1 rules vs v2 live rules vs equal-weight hold of the 8 chips.
Jul 13 -> Nov 11 2026, $15,000, 5 bps/side, engine origin/main (v1 = parameter overrides), official-close data,
17:00 UTC hourly bar as the check price; hold bought at the Jul 13 17:00 bar. Monthly P&L = change in equity
between month-end marks of the same continuous run. Gate: v2 Oct1->Nov5 = 13,370.47.
MEASURED. Reproduce: python3 scripts/margin_style_4mo_v1_v2_hold.py
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_17h_backtest as H
import margin_style_sep_v1_vs_v2 as S   # runs its own gates on import (v2 Oct1->Nov5, v2 Sep)

START, END, CAP = '2026-07-13', '2026-11-11', 15000.0
r = {k: S.rep(START, END, p, f'm4_{k}') for k, p in (('v1', S.V1), ('v2', S.V2))}
days = sorted(r['v2']['day_equity'])
hold = {d: sum(CAP / 8 * S.hr[s][d] / S.hr[s][START] for s in S.CHIPS) for d in days if all(d in S.hr[s] for s in S.CHIPS)}
series = {'v1': r['v1']['day_equity'], 'v2': r['v2']['day_equity'], 'hold': hold}
months = ['2026-07', '2026-08', '2026-09', '2026-10', '2026-11']
out = {'start': START, 'end': END, 'capital': CAP, 'monthly': {}, 'total': {}}
for k, eq in series.items():
    prev = CAP; rows = {}
    for m in months:
        ds = [d for d in sorted(eq) if d.startswith(m)]
        e = eq[ds[-1]]; rows[m] = {'pnl': e - prev, 'pct': (e / prev - 1) * 100, 'end': e}; prev = e
    pk = dd = 0.0
    for d in sorted(eq):
        pk = max(pk, eq[d]); dd = min(dd, eq[d] / pk - 1)
    out['monthly'][k] = rows
    out['total'][k] = {'end': prev, 'pnl': prev - CAP, 'pct': (prev / CAP - 1) * 100, 'max_dd': dd * 100,
                       'trades': r[k]['trade_count'] if k in r else None}
json.dump(out, open(os.path.join(S.ROOT, 'data', 'research', '4mo_v1_v2_hold.json'), 'w'), indent=1)
for m in months:
    print(m, '  '.join(f"{k} {out['monthly'][k][m]['pnl']:+9.2f} ({out['monthly'][k][m]['pct']:+6.2f}%)" for k in series))
for k in series:
    t = out['total'][k]; print(k, f"end {t['end']:,.2f} pnl {t['pnl']:+,.2f} ({t['pct']:+.2f}%) maxDD {t['max_dd']:+.2f}% trades {t['trades']}")
