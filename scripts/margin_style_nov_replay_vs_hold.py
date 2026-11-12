#!/usr/bin/env python3
"""Nov replay: live v2 engine from 2026-11-02 with $15,000 vs buying and holding the same 8 stocks.
Engine origin/main (v2, incl. peak reset). 5 bps/side. Check price = 17:00 UTC hourly bar (replay convention).
Hold: equal weight, $15,000, bought at the Nov 2 17:00 bar close and marked at the Nov 11 17:00 bar close.
Daily data: official closes through Nov 11 (Nov 9-11 official closes from quote tool; Nov 2-8 from the saved file).
Gate: Oct 1 -> Nov 5 at $15,000 must still reproduce 13,370.47 (the committed result).
MEASURED by full engine replay. Reproduce: python3 scripts/margin_style_nov_replay_vs_hold.py
"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_17h_backtest as H

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, 'data', 'margin_live_daily_to_2026-11-11.json')
HR = os.path.join(ROOT, 'data', 'margin_live_hourly_to_2026-11-11.json')
CHIPS = ['AMD', 'MU', 'WDC', 'SNDK', 'TSM', 'INTC', 'LRCX', 'STX']
H.UNIVERSE = list(CHIPS)

gate = H.run('2026-10-01', '2026-11-05', 15000.0, 'origin/main', cost_bps=5.0, daily_path=D, hourly_path=HR, tag='gate')
g_end = gate['day_equity'][max(gate['day_equity'])]
assert abs(g_end - 13370.47) < 0.01, f'GATE FAILED {g_end}'
print(f'gate PASS: Oct1->Nov5 $15k = {g_end:,.2f}', flush=True)

START = sys.argv[1] if len(sys.argv) > 1 else '2026-11-02'
END = sys.argv[2] if len(sys.argv) > 2 else '2026-11-11'
r = H.run(START, END, 15000.0, 'origin/main', cost_bps=5.0, daily_path=D, hourly_path=HR, tag='nov')
eq = r['day_equity']

hr = {r_['symbol']: {b['begins_at'][:10]: float(b['close_price']) for b in r_['bars'] if b['begins_at'].endswith('17:00:00Z')}
      for r_ in json.load(open(HR))['data']['results']}
per = 15000.0 / len(CHIPS)
hold_val = {}
base = START
days = sorted({d for s_ in CHIPS for d in hr[s_] if base <= d <= END})
for d in days:
    hold_val[d] = sum(per * hr[s_][d] / hr[s_][base] for s_ in CHIPS if d in hr[s_] and base in hr[s_])
out = {'start': START, 'end': END, 'capital': 15000.0,
       'replay': {'end_equity': eq[max(eq)], 'ret': (eq[max(eq)] / 15000 - 1) * 100,
                  'realized': r['realized'], 'unrealized': r['unrealized'], 'trades': r['trade_count'],
                  'day_equity': eq, 'day_pnl': r['day_pnl'], 'trades_list': r['trades']},
       'hold': {'end_value': hold_val[END], 'ret': (hold_val[END] / 15000 - 1) * 100,
                'by_day': hold_val}}
json.dump(out, open(os.path.join(ROOT, 'data', 'research', f'replay_vs_hold_{START}_{END}.json'), 'w'), indent=1, default=str)
print(f"replay: ${out['replay']['end_equity']:,.2f} ({out['replay']['ret']:+.2f}%) trades {out['replay']['trades']}")
print(f"hold:   ${out['hold']['end_value']:,.2f} ({out['hold']['ret']:+.2f}%)")
