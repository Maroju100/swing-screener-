"""Live rules vs buy & hold over any window (asked 2026-11-05: Jul 22 -> Aug 22).
Real engine replay (origin/main), $15,000, 5 bps/side, 17:00 UTC hourly check price; buy & hold =
equal $ in the 8 stocks at the first day's check price, held to the last day's (5 bps in).
Also shows the crash-grid candidate (kill-switch -8%, 10 days, no SMA lock-out).
Reproduce: python3 scripts/window_vs_hold.py 2026-07-22 2026-08-22
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_protect_rules2 as P2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY = os.path.join(ROOT, 'data', 'margin_live_daily_ext_2025-11-03_2026-11-03.json')
HOURLY = os.path.join(ROOT, 'data', 'margin_live_hourly_ext_2026-03-06_2026-11-03.json')
A, B = sys.argv[1], sys.argv[2]
CAP = 15000.0


def run(p, tag):
    r = R.replay(start=A, end=B, params=p, tag=tag, cost_bps=5.0, capital=CAP, src_patches=P2.PATCHES,
                 daily=DAILY, hourly=HOURLY)
    eq = sorted(r['day_equity'].items())
    pk, dd = 0, 0
    for _, v in eq:
        pk = max(pk, v); dd = min(dd, v / pk - 1)
    return eq, dd, r['trade_count']


h = json.load(open(HOURLY))['data']['results']
chk = {x['symbol']: {b['begins_at'][:10]: float(b['close_price']) for b in x['bars'] if b['begins_at'][11:16] == '17:00'} for x in h}
for name, p in [('Live rules (production)', {}),
                ('Candidate: kill -8% / 10d / no SMA lock-out', {'KILL_SWITCH_DD': -0.08, 'KILL_SWITCH_RESUME_DAYS': 10, 'NO_TREND_GATE': True})]:
    eq, dd, n = run(p, f"wvh_{name[:4]}")
    print(f"{name:45} ${CAP:,.0f} -> ${eq[-1][1]:,.0f} ({(eq[-1][1] / CAP - 1) * 100:+.1f}%)  worst drop {dd * 100:.1f}%  trades {n}"
          f"  [{eq[0][0]} -> {eq[-1][0]}]")
days = sorted(d for d in chk['AMD'] if A <= d <= B)
sh = {s: CAP / 8 * (1 - 5e-4) / chk[s][days[0]] for s in chk}
vals = [sum(sh[s] * chk[s][d] for s in chk) for d in days]
pk, dd = 0, 0
for v in vals:
    pk = max(pk, v); dd = min(dd, v / pk - 1)
print(f"{'Buy & hold the 8 stocks':45} ${CAP:,.0f} -> ${vals[-1]:,.0f} ({(vals[-1] / CAP - 1) * 100:+.1f}%)  worst drop {dd * 100:.1f}%")
for s in chk:
    print(f"   {s:5} {chk[s][days[-1]] / chk[s][days[0]] - 1:+.1%}")
