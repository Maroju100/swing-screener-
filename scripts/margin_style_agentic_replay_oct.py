#!/usr/bin/env python3
"""Agentic account (912291820) replay from Oct 1, 2026 with $18,056, every rule signal executed
("nothing skipped"), engine origin/main = the live v2 engine incl. peak reset. Chips only (the 8 semis),
5 bps/side, 17:00 UTC hourly check price. Gate: at $15,000 the same engine to Nov 5 must reproduce the
committed Oct1->Nov5 result (13,370.47). Nov 9 close = last regular-session trade (quotes, 20:59Z).
Nov 6 official close used; Nov 9 hourly 17:00 bar used for the check price.
MEASURED by full engine replay. Reproduce: python3 scripts/margin_style_agentic_replay_oct.py
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_17h_backtest as H

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, 'data', 'margin_live_daily_to_2026-11-09.json')
HR = os.path.join(ROOT, 'data', 'margin_live_hourly_to_2026-11-09.json')
CHIPS = ['AMD', 'MU', 'WDC', 'SNDK', 'TSM', 'INTC', 'LRCX', 'STX']
H.UNIVERSE = list(CHIPS)

gate = H.run('2026-10-01', '2026-11-05', 15000.0, 'origin/main', cost_bps=5.0, daily_path=D, hourly_path=HR, tag='gate')
assert abs(gate['total'] - (gate['realized'] + gate['unrealized'])) < 0.01
g_end = gate['day_equity'][max(gate['day_equity'])]
print(f"gate $15k Oct1->Nov5 end equity {g_end:,.2f} (committed 13,370.47)", flush=True)
assert abs(g_end - 13370.47) < 0.01, 'GATE FAILED'

r = H.run('2026-10-01', '2026-11-09', 18056.0, 'origin/main', cost_bps=5.0, daily_path=D, hourly_path=HR, tag='agentic')
out = {'capital': 18056.0, 'start': '2026-10-01', 'end': '2026-11-09', 'cost_bps': 5.0,
       'realized': r['realized'], 'unrealized': r['unrealized'], 'total': r['total'], 'total_pct': r['total_pct'],
       'day_pnl': r['day_pnl'], 'day_equity': r['day_equity'], 'trades': r['trades']}
json.dump(out, open(os.path.join(ROOT, 'data', 'research', 'agentic_replay_oct_2026-11-09.json'), 'w'), indent=1, default=str)
print(json.dumps({k: out[k] for k in ('realized', 'unrealized', 'total', 'total_pct')}, indent=1))
for d in sorted(out['day_equity']):
    tr = [t for t in r['trades'] if str(t.get('date', t.get('day', ''))).startswith(d)]
    print(d, round(out['day_pnl'].get(d, 0), 2), round(out['day_equity'][d], 2), tr[:6])
