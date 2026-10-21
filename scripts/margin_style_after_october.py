#!/usr/bin/env python3
"""Rules suggested by what actually happened in October (asked 2026-10-21).

What the live account showed (scripts/margin_style_no_skips_since_1002.py --from-0922): with
every plan executed, the rules bought dips, were stopped out the next day five times, tripped
the kill-switch on 10-14 and then sat in cash for 20 trading days through the rebound. The
real account, which skipped or held those runs, ended ~$1,900 better. Two mechanisms:

  1. the 20-trading-day kill-switch lock-out (plus its permanent 50-day-average gate) kept
     the system out of the bounce;
  2. the -1.51% stop fired on whole-sector down days, selling everything at the low.

SETTINGS AND PASS CRITERIA FIXED BEFORE ANY RUN:

  R1  kill-switch cool-off 5 trading days instead of 20 (still fires at -15%)
  R2  R1 + no permanent 50-day-average re-entry gate after the kill-switch
  R3  sector-day stop exemption: when 6 or more of the 8 stocks are below their own stop line
      at the check, it is a sector move, not a stock problem -> skip the STOP sells this run,
      hold, and buy nothing this run. Any other day the -1.51% stop works exactly as now.
      ** R3 changes the intraday stop, which CLAUDE.md protects. Tested at the user's request;
      not to be deployed without the user's explicit go-ahead. **
  R4  R3 + R2

Windows / PASS criteria are round 1's (margin_style_protect_rules.py) but run to Oct 21 so the
kill-switch cool-off can end inside the window: 6M Mar 13 -> Oct 21 $80k, thirds, 3M Jul 13 ->
Oct 21 $15k, 5 bps (10-21 priced at the 17:00 hourly bar, which may be incomplete); PASS needs ALL of
  a) smaller worst drawdown than production on 6M AND 3M
  b) ends 3M with at least production's equity
  c) 6M return no more than 10 points below production
  d) return >= production in at least 2 of 3 thirds
Gate: every patch off reproduces production exactly ($124,289.71 / 771 trades).

Reproduce:  python3 scripts/margin_style_after_october.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_sizing_rules as SZ
import margin_style_protect_rules as P1

_sub = P1._sub
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
P1.DAILY = os.path.join(DATA, 'margin_live_daily_ext_2025-11-03_2026-10-21.json')
P1.HOURLY = os.path.join(DATA, 'margin_live_hourly_ext_2026-03-06_2026-10-21.json')
P1.END = '2026-10-21'


def patch_sector(src):
    src = _sub(src, "MAX_HOLD_DAYS = 6\n", "MAX_HOLD_DAYS = 6\nSECTOR_MOVE_N = 0\n")
    src = _sub(src, "    pending_peak_gain = {}\n    peak_updates = {}\n    for sym, pos in list(state['open_positions'].items()):\n",
               "    pending_peak_gain = {}\n    peak_updates = {}\n"
               "    _below = sum(1 for _s in SYMBOLS if _s in bars_by_sym and _s in quotes and len(bars_by_sym[_s]) >= 1\n"
               "                 and quotes[_s] <= bars_by_sym[_s][-1]['close'] * (1 + INTRADAY_STOP))\n"
               "    sector_day = bool(SECTOR_MOVE_N) and _below >= SECTOR_MOVE_N\n"
               "    for sym, pos in list(state['open_positions'].items()):\n")
    src = _sub(src, "        if live_price <= prev_close * (1 + INTRADAY_STOP):\n            sells.append(",
               "        if not sector_day and live_price <= prev_close * (1 + INTRADAY_STOP):\n            sells.append(")
    src = _sub(src, "    circuit_breaker_triggered = stop_count >= CIRCUIT_BREAKER_STOP_COUNT\n",
               "    circuit_breaker_triggered = stop_count >= CIRCUIT_BREAKER_STOP_COUNT or sector_day\n")
    return src


PATCHES = [P1.patch_protect, SZ.patch_size, patch_sector]
VARIANTS = {
    'PRODUCTION': {},
    'R1 kill-switch cool-off 5 days': {'KILL_SWITCH_RESUME_DAYS': 5},
    'R2 R1 + no 50-day re-entry gate': {'KILL_SWITCH_RESUME_DAYS': 5, 'NO_TREND_GATE': True},
    'R3 hold through sector-wide drops': {'SECTOR_MOVE_N': 6},
    'R4 R3 + R2': {'SECTOR_MOVE_N': 6, 'KILL_SWITCH_RESUME_DAYS': 5, 'NO_TREND_GATE': True},
}


def run(start, end, params, cap, tag):
    r = R.replay(start=start, end=end, params=dict(params), tag=tag, cost_bps=P1.COST, capital=cap,
                 src_patches=PATCHES, daily=P1.DAILY, hourly=P1.HOURLY)
    s = R.summarize(r)
    eq = sorted(r['day_equity'].items())
    s['end_equity'] = round(eq[-1][1], 2)
    s['ret_pct'] = round((eq[-1][1] / cap - 1) * 100, 2)
    s['peak_equity'] = round(max(v for _, v in eq), 2)
    s['day_equity'] = {d: round(v, 2) for d, v in eq}
    return s


def main():
    g = R.replay(start='2026-03-13', end='2026-09-21', params={}, tag='aoct_gate', cost_bps=P1.COST,
                 src_patches=PATCHES, daily=P1.DAILY, hourly=P1.HOURLY)
    if abs(g['realized'] - 124289.71) > 0.005 or g['trade_count'] != 771:
        raise SystemExit(f"GATE FAILED: {g['realized']} / {g['trade_count']}")
    print('gate PASS: all patches off reproduce production ($124,289.71, 771 trades)\n')
    days = sorted(b['begins_at'][:10] for b in json.load(open(P1.DAILY))['data']['results'][0]['bars']
                  if '2026-03-13' <= b['begins_at'][:10] <= P1.END)
    n = len(days) // 3
    wins = {'6M': ('2026-03-13', P1.END, 80000.0), '3M': ('2026-07-13', P1.END, 15000.0),
            'T1': (days[0], days[n - 1], 80000.0), 'T2': (days[n], days[2 * n - 1], 80000.0),
            'T3': (days[2 * n], days[-1], 80000.0)}
    out = {}
    for name, params in VARIANTS.items():
        k = name.split()[0]
        r = {w: run(a, b, params, cap, f'aoct_{k}_{w}') for w, (a, b, cap) in wins.items()}
        out[name] = r
        gain = r['3M']['peak_equity'] - 15000
        kept = f"{(r['3M']['end_equity'] - 15000) / gain * 100:.0f}%" if gain > 1 else 'n/a (never above start)'
        print(f"{name:36} 6M {r['6M']['ret_pct']:+7.1f}% dd {r['6M']['max_dd_pct']:+6.1f}% sh {r['6M']['sharpe']:.2f} | "
              f"T {r['T1']['ret_pct']:+6.1f} {r['T2']['ret_pct']:+6.1f} {r['T3']['ret_pct']:+6.1f} | "
              f"3M ${r['3M']['end_equity']:,.0f} peak ${r['3M']['peak_equity']:,.0f} dd {r['3M']['max_dd_pct']:+.1f}% "
              f"kept {kept}", flush=True)
    Pr = out['PRODUCTION']
    print('\nVERDICTS (pre-set criteria a-d):')
    for name, r in out.items():
        if name == 'PRODUCTION':
            continue
        a = r['6M']['max_dd_pct'] > Pr['6M']['max_dd_pct'] and r['3M']['max_dd_pct'] > Pr['3M']['max_dd_pct']
        b = r['3M']['end_equity'] >= Pr['3M']['end_equity']
        c = r['6M']['ret_pct'] >= Pr['6M']['ret_pct'] - 10
        d = sum(r[t]['ret_pct'] >= Pr[t]['ret_pct'] for t in ('T1', 'T2', 'T3')) >= 2
        r['checks'] = {'a': a, 'b': b, 'c': c, 'd': d, 'PASS': a and b and c and d}
        print(f"  {name:34} a={a!s:5} b={b!s:5} c={c!s:5} d={d!s:5} -> {'PASS' if r['checks']['PASS'] else 'fail'}")
    R.save('after_october.json', {'windows': wins, 'results': out})


if __name__ == '__main__':
    main()
