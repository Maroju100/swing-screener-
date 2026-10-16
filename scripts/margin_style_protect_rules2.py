#!/usr/bin/env python3
"""Round 2 of rules to stop giving back gains (asked 2026-10-16, "think a better setup").

Round 1 (margin_style_protect_rules.py) attacked the give-back at portfolio level: faster
kill-switch, banking gains. Each cut the drop and cost return. Looking at HOW October was
lost: the same names (WDC, STX, SNDK, INTC, LRCX) were bought on a dip, stopped out the next
day, re-bought on the next dip, stopped again -- four cycles in two weeks. These rules break
that cycle instead of shrinking the whole book. SETTINGS FIXED BEFORE ANY RUN:

  S2   Stop cool-off: a symbol stopped out is not re-bought for 2 trading days (same-day
       re-buy included). Other symbols, sells and sizing untouched.
  S5   Same, 5 trading days.
  EQ10 Equity-curve filter: no new buys while today's equity is below the average of the
       previous 10 runs' equity. Exits untouched.
  S2+D, EQ10+D   each combined with volatility sizing 3% (rule D).
  References: PRODUCTION, D, and round 1's C1.

Same windows, data, costs and PASS criteria as round 1:
  a) smaller worst drawdown than production on 6M AND on 3M
  b) ends with at least production's equity on 3M
  c) 6M return no more than 10 points below production
  d) return >= production in at least 2 of the 3 thirds
Gate: all patches off reproduce production exactly ($124,289.71 / 771 trades).

Reproduce:  python3 scripts/margin_style_protect_rules2.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_sizing_rules as SZ
import margin_style_protect_rules as P1

_sub = P1._sub


def patch_cycle(src):
    src = _sub(src, "MAX_HOLD_DAYS = 6\n", "MAX_HOLD_DAYS = 6\nSTOP_COOLDOWN = 0\nEQ_FILTER_DAYS = 0\n")
    src = _sub(src, "                  'trend_gate_active': trend_gate_active}\n",
               "                  'trend_gate_active': trend_gate_active}\n"
               "    _sd = dict(state.get('stop_dates', {}))\n"
               "    for _s in sells:\n"
               "        if _s['reason'] == 'STOP':\n"
               "            _sd[_s['symbol']] = today\n"
               "    risk_state['stop_dates'] = _sd\n"
               "    _eh_prev = state.get('eq_hist', [])\n"
               "    risk_state['eq_hist'] = (_eh_prev + [total_equity])[-max(EQ_FILTER_DAYS, 1):]\n"
               "    _eq_block = bool(EQ_FILTER_DAYS) and len(_eh_prev) >= EQ_FILTER_DAYS and \\\n"
               "        total_equity < sum(_eh_prev[-EQ_FILTER_DAYS:]) / EQ_FILTER_DAYS\n"
               "    def _cooling(_sym):\n"
               "        if not STOP_COOLDOWN or _sym not in _sd:\n"
               "            return False\n"
               "        _d = datetime.strptime(_sd[_sym], '%Y-%m-%d')\n"
               "        for _ in range(STOP_COOLDOWN):\n"
               "            _d = next_business_day(_d)\n"
               "        return today < _d.date().isoformat()\n")
    src = _sub(src, "    if not circuit_breaker_triggered and not kill_switch_active:\n",
               "    if not circuit_breaker_triggered and not kill_switch_active and not _eq_block:\n")
    src = _sub(src, "            pos = None if sym in full_exit_symbols else state['open_positions'].get(sym)\n"
                    "            if pos and pos.get('tranches', 0) >= MAX_TRANCHES:\n",
               "            pos = None if sym in full_exit_symbols else state['open_positions'].get(sym)\n"
               "            if _cooling(sym):\n"
               "                continue\n"
               "            if pos and pos.get('tranches', 0) >= MAX_TRANCHES:\n")
    src = _sub(src, "        state['trend_gate_active'] = actions['risk_state']['trend_gate_active']\n",
               "        state['trend_gate_active'] = actions['risk_state']['trend_gate_active']\n"
               "        for _k in ('stop_dates', 'eq_hist'):\n"
               "            if _k in actions['risk_state']:\n"
               "                state[_k] = actions['risk_state'][_k]\n")
    return src


PATCHES = [P1.patch_protect, patch_cycle, SZ.patch_size]
VOL = {'VOL_SIZE': True, 'VOL_TARGET': 0.03}
VARIANTS = {
    'PRODUCTION': {},
    'S2 stop cool-off 2 days': {'STOP_COOLDOWN': 2},
    'S5 stop cool-off 5 days': {'STOP_COOLDOWN': 5},
    'EQ10 equity-curve filter': {'EQ_FILTER_DAYS': 10},
    'S2+D cool-off 2 days + vol sizing': dict(VOL, STOP_COOLDOWN=2),
    'EQ10+D equity filter + vol sizing': dict(VOL, EQ_FILTER_DAYS=10),
    'D volatility sizing 3%': dict(VOL),
    'C1 fast switch + vol sizing (round 1)': dict(P1.FAST, NO_TREND_GATE=True, **VOL),
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
    g = R.replay(start='2026-03-13', end='2026-09-21', params={}, tag='prot2_gate', cost_bps=P1.COST,
                 src_patches=PATCHES, daily=P1.DAILY, hourly=P1.HOURLY)
    if abs(g['realized'] - 124289.71) > 0.005 or g['trade_count'] != 771:
        raise SystemExit(f"GATE FAILED: {g['realized']} / {g['trade_count']}")
    print('gate PASS: all patches off reproduce production ($124,289.71, 771 trades)\n')
    days = sorted(d['begins_at'][:10] for d in json.load(open(P1.DAILY))['data']['results'][0]['bars']
                  if '2026-03-13' <= d['begins_at'][:10] <= P1.END)
    n = len(days) // 3
    thirds = [(days[0], days[n - 1]), (days[n], days[2 * n - 1]), (days[2 * n], days[-1])]
    out = {'windows': {'6M': ['2026-03-13', P1.END], 'thirds': thirds, '3M': ['2026-07-13', P1.END]},
           'cost_bps': P1.COST, 'results': {}}
    for name, params in VARIANTS.items():
        k = name.split()[0].replace('+', 'p')
        res = {'6M': run('2026-03-13', P1.END, params, 80000.0, f'p2_{k}_6m'),
               '3M': run('2026-07-13', P1.END, params, 15000.0, f'p2_{k}_3m'),
               'thirds': [run(a, b, params, 80000.0, f'p2_{k}_t{i}') for i, (a, b) in enumerate(thirds)]}
        out['results'][name] = res
        print(f"{name:40} 6M {res['6M']['ret_pct']:+7.1f}% dd {res['6M']['max_dd_pct']:+6.1f}% "
              f"sh {res['6M']['sharpe']:.2f} | thirds " + ' '.join(f"{t['ret_pct']:+6.1f}" for t in res['thirds'])
              + f" | 3M ${res['3M']['end_equity']:,.0f} peak ${res['3M']['peak_equity']:,.0f} "
              f"dd {res['3M']['max_dd_pct']:+.1f}%", flush=True)
    Pr = out['results']['PRODUCTION']
    print('\nVERDICTS (pre-set criteria a-d):')
    for name, res in out['results'].items():
        if name == 'PRODUCTION':
            continue
        a = res['6M']['max_dd_pct'] > Pr['6M']['max_dd_pct'] and res['3M']['max_dd_pct'] > Pr['3M']['max_dd_pct']
        b = res['3M']['end_equity'] >= Pr['3M']['end_equity']
        c = res['6M']['ret_pct'] >= Pr['6M']['ret_pct'] - 10
        d = sum(x['ret_pct'] >= y['ret_pct'] for x, y in zip(res['thirds'], Pr['thirds'])) >= 2
        res['checks'] = {'a_smaller_dd_both': a, 'b_3m_end_ge_prod': b, 'c_6m_within_10pts': c,
                         'd_2_of_3_thirds': d, 'PASS': a and b and c and d}
        print(f"  {name:40} a={a!s:5} b={b!s:5} c={c!s:5} d={d!s:5} -> {'PASS' if res['checks']['PASS'] else 'fail'}")
    R.save('protect_rules2.json', out)


if __name__ == '__main__':
    main()
