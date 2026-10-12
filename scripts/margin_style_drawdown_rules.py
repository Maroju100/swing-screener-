#!/usr/bin/env python3
"""Three drawdown-control rules for Margin-Style Live, tested by full engine replay.

Asked 2026-10-12, after the missed-week replay showed the live rules would have
lost ~$2,280 (10-05..10-12) by buying a dip, getting stopped the next run, and
buying again -- three times: "can you think of some rules or setup that can be
added to the live setup to avoid such drawdowns?"

THE IDEAS (proposed and fixed BEFORE any run -- nothing tuned to a result)
  A  WHIPSAW_PAUSE   If the previous run's circuit breaker fired (2+ STOPs), block
                     new buys this run too. The live breaker only blocks the run it
                     fires in; the missed week re-bought the very next run each time.
  B  BREADTH_GATE    Skip NORMAL_DIP entries when 6 or more of the 8 stocks closed
                     down on the last completed day (a basket-wide selloff, not a
                     single-name dip). HUGE_DIP unaffected. Causal: completed closes.
  C  DD_THROTTLE     Scale every buy by (1 + drawdown / 0.15), floored at 0, where
                     drawdown is total_equity vs equity_peak. Full size at the peak,
                     half size at -7.5%, zero at -15% (where the kill-switch sits).
  Already tested and rejected, NOT re-run here (see engine comments / CLAUDE.md):
  per-symbol STOP cooldown, a same-day total deployment cap, 3+ down-day quality
  filter, waiting for a bounce, a daily loss stop, tighter per-trade/symbol caps.

PASS CRITERIA (fixed in advance; the question is drawdown, so two tiers)
  DRAWDOWN check (all must hold): smaller max drawdown than production on the
    full window, in both halves, and at both 30-minute marks.
  COST check: full-window P&L not significantly worse -- bootstrap P(variant
    better) >= 0.10 on daily returns.
  A rule that passes BOTH is a forward-tracking candidate, not a change. The
  standard 5 P&L checks are also reported for comparison with earlier studies.
  The missed week (10-05..10-12, outside the replay window) is reported as an
  illustration only: it is the case that motivated the ideas, so it is in-sample
  by construction and is NOT one of the checks.

Every patch switched off must reproduce production exactly, or nothing is reported.
$80k, 5 bps per side.

Reproduce:
    python3 scripts/margin_style_drawdown_rules.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import margin_style_17h_backtest as H
import margin_style_intraday_study as I
import margin_style_missed_week_replay as MW
import margin_style_research as R

OUT = os.path.join(I.RESULTS, 'drawdown_rules.json')
CAPITAL = 80000.0
COST = 5.0
FULL = ('2026-03-13', '2026-09-21')
HALVES = {'rising (Mar 13-Jun 19)': ('2026-03-13', '2026-06-19'),
          'falling (Jun 22-Sep 21)': ('2026-06-22', '2026-09-21')}
FINE = ('2026-06-22', '2026-09-21')
MARKS = ('17:00', '17:30')


def _sub(src, old, new):
    n = src.count(old)
    if n != 1:
        raise SystemExit(f'patch anchor matched {n}x, expected 1:\n{old[:160]}')
    return src.replace(old, new)


def patch_dd(src):
    src = _sub(src, "MAX_HOLD_DAYS = 6\n",
               "MAX_HOLD_DAYS = 6\n"
               "WHIPSAW_PAUSE = False\n"
               "BREADTH_GATE = False\n"
               "BREADTH_MAX_DOWN = 6\n"
               "DD_THROTTLE = False\n"
               "DD_THROTTLE_ZERO_AT = 0.15\n")
    # A: remember whether this run's breaker fired; block the next run's buys
    src = _sub(src,
               "                  'trend_gate_active': trend_gate_active}\n",
               "                  'trend_gate_active': trend_gate_active,\n"
               "                  'cb_prev': circuit_breaker_triggered}\n")
    src = _sub(src,
               "        state['trend_gate_active'] = actions['risk_state']['trend_gate_active']\n",
               "        state['trend_gate_active'] = actions['risk_state']['trend_gate_active']\n"
               "        state['cb_prev'] = actions['risk_state'].get('cb_prev', False)\n")
    # B: basket breadth from the last two COMPLETED closes
    src = _sub(src,
               "    candidates = []\n    if not circuit_breaker_triggered and not kill_switch_active:\n",
               "    _br_down = sum(1 for _b in bars_by_sym.values()\n"
               "                   if len(_b) >= 2 and _b[-1]['close'] < _b[-2]['close'])\n"
               "    _breadth_block = BREADTH_GATE and _br_down >= BREADTH_MAX_DOWN\n"
               "    _whipsaw_block = WHIPSAW_PAUSE and state.get('cb_prev', False)\n"
               "    candidates = []\n"
               "    if not circuit_breaker_triggered and not kill_switch_active and not _whipsaw_block:\n")
    src = _sub(src,
               "            elif day_return <= -NORMAL_DIP_THRESHOLD and (not pos or pos.get('tranches', 0) < MAX_TRANCHES):\n",
               "            elif (day_return <= -NORMAL_DIP_THRESHOLD and not _breadth_block\n"
               "                  and (not pos or pos.get('tranches', 0) < MAX_TRANCHES)):\n")
    # C: size multiplier from drawdown vs the system's own high-water mark
    src = _sub(src,
               "        uncapped_deploy = safe_cash * pct\n",
               "        _dd_now = (total_equity / equity_peak - 1) if equity_peak > 0 else 0.0\n"
               "        _thr = max(0.0, 1 + _dd_now / DD_THROTTLE_ZERO_AT) if DD_THROTTLE else 1.0\n"
               "        uncapped_deploy = safe_cash * pct * min(1.0, _thr)\n")
    src = _sub(src,
               "        deploy = min(uncapped_deploy, trade_cap_pct * total_equity)\n",
               "        deploy = min(uncapped_deploy, trade_cap_pct * total_equity * min(1.0, _thr))\n")
    return src


PATCH = [patch_dd]
VARIANTS = [
    ('A Whipsaw pause: no buys the run after a circuit breaker', {'WHIPSAW_PAUSE': True}),
    ('B Breadth gate: no dip buys when 6+ of 8 fell', {'BREADTH_GATE': True}),
    ('C Drawdown throttle: size x (1 + dd/15%)', {'DD_THROTTLE': True}),
]


def hourly(s, e, params, tag):
    return R.replay(start=s, end=e, params=params, tag=tag, src_patches=PATCH, cost_bps=COST)


def fine(mark, params, tag):
    return I.replay_intraday(FINE[0], FINE[1], check_times=(mark,), tag=tag, params=params,
                             src_patches=PATCH, cost_bps=COST, capital=CAPITAL,
                             use_hourly_at_1700=False, exact_open=True)


def pct(r):
    return round(r['realized'] / CAPITAL * 100, 2)


def dd(r):
    """Max drawdown in % (negative) from the run's own daily equity curve."""
    eq = [v for _, v in sorted(r['day_equity'].items())]
    peak, m = -1e18, 0.0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            m = min(m, v / peak - 1)
    return round(m * 100, 2)


def missed_week(params):
    MW.SRC_PATCH, MW.PARAMS = patch_dd, dict(params or {})
    data = json.load(open(MW.PRICES))
    with tempfile.TemporaryDirectory() as tmp:
        rows = MW.run_path(MW.DAYS, data, 0.0, tmp)
    MW.SRC_PATCH, MW.PARAMS = None, {}
    return rows


def main():
    a = H.run('2026-03-13', '2026-09-04', 80000.0, '859057e', tag='dd_anchor')
    if a['realized'] != 124080.90:
        raise SystemExit('ANCHOR FAILED -- refusing to emit.')
    base = R.replay(tag='dd_base', cost_bps=COST)
    off = hourly(FULL[0], FULL[1], None, 'dd_off')
    if off['realized'] != base['realized'] or off['trade_count'] != base['trade_count']:
        raise SystemExit(f"PATCH NOT A NO-OP: {off['realized']} vs {base['realized']}")
    mw_off = missed_week(None)
    if abs(mw_off[-1]['equity_post_run'] - 15541.39) > 0.005:
        raise SystemExit(f"missed-week no-op gate failed: {mw_off[-1]['equity_post_run']}")
    print(f"gates PASS: anchor $124,080.90; patch off == production (${base['realized']:,.2f}, "
          f"{base['trade_count']} trades); missed week off == 15,541.39\n")

    days = sorted(base['day_pnl']); k = len(days) // 3
    thirds = [(days[0], days[k - 1]), (days[k], days[2 * k - 1]), (days[2 * k], days[-1])]
    P = {'full': base,
         'thirds': [hourly(s, e, None, f'dd_pt{i}') for i, (s, e) in enumerate(thirds)],
         'halves': {h: hourly(s, e, None, f'dd_ph{h[:4]}') for h, (s, e) in HALVES.items()},
         'fine': {m: fine(m, None, f'dd_pf{m[:2]}{m[3:]}') for m in MARKS}}
    prod = {'full_pct': pct(base), 'full_dd': dd(base), 'sharpe': R.summarize(base)['sharpe'],
            'trades': base['trade_count'],
            'thirds_pct': [pct(r) for r in P['thirds']],
            'halves_pct': {h: pct(r) for h, r in P['halves'].items()},
            'halves_dd': {h: dd(r) for h, r in P['halves'].items()},
            'fine_pct': {m: pct(r) for m, r in P['fine'].items()},
            'fine_dd': {m: dd(r) for m, r in P['fine'].items()},
            'missed_week_end': mw_off[-1]['equity_post_run']}
    out = {'generated': '2026-10-12', 'engine': R.ENGINE, 'capital': CAPITAL, 'cost_bps': COST,
           'thirds': thirds, 'production': prod, 'variants': []}

    for i, (lbl, params) in enumerate(VARIANTS):
        vf = hourly(FULL[0], FULL[1], params, f'dd_v{i}f')
        vt = [hourly(s, e, params, f'dd_v{i}t{j}') for j, (s, e) in enumerate(thirds)]
        vh = {h: hourly(s, e, params, f'dd_v{i}h{h[:4]}') for h, (s, e) in HALVES.items()}
        vn = {m: fine(m, params, f'dd_v{i}m{m[:2]}{m[3:]}') for m in MARKS}
        lo, hi, p = R.block_bootstrap_diff(R.daily_returns(vf), R.daily_returns(base))
        mw = missed_week(params)
        # max_dd_pct is negative; "smaller drawdown" = closer to zero = greater
        dd_checks = {
            'full window': dd(vf) > prod['full_dd'],
            'both halves': all(dd(vh[h]) > prod['halves_dd'][h] for h in HALVES),
            'both 30-min marks': all(dd(vn[m]) > prod['fine_dd'][m] for m in MARKS),
        }
        pnl_checks = {
            'full window': vf['realized'] > base['realized'],
            'all 3 thirds': all(v['realized'] > b['realized'] for v, b in zip(vt, P['thirds'])),
            'both halves': all(vh[h]['realized'] > P['halves'][h]['realized'] for h in HALVES),
            'both 30-min marks': all(vn[m]['realized'] > P['fine'][m]['realized'] for m in MARKS),
            'bootstrap CI excludes 0': lo > 0,
        }
        dd_pass, cost_ok = all(dd_checks.values()), p >= 0.10
        row = {'variant': lbl, 'params': params,
               'full_pct': pct(vf), 'full_dd': dd(vf), 'sharpe': R.summarize(vf)['sharpe'],
               'trades': vf['trade_count'], 'full_delta': round(vf['realized'] - base['realized'], 2),
               'thirds_pct': [pct(r) for r in vt],
               'halves_pct': {h: pct(r) for h, r in vh.items()},
               'halves_dd': {h: dd(r) for h, r in vh.items()},
               'fine_pct': {m: pct(r) for m, r in vn.items()},
               'fine_dd': {m: dd(r) for m, r in vn.items()},
               'bootstrap': {'ci_daily': [lo, hi], 'p_better': p},
               'dd_checks': dd_checks, 'pnl_checks': pnl_checks,
               'pnl_checks_passed': sum(pnl_checks.values()),
               'missed_week_end': mw[-1]['equity_post_run'],
               'missed_week_vs_prod': round(mw[-1]['equity_post_run'] - prod['missed_week_end'], 2),
               'verdict': ('CANDIDATE -- less drawdown, cost not significant' if dd_pass and cost_ok
                           else 'less drawdown but significantly costlier' if dd_pass
                           else 'NOT AN IMPROVEMENT')}
        out['variants'].append(row)
        print(f"{lbl}\n   6mo {row['full_pct']:+.1f}% (prod {prod['full_pct']:+.1f}%)  maxDD "
              f"{row['full_dd']:.1f}% (prod {prod['full_dd']:.1f}%)  P(better)={p:.2f}  "
              f"dd {sum(dd_checks.values())}/3  pnl {row['pnl_checks_passed']}/5  "
              f"missed week {row['missed_week_vs_prod']:+,.0f}  -> {row['verdict']}")
    json.dump(out, open(OUT, 'w'), indent=1)
    print(f'\nwrote {OUT}')


if __name__ == '__main__':
    main()
