#!/usr/bin/env python3
"""Weekly P&L of the production rules, 6-month replay extended to 2026-10-14.

Production engine (origin/main, unpatched), $80k from 2026-03-13, 5 bps per side,
committed hourly basis (the ~17:00 UTC bar's close, i.e. ~1 PM CDT pricing).
Price data extended past the anchor window by appending strictly-newer bars only
(data/margin_live_{hourly,daily}_ext_..._2026-10-14.json, provenance inside).

Gate: the extended data, replayed only to 2026-09-21, must reproduce the research
baseline exactly ($124,289.71, 771 trades) -- otherwise nothing is reported.

Weekly P&L = change in equity (cash + positions at that day's check price) from the
previous week's last trading day; "realized" = closed-trade P&L booked that week.
A BACKTEST, not the real account: it compounds from $80k and does not include the
live account's missed runs, deposits or fills.

Reproduce:
    python3 scripts/margin_style_weekly_pnl.py [--capital 15000] [--vol-target 0.03]

--vol-target applies rule D (volatility sizing) from margin_style_sizing_rules.py:
each buy x min(1, target / the stock's 20-day daily volatility). The patch is the
same anchored patch that study gates against production; with the flag omitted the
engine is unpatched.
"""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
DAILY = os.path.join(DATA, 'margin_live_daily_ext_2025-11-03_2026-10-14.json')
HOURLY = os.path.join(DATA, 'margin_live_hourly_ext_2026-03-06_2026-10-14.json')
OUT = os.path.join(DATA, 'research', 'weekly_pnl.json')
CAP, COST = 80000.0, 5.0


def main():
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument('--capital', type=float, default=80000.0)
    ap.add_argument('--vol-target', type=float, default=None)
    a = ap.parse_args()
    global CAP, OUT
    CAP = a.capital
    if CAP != 80000.0:
        OUT = OUT.replace('weekly_pnl.json', f'weekly_pnl_{int(CAP)}.json')
    kw = {}
    if a.vol_target:
        import margin_style_sizing_rules as SZ
        kw = {'src_patches': [SZ.patch_size], 'params': {'VOL_SIZE': True, 'VOL_TARGET': a.vol_target}}
        OUT = OUT.replace('.json', f'_vol{int(a.vol_target * 1000)}.json')
    g = R.replay(start='2026-03-13', end='2026-09-21', tag='wk_gate', cost_bps=COST, daily=DAILY, hourly=HOURLY)
    if abs(g['realized'] - 124289.71) > 0.005 or g['trade_count'] != 771:
        raise SystemExit(f"GATE FAILED: {g['realized']} / {g['trade_count']}")
    print('gate PASS: extended data reproduces the baseline to 09-21 ($124,289.71, 771 trades)\n')
    r = R.replay(start='2026-03-13', end='2026-10-14', tag=f'wk_full{int(CAP)}{"v" if kw else ""}', cost_bps=COST, daily=DAILY,
                 hourly=HOURLY, capital=CAP, **kw)
    eq = sorted(r['day_equity'].items())
    weeks, prev = [], CAP
    for d, v in eq:
        mon = (dt.date.fromisoformat(d) - dt.timedelta(days=dt.date.fromisoformat(d).weekday())).isoformat()
        if not weeks or weeks[-1]['week_of'] != mon:
            weeks.append({'week_of': mon, 'start_equity': prev, 'days': 0, 'realized': 0.0})
        w = weeks[-1]
        w['end_equity'] = v; w['last_day'] = d; w['days'] += 1
        w['realized'] += r['day_pnl'].get(d, 0.0)
        prev = v
    peak = CAP
    for w in weeks:
        w['pnl'] = round(w['end_equity'] - w['start_equity'], 2)
        w['pct'] = round(w['pnl'] / w['start_equity'] * 100, 2)
        w['realized'] = round(w['realized'], 2)
        peak = max(peak, w['end_equity'])
        w['below_peak_pct'] = round((w['end_equity'] / peak - 1) * 100, 2)
        w['start_equity'] = round(w['start_equity'], 2); w['end_equity'] = round(w['end_equity'], 2)
    print(f"{'week of':11}{'days':>5}{'P&L':>12}{'%':>8}{'realized':>12}{'equity':>13}{'vs peak':>9}")
    for w in weeks:
        print(f"{w['week_of']:11}{w['days']:>5}{w['pnl']:>+12,.0f}{w['pct']:>+8.2f}{w['realized']:>+12,.0f}"
              f"{w['end_equity']:>13,.0f}{w['below_peak_pct']:>+9.2f}")
    tot = weeks[-1]['end_equity'] - CAP
    print(f"\ntotal {tot:+,.0f} ({tot/CAP*100:+.1f}%), {len(weeks)} weeks, "
          f"{sum(1 for w in weeks if w['pnl'] > 0)} up / {sum(1 for w in weeks if w['pnl'] <= 0)} down")
    json.dump({'engine': R.ENGINE, 'cost_bps': COST, 'capital': CAP, 'through': '2026-10-14',
               'basis': 'hourly 17:00 bar close (~1 PM CDT)', 'weeks': weeks}, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
