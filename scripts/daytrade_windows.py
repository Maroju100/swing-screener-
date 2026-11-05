"""Day-trading setups on the consolidated windows, sliced from the committed continuous 6-month run
(data/research/daytrade_setups_6m.json, $15k, 5 bps/side). 5-minute data exists only Apr 21 -> Oct 21,
so RISING = Apr 21-Jun 19 (partial), CRASH = Oct 1-Oct 21 (partial). Window returns are ratios of the
continuous equity curve (end / value on the last day before the window), not fresh starts.
v3 rows cover Aug 10 -> Oct 16 only (1-minute data limit); their rising window is n/a.
Reproduce: python3 scripts/daytrade_windows.py
"""
import json, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d = json.load(open(os.path.join(ROOT, 'data', 'research', 'daytrade_setups_6m.json')))
W = {'rising*': ('2026-04-21', '2026-06-19'), 'falling': ('2026-06-22', '2026-09-30'),
     'crash*': ('2026-10-01', '2026-10-21'), 'full*': ('2026-04-21', '2026-10-21')}
out = {}
for k, v in sorted(d['results'].items(), key=lambda kv: -kv[1]['return_pct']):
    c = sorted(v['curve'].items())
    row = {}
    for w, (a, b) in W.items():
        before = [x for t, x in c if t < a]
        inside = [x for t, x in c if a <= t <= b]
        if not inside or (not before and c[0][0] > a):
            row[w] = None; continue
        start = before[-1] if before else d['capital']
        row[w] = round((inside[-1] / start - 1) * 100, 1)
    out[k] = row
    print(f"{k:38}" + ''.join(f"{w} {row[w]:+6.1f}%  " if row[w] is not None else f"{w}   n/a   " for w in W))
json.dump({'windows': W, 'rows': out}, open(os.path.join(ROOT, 'data', 'research', 'daytrade_windows.json'), 'w'), indent=1)
