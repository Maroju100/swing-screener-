"""Which stocks do the Margin-Style Live rules work on robustly? (asked 2026-10-30)

Production engine (origin/main), rules unpatched; only the tradable list changes. Each of
38 symbols (the 8 chips, 14 sector funds / non-tech large caps from the diversify study, and
16 more: other semis, big tech, SMH/QQQ/SPY) is traded ALONE by the same rules, $15,000,
5 bps/side, 17:00 hourly bar as the check price. (Alone, the engine's 50% per-symbol cap
means at most half the money is ever in the stock.)
Windows: RISING Mar 13-Jun 19, FALLING Jun 22-Sep 21, OCTOBER Sep 22-Oct 16 (data end).
SELECTION RULE, fixed before running: a symbol is ROBUST if the rules made money in BOTH
the rising and falling windows. October is NOT used to select; it is the test. Then:
  - the robust symbols traded together as one basket vs the current 8, on October;
  - same comparison over Mar 13-Oct 16 (in-sample for the selection, labelled as such).
Also shown per symbol: buy & hold over each window, so "rules added value" is visible.
NVDA is not in the pool (prohibited account-wide).
CAVEAT -- survivorship and hindsight: every symbol here exists today; one 7-month path.
Data: data/margin_live_{daily,hourly}_ext_..._2026-10-16_wide.json (22 committed diversify
symbols untouched + 16 appended, 0 interpolated bars). Gate: the chip universe on these files
reproduces production ($124,289.71 / 771 trades, 2026-03-13 -> 2026-09-21, 5 bps).
Reproduce: python3 scripts/margin_style_symbol_sweep.py
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_17h_backtest as H

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY = os.path.join(ROOT, 'data', 'margin_live_daily_ext_2025-11-03_2026-10-16_wide.json')
HOURLY = os.path.join(ROOT, 'data', 'margin_live_hourly_ext_2026-03-06_2026-10-16_wide.json')
CHIPS = ['AMD', 'MU', 'WDC', 'SNDK', 'TSM', 'INTC', 'LRCX', 'STX']
CAP, COST = 15000.0, 5.0
W = {'rising': ('2026-03-13', '2026-06-19'), 'falling': ('2026-06-22', '2026-09-21'),
     'october': ('2026-09-22', '2026-10-16'), 'full': ('2026-03-13', '2026-10-16')}
CLOSE = {r['symbol']: {b['begins_at'][:10]: float(b['close_price']) for b in r['bars']}
         for r in json.load(open(DAILY))['data']['results']}
SYMS = [r['symbol'] for r in json.load(open(DAILY))['data']['results']]


def run(univ, a, b, tag):
    H.UNIVERSE = list(univ)
    r = R.replay(start=a, end=b, params={}, tag=tag, cost_bps=COST, capital=CAP, daily=DAILY, hourly=HOURLY)
    eq = sorted(r['day_equity'].items())
    pk, dd = 0, 0
    for _, v in eq:
        pk = max(pk, v); dd = min(dd, v / pk - 1)
    return {'ret': (eq[-1][1] / CAP - 1) * 100, 'dd': dd * 100, 'trades': r['trade_count']}


def bh(univ, a, b):
    rs = []
    for s in univ:
        ds = sorted(d for d in CLOSE[s] if d < a)
        de = sorted(d for d in CLOSE[s] if d <= b)
        rs.append(CLOSE[s][de[-1]] / CLOSE[s][ds[-1]] - 1)
    return sum(rs) / len(rs) * 100


def main():
    H.UNIVERSE = CHIPS
    g = R.replay(start='2026-03-13', end='2026-09-21', params={}, tag='sw_gate', cost_bps=COST, daily=DAILY, hourly=HOURLY)
    if abs(g['realized'] - 124289.71) > 0.005 or g['trade_count'] != 771:
        raise SystemExit(f"GATE FAILED: {g['realized']} / {g['trade_count']}")
    print('gate PASS: chip universe on the wide files reproduces production\n')
    per = {}
    for s in SYMS:
        per[s] = {w: {**run([s], a, b, f'sw_{s}_{w}'), 'bh': bh([s], a, b)} for w, (a, b) in W.items() if w != 'full'}
    robust = [s for s in SYMS if per[s]['rising']['ret'] > 0 and per[s]['falling']['ret'] > 0]
    print(f"{'sym':6}{'rising':>9}{'(B&H)':>8}{'falling':>9}{'(B&H)':>8}{'October':>9}{'(B&H)':>8}  robust")
    for s in sorted(SYMS, key=lambda s: -min(per[s]['rising']['ret'], per[s]['falling']['ret'])):
        p = per[s]
        print(f"{s:6}{p['rising']['ret']:>+8.1f}%{p['rising']['bh']:>+7.0f}%{p['falling']['ret']:>+8.1f}%{p['falling']['bh']:>+7.0f}%"
              f"{p['october']['ret']:>+8.1f}%{p['october']['bh']:>+7.0f}%  {'YES' if s in robust else ''}")
    print(f"\nROBUST ({len(robust)}): {robust}")
    baskets = {'current 8 chips': CHIPS, f'robust basket ({len(robust)})': robust}
    out = {'per_symbol': per, 'robust': robust, 'baskets': {}}
    for name, u in baskets.items():
        if not u:
            continue
        res = {w: {**run(u, a, b, f'sw_b_{name[:6]}_{w}'), 'bh': bh(u, a, b)} for w, (a, b) in W.items()}
        out['baskets'][name] = res
        print(f"{name:22}" + ''.join(f"  {w} {res[w]['ret']:+6.1f}% (dd {res[w]['dd']:+5.1f}%, B&H {res[w]['bh']:+5.1f}%)" for w in W))
    H.UNIVERSE = CHIPS
    R.save('symbol_sweep.json', out)


if __name__ == '__main__':
    main()
