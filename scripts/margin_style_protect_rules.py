#!/usr/bin/env python3
"""Rules aimed at NOT GIVING BACK GAINS in bad weeks (asked 2026-10-16).

The user's point: on the 3-month $15k replay the live rules were +22% at the end of
September and gave almost all of it back in two October weeks. Earlier timing rules
(whipsaw pause, breadth gate, drawdown throttle, streak pause, exposure cap, 2 buys/run)
all failed because skipping buys after bad days also skips the rebound. These variants
attack the give-back directly. SETTINGS AND PASS CRITERIA FIXED BEFORE ANY RUN:

  K1  Fast kill-switch: flatten at -8% from the high (live: -15%), cool off 5 trading
      days (live: 20). Engine's own permanent SMA-50 re-entry gate unchanged.
  K2  K1 without the permanent SMA-50 re-entry gate (it otherwise switches on for good
      the first time the faster switch fires).
  L1  Profit lock: half of every dollar above the starting capital at the high-water mark
      is banked -- held as cash the buy loop cannot spend. Sells are untouched.
  C1  K2 + volatility sizing 3% (rule D from margin_style_sizing_rules.py).
  D   volatility sizing 3% alone, as the reference already on the dashboard.

Windows (extended data through 2026-10-16, hourly 17:00 close basis, 5 bps/side):
  6M  2026-03-13 -> 2026-10-16, $80k (includes October)
  T1/T2/T3  the same span split into equal thirds, each a fresh flat start at $80k
  3M  2026-07-13 -> 2026-10-16, $15k (the dashboard's weekly table)

PASS ("protects profits better") requires ALL of:
  a) smaller worst drawdown than production on 6M AND on 3M
  b) ends with at least production's equity on 3M
  c) 6M return no more than 10 points below production
  d) return >= production in at least 2 of the 3 thirds

Gate: every patch switched off must reproduce production exactly
($124,289.71 / 771 trades, 2026-03-13 -> 2026-09-21, 5 bps).

Reproduce:  python3 scripts/margin_style_protect_rules.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_sizing_rules as SZ

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
DAILY = os.path.join(DATA, 'margin_live_daily_ext_2025-11-03_2026-10-16.json')
HOURLY = os.path.join(DATA, 'margin_live_hourly_ext_2026-03-06_2026-10-16.json')
COST = 5.0
END = '2026-10-16'


def _sub(src, old, new):
    n = src.count(old)
    if n != 1:
        raise SystemExit(f'patch anchor matched {n}x, expected 1:\n{old[:160]}')
    return src.replace(old, new)


def patch_protect(src):
    src = _sub(src, "MAX_HOLD_DAYS = 6\n",
               "MAX_HOLD_DAYS = 6\nNO_TREND_GATE = False\nLOCK_PCT = 0.0\nLOCK_BASE = 0.0\n")
    src = _sub(src, "        kill_switch_active = True\n        trend_gate_active = True\n",
               "        kill_switch_active = True\n        trend_gate_active = not NO_TREND_GATE\n")
    src = _sub(src, "    buys = []\n    netted_symbols = set()\n",
               "    if LOCK_PCT:\n"
               "        safe_cash = max(0.0, safe_cash - LOCK_PCT * max(0.0, equity_peak - LOCK_BASE))\n"
               "    buys = []\n    netted_symbols = set()\n")
    return src


FAST = {'KILL_SWITCH_DD': -0.08, 'KILL_SWITCH_RESUME_DAYS': 5}
VARIANTS = {
    'PRODUCTION': {},
    'K1 fast kill-switch (-8%, 5 days)': dict(FAST),
    'K2 fast kill-switch, no SMA-50 lock-out': dict(FAST, NO_TREND_GATE=True),
    'L1 bank 50% of gains': {'LOCK_PCT': 0.5},
    'C1 K2 + volatility sizing 3%': dict(FAST, NO_TREND_GATE=True, VOL_SIZE=True, VOL_TARGET=0.03),
    'D volatility sizing 3%': {'VOL_SIZE': True, 'VOL_TARGET': 0.03},
}


def run(start, end, params, cap, tag):
    p = dict(params)
    if p.get('LOCK_PCT'):
        p['LOCK_BASE'] = cap
    r = R.replay(start=start, end=end, params=p, tag=tag, cost_bps=COST, capital=cap,
                 src_patches=[patch_protect, SZ.patch_size], daily=DAILY, hourly=HOURLY)
    s = R.summarize(r)
    eq = sorted(r['day_equity'].items())
    s['end_equity'] = round(eq[-1][1], 2)
    s['ret_pct'] = round((eq[-1][1] / cap - 1) * 100, 2)
    s['peak_equity'] = round(max(v for _, v in eq), 2)
    s['kill_switch_days'] = None
    s['day_equity'] = {d: round(v, 2) for d, v in eq}
    return s


def main():
    g = R.replay(start='2026-03-13', end='2026-09-21', params={}, tag='prot_gate', cost_bps=COST,
                 src_patches=[patch_protect, SZ.patch_size], daily=DAILY, hourly=HOURLY)
    if abs(g['realized'] - 124289.71) > 0.005 or g['trade_count'] != 771:
        raise SystemExit(f"GATE FAILED: {g['realized']} / {g['trade_count']}")
    print('gate PASS: all patches off reproduce production ($124,289.71, 771 trades)\n')

    days = sorted(d['begins_at'][:10] for d in json.load(open(DAILY))['data']['results'][0]['bars']
                  if '2026-03-13' <= d['begins_at'][:10] <= END)
    n = len(days) // 3
    thirds = [(days[0], days[n - 1]), (days[n], days[2 * n - 1]), (days[2 * n], days[-1])]

    out = {'windows': {'6M': ['2026-03-13', END], 'thirds': thirds, '3M': ['2026-07-13', END]},
           'cost_bps': COST, 'results': {}}
    for name, params in VARIANTS.items():
        k = name.split()[0]
        res = {'6M': run('2026-03-13', END, params, 80000.0, f'prot_{k}_6m'),
               '3M': run('2026-07-13', END, params, 15000.0, f'prot_{k}_3m'),
               'thirds': [run(a, b, params, 80000.0, f'prot_{k}_t{i}') for i, (a, b) in enumerate(thirds)]}
        out['results'][name] = res
        print(f"{name:42} 6M {res['6M']['ret_pct']:+7.1f}% dd {res['6M']['max_dd_pct']:+6.1f}% "
              f"sh {res['6M']['sharpe']:.2f} | thirds " + ' '.join(f"{t['ret_pct']:+6.1f}" for t in res['thirds'])
              + f" | 3M ${res['3M']['end_equity']:,.0f} dd {res['3M']['max_dd_pct']:+.1f}%", flush=True)

    P = out['results']['PRODUCTION']
    print('\nVERDICTS (pre-set criteria a-d):')
    for name, res in out['results'].items():
        if name == 'PRODUCTION':
            continue
        a = res['6M']['max_dd_pct'] > P['6M']['max_dd_pct'] and res['3M']['max_dd_pct'] > P['3M']['max_dd_pct']
        b = res['3M']['end_equity'] >= P['3M']['end_equity']
        c = res['6M']['ret_pct'] >= P['6M']['ret_pct'] - 10
        d = sum(x['ret_pct'] >= y['ret_pct'] for x, y in zip(res['thirds'], P['thirds'])) >= 2
        res['checks'] = {'a_smaller_dd_both': a, 'b_3m_end_ge_prod': b, 'c_6m_within_10pts': c,
                         'd_2_of_3_thirds': d, 'PASS': a and b and c and d}
        print(f"  {name:42} a={a!s:5} b={b!s:5} c={c!s:5} d={d!s:5} -> {'PASS' if res['checks']['PASS'] else 'fail'}")
    R.save('protect_rules.json', out)


if __name__ == '__main__':
    main()
