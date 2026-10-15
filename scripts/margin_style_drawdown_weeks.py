#!/usr/bin/env python3
"""Which weeks in the 6-month replay had the deepest drawdowns? (asked 2026-10-15)

Production engine (origin/main, unpatched) replayed 2026-03-13 -> 2026-09-21 at
$80k, 5 bps per side, on the committed hourly basis (~1 PM CDT pricing), plus the
30-minute basis at 17:30 UTC (the live check time) for 2026-06-22 -> 2026-09-21.
Reports, from each run's own daily equity curve (valued at the check, not intraday):
  * the worst non-overlapping 5-trading-day equity changes, and
  * every drawdown episode deeper than 4%: peak date, trough date, depth, and the
    date equity regained the peak (or "not recovered").
Also the equal-weight basket's change over the same 5 days, for context.

Reproduce:
    python3 scripts/margin_style_drawdown_weeks.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_intraday_study as I
import margin_style_research as R

OUT = os.path.join(I.RESULTS, 'drawdown_weeks.json')
COST = 5.0


def weeks(eq_items, n=8):
    d = [k for k, _ in eq_items]; v = [x for _, x in eq_items]
    cand = sorted(((v[i] / v[i - 5] - 1, i) for i in range(5, len(v))))
    picked, used = [], set()
    for chg, i in cand:
        if any(j in used for j in range(i - 5, i + 1)):
            continue
        picked.append({'from': d[i - 5], 'to': d[i], 'change_pct': round(chg * 100, 2),
                       'equity_from': round(v[i - 5], 2), 'equity_to': round(v[i], 2)})
        used.update(range(i - 5, i + 1))
        if len(picked) == n:
            break
    return picked


def episodes(eq_items, min_dd=0.04):
    out, peak_v, peak_d, trough_v, trough_d = [], None, None, None, None
    for d, v in eq_items:
        if peak_v is None or v >= peak_v:
            if peak_v is not None and trough_v is not None and trough_v / peak_v - 1 <= -min_dd:
                out.append({'peak': peak_d, 'trough': trough_d, 'depth_pct': round((trough_v / peak_v - 1) * 100, 2),
                            'recovered': d})
            peak_v, peak_d, trough_v, trough_d = v, d, None, None
        elif trough_v is None or v < trough_v:
            trough_v, trough_d = v, d
    if trough_v is not None and trough_v / peak_v - 1 <= -min_dd:
        out.append({'peak': peak_d, 'trough': trough_d, 'depth_pct': round((trough_v / peak_v - 1) * 100, 2),
                    'recovered': None})
    return sorted(out, key=lambda e: e['depth_pct'])


def main():
    hourly = R.replay(tag='dw_base', cost_bps=COST)
    fine = I.replay_intraday('2026-06-22', '2026-09-21', check_times=('17:30',), tag='dw_fine',
                             cost_bps=COST, capital=80000.0, use_hourly_at_1700=False, exact_open=True)
    out = {}
    for name, r in (('hourly_6mo', hourly), ('30min_1730_64d', fine)):
        eq = sorted(r['day_equity'].items())
        out[name] = {'worst_weeks': weeks(eq), 'episodes_over_4pct': episodes(eq)}
        print(f"\n== {name} ==\nworst 5-trading-day stretches:")
        for w in out[name]['worst_weeks']:
            print(f"  {w['from']} -> {w['to']}  {w['change_pct']:+6.2f}%   (${w['equity_from']:,.0f} -> ${w['equity_to']:,.0f})")
        print("drawdown episodes deeper than 4% (peak -> trough, recovered):")
        for e in out[name]['episodes_over_4pct']:
            print(f"  {e['peak']} -> {e['trough']}  {e['depth_pct']:+6.2f}%  recovered {e['recovered'] or 'NOT YET'}")
    json.dump(out, open(OUT, 'w'), indent=1)
    print(f'\nwrote {OUT}')


if __name__ == '__main__':
    main()
