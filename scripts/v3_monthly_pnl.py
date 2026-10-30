"""Monthly P&L of the v3 day-trading engine (asked 2026-10-30). Same harness and gates as
scripts/v3_weekly_pnl.py (real engine, 1-minute bars, MU/SNDK/WDC, 5 bps/side), $15,000 start,
one continuous replay; month-end equity is a truncated replay (the engine is flat every night).
NOT AVAILABLE: anything before 2026-08-10 -- no real 1-minute bars from the source (Evidence
Rule 6), so July is not reported. August is a partial month (from the 10th).
Reproduce: python3 scripts/v3_monthly_pnl.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v3_weekly_pnl as W
import v3_replay as VR

CAP = 15000.0
bars, days = W.load()
for name, (geq, gn) in [('baseline', (5018.91, 767)), ('tightened', (4900.96, 635))]:
    p = VR.PARAMS[name]
    W.set_capital(5000.0)
    g = VR.replay(f'mo_gate_{name}', p, [d for d in days if d <= '2026-09-21'], bars, cost_bps=W.COST)
    if abs(g['equity'] - geq) > 0.005 or g['trades'] != gn:
        raise SystemExit(f'GATE FAILED {name}: {g["equity"]} / {g["trades"]}')
    W.set_capital(CAP)
    prev, prev_n = CAP, 0
    print(f"\nv3 {name} (gate PASS), ${CAP:,.0f}")
    for m in sorted({d[:7] for d in days}):
        last = max(d for d in days if d[:7] == m)
        r = VR.replay(f'mo_{name}_{m}', p, [d for d in days if d <= last], bars, cost_bps=W.COST)
        n = sum(1 for d in days if d[:7] == m)
        print(f"  {m} ({n:2} days to {last})  P&L {r['equity'] - prev:+8,.0f}  ({(r['equity'] / prev - 1) * 100:+5.2f}%)"
              f"  equity ${r['equity']:,.0f}  trades {r['trades'] - prev_n}")
        prev, prev_n = r['equity'], r['trades']
    print(f"  TOTAL {prev - CAP:+,.0f} ({(prev / CAP - 1) * 100:+.2f}%)")
