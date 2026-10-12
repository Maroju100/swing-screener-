#!/usr/bin/env python3
"""Two lower-risk setups for Margin-Style Live, tested by full engine replay.

Asked 2026-10-12, after margin_style_drawdown_rules.py rejected three rules:
"can you also test the two options that weren't tested, if I want lower risk".
Settings below were fixed BEFORE any run.

OPTION 1 -- RUN THE STRATEGY ON PART OF THE ACCOUNT
  Pass only a fraction f of buying power to the engine; the rest sits in cash.
  Measured, not assumed: the engine is replayed with f x $80k, and the ACCOUNT's
  equity is that engine equity plus the (1 - f) x $80k left idle. Fractions
  100 / 75 / 50 / 25%. Not a rule choice (nothing is selected from the results),
  so there is no overfitting question -- the point is to measure whether risk
  and return scale down together, and by how much.

OPTION 2 -- PAUSE AFTER A STOP-OUT STREAK
  If the circuit breaker (2+ STOPs in one run) fired on 2 or more of the last 5
  runs, block new buys for the next 3 runs. Exits are never blocked. Different
  from rule A of the drawdown study (which paused after EVERY breaker for one
  run): this waits for a streak, then steps aside for longer.
  Pass criteria (same as the drawdown study, fixed in advance): smaller max
  drawdown than production on the full window, both halves and both 30-minute
  marks, AND full-window P&L not significantly worse (bootstrap P(better)>=0.10).

Gates: anchor $124,080.90; option-2 patch off == production to the cent;
option 1 at f=100% == production. $80k, 5 bps per side.

Reproduce:
    python3 scripts/margin_style_lower_risk.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import margin_style_17h_backtest as H
import margin_style_intraday_study as I
import margin_style_research as R

OUT = os.path.join(I.RESULTS, 'lower_risk.json')
CAPITAL = 80000.0
COST = 5.0
FULL = ('2026-03-13', '2026-09-21')
HALVES = {'rising (Mar 13-Jun 19)': ('2026-03-13', '2026-06-19'),
          'falling (Jun 22-Sep 21)': ('2026-06-22', '2026-09-21')}
FINE = ('2026-06-22', '2026-09-21')
MARKS = ('17:00', '17:30')
FRACTIONS = (1.0, 0.75, 0.5, 0.25)
STREAK = {'STREAK_PAUSE': True}


def _sub(src, old, new):
    n = src.count(old)
    if n != 1:
        raise SystemExit(f'patch anchor matched {n}x, expected 1:\n{old[:160]}')
    return src.replace(old, new)


def patch_streak(src):
    src = _sub(src, "MAX_HOLD_DAYS = 6\n",
               "MAX_HOLD_DAYS = 6\n"
               "STREAK_PAUSE = False\n"
               "STREAK_WINDOW = 5\n"
               "STREAK_MIN_BREAKERS = 2\n"
               "STREAK_PAUSE_RUNS = 3\n")
    src = _sub(src,
               "    risk_state = {'equity_peak': round(equity_peak, 2), 'kill_switch_active': kill_switch_active,\n",
               "    _pl = int(state.get('pause_left', 0))\n"
               "    _paused = STREAK_PAUSE and _pl > 0\n"
               "    if _pl > 0:\n"
               "        _pl -= 1\n"
               "    _hist = (list(state.get('cb_hist', [])) + [bool(circuit_breaker_triggered)])[-STREAK_WINDOW:]\n"
               "    if STREAK_PAUSE and _pl == 0 and sum(_hist) >= STREAK_MIN_BREAKERS:\n"
               "        _pl, _hist = STREAK_PAUSE_RUNS, []\n"
               "    risk_state = {'equity_peak': round(equity_peak, 2), 'kill_switch_active': kill_switch_active,\n")
    src = _sub(src,
               "                  'trend_gate_active': trend_gate_active}\n",
               "                  'trend_gate_active': trend_gate_active,\n"
               "                  'pause_left': _pl, 'cb_hist': _hist}\n")
    src = _sub(src,
               "        state['trend_gate_active'] = actions['risk_state']['trend_gate_active']\n",
               "        state['trend_gate_active'] = actions['risk_state']['trend_gate_active']\n"
               "        state['pause_left'] = actions['risk_state'].get('pause_left', 0)\n"
               "        state['cb_hist'] = actions['risk_state'].get('cb_hist', [])\n")
    src = _sub(src,
               "    candidates = []\n    if not circuit_breaker_triggered and not kill_switch_active:\n",
               "    candidates = []\n    if not circuit_breaker_triggered and not kill_switch_active and not _paused:\n")
    return src


PATCH = [patch_streak]


def hourly(s, e, params, tag, capital=CAPITAL):
    return R.replay(start=s, end=e, params=params, tag=tag, src_patches=PATCH,
                    cost_bps=COST, capital=capital)


def fine(mark, params, tag, capital=CAPITAL):
    return I.replay_intraday(FINE[0], FINE[1], check_times=(mark,), tag=tag, params=params,
                             src_patches=PATCH, cost_bps=COST, capital=capital,
                             use_hourly_at_1700=False, exact_open=True)


def account_curve(r, idle):
    return [v + idle for _, v in sorted(r['day_equity'].items())]


def max_dd(eq):
    peak, m = -1e18, 0.0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            m = min(m, v / peak - 1)
    return round(m * 100, 2)


def worst_week(eq):
    """Worst 5-trading-day change in account equity, % of the starting value."""
    if len(eq) < 6:
        return 0.0
    return round(min((eq[i] - eq[i - 5]) / eq[i - 5] for i in range(5, len(eq))) * 100, 2)


def acct(r, f):
    """Account-level figures when the engine runs on f of the capital."""
    idle = CAPITAL * (1 - f)
    eq = account_curve(r, idle)
    return {'realized': round(r['realized'], 2), 'return_pct': round(r['realized'] / CAPITAL * 100, 2),
            'max_dd_pct': max_dd(eq), 'worst_week_pct': worst_week(eq),
            'sharpe': round(R.sharpe_of([(eq[i] / eq[i - 1] - 1) for i in range(1, len(eq))]), 2)}


def main():
    a = H.run('2026-03-13', '2026-09-04', 80000.0, '859057e', tag='lr_anchor')
    if a['realized'] != 124080.90:
        raise SystemExit('ANCHOR FAILED -- refusing to emit.')
    base = R.replay(tag='lr_base', cost_bps=COST)
    off = hourly(FULL[0], FULL[1], None, 'lr_off')
    if off['realized'] != base['realized'] or off['trade_count'] != base['trade_count']:
        raise SystemExit(f"PATCH NOT A NO-OP: {off['realized']} vs {base['realized']}")
    print(f"gates PASS: anchor $124,080.90; patch off == production "
          f"(${base['realized']:,.2f}, {base['trade_count']} trades)\n")

    # ---------------- option 1: fraction of the account ----------------
    opt1 = []
    for f in FRACTIONS:
        cap = CAPITAL * f
        rf = hourly(FULL[0], FULL[1], None, f'lr_f{int(f*100)}', capital=cap)
        if f == 1.0 and rf['realized'] != base['realized']:
            raise SystemExit('fraction 100% does not reproduce production')
        rh = {h: hourly(s, e, None, f'lr_f{int(f*100)}{h[:4]}', capital=cap) for h, (s, e) in HALVES.items()}
        rn = {m: fine(m, None, f'lr_f{int(f*100)}m{m[:2]}{m[3:]}', capital=cap) for m in MARKS}
        row = {'fraction': f, 'full': acct(rf, f),
               'halves': {h: acct(r, f) for h, r in rh.items()},
               'fine': {m: acct(r, f) for m, r in rn.items()},
               'scale_vs_full': round(rf['realized'] / base['realized'], 4)}
        opt1.append(row)
        x = row['full']
        print(f"run on {f:>4.0%} of the account: return {x['return_pct']:>+7.1f}%  maxDD {x['max_dd_pct']:>6.1f}%  "
              f"worst week {x['worst_week_pct']:>6.1f}%  sharpe {x['sharpe']:.2f}  "
              f"(P&L = {row['scale_vs_full']:.3f} x full)")

    # ---------------- option 2: streak pause ----------------
    days = sorted(base['day_pnl']); k = len(days) // 3
    thirds = [(days[0], days[k - 1]), (days[k], days[2 * k - 1]), (days[2 * k], days[-1])]
    P = {'thirds': [hourly(s, e, None, f'lr_pt{i}') for i, (s, e) in enumerate(thirds)],
         'halves': {h: hourly(s, e, None, f'lr_ph{h[:4]}') for h, (s, e) in HALVES.items()},
         'fine': {m: fine(m, None, f'lr_pf{m[:2]}{m[3:]}') for m in MARKS}}
    V = {'full': hourly(FULL[0], FULL[1], STREAK, 'lr_vf'),
         'thirds': [hourly(s, e, STREAK, f'lr_vt{i}') for i, (s, e) in enumerate(thirds)],
         'halves': {h: hourly(s, e, STREAK, f'lr_vh{h[:4]}') for h, (s, e) in HALVES.items()},
         'fine': {m: fine(m, STREAK, f'lr_vm{m[:2]}{m[3:]}') for m in MARKS}}
    lo, hi, p = R.block_bootstrap_diff(R.daily_returns(V['full']), R.daily_returns(base))

    def ddv(r):
        return max_dd(account_curve(r, 0.0))
    dd_checks = {
        'full window': ddv(V['full']) > ddv(base),
        'both halves': all(ddv(V['halves'][h]) > ddv(P['halves'][h]) for h in HALVES),
        'both 30-min marks': all(ddv(V['fine'][m]) > ddv(P['fine'][m]) for m in MARKS),
    }
    pnl_checks = {
        'full window': V['full']['realized'] > base['realized'],
        'all 3 thirds': all(v['realized'] > b['realized'] for v, b in zip(V['thirds'], P['thirds'])),
        'both halves': all(V['halves'][h]['realized'] > P['halves'][h]['realized'] for h in HALVES),
        'both 30-min marks': all(V['fine'][m]['realized'] > P['fine'][m]['realized'] for m in MARKS),
        'bootstrap CI excludes 0': lo > 0,
    }
    dd_pass, cost_ok = all(dd_checks.values()), p >= 0.10
    opt2 = {'settings': {'window': 5, 'min_breakers': 2, 'pause_runs': 3},
            'production': {'full': acct(base, 1.0), 'halves': {h: acct(r, 1.0) for h, r in P['halves'].items()},
                           'fine': {m: acct(r, 1.0) for m, r in P['fine'].items()},
                           'thirds_pct': [round(r['realized'] / CAPITAL * 100, 2) for r in P['thirds']],
                           'trades': base['trade_count']},
            'variant': {'full': acct(V['full'], 1.0), 'halves': {h: acct(r, 1.0) for h, r in V['halves'].items()},
                        'fine': {m: acct(r, 1.0) for m, r in V['fine'].items()},
                        'thirds_pct': [round(r['realized'] / CAPITAL * 100, 2) for r in V['thirds']],
                        'trades': V['full']['trade_count']},
            'bootstrap': {'ci_daily': [lo, hi], 'p_better': p},
            'dd_checks': dd_checks, 'pnl_checks': pnl_checks,
            'verdict': ('CANDIDATE -- less drawdown, cost not significant' if dd_pass and cost_ok
                        else 'less drawdown but significantly costlier' if dd_pass
                        else 'NOT AN IMPROVEMENT')}
    pv, vv = opt2['production']['full'], opt2['variant']['full']
    print(f"\nstreak pause (2 breakers in 5 runs -> no buys for 3 runs)")
    print(f"   production: {pv['return_pct']:+.1f}%  maxDD {pv['max_dd_pct']:.1f}%  worst week {pv['worst_week_pct']:.1f}%")
    print(f"   variant:    {vv['return_pct']:+.1f}%  maxDD {vv['max_dd_pct']:.1f}%  worst week {vv['worst_week_pct']:.1f}%  "
          f"P(better)={p:.2f}  dd {sum(dd_checks.values())}/3  pnl {sum(pnl_checks.values())}/5  -> {opt2['verdict']}")
    json.dump({'generated': '2026-10-12', 'engine': R.ENGINE, 'capital': CAPITAL, 'cost_bps': COST,
               'option1_fraction': opt1, 'option2_streak_pause': opt2}, open(OUT, 'w'), indent=1)
    print(f'\nwrote {OUT}')


if __name__ == '__main__':
    main()
