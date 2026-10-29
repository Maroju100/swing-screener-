"""Live rules, unlevered, on the Margin account's size ($28,700), Jun 30 -> Oct 21 2026 (asked 2026-10-29).
Reuses margin_style_leverage.run at L=1.0 (gate-checked there). Reproduce: python3 scripts/margin_style_live_on_margin_acct.py
"""
import sys; import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_leverage as M
M.MONTH_ENDS=['2026-07-31','2026-08-31','2026-09-30','2026-10-21']
s=M.run(1.0,start='2026-06-30',end='2026-10-21',cap=28700.0,tag='lom')
print(f"Jun30->Oct21  $28,700 -> ${s['end']:,.0f} ({(s['end']/28700-1)*100:+.1f}%)  peak ${s['peak']:,.0f}  worst drop {s['dd']:.1f}%  trades {s['trades']}")
prev=28700
for m,v in s['months']: print(m, f"{v:+,.0f}")
