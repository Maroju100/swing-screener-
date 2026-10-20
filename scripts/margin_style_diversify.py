#!/usr/bin/env python3
"""Spread Margin-Style Live beyond chips (asked 2026-10-20: "spread beyond chips and see
what difference it makes").

Same production engine and rules, unpatched -- only the list of stocks it may trade changes.
The user did not name instruments, so two universes were FIXED BEFORE ANY RUN, chosen by
sector, not by performance (one fund or one large, liquid stock per sector):

  A  chips + 6 sector funds: XLF financials, XLV health care, XLE energy, XLP staples,
     XLU utilities, XLI industrials                                   (14 symbols)
  B  chips + 8 large non-tech stocks: JPM, XOM, LLY, WMT, CAT, NEE, HD, KO  (16 symbols)

Also reported, as context not candidates: each added group traded ALONE by the same rules,
and buy & hold of each universe.

Data: data/margin_live_{daily,hourly}_ext_..._2026-10-16_diversified.json -- the committed
chip bars untouched, the new symbols appended (0 interpolated bars). Gate: with the chip
universe, the diversified files must still reproduce production exactly
($124,289.71 / 771 trades, 2026-03-13 -> 2026-09-21, 5 bps).

Windows and PASS criteria are round 1's (margin_style_protect_rules.py):
  a) smaller worst drawdown than production on 6M AND 3M
  b) ends 3M with at least production's equity
  c) 6M return no more than 10 points below production
  d) return >= production in at least 2 of 3 thirds

CAVEAT -- hindsight: the sectors were picked without looking at results, but every one of
these names survived to today, and 7 months is one market path.

Reproduce:  python3 scripts/margin_style_diversify.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_17h_backtest as H
import margin_style_protect_rules as P1

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
DAILY = os.path.join(DATA, 'margin_live_daily_ext_2025-11-03_2026-10-16_diversified.json')
HOURLY = os.path.join(DATA, 'margin_live_hourly_ext_2026-03-06_2026-10-16_diversified.json')
CHIPS = ['AMD', 'MU', 'WDC', 'SNDK', 'TSM', 'INTC', 'LRCX', 'STX']
FUNDS = ['XLF', 'XLV', 'XLE', 'XLP', 'XLU', 'XLI']
STOCKS = ['JPM', 'XOM', 'LLY', 'WMT', 'CAT', 'NEE', 'HD', 'KO']
UNIVERSES = {
    'PRODUCTION (8 chips)': CHIPS,
    'A chips + 6 sector funds': CHIPS + FUNDS,
    'B chips + 8 non-tech stocks': CHIPS + STOCKS,
    'context: 6 sector funds alone': FUNDS,
    'context: 8 non-tech stocks alone': STOCKS,
}


def run(univ, start, end, cap, tag):
    H.UNIVERSE = list(univ)
    r = R.replay(start=start, end=end, params={}, tag=tag, cost_bps=5.0, capital=cap,
                 daily=DAILY, hourly=HOURLY)
    s = R.summarize(r)
    eq = sorted(r['day_equity'].items())
    s['end_equity'] = round(eq[-1][1], 2)
    s['ret_pct'] = round((eq[-1][1] / cap - 1) * 100, 2)
    s['peak_equity'] = round(max(v for _, v in eq), 2)
    s['quote_fallbacks'] = len(r.get('quote_fallbacks') or [])
    s['day_equity'] = {d: round(v, 2) for d, v in eq}
    return s


def buy_hold(univ, start, end, cap):
    import json
    hd = json.load(open(HOURLY))
    chk = {r['symbol']: {b['begins_at'][:10]: float(b['close_price']) for b in r['bars']
                         if b['begins_at'][11:16] == '17:00'} for r in hd['data']['results'] if r['symbol'] in univ}
    days = sorted(d for d in chk[univ[0]] if start <= d <= end)
    sh = {s: cap / len(univ) * (1 - 5e-4) / chk[s][days[0]] for s in univ}
    v = [sum(sh[s] * chk[s][d] for s in univ) for d in days]
    peak, dd = cap, 0.0
    for x in v:
        peak = max(peak, x); dd = min(dd, x / peak - 1)
    return {'end_equity': round(v[-1], 2), 'ret_pct': round((v[-1] / cap - 1) * 100, 2), 'max_dd_pct': round(dd * 100, 2)}


def main():
    H.UNIVERSE = CHIPS
    g = R.replay(start='2026-03-13', end='2026-09-21', params={}, tag='div_gate', cost_bps=5.0,
                 daily=DAILY, hourly=HOURLY)
    if abs(g['realized'] - 124289.71) > 0.005 or g['trade_count'] != 771:
        raise SystemExit(f"GATE FAILED: {g['realized']} / {g['trade_count']}")
    print('gate PASS: diversified files reproduce production with the chip universe ($124,289.71, 771 trades)\n')

    import json
    days = sorted(b['begins_at'][:10] for b in json.load(open(DAILY))['data']['results'][0]['bars']
                  if '2026-03-13' <= b['begins_at'][:10] <= P1.END)
    n = len(days) // 3
    wins = {'6M': ('2026-03-13', P1.END, 80000.0), '3M': ('2026-07-13', P1.END, 15000.0),
            'T1': (days[0], days[n - 1], 80000.0), 'T2': (days[n], days[2 * n - 1], 80000.0),
            'T3': (days[2 * n], days[-1], 80000.0)}
    out = {}
    for name, univ in UNIVERSES.items():
        k = name.split()[0].replace(':', '') + str(len(univ))
        r = {w: run(univ, a, b, cap, f'div_{k}_{w}') for w, (a, b, cap) in wins.items()}
        r['buy_hold'] = {w: buy_hold(univ, a, b, cap) for w, (a, b, cap) in wins.items() if w in ('6M', '3M')}
        out[name] = r
        print(f"{name:34} 6M {r['6M']['ret_pct']:+7.1f}% dd {r['6M']['max_dd_pct']:+6.1f}% sh {r['6M']['sharpe']:.2f} | "
              f"T {r['T1']['ret_pct']:+6.1f} {r['T2']['ret_pct']:+6.1f} {r['T3']['ret_pct']:+6.1f} | "
              f"3M ${r['3M']['end_equity']:,.0f} peak ${r['3M']['peak_equity']:,.0f} dd {r['3M']['max_dd_pct']:+.1f}% | "
              f"B&H 6M {r['buy_hold']['6M']['ret_pct']:+.1f}% / 3M {r['buy_hold']['3M']['ret_pct']:+.1f}%"
              f" | fallbacks {r['6M']['quote_fallbacks']}", flush=True)
    Pr = out['PRODUCTION (8 chips)']
    print('\nVERDICTS (pre-set criteria a-d; context rows are not candidates):')
    for name in ('A chips + 6 sector funds', 'B chips + 8 non-tech stocks'):
        r = out[name]
        a = r['6M']['max_dd_pct'] > Pr['6M']['max_dd_pct'] and r['3M']['max_dd_pct'] > Pr['3M']['max_dd_pct']
        b = r['3M']['end_equity'] >= Pr['3M']['end_equity']
        c = r['6M']['ret_pct'] >= Pr['6M']['ret_pct'] - 10
        d = sum(r[t]['ret_pct'] >= Pr[t]['ret_pct'] for t in ('T1', 'T2', 'T3')) >= 2
        r['checks'] = {'a': a, 'b': b, 'c': c, 'd': d, 'PASS': a and b and c and d}
        print(f"  {name:30} a={a!s:5} b={b!s:5} c={c!s:5} d={d!s:5} -> {'PASS' if r['checks']['PASS'] else 'fail'}")
    H.UNIVERSE = CHIPS
    R.save('diversify.json', {'windows': wins, 'universes': UNIVERSES, 'results': out})


if __name__ == '__main__':
    main()
