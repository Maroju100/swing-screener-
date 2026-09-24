#!/usr/bin/env python3
"""Four new rule ideas for Margin-Style Live, tested by full engine replay.

Asked 2026-09-24: "can you think of better rules than above that can increase
the pl" -> "test all four". The ideas were proposed BEFORE any of them was run,
and their settings are fixed below. Nothing here was tuned after seeing a
result -- that is what keeps this from being another grid search that finds a
winner on the window it was fitted to.

THE IDEAS (settings fixed in advance)
  1  REGIME      When >= half the 8 stocks closed above their own 50-day average
                 (a rising market), trim 30% on a new high instead of 74.3% and
                 hold up to 10 days instead of 6. Otherwise the live rules.
                 Motivation: in the rising half of the backtest the live rules
                 made +68% while holding the basket made +155%.
  2a EQUAL_SPLIT Split cash evenly across every stock that qualifies that day,
                 instead of letting the first few in line take 25% each.
  2b DAY_DROP    Rank qualifiers by yesterday's drop instead of by distance
                 below the 60-day high.
  3  BOUNCE      Buy a NORMAL_DIP qualifier only if it is trading at or above
                 yesterday's close at the check (the bounce has started).
  4  MIN_ORDER   Skip any buy under $500 (engine default MIN_NOTIONAL is $25).

METHOD (Evidence Rule 1 -- every number is a replay of origin/main)
  Each idea is one anchored source patch whose disabled state reproduces the
  live engine EXACTLY (asserted before anything is reported). Idea 4 is a
  plain setting. Every variant is measured on:
    * hourly bars, 2026-03-13 -> 2026-09-21 (132 days), the committed basis
    * each third of that window, each replayed from a flat start
    * the rising half (Mar 13 - Jun 19) and falling half (Jun 22 - Sep 21)
    * 30-minute bars at 17:00 and 17:30 UTC (the more accurate series)
    * a moving-block bootstrap on the full-window daily-return difference
  $80k, 5 bps per side throughout.

PASS CRITERIA (fixed in advance): beat production on the full window, in all
three thirds, in both halves, at both 30-minute marks, AND a bootstrap CI that
excludes zero. Five variants are tested, so even one pass could be chance at
the 5% level; a pass would be a candidate for forward tracking, not a change.

Reproduce:
    python3 scripts/margin_style_rule_ideas.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import margin_style_17h_backtest as H
import margin_style_intraday_study as I
import margin_style_research as R

OUT = os.path.join(I.RESULTS, 'rule_ideas.json')
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
        raise SystemExit(f'patch anchor matched {n}x, expected 1:\n{old[:120]}')
    return src.replace(old, new)


def patch_ideas(src):
    """All four structural ideas, each behind its own switch, all OFF by default."""
    src = _sub(src, "MAX_HOLD_DAYS = 6\n",
               "MAX_HOLD_DAYS = 6\n"
               "REGIME_ADAPTIVE = False\n"
               "REGIME_SMA_DAYS = 50\n"
               "REGIME_PEAK_SELL_PCT = 0.743\n"
               "REGIME_MAX_HOLD_DAYS = 6\n"
               "EQUAL_SPLIT = False\n"
               "RANK_BY_DAY_DROP = False\n"
               "BOUNCE_CONFIRM = False\n")
    # Idea 1: regime computed once per run from COMPLETED closes only (causal)
    src = _sub(src,
               "    pending_peak_gain = {}\n    peak_updates = {}\n"
               "    for sym, pos in list(state['open_positions'].items()):\n",
               "    _rg_n = 0\n    _rg_up_n = 0\n"
               "    for _s, _b in bars_by_sym.items():\n"
               "        if len(_b) >= REGIME_SMA_DAYS:\n"
               "            _rg_n += 1\n"
               "            if _b[-1]['close'] > sum(x['close'] for x in _b[-REGIME_SMA_DAYS:]) / REGIME_SMA_DAYS:\n"
               "                _rg_up_n += 1\n"
               "    _rg_up = REGIME_ADAPTIVE and _rg_n > 0 and _rg_up_n * 2 >= _rg_n\n"
               "    pending_peak_gain = {}\n    peak_updates = {}\n"
               "    for sym, pos in list(state['open_positions'].items()):\n")
    src = _sub(src,
               "        if 'opened' in pos and business_days_elapsed(pos['opened'], today) >= MAX_HOLD_DAYS:\n",
               "        if 'opened' in pos and business_days_elapsed(pos['opened'], today) >= "
               "(REGIME_MAX_HOLD_DAYS if _rg_up else MAX_HOLD_DAYS):\n")
    src = _sub(src,
               "            sell_shares = round(pos['shares'] * PEAK_SELL_PCT, 6)\n",
               "            sell_shares = round(pos['shares'] * "
               "(REGIME_PEAK_SELL_PCT if _rg_up else PEAK_SELL_PCT), 6)\n")
    # Idea 3: bounce confirmation, NORMAL_DIP only
    src = _sub(src,
               "            candidates.append({'symbol': sym, 'drawdown': drawdown, "
               "'day_return': day_return, 'reason': reason})\n",
               "            if BOUNCE_CONFIRM and reason == 'NORMAL_DIP' and quotes[sym] < yesterday_close:\n"
               "                continue\n"
               "            candidates.append({'symbol': sym, 'drawdown': drawdown, "
               "'day_return': day_return, 'reason': reason})\n")
    # Ideas 2a / 2b: ranking and equal split
    src = _sub(src,
               "    candidates.sort(key=lambda c: c['drawdown'])\n",
               "    candidates.sort(key=lambda c: (c['day_return'] if RANK_BY_DAY_DROP else c['drawdown']))\n"
               "    _eq_budget = (safe_cash / len(candidates)) if (EQUAL_SPLIT and candidates) else float('inf')\n")
    src = _sub(src,
               "        uncapped_deploy = safe_cash * pct\n",
               "        uncapped_deploy = min(safe_cash * pct, _eq_budget)\n")
    return src


PATCH = [patch_ideas]
VARIANTS = [
    ('1 Regime: trim 30% / hold 10d in rising market',
     {'REGIME_ADAPTIVE': True, 'REGIME_PEAK_SELL_PCT': 0.30, 'REGIME_MAX_HOLD_DAYS': 10}),
    ('2a Equal split across qualifiers', {'EQUAL_SPLIT': True}),
    ('2b Rank by yesterday\'s drop', {'RANK_BY_DAY_DROP': True}),
    ('3 Buy only once the bounce has started', {'BOUNCE_CONFIRM': True}),
    ('4 Skip buys under $500', {'MIN_NOTIONAL': 500.0}),
]


def hourly(start, end, params, tag):
    return R.replay(start=start, end=end, params=params, tag=tag,
                    src_patches=PATCH, cost_bps=COST)


def fine(mark, params, tag):
    return I.replay_intraday(FINE[0], FINE[1], check_times=(mark,), tag=tag,
                             params=params, src_patches=PATCH, cost_bps=COST,
                             capital=CAPITAL, use_hourly_at_1700=False, exact_open=True)


def thirds():
    days = sorted(hourly(FULL[0], FULL[1], None, 'ri_days')['day_pnl'])
    k = len(days) // 3
    return [(days[0], days[k - 1]), (days[k], days[2 * k - 1]), (days[2 * k], days[-1])]


def pct(r):
    return round(r['realized'] / CAPITAL * 100, 2)


def main():
    # Gate 1: the research harness still reproduces the published anchor
    a = H.run('2026-03-13', '2026-09-04', 80000.0, '859057e', tag='ri_anchor')
    if a['realized'] != 124080.90:
        raise SystemExit('ANCHOR FAILED -- refusing to emit.')
    # Gate 2: every patch, switched off or set neutral, IS the live engine
    base = R.replay(tag='ri_base', cost_bps=COST)
    for lbl, p in [('all off', None),
                   ('regime neutral', {'REGIME_ADAPTIVE': True, 'REGIME_PEAK_SELL_PCT': 0.743,
                                       'REGIME_MAX_HOLD_DAYS': 6})]:
        r = hourly(FULL[0], FULL[1], p, 'ri_neutral')
        if r['realized'] != base['realized'] or r['trade_count'] != base['trade_count']:
            raise SystemExit(f'PATCH NOT A NO-OP ({lbl}): {r["realized"]} vs {base["realized"]}')
    print(f"gates PASS: anchor $124,080.90; patches neutral == production "
          f"(${base['realized']:,.2f}, {base['trade_count']} trades)\n")

    tw = thirds()
    prod = {'full': base,
            'thirds': [hourly(s, e, None, f'ri_pt{i}') for i, (s, e) in enumerate(tw)],
            'halves': {k: hourly(s, e, None, f'ri_ph{k[:4]}') for k, (s, e) in HALVES.items()},
            'fine': {m: fine(m, None, f'ri_pf{m[:2]}{m[3:]}') for m in MARKS}}

    out = {'generated': '2026-09-24', 'engine': 'origin/main', 'capital': CAPITAL,
           'cost_bps': COST, 'thirds': tw, 'halves': HALVES, 'fine_window': FINE,
           'production': {
               'full_pct': pct(prod['full']),
               'full_summary': R.summarize(prod['full']),
               'thirds_pct': [pct(r) for r in prod['thirds']],
               'halves_pct': {k: pct(r) for k, r in prod['halves'].items()},
               'fine_pct': {m: pct(r) for m, r in prod['fine'].items()}},
           'variants': []}

    for i, (lbl, params) in enumerate(VARIANTS):
        v_full = hourly(FULL[0], FULL[1], params, f'ri_v{i}f')
        v_th = [hourly(s, e, params, f'ri_v{i}t{j}') for j, (s, e) in enumerate(tw)]
        v_hv = {k: hourly(s, e, params, f'ri_v{i}h{k[:4]}') for k, (s, e) in HALVES.items()}
        v_fn = {m: fine(m, params, f'ri_v{i}m{m[:2]}{m[3:]}') for m in MARKS}
        lo, hi, p = R.block_bootstrap_diff(R.daily_returns(v_full), R.daily_returns(base))
        checks = {
            'full window': v_full['realized'] > base['realized'],
            'all 3 thirds': all(v['realized'] > b['realized'] for v, b in zip(v_th, prod['thirds'])),
            'both halves': all(v_hv[k]['realized'] > prod['halves'][k]['realized'] for k in HALVES),
            'both 30-min marks': all(v_fn[m]['realized'] > prod['fine'][m]['realized'] for m in MARKS),
            'bootstrap CI excludes 0': lo > 0,
        }
        row = {'variant': lbl, 'params': params,
               'full_pct': pct(v_full), 'full_summary': R.summarize(v_full),
               'full_delta': round(v_full['realized'] - base['realized'], 2),
               'thirds_pct': [pct(r) for r in v_th],
               'halves_pct': {k: pct(r) for k, r in v_hv.items()},
               'fine_pct': {m: pct(r) for m, r in v_fn.items()},
               'bootstrap': {'ci_daily': [lo, hi], 'p_better': p},
               'checks': checks, 'checks_passed': sum(checks.values()),
               'verdict': 'PASS -- forward-track candidate' if all(checks.values())
                          else 'NOT AN IMPROVEMENT'}
        out['variants'].append(row)
        print(f"{lbl}: {row['checks_passed']}/5  full {row['full_pct']:+.1f}% "
              f"(prod {out['production']['full_pct']:+.1f}%)  -> {row['verdict']}")

    json.dump(out, open(OUT, 'w'), indent=1)
    print(f'\nwrote {OUT}')
    report(out)


def report(o):
    P = o['production']
    t = ['T1', 'T2', 'T3']
    print(f"\n{'':44}{'6mo':>8}{'T1':>8}{'T2':>8}{'T3':>8}{'rise':>8}{'fall':>8}{'12:00':>8}{'12:30':>8}  pass")
    hk = list(o['halves'])

    def line(name, full, th, hv, fn, extra=''):
        print(f"{name[:44]:44}{full:>+8.1f}" + ''.join(f"{x:>+8.1f}" for x in th)
              + ''.join(f"{hv[k]:>+8.1f}" for k in hk)
              + ''.join(f"{fn[m]:>+8.1f}" for m in MARKS) + f"  {extra}")
    line('PRODUCTION (live rules)', P['full_pct'], P['thirds_pct'], P['halves_pct'], P['fine_pct'])
    for v in o['variants']:
        line(v['variant'], v['full_pct'], v['thirds_pct'], v['halves_pct'], v['fine_pct'],
             f"{v['checks_passed']}/5")
    print('\nthirds:', ' | '.join(f'{a}..{b}' for a, b in o['thirds']))
    for v in o['variants']:
        b = v['bootstrap']
        print(f"  {v['variant'][:40]:40} CI [{b['ci_daily'][0]*100:+.3f}%, {b['ci_daily'][1]*100:+.3f}%] "
              f"P={b['p_better']:.3f}  maxDD {v['full_summary']['max_dd_pct']:.1f}% "
              f"(prod {P['full_summary']['max_dd_pct']:.1f}%)")


if __name__ == '__main__':
    main()
