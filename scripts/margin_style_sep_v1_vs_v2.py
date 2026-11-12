#!/usr/bin/env python3
"""September 2026 only: v1 rules vs v2 (production) rules, $15,000, 5 bps/side, same official-close data as
margin_style_nov_replay_vs_hold.py. Full engine replay of origin/main with parameter overrides only.
v1 = MIN_NOTIONAL 25, kill-switch -15% / 20 days / trend lock, no peak reset.
v2 = production defaults (no overrides).
Gates: (a) v2 Oct1->Nov5 must still reproduce 13,370.47; (b) v2 Sep1->Sep30 must equal the committed
replay_vs_hold_2026-09-01_2026-09-30.json. Hold = equal-weight 8 chips, bought at Sep 1 17:00 bar, marked Sep 30 17:00 bar.
MEASURED. Reproduce: python3 scripts/margin_style_sep_v1_vs_v2.py
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_17h_backtest as H

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, 'data', 'margin_live_daily_to_2026-11-11.json')
HR = os.path.join(ROOT, 'data', 'margin_live_hourly_to_2026-11-11.json')
CHIPS = ['AMD', 'MU', 'WDC', 'SNDK', 'TSM', 'INTC', 'LRCX', 'STX']
H.UNIVERSE = list(CHIPS)
V1 = {'MIN_NOTIONAL': 25.0, 'KILL_SWITCH_DD': -0.15, 'KILL_SWITCH_RESUME_DAYS': 20,
      'KILL_SWITCH_TREND_LOCK': True, 'KILL_SWITCH_RESET_PEAK_ON_RELEASE': False}
V2 = {}
START, END, CAP = '2026-09-01', '2026-09-30', 15000.0

def rep(a, b, params, tag):
    r = R.replay(start=a, end=b, params=dict(params), tag=tag, engine='origin/main', cost_bps=5.0,
                 capital=CAP, src_patches=[], daily=D, hourly=HR)
    return r

g = rep('2026-10-01', '2026-11-05', V2, 'gate_oct')
g_end = g['day_equity'][max(g['day_equity'])]
assert abs(g_end - 13370.47) < 0.01, f'GATE A FAILED {g_end}'
print(f'gate A PASS: v2 Oct1->Nov5 = {g_end:,.2f}', flush=True)

r1 = rep(START, END, V1, 'sep_v1')
r2 = rep(START, END, V2, 'sep_v2')
e2 = r2['day_equity'][max(r2['day_equity'])]
committed = json.load(open(os.path.join(ROOT, 'data', 'research', 'replay_vs_hold_2026-09-01_2026-09-30.json')))
assert abs(e2 - committed['replay']['end_equity']) < 0.01, f'GATE B FAILED {e2}'
print(f'gate B PASS: v2 Sep = {e2:,.2f}', flush=True)

hr = {x['symbol']: {b['begins_at'][:10]: float(b['close_price']) for b in x['bars'] if b['begins_at'].endswith('17:00:00Z')}
      for x in json.load(open(HR))['data']['results']}
days = sorted({d for s in CHIPS for d in hr[s] if START <= d <= END})
per = CAP / len(CHIPS)
hold_by_day = {d: sum(per * hr[s][d] / hr[s][START] for s in CHIPS if d in hr[s] and START in hr[s]) for d in days}

def summ(r):
    eq = r['day_equity']; e = eq[max(eq)]
    pk = dd = 0.0
    for d in sorted(eq):
        pk = max(pk, eq[d]); dd = min(dd, eq[d] / pk - 1)
    return {'end': e, 'ret': (e / CAP - 1) * 100, 'max_dd': dd * 100, 'trades': r['trade_count'],
            'realized': r['realized'], 'unrealized': r['unrealized'], 'day_equity': eq}

out = {'start': START, 'end': END, 'capital': CAP, 'v1': summ(r1), 'v2': summ(r2),
       'hold': {'end_value': hold_by_day[days[-1]], 'ret': (hold_by_day[days[-1]] / CAP - 1) * 100,
                'by_day': hold_by_day}}
json.dump(out, open(os.path.join(ROOT, 'data', 'research', 'sep_v1_vs_v2.json'), 'w'), indent=1, default=str)
for k in ('v1', 'v2'):
    s = out[k]
    print(f"{k}: ${s['end']:,.2f} ({s['ret']:+.2f}%)  maxDD {s['max_dd']:+.2f}%  trades {s['trades']}  realized {s['realized']:,.2f}")
print(f"hold: ${out['hold']['end_value']:,.2f} ({out['hold']['ret']:+.2f}%)")
