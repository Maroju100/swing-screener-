#!/usr/bin/env python3
"""Three SIZING rules for Margin-Style Live, tested by full engine replay.

Asked 2026-10-12: "come up with a better setup that can take care of bad weeks
like this" -- after five timing rules (pause after a breaker, breadth gate,
drawdown throttle, streak pause, and earlier a per-symbol cooldown / daily cap)
all failed for the same reason: skipping buys after bad days also skips the
rebound the strategy is paid for. These rules leave WHEN to buy untouched and
change only HOW MUCH is at risk. Settings fixed BEFORE any run.

  D  VOL_SIZE      Scale each buy (and its per-trade cap) by min(1, 3% / the stock's
                   standard deviation of daily returns over its last 20 completed
                   closes). Wild names get smaller positions; never scaled up.
  E  EXPOSURE_CAP  Total stock holdings may not exceed 60% of total equity after a
                   run's buys; buys are trimmed or skipped to respect it.
  F  MAX_NEW_BUYS  At most 2 buys per run (deepest drawdown first, as now), so
                   one run cannot spread the account over 5 correlated names.

Pass criteria, battery, gates and the missed-week illustration are identical to
margin_style_drawdown_rules.py (from which the harness code is reused).

Reproduce:
    python3 scripts/margin_style_sizing_rules.py
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

OUT = os.path.join(I.RESULTS, 'sizing_rules.json')
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


def patch_size(src):
    src = _sub(src, "MAX_HOLD_DAYS = 6\n",
               "MAX_HOLD_DAYS = 6\n"
               "VOL_SIZE = False\n"
               "VOL_TARGET = 0.03\n"
               "VOL_DAYS = 20\n"
               "EXPOSURE_CAP = None\n"
               "MAX_NEW_BUYS = None\n")
    # exposure already held going into the buy loop (positions not fully exited this run)
    src = _sub(src,
               "    buys = []\n    netted_symbols = set()\n",
               "    buys = []\n    netted_symbols = set()\n"
               "    _invested = sum(p['shares'] * quotes.get(s, 0.0) for s, p in state['open_positions'].items()\n"
               "                    if s not in full_exit_symbols)\n")
    src = _sub(src,
               "        uncapped_deploy = safe_cash * pct\n",
               "        _vm = 1.0\n"
               "        if VOL_SIZE:\n"
               "            _cl = [b['close'] for b in bars_by_sym[sym][-(VOL_DAYS + 1):]]\n"
               "            _rt = [_cl[i] / _cl[i - 1] - 1 for i in range(1, len(_cl))]\n"
               "            if len(_rt) >= 2:\n"
               "                _mu = sum(_rt) / len(_rt)\n"
               "                _sd = (sum((x - _mu) ** 2 for x in _rt) / (len(_rt) - 1)) ** 0.5\n"
               "                _vm = min(1.0, VOL_TARGET / _sd) if _sd > 0 else 1.0\n"
               "        uncapped_deploy = safe_cash * pct * _vm\n")
    src = _sub(src,
               "        deploy = min(uncapped_deploy, trade_cap_pct * total_equity)\n",
               "        deploy = min(uncapped_deploy, trade_cap_pct * total_equity * _vm)\n")
    src = _sub(src,
               "        capped = min(deploy, room)\n",
               "        capped = min(deploy, room)\n"
               "        if EXPOSURE_CAP is not None:\n"
               "            capped = min(capped, max(0.0, EXPOSURE_CAP * total_equity - _invested))\n"
               "        if MAX_NEW_BUYS is not None and len(buys) >= MAX_NEW_BUYS:\n"
               "            break\n")
    src = _sub(src,
               "        safe_cash -= actual_deploy  # subsequent symbols this run see reduced remaining cash\n",
               "        safe_cash -= actual_deploy  # subsequent symbols this run see reduced remaining cash\n"
               "        _invested += actual_deploy\n")
    return src


PATCH = [patch_size]
VARIANTS = [
    ('D Volatility sizing: buy x min(1, 3% / 20-day vol)', {'VOL_SIZE': True}),
    ('E Exposure cap: at most 60% of equity in stocks', {'EXPOSURE_CAP': 0.60}),
    ('F At most 2 new buys per run', {'MAX_NEW_BUYS': 2}),
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
    MW.SRC_PATCH, MW.PARAMS = patch_size, dict(params or {})
    data = json.load(open(MW.PRICES))
    with tempfile.TemporaryDirectory() as tmp:
        rows = MW.run_path(MW.DAYS, data, 0.0, tmp)
    MW.SRC_PATCH, MW.PARAMS = None, {}
    return rows


def main():
    a = H.run('2026-03-13', '2026-09-04', 80000.0, '859057e', tag='sz_anchor')
    if a['realized'] != 124080.90:
        raise SystemExit('ANCHOR FAILED -- refusing to emit.')
    base = R.replay(tag='sz_base', cost_bps=COST)
    off = hourly(FULL[0], FULL[1], None, 'sz_off')
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
         'thirds': [hourly(s, e, None, f'sz_pt{i}') for i, (s, e) in enumerate(thirds)],
         'halves': {h: hourly(s, e, None, f'sz_ph{h[:4]}') for h, (s, e) in HALVES.items()},
         'fine': {m: fine(m, None, f'sz_pf{m[:2]}{m[3:]}') for m in MARKS}}
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
        vf = hourly(FULL[0], FULL[1], params, f'sz_v{i}f')
        vt = [hourly(s, e, params, f'sz_v{i}t{j}') for j, (s, e) in enumerate(thirds)]
        vh = {h: hourly(s, e, params, f'sz_v{i}h{h[:4]}') for h, (s, e) in HALVES.items()}
        vn = {m: fine(m, params, f'sz_v{i}m{m[:2]}{m[3:]}') for m in MARKS}
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
               'sz_checks': dd_checks, 'pnl_checks': pnl_checks,
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
