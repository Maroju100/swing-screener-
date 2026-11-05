"""Live rules on the Margin account's size, Oct 1 -> Nov 3 2026, unlevered and at 1.8x (asked 2026-11-05).
Reuses margin_style_leverage.run (gate-checked there) on data extended through 2026-11-03
(official daily closes; hourly bars from get_equity_historicals). $28,700 start (Margin account
value on 10-28 -- its Oct 1 value is not available from the tools), 5 bps/side,
margin interest 6%/yr ESTIMATED. The replay prices at the 17:00 UTC hourly bar every day,
which is 12:00 CDT in October but 11:00 CST on Nov 2-3 (DST ended Nov 1).
Reproduce: python3 scripts/margin_style_oct_nov.py [--cap 29675]   (29,675 = owner-reported Oct 1 value)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_leverage as M
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M.DAILY = os.path.join(ROOT, 'data', 'margin_live_daily_ext_2025-11-03_2026-11-03.json')
M.HOURLY = os.path.join(ROOT, 'data', 'margin_live_hourly_ext_2026-03-06_2026-11-03.json')
M.MONTH_ENDS = ['2026-10-31', '2026-11-03']
CAP = float(sys.argv[sys.argv.index('--cap') + 1]) if '--cap' in sys.argv else 28700.0
for L in (1.0, 1.8):
    s = M.run(L, start='2026-10-01', end='2026-11-03', cap=CAP, tag="octnov")
    d, ratio, _ = s['min_ratio']
    print(f"L={L}: ${CAP:,.0f} -> ${s['end']:,.0f} ({(s['end'] / CAP - 1) * 100:+.1f}%)  peak ${s['peak']:,.0f}  worst drop {s['dd']:.1f}%"
          f"  interest ${s['interest']:,.0f}  max debt ${s['max_debt']:,.0f}  trades {s['trades']}  lowest equity/positions {ratio:.0%} on {d}"
          f"  | Oct {s['months'][0][1]:+,.0f}  Nov 2-3 {s['months'][1][1]:+,.0f}")
