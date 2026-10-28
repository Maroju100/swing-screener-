"""Your dip-buy style, unlevered vs on margin (asked 2026-10-28).

"Your style" = the Margin-Style Live engine, which was reverse-engineered from the owner's
Margin account (410961445) in July. Real engine replay (origin/main), Apr 21 -> Oct 21 2026
(data ends 10-21), 5 bps/side, starting equity $28,700 (the Margin account's value on 10-28).

LEVERAGE L: each day the engine is told its buying power is L x equity minus what it already
holds, instead of its cash. L = 1.0 is exactly production (gate below). Cash may go negative
(margin debt) and is charged interest daily.
  ESTIMATED: margin interest 6.0%/yr on the debt; Robinhood's actual rate depends on the
  balance and Gold membership.
  NOT SIMULATED: margin calls. The replay reports the lowest equity / positions ratio reached;
  below ~30% (Robinhood's typical maintenance, often higher for volatile stocks) a real account
  would have been forced to sell, so a run that goes below it overstates what leverage keeps.
Sale proceeds are usable the next day in both runs (production's settlement model), so the
only difference between runs is the leverage.
Reproduce: python3 scripts/margin_style_leverage.py
"""
import inspect, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_17h_backtest as H
import margin_style_protect_rules as P1
import margin_style_research as R

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY = os.path.join(ROOT, 'data', 'margin_live_daily_ext_2025-11-03_2026-10-21.json')
HOURLY = os.path.join(ROOT, 'data', 'margin_live_hourly_ext_2026-03-06_2026-10-21.json')
CAP, START, END, RATE, MAINT = 28700.0, '2026-04-21', '2026-10-21', 0.06, 0.30
MONTH_ENDS = ['2026-04-30', '2026-05-29', '2026-06-30', '2026-07-31', '2026-08-31', '2026-09-30', '2026-10-21']


def _sub(src, old, new):
    assert src.count(old) == 1, old
    return src.replace(old, new)


src = inspect.getsource(H.run)
src = _sub(src, "def run(", "def run_lev(")
src = _sub(src, "        buf = io.StringIO()\n        with contextlib.redirect_stdout(buf):\n            cmd_plan(hist_path, quotes_path, cash, [])\n",
           "        _st = json.load(open(state_path)) if os.path.exists(state_path) else {'open_positions': {}}\n"
           "        _ov = sum(p['shares'] * quotes.get(s, p['entry']) for s, p in _st['open_positions'].items())\n"
           "        _bp = max(0.0, (cash + _ov) * LEV['L'] - _ov) if LEV['L'] != 1.0 else cash\n"
           "        buf = io.StringIO()\n"
           "        with contextlib.redirect_stdout(buf):\n"
           "            cmd_plan(hist_path, quotes_path, _bp, [])\n")
src = _sub(src, "        day_equity[D] = cash + open_val\n",
           "        if LEV['L'] != 1.0 and cash < 0:\n"
           "            LEV['interest'] += -cash * LEV['rate'] / 252\n"
           "            cash -= -cash * LEV['rate'] / 252\n"
           "        day_equity[D] = cash + open_val\n"
           "        LEV['ratio'].append((D, (cash + open_val) / open_val if open_val > 0 else 1.0, cash))\n")
H.LEV = {'L': 1.0, 'rate': RATE, 'interest': 0.0, 'ratio': []}
exec(compile(src, '<run_lev>', 'exec'), H.__dict__)


def run(L, start=START, end=END, cap=CAP, tag='lev'):
    H.LEV.update(L=L, interest=0.0, ratio=[])
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        r = H.run_lev(start, end, cap, R.ENGINE, tag=f'{tag}_{L}', daily_path=DAILY, hourly_path=HOURLY,
                      cost_bps=5.0)
    eq = sorted(r['day_equity'].items())
    peak, dd = 0.0, 0.0
    for _, v in eq:
        peak = max(peak, v); dd = min(dd, v / peak - 1)
    by_month, prev = [], cap
    for m in MONTH_ENDS:
        v = [x for d, x in eq if d <= m][-1]
        by_month.append((m[:7], v - prev)); prev = v
    worst = min(H.LEV['ratio'], key=lambda t: t[1])
    return {'end': eq[-1][1], 'peak': max(v for _, v in eq), 'dd': dd * 100, 'months': by_month,
            'interest': H.LEV['interest'], 'min_ratio': worst, 'max_debt': -min(c for _, _, c in H.LEV['ratio']),
            'trades': r['trade_count'], 'realized': r['realized']}


if __name__ == '__main__':
    g = R.replay(start='2026-03-13', end='2026-09-21', params={}, tag='lev_gate0', cost_bps=5.0,
                 daily=P1.DAILY, hourly=P1.HOURLY)
    H.LEV.update(L=1.0)
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        g1 = H.run_lev('2026-03-13', '2026-09-21', 80000.0, R.ENGINE, tag='lev_gate1', daily_path=P1.DAILY,
                       hourly_path=P1.HOURLY, cost_bps=5.0)
    if abs(g['realized'] - 124289.71) > 0.005 or abs(g1['realized'] - g['realized']) > 0.005:
        raise SystemExit(f"GATE FAILED: {g['realized']} / {g1['realized']}")
    print('gate PASS: L=1.0 reproduces production ($124,289.71)\n')
    res = {L: run(L) for L in (1.0, 1.4, 1.8)}
    for L, s in res.items():
        d, ratio, _ = s['min_ratio']
        print(f"L={L}: ${CAP:,.0f} -> ${s['end']:,.0f} ({(s['end'] / CAP - 1) * 100:+.1f}%)  peak ${s['peak']:,.0f}  "
              f"worst drop {s['dd']:.1f}%  interest ${s['interest']:,.0f}  max debt ${s['max_debt']:,.0f}  "
              f"lowest equity/positions {ratio:.0%} on {d}{'  <-- below ~30% maintenance' if ratio < MAINT else ''}")
    print(f"\n{'month':8}" + ''.join(f"{'L=' + str(L):>12}" for L in res))
    for i, (m, _) in enumerate(res[1.0]['months']):
        print(f"{m:8}" + ''.join(f"{res[L]['months'][i][1]:>+12,.0f}" for L in res))
