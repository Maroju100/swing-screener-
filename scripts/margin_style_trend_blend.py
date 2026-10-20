#!/usr/bin/env python3
"""A different KIND of setup, after ten rule tweaks failed (asked 2026-10-20).

Why: Margin-Style Live is a dip-buyer. Its measured profile is the mirror image of a
trend follower -- it trailed buy & hold ~2.3x in the rising half and beat it ~54pp in the
falling half, then gave back its gains in October's crash. Every rule bolted on to make
it give back less (ten, two rounds) cut the return by more than the drawdown. So instead
of patching it, this tests a strategy with the OPPOSITE regime profile, alone and blended.

  TREND  Same 8 stocks. Each check, hold an equal-weight slice of every stock whose
         previous completed daily close is above its own 50-day average; anything below
         is sold to cash. Signals read only completed closes (no look-ahead). Trades at
         the same check price the engine uses (hourly 17:00 close), 5 bps per side;
         rebalanced only when the set of qualifying stocks changes.
  BLEND  Half the money in production Margin-Style Live (real engine replay at half
         capital), half in TREND. Two separate pots, never rebalanced between them.

FIXED BEFORE RUNNING: 50-day average, equal weight, rebalance-on-change, 50/50 blend. The
20-day version is reported as a sensitivity check only -- it is NOT a candidate, so the
choice of 50 cannot be tuned after seeing results.

Windows and PASS criteria are round 1's (margin_style_protect_rules.py):
  a) smaller worst drawdown than production on 6M AND 3M
  b) ends 3M with at least production's equity
  c) 6M return no more than 10 points below production
  d) return >= production in at least 2 of 3 thirds

Reproduce:  python3 scripts/margin_style_trend_blend.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_protect_rules as P1

COST = 5.0 / 1e4


def load():
    dd = json.load(open(P1.DAILY))
    hd = json.load(open(P1.HOURLY))
    daily = {r['symbol']: {b['begins_at'][:10]: float(b['close_price']) for b in r['bars']
                           if not b.get('provisional')} for r in dd['data']['results']}
    chk = {r['symbol']: {b['begins_at'][:10]: float(b['close_price']) for b in r['bars']
                         if b['begins_at'][11:16] == '17:00'} for r in hd['data']['results']}
    return daily, chk


def trend(start, end, cap, sma, daily, chk):
    syms = sorted(chk)
    days = sorted(d for d in chk[syms[0]] if start <= d <= end)
    cash, sh, held, eqs = cap, {s: 0.0 for s in syms}, None, {}
    for d in days:
        px = {s: chk[s][d] for s in syms}
        want = set()
        for s in syms:
            past = [daily[s][x] for x in sorted(daily[s]) if x < d]
            if len(past) >= sma and past[-1] > sum(past[-sma:]) / sma:
                want.add(s)
        if want != held:
            for s in syms:                              # sell everything not wanted, then
                if sh[s] and s not in want:              # re-split equity across the wanted set
                    cash += sh[s] * px[s] * (1 - COST); sh[s] = 0.0
            eq = cash + sum(sh[s] * px[s] for s in syms)
            tgt = eq / len(want) if want else 0.0
            for s in want:                               # trim overweights first, then buy
                cur = sh[s] * px[s]
                if cur > tgt:
                    q = (cur - tgt) / px[s]; cash += q * px[s] * (1 - COST); sh[s] -= q
            for s in want:
                cur = sh[s] * px[s]
                if cur < tgt:
                    spend = min(tgt - cur, cash)
                    sh[s] += spend / (px[s] * (1 + COST)); cash -= spend
            held = want
        eqs[d] = cash + sum(sh[s] * px[s] for s in syms)
    return eqs


def stats(eqs, cap):
    v = [x for _, x in sorted(eqs.items())]
    peak, dd = cap, 0.0
    for x in v:
        peak = max(peak, x); dd = min(dd, x / peak - 1)
    rets = [v[i] / v[i - 1] - 1 for i in range(1, len(v))]
    return {'end_equity': round(v[-1], 2), 'ret_pct': round((v[-1] / cap - 1) * 100, 2),
            'max_dd_pct': round(dd * 100, 2), 'sharpe': round(R.sharpe_of(rets), 2),
            'peak_equity': round(max(v), 2), 'day_equity': {d: round(x, 2) for d, x in sorted(eqs.items())}}


def prod(start, end, cap, tag):
    r = R.replay(start=start, end=end, params={}, tag=tag, cost_bps=5.0, capital=cap,
                 daily=P1.DAILY, hourly=P1.HOURLY)
    return r['day_equity']


def main():
    g = R.replay(start='2026-03-13', end='2026-09-21', params={}, tag='tb_gate', cost_bps=5.0,
                 daily=P1.DAILY, hourly=P1.HOURLY)
    if abs(g['realized'] - 124289.71) > 0.005 or g['trade_count'] != 771:
        raise SystemExit(f"GATE FAILED: {g['realized']} / {g['trade_count']}")
    print('gate PASS: production replay reproduces $124,289.71 / 771 trades\n')
    daily, chk = load()
    days = sorted(d for d in chk['AMD'] if '2026-03-13' <= d <= P1.END)
    n = len(days) // 3
    wins = {'6M': ('2026-03-13', P1.END, 80000.0), '3M': ('2026-07-13', P1.END, 15000.0),
            'T1': (days[0], days[n - 1], 80000.0), 'T2': (days[n], days[2 * n - 1], 80000.0),
            'T3': (days[2 * n], days[-1], 80000.0)}
    out = {}
    for name in ('PRODUCTION', 'TREND 50-day', 'BLEND 50/50', 'BUY & HOLD', 'TREND 20-day (sensitivity only)'):
        out[name] = {}
        for w, (a, b, cap) in wins.items():
            if name == 'PRODUCTION':
                e = prod(a, b, cap, f'tb_p_{w}')
            elif name.startswith('TREND 50'):
                e = trend(a, b, cap, 50, daily, chk)
            elif name.startswith('TREND 20'):
                e = trend(a, b, cap, 20, daily, chk)
            elif name == 'BUY & HOLD':
                sy = sorted(chk); d0 = min(d for d in chk[sy[0]] if d >= a)
                shs = {s: cap / len(sy) * (1 - COST) / chk[s][d0] for s in sy}
                e = {d: sum(shs[s] * chk[s][d] for s in sy) for d in sorted(chk[sy[0]]) if a <= d <= b}
            else:
                pe = prod(a, b, cap / 2, f'tb_b_{w}')
                te = trend(a, b, cap / 2, 50, daily, chk)
                e = {d: pe[d] + te[d] for d in pe if d in te}
            out[name][w] = stats(e, cap)
        r = out[name]
        print(f"{name:32} 6M {r['6M']['ret_pct']:+7.1f}% dd {r['6M']['max_dd_pct']:+6.1f}% sh {r['6M']['sharpe']:.2f} | "
              f"T {r['T1']['ret_pct']:+6.1f} {r['T2']['ret_pct']:+6.1f} {r['T3']['ret_pct']:+6.1f} | "
              f"3M ${r['3M']['end_equity']:,.0f} peak ${r['3M']['peak_equity']:,.0f} dd {r['3M']['max_dd_pct']:+.1f}%",
              flush=True)
    Pr = out['PRODUCTION']
    print('\nVERDICTS (pre-set criteria a-d; sensitivity row and buy & hold are not candidates):')
    for name in ('TREND 50-day', 'BLEND 50/50'):
        r = out[name]
        a = r['6M']['max_dd_pct'] > Pr['6M']['max_dd_pct'] and r['3M']['max_dd_pct'] > Pr['3M']['max_dd_pct']
        b = r['3M']['end_equity'] >= Pr['3M']['end_equity']
        c = r['6M']['ret_pct'] >= Pr['6M']['ret_pct'] - 10
        d = sum(r[t]['ret_pct'] >= Pr[t]['ret_pct'] for t in ('T1', 'T2', 'T3')) >= 2
        r['checks'] = {'a': a, 'b': b, 'c': c, 'd': d, 'PASS': a and b and c and d}
        print(f"  {name:20} a={a!s:5} b={b!s:5} c={c!s:5} d={d!s:5} -> {'PASS' if r['checks']['PASS'] else 'fail'}")
    R.save('trend_blend.json', {'windows': wins, 'results': out})


if __name__ == '__main__':
    main()
