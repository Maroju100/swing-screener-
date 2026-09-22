#!/usr/bin/env python3
"""Margin-Style Live rule research: baselines, costs, gaps, grid search, statistics.

EVERYTHING HERE GOES THROUGH FULL ENGINE REPLAY (Evidence Rule 1). No number in
this file is ever produced by post-processing a day_pnl series -- that method is
what invalidated the "1% daily stop +248.36%", "3x/day +2.7pp" and "close at
2:45 PM CDT" claims. The replay core is scripts/margin_style_17h_backtest.py,
which self-validates against the $124,080.90 anchor before it may be trusted;
cmd_baselines re-checks that anchor and REFUSES to emit research numbers if it
does not reproduce.

WHY THERE ARE TWO BASELINES
---------------------------
The published anchor ran on data BEGINNING at the window start, so its first ~60
days had incomplete HUGE_DIP (60-day high) and TREND_GATE (50-day SMA) lookback.
The extended dataset starts 2025-11-03, so the same window now runs with full
lookback from day one. MEASURED difference: $124,080.90 -> $124,353.48 (-0.2%).
Small, but real, and it is NOT a rule effect.

  * ANCHOR baseline   -- ramp-up lookback. Used ONLY to prove the harness sound.
  * RESEARCH baseline -- full lookback, extended window. EVERY variant compares
                         against this. Comparing a variant against the anchor
                         would book the lookback difference as a rule effect.

TRANSACTION COST
----------------
The original harness modelled ZERO friction across 771 trades. Real fills pay
the spread. `--cost-bps` is PER SIDE and is applied to executions, not signals
(slippage does not move a signal). Every headline here is reported at several
cost levels, because a result that only survives at zero cost is not a result.

USAGE
    python3 scripts/margin_style_research.py baselines
    python3 scripts/margin_style_research.py costs
    python3 scripts/margin_style_research.py gaps
    python3 scripts/margin_style_research.py grid [--folds 3]
    python3 scripts/margin_style_research.py variants
"""
import argparse
import contextlib
import io
import itertools
import json
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_17h_backtest as H  # noqa: E402  (the validated replay core)

ROOT = H.ROOT
DATA = os.path.join(ROOT, 'data')
RESULTS = os.path.join(DATA, 'research')

DAILY_EXT = os.path.join(DATA, 'margin_live_daily_ext_2025-11-03_2026-09-21.json')
HOURLY_EXT = os.path.join(DATA, 'margin_live_hourly_ext_2026-03-06_2026-09-22.json')
MIN30 = os.path.join(DATA, 'margin_live_30min_2026-06-22_2026-09-22.json')

ENGINE = 'origin/main'          # the revision that actually trades real money
CAPITAL = 80000.0
RESEARCH_START = '2026-03-13'
RESEARCH_END = '2026-09-21'

# Cost levels every headline is reported at. 0 is the legacy assumption and is
# kept only for comparability with the anchor.
COST_LEVELS = [0.0, 2.5, 5.0, 10.0]
DEFAULT_COST = 5.0   # the level conclusions are drawn at, unless stated otherwise


def replay(start=RESEARCH_START, end=RESEARCH_END, params=None, tag='res',
           engine=ENGINE, capital=CAPITAL, src_patches=None,
           daily=DAILY_EXT, hourly=HOURLY_EXT, cost_bps=0.0, price_field='close_price'):
    t0 = time.time()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        r = H.run(start, end, capital, engine, params=params, tag=tag,
                  src_patches=src_patches, daily_path=daily, hourly_path=hourly,
                  cost_bps=cost_bps, price_field=price_field)
    r['seconds'] = round(time.time() - t0, 2)
    return r


def daily_returns(r):
    eq = [v for _, v in sorted(r['day_equity'].items())]
    return [(eq[i] / eq[i - 1] - 1) for i in range(1, len(eq)) if eq[i - 1] > 0]


def sharpe_of(rets):
    n = len(rets)
    if n < 2:
        return 0.0
    m = sum(rets) / n
    sd = (sum((x - m) ** 2 for x in rets) / (n - 1)) ** 0.5
    return (m / sd * math.sqrt(252)) if sd > 0 else 0.0


def summarize(r):
    rets = daily_returns(r)
    eq = [v for _, v in sorted(r['day_equity'].items())]
    peak, maxdd = -1e18, 0.0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            maxdd = min(maxdd, v / peak - 1)
    return {
        'realized': r['realized'], 'total': r['total'],
        'realized_pct': r['realized_pct'], 'total_pct': r['total_pct'],
        'trades': r['trade_count'], 'days': r['trading_days'],
        'days_with_pnl': sum(1 for v in r['day_pnl'].values() if abs(v) > 1e-9),
        'sharpe': round(sharpe_of(rets), 3),
        'max_dd_pct': round(maxdd * 100, 2),
        'cost_bps': r.get('cost_bps', 0.0),
        'seconds': r.get('seconds'),
    }


def save(name, obj):
    os.makedirs(RESULTS, exist_ok=True)
    dest = os.path.join(RESULTS, name)
    json.dump(obj, open(dest, 'w'), indent=1)
    print(f'\nwrote {os.path.relpath(dest, ROOT)}')
    return dest


# --------------------------------------------------------------------------
def cmd_baselines(_):
    out = {}
    print('=' * 78)
    print('BASELINES -- full engine replay of', ENGINE)
    print('=' * 78)

    print('\n[1/3] ANCHOR reproduction (ramp-up lookback, anchor data) ...', flush=True)
    a = replay(start=H.REF_START, end='2026-09-04', tag='anchor',
               daily=H.DAILY, hourly=H.HOURLY)
    ok = abs(a['realized'] - H.REF_REALIZED) < 0.01
    print(f"      ${a['realized']:,.2f} ({a['realized_pct']:+.2f}%)  {a['trade_count']} trades  "
          f"{'PASS' if ok else 'FAIL'}")
    if not ok:
        raise SystemExit('anchor did not reproduce; refusing to emit research numbers')
    out['anchor'] = summarize(a)

    print('[2/3] Same window, FULL lookback ...', flush=True)
    b = replay(start=H.REF_START, end='2026-09-04', tag='fulllb')
    print(f"      ${b['realized']:,.2f} ({b['realized_pct']:+.2f}%)  {b['trade_count']} trades")
    out['anchor_window_full_lookback'] = summarize(b)

    print('[3/3] RESEARCH baseline: extended window, full lookback ...', flush=True)
    c = replay(tag='base')
    s = summarize(c)
    print(f"      ${c['realized']:,.2f} ({c['realized_pct']:+.2f}%)  {c['trade_count']} trades  "
          f"sharpe {s['sharpe']}  maxDD {s['max_dd_pct']}%")
    out['research_baseline'] = s

    d = a['realized'] - b['realized']
    print('\nLOOKBACK EFFECT (MEASURED, not a rule effect): '
          f"${d:+,.2f} ({d / a['realized'] * 100:+.1f}%)")
    out['_meta'] = {
        'engine': ENGINE, 'capital': CAPITAL, 'anchor_reproduced': ok,
        'research_window': [RESEARCH_START, RESEARCH_END],
        'lookback_effect_usd': round(d, 2),
        'daily_data': os.path.basename(DAILY_EXT),
        'hourly_data': os.path.basename(HOURLY_EXT),
    }
    save('baselines.json', out)


# --------------------------------------------------------------------------
def cmd_costs(_):
    print('=' * 78)
    print('TRANSACTION-COST SENSITIVITY of the research baseline')
    print('  cost is PER SIDE in basis points, applied to executions not signals')
    print('=' * 78)
    rows = []
    print(f"\n{'bps/side':>9} {'realized':>14} {'return':>10} {'sharpe':>8} {'maxDD':>8} {'trades':>7}")
    for c in [0.0, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0]:
        r = replay(tag=f'cost{c}', cost_bps=c)
        s = summarize(r)
        rows.append({'cost_bps': c, **s})
        print(f"{c:>9.1f} {s['realized']:>14,.2f} {s['realized_pct']:>9.2f}% "
              f"{s['sharpe']:>8.2f} {s['max_dd_pct']:>7.2f}% {s['trades']:>7}")
    base = rows[0]['realized']
    for row in rows:
        row['pct_of_zero_cost'] = round(row['realized'] / base * 100, 1)
    print('\nRetained vs zero-cost: ' +
          '  '.join(f"{r['cost_bps']:g}bp={r['pct_of_zero_cost']}%" for r in rows))
    breakeven = next((r['cost_bps'] for r in rows if r['realized'] <= 0), None)
    print(f"Breakeven cost: {'>30 bps/side (not reached in sweep)' if breakeven is None else str(breakeven)+' bps/side'}")
    save('cost_sensitivity.json', {'rows': rows, 'engine': ENGINE,
                                   'window': [RESEARCH_START, RESEARCH_END],
                                   'note': 'MEASURED by full replay at each cost level'})


# --------------------------------------------------------------------------
def load_bars(path, field='close_price'):
    d = json.load(open(path))
    out = {}
    for r in d['data']['results']:
        for b in r['bars']:
            out.setdefault(r['symbol'], {})[b['begins_at']] = float(b[field])
    return out


def cmd_gaps(_):
    """Decompose where the strategy's exposure actually earns and loses.

    The engine checks at 17:00 UTC. So a position held from one check to the
    next passes through three legs:
        A  17:00 -> 20:00 same day  (rest of session after the check)
        B  20:00 -> 13:30 next day  (TRUE OVERNIGHT -- unhedgeable, no trading)
        C  13:30 -> 17:00 next day  (morning, before the next check)
    Only B is what an early close could avoid, and only partly.

    This is a MEASUREMENT of the baseline's own positions, not a variant test.
    """
    print('=' * 78)
    print('OVERNIGHT EXPOSURE DECOMPOSITION (MEASURED on 30-minute bars)')
    print('=' * 78)
    base = replay(tag='gapbase')
    closes = load_bars(MIN30)
    opens = load_bars(MIN30, 'open_price')

    days = sorted({ts[:10] for ts in next(iter(closes.values()))})
    dayset = set(days)

    # rebuild end-of-day holdings from the trade list
    holdings, eod = {}, {}
    for t in base['trades']:
        q = holdings.setdefault(t['symbol'], 0.0)
        holdings[t['symbol']] = q + (t['shares'] if t['side'] == 'buy' else -t['shares'])
        eod[t['date']] = {k: v for k, v in holdings.items() if v > 1e-9}
    last = {}
    snap = {}
    for D in sorted(set(list(eod) + days)):
        if D in eod:
            last = eod[D]
        snap[D] = dict(last)

    def px(sym, day, hhmm, series):
        return series.get(sym, {}).get(f'{day}T{hhmm}:00Z')

    legs = {'A_after_check': 0.0, 'B_overnight': 0.0, 'C_morning': 0.0}
    counts = {'A_after_check': 0, 'B_overnight': 0, 'C_morning': 0}
    worst_gap = []
    for i, D in enumerate(days[:-1]):
        N = days[i + 1]
        held = snap.get(D, {})
        for sym, sh in held.items():
            p17 = px(sym, D, '17:00', closes)
            p20 = px(sym, D, '19:30', closes)        # 19:30 bar closes at 20:00
            pO = px(sym, N, '13:30', opens)          # next session's opening print
            p17n = px(sym, N, '17:00', closes)
            if None in (p17, p20, pO, p17n):
                continue
            a, b, c = sh * (p20 - p17), sh * (pO - p20), sh * (p17n - pO)
            legs['A_after_check'] += a
            legs['B_overnight'] += b
            legs['C_morning'] += c
            counts['A_after_check'] += 1
            counts['B_overnight'] += 1
            counts['C_morning'] += 1
            worst_gap.append((b, sym, D, N, round((pO / p20 - 1) * 100, 2)))

    tot = sum(legs.values())
    print(f"\nWindow {days[0]} -> {days[-1]}  ({len(days)} trading days, "
          f"{counts['B_overnight']} position-nights)\n")
    print(f"{'leg':<28}{'P&L $':>14}{'share':>10}")
    labels = {'A_after_check': 'A  17:00 -> 20:00 (post-check)',
              'B_overnight': 'B  20:00 -> next 13:30 (OVERNIGHT)',
              'C_morning': 'C  13:30 -> 17:00 (morning)'}
    for k in ('A_after_check', 'B_overnight', 'C_morning'):
        share = (legs[k] / tot * 100) if tot else 0
        print(f"{labels[k]:<38}{legs[k]:>14,.2f}{share:>9.1f}%")
    print(f"{'TOTAL held-position P&L':<38}{tot:>14,.2f}")

    worst_gap.sort()
    print('\nWorst 6 overnight gaps by $ impact on held positions:')
    for b, sym, D, N, pct in worst_gap[:6]:
        print(f"   {D} -> {N}  {sym:<5} {pct:>7.2f}%   ${b:>11,.2f}")

    downside = sum(b for b, *_ in worst_gap if b < 0)
    upside = sum(b for b, *_ in worst_gap if b > 0)
    print(f"\nOvernight gap gross: down ${downside:,.2f} / up ${upside:,.2f} "
          f"=> net ${downside + upside:,.2f}")
    print('READ THIS CAREFULLY: an early close forgoes the UP gaps as well as the')
    print('down ones. A negative "B" is not automatically an argument for closing.')

    save('overnight_decomposition.json', {
        'window': [days[0], days[-1]], 'position_nights': counts['B_overnight'],
        'legs': {k: round(v, 2) for k, v in legs.items()},
        'overnight_down': round(downside, 2), 'overnight_up': round(upside, 2),
        'overnight_net': round(downside + upside, 2),
        'worst': [{'pnl': round(b, 2), 'symbol': s, 'from': d, 'to': n, 'gap_pct': p}
                  for b, s, d, n, p in worst_gap[:12]],
        'method': ('MEASURED. Baseline replay holdings marked on real 30-minute bars. '
                   'Leg B is the only part an early close could avoid.'),
    })


# --------------------------------------------------------------------------
def patch_sell_epsilon(src):
    """Give Guardrail 4's CHECK the same tolerance its own MUTATION already has.

    MEASURED DEFECT (found 2026-09-22 by this grid search, engine origin/main):
    cmd_commit validates with a strict
            if pos and s['shares'] > pos['shares']:
    comparing a sell quantity ROUNDED to 6dp against an UNROUNDED held quantity.
    Selling a whole position therefore aborts the commit on floating-point dust:

        AMD held 155.40438799999998, sell 155.404388  ->  abort, off by 2e-14

    The mutation four lines below already handles this correctly --
    `remaining = round(pos['shares'] - s['shares'], 6)` then `if remaining <= 1e-6:
    del ...` -- so only the check is missing the tolerance. That asymmetry is the
    whole defect.

    LIVE IMPACT TODAY: none. Production PEAK_SELL_PCT is 0.743, so a PEAK sell
    never lands on 100% of a position, and STOP/MAX_HOLD/KILL_SWITCH pass
    pos['shares'] through unrounded. It is latent, not active -- but it makes
    PEAK_SELL_PCT >= 1.0 untestable against the unmodified engine, which is how
    it was found.

    This patch is applied in memory only, and cmd_grid asserts it is a no-op on
    the baseline before using it.
    """
    old = "        if pos and s['shares'] > pos['shares']:"
    new = "        if pos and s['shares'] > pos['shares'] + 1e-6:"
    if new in src:
        # FIXED IN PRODUCTION 2026-09-22 (main commit 6343f5e). The engine now carries
        # the tolerance, so this patch has nothing to do and returns the source
        # untouched. Kept so older engine revisions stay testable, and so the history
        # of the defect is not silently erased from the research code.
        return src
    if src.count(old) != 1:
        raise SystemExit(f'sell-epsilon anchor matched {src.count(old)}x, expected 1')
    return src.replace(old, new)


GRID = {
    'INTRADAY_STOP': [-0.010, -0.0151, -0.020, -0.030, -9.99],   # -9.99 = effectively off
    'PEAK_SELL_PCT': [0.50, 0.65, 0.743, 0.85, 1.00],
    'MAX_HOLD_DAYS': [3, 4, 6, 8, 12],
    'NORMAL_DIP_THRESHOLD': [0.002, 0.004, 0.008, 0.015],
}


def folds(dates, k):
    """Anchored walk-forward. Each fold is an INDEPENDENT replay starting flat,
    so no state leaks between train and test -- the leak that makes most
    walk-forward code optimistic."""
    n = len(dates)
    size = n // (k + 1)
    out = []
    for i in range(1, k + 1):
        tr = (dates[0], dates[i * size - 1])
        te = (dates[i * size], dates[min((i + 1) * size, n) - 1])
        out.append((tr, te))
    return out


def cmd_grid(a):
    print('=' * 78)
    print(f'WALK-FORWARD GRID SEARCH  (engine {ENGINE}, cost {a.cost} bps/side)')
    print('=' * 78)
    base = replay(tag='gbase', cost_bps=a.cost)
    chk = replay(tag='gbasep', cost_bps=a.cost, src_patches=[patch_sell_epsilon])
    if abs(base['realized'] - chk['realized']) > 0.01:
        raise SystemExit('sell-epsilon patch is NOT a no-op on the baseline '
                         f"({base['realized']} vs {chk['realized']}) -- do not use it")
    print(f"sell-epsilon patch verified no-op on baseline "
          f"(${base['realized']:,.2f} both ways)")
    all_dates = sorted(base['day_equity'])
    fl = folds(all_dates, a.folds)

    keys = list(GRID)
    combos = [dict(zip(keys, v)) for v in itertools.product(*(GRID[k] for k in keys))]
    print(f'\ngrid: {" x ".join(f"{k}({len(GRID[k])})" for k in keys)} = {len(combos)} configs')
    print(f'folds: {a.folds} anchored walk-forward, each an independent flat-start replay')
    print(f'total replays: {len(combos) * a.folds + a.folds} '
          f'(~{(len(combos) * a.folds + a.folds) * 0.8 / 60:.0f} min)\n')

    results = {'trials': len(combos), 'folds': [], 'cost_bps': a.cost, 'engine': ENGINE}
    t0 = time.time()
    for fi, (tr, te) in enumerate(fl, 1):
        print(f'--- fold {fi}: train {tr[0]}..{tr[1]}   test {te[0]}..{te[1]}', flush=True)
        scored = []
        for ci, cfg in enumerate(combos):
            r = replay(start=tr[0], end=tr[1], params=cfg, tag=f'g{fi}', cost_bps=a.cost,
                       src_patches=[patch_sell_epsilon])
            scored.append((sharpe_of(daily_returns(r)), r['realized'], cfg))
            if (ci + 1) % 100 == 0:
                print(f'      {ci+1}/{len(combos)}  [{time.time()-t0:.0f}s]', flush=True)
        # select on TRAIN Sharpe (risk-adjusted, not raw P&L -- raw P&L selection
        # reliably picks the most leveraged config, which is not an edge)
        scored.sort(key=lambda x: -x[0])
        best = scored[0][2]

        bt = replay(start=te[0], end=te[1], params=best, tag=f't{fi}', cost_bps=a.cost,
                    src_patches=[patch_sell_epsilon])
        bb = replay(start=te[0], end=te[1], tag=f'b{fi}', cost_bps=a.cost,
                    src_patches=[patch_sell_epsilon])
        results['folds'].append({
            'fold': fi, 'train': tr, 'test': te,
            'best_params': {k: best[k] for k in keys},
            'train_sharpe': round(scored[0][0], 3),
            'train_realized': scored[0][1],
            'test_variant': summarize(bt),
            'test_baseline': summarize(bb),
            'test_delta_realized': round(bt['realized'] - bb['realized'], 2),
            'test_delta_sharpe': round(sharpe_of(daily_returns(bt))
                                       - sharpe_of(daily_returns(bb)), 3),
            'top5_train': [{'sharpe': round(s, 3), 'realized': rz,
                            **{k: c[k] for k in keys}} for s, rz, c in scored[:5]],
        })
        f = results['folds'][-1]
        print(f"      picked {f['best_params']}")
        print(f"      train sharpe {f['train_sharpe']}")
        print(f"      TEST  variant ${bt['realized']:,.2f} vs baseline ${bb['realized']:,.2f}"
              f"   delta ${f['test_delta_realized']:+,.2f}"
              f"   sharpe {f['test_delta_sharpe']:+.3f}\n", flush=True)

    wins = sum(1 for f in results['folds'] if f['test_delta_realized'] > 0)
    results['test_folds_won'] = wins
    results['verdict'] = ('tuning did NOT generalize' if wins <= len(fl) / 2
                          else 'tuning won a majority of test folds -- needs DSR check')
    print('=' * 78)
    print(f"out-of-sample test folds won by the tuned config: {wins}/{len(fl)}")
    print(results['verdict'])
    save('grid_walkforward.json', results)


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('baselines').set_defaults(fn=cmd_baselines)
    sub.add_parser('costs').set_defaults(fn=cmd_costs)
    sub.add_parser('gaps').set_defaults(fn=cmd_gaps)
    g = sub.add_parser('grid')
    g.add_argument('--folds', type=int, default=3)
    g.add_argument('--cost', type=float, default=DEFAULT_COST)
    g.set_defaults(fn=cmd_grid)
    v = sub.add_parser('variants')
    v.add_argument('--cost', type=float, default=DEFAULT_COST)
    v.set_defaults(fn=cmd_variants)
    st = sub.add_parser('stats')
    st.set_defaults(fn=cmd_stats)
    rk = sub.add_parser('ranking')
    rk.add_argument('--cost', type=float, default=DEFAULT_COST)
    rk.set_defaults(fn=cmd_ranking)
    a = ap.parse_args()
    a.fn(a)




# ==========================================================================
# VARIANTS -- structural rule changes, each a single anchored source patch
# ==========================================================================
def patch_quality_filter(src):
    """Entry Signal Quality Filter: require N consecutive down closes before entry.

    CLAUDE.md records this as status UNKNOWN -- three different numbers were
    published for it (+40.31%, +32.24%, -99%) and ALL THREE came from the
    forbidden day_pnl-multiplier method, so none may be cited. This is the first
    replay-based measurement of it.

    The filter is injected as a global so the threshold can be swept; 0 disables
    it, and 0 must reproduce the baseline exactly (asserted in cmd_variants).
    """
    old = ("            if drawdown <= HUGE_DIP_DRAWDOWN:\n"
           "                reason = 'HUGE_DIP'")
    new = ("            if QUALITY_MIN_DOWN_DAYS:\n"
           "                _streak = 0\n"
           "                for _k in range(len(bars) - 1, 0, -1):\n"
           "                    if bars[_k]['close'] < bars[_k - 1]['close']:\n"
           "                        _streak += 1\n"
           "                    else:\n"
           "                        break\n"
           "                if _streak < QUALITY_MIN_DOWN_DAYS:\n"
           "                    continue\n"
           "            if drawdown <= HUGE_DIP_DRAWDOWN:\n"
           "                reason = 'HUGE_DIP'")
    if src.count(old) != 1:
        raise SystemExit(f'quality-filter anchor matched {src.count(old)}x, expected 1')
    return src.replace(old, new) + "\nQUALITY_MIN_DOWN_DAYS = 0\n"


def patch_trailing_stop(src):
    """Trailing stop: exit the whole position if price falls TRAIL_PCT below the
    peak the engine already tracks since entry. Inserted immediately after the
    existing INTRADAY_STOP test so priority order is unchanged."""
    old = "        if live_price <= prev_close * (1 + INTRADAY_STOP):"
    new = ("        if TRAIL_PCT and pos.get('peak') and live_price <= pos['peak'] * (1 - TRAIL_PCT):\n"
           "            sells.append({'symbol': sym, 'shares': pos['shares'], 'price': live_price,\n"
           "                          'reason': 'STOP', 'entry': pos['entry']})\n"
           "            continue\n"
           "        if live_price <= prev_close * (1 + INTRADAY_STOP):")
    if src.count(old) != 1:
        raise SystemExit(f'trailing-stop anchor matched {src.count(old)}x, expected 1')
    return src.replace(old, new) + "\nTRAIL_PCT = 0.0\n"


def cmd_variants(a):
    print('=' * 84)
    print(f'STRUCTURAL VARIANTS  (engine {ENGINE}, cost {a.cost} bps/side, '
          f'{RESEARCH_START}..{RESEARCH_END})')
    print('=' * 84)
    base = replay(tag='vbase', cost_bps=a.cost)
    bs = summarize(base)
    print(f"\nbaseline: ${base['realized']:,.2f} ({base['realized_pct']:+.2f}%)  "
          f"sharpe {bs['sharpe']}  maxDD {bs['max_dd_pct']}%  {bs['trades']} trades")

    rows = [{'variant': 'BASELINE (production)', **bs}]

    # neutrality assertions: a disabled patch must be a no-op, or the patch is wrong
    z1 = replay(tag='vq0', cost_bps=a.cost, src_patches=[patch_quality_filter],
                params={'QUALITY_MIN_DOWN_DAYS': 0})
    z2 = replay(tag='vt0', cost_bps=a.cost, src_patches=[patch_trailing_stop],
                params={'TRAIL_PCT': 0.0})
    for nm, z in (('quality-filter', z1), ('trailing-stop', z2)):
        if abs(z['realized'] - base['realized']) > 0.01:
            raise SystemExit(f'{nm} patch is not neutral when disabled '
                             f"({z['realized']} vs {base['realized']}) -- patch is wrong")
    print('patch neutrality verified: both disabled patches reproduce the baseline exactly')

    print(f"\n{'variant':<42}{'realized':>13}{'return':>9}{'sharpe':>8}{'maxDD':>8}{'trades':>8}")
    print(f"{'BASELINE (production)':<42}{base['realized']:>13,.0f}"
          f"{base['realized_pct']:>8.1f}%{bs['sharpe']:>8.2f}{bs['max_dd_pct']:>7.1f}%{bs['trades']:>8}")

    for n in (1, 2, 3, 4):
        r = replay(tag=f'vq{n}', cost_bps=a.cost, src_patches=[patch_quality_filter],
                   params={'QUALITY_MIN_DOWN_DAYS': n})
        s = summarize(r)
        rows.append({'variant': f'quality filter: {n}+ consecutive down days', **s})
        print(f"{f'quality filter: {n}+ down days':<42}{r['realized']:>13,.0f}"
              f"{r['realized_pct']:>8.1f}%{s['sharpe']:>8.2f}{s['max_dd_pct']:>7.1f}%{s['trades']:>8}")

    for t in (0.03, 0.05, 0.08, 0.12):
        r = replay(tag=f'vt{int(t*100)}', cost_bps=a.cost, src_patches=[patch_trailing_stop],
                   params={'TRAIL_PCT': t})
        s = summarize(r)
        rows.append({'variant': f'trailing stop {t:.0%} below peak', **s})
        print(f"{f'trailing stop {t:.0%} below peak':<42}{r['realized']:>13,.0f}"
              f"{r['realized_pct']:>8.1f}%{s['sharpe']:>8.2f}{s['max_dd_pct']:>7.1f}%{s['trades']:>8}")

    for lbl, p in [('no intraday stop', {'INTRADAY_STOP': -9.99}),
                   ('stop -1.0% (tighter)', {'INTRADAY_STOP': -0.010}),
                   ('stop -2.5% (looser)', {'INTRADAY_STOP': -0.025}),
                   ('max 1 tranche per symbol', {'MAX_TRANCHES': 1}),
                   ('symbol cap 25% (was 50%)', {'MAX_SYMBOL_ALLOCATION_PCT': 0.25}),
                   ('trade cap 10% (was 25%)', {'MAX_TRADE_NOTIONAL_PCT': 0.10})]:
        r = replay(tag='vp' + lbl[:6].replace(' ', ''), cost_bps=a.cost, params=p)
        s = summarize(r)
        rows.append({'variant': lbl, 'params': p, **s})
        print(f"{lbl:<42}{r['realized']:>13,.0f}"
              f"{r['realized_pct']:>8.1f}%{s['sharpe']:>8.2f}{s['max_dd_pct']:>7.1f}%{s['trades']:>8}")

    for r_ in rows:
        r_['delta_vs_baseline'] = round(r_['realized'] - base['realized'], 2)
    save('variants.json', {'engine': ENGINE, 'cost_bps': a.cost,
                           'window': [RESEARCH_START, RESEARCH_END],
                           'baseline_realized': base['realized'], 'rows': rows,
                           'method': 'MEASURED by full engine replay; disabled patches asserted no-op'})


# ==========================================================================
# STATISTICS -- the part that decides whether a "winner" is real
# ==========================================================================
from statistics import NormalDist  # noqa: E402

_ND = NormalDist()
EULER = 0.5772156649015329


def _moments(xs):
    n = len(xs)
    m = sum(xs) / n
    v = sum((x - m) ** 2 for x in xs) / (n - 1)
    sd = v ** 0.5
    if sd == 0:
        return m, sd, 0.0, 3.0
    sk = sum(((x - m) / sd) ** 3 for x in xs) / n
    ku = sum(((x - m) / sd) ** 4 for x in xs) / n
    return m, sd, sk, ku


def expected_max_sharpe(trial_sharpes):
    """E[max SR] under the null of ZERO skill across N independent trials
    (Bailey & Lopez de Prado). Searching 500 configs guarantees a high best
    Sharpe even on noise; this is the bar that best Sharpe must clear."""
    n = len(trial_sharpes)
    if n < 2:
        return 0.0
    _, sd, _, _ = _moments(trial_sharpes)
    return sd * ((1 - EULER) * _ND.inv_cdf(1 - 1.0 / n)
                 + EULER * _ND.inv_cdf(1 - 1.0 / (n * math.e)))


def deflated_sharpe(sr_daily, sr_benchmark, returns):
    """P(true SR > benchmark), correcting for non-normality AND selection.
    SR and benchmark are per-period (daily), matching T."""
    t = len(returns)
    _, _, sk, ku = _moments(returns)
    den = math.sqrt(max(1e-12, 1 - sk * sr_daily + (ku - 1) / 4.0 * sr_daily ** 2))
    return _ND.cdf((sr_daily - sr_benchmark) * math.sqrt(t - 1) / den)


def block_bootstrap_diff(a_rets, b_rets, block=5, iters=5000, seed=7):
    """Moving-block bootstrap CI on mean daily return difference. Blocks preserve
    the autocorrelation an IID bootstrap would destroy -- and this series is
    strongly autocorrelated, because positions are held for days."""
    rnd = random.Random(seed)
    n = min(len(a_rets), len(b_rets))
    a, b = a_rets[:n], b_rets[:n]
    nb = max(1, n // block)
    diffs = []
    for _ in range(iters):
        idx = []
        for _ in range(nb):
            s = rnd.randrange(0, max(1, n - block))
            idx.extend(range(s, min(s + block, n)))
        idx = idx[:n]
        diffs.append(sum(a[i] - b[i] for i in idx) / len(idx))
    diffs.sort()
    lo = diffs[int(0.025 * len(diffs))]
    hi = diffs[int(0.975 * len(diffs))]
    p_pos = sum(1 for d in diffs if d > 0) / len(diffs)
    return lo, hi, p_pos


def cmd_stats(a):
    grid = json.load(open(os.path.join(RESULTS, 'grid_walkforward.json')))
    print('=' * 84)
    print('STATISTICAL VALIDATION -- does any "winner" survive multiple testing?')
    print('=' * 84)
    n_trials = grid['trials']
    print(f"\nconfigurations searched per fold : {n_trials}")
    print(f"walk-forward test folds won      : {grid['test_folds_won']}/{len(grid['folds'])}")

    out = {'trials': n_trials, 'folds': []}
    for f in grid['folds']:
        sharpes = [t['sharpe'] for t in f['top5_train']]
        print(f"\n--- fold {f['fold']}   test {f['test'][0]}..{f['test'][1]}")
        print(f"    picked on train: {f['best_params']}")
        print(f"    TEST delta P&L : ${f['test_delta_realized']:+,.2f}")
        print(f"    TEST delta SR  : {f['test_delta_sharpe']:+.3f}")
        v, b = f['test_variant'], f['test_baseline']
        print(f"    variant  ${v['realized']:>11,.2f}  SR {v['sharpe']:>6.2f}  maxDD {v['max_dd_pct']:>6.2f}%")
        print(f"    baseline ${b['realized']:>11,.2f}  SR {b['sharpe']:>6.2f}  maxDD {b['max_dd_pct']:>6.2f}%")
        out['folds'].append({'fold': f['fold'], 'delta': f['test_delta_realized'],
                             'delta_sharpe': f['test_delta_sharpe'],
                             'top5_train_sharpes': sharpes})

    # Full-window comparison of the most-selected config, with DSR + bootstrap
    from collections import Counter
    picks = Counter(json.dumps(f['best_params'], sort_keys=True) for f in grid['folds'])
    cfg = json.loads(picks.most_common(1)[0][0])
    times = picks.most_common(1)[0][1]
    print(f"\nmost-selected config ({times}/{len(grid['folds'])} folds): {cfg}")
    print('evaluating it over the FULL research window against baseline ...', flush=True)

    var = replay(params=cfg, tag='stv', cost_bps=grid['cost_bps'],
                 src_patches=[patch_sell_epsilon])
    base = replay(tag='stb', cost_bps=grid['cost_bps'], src_patches=[patch_sell_epsilon])
    vr, br = daily_returns(var), daily_returns(base)
    vs, bs = summarize(var), summarize(base)
    print(f"    variant  ${var['realized']:>11,.2f} ({vs['realized_pct']:+.1f}%)  "
          f"SR {vs['sharpe']:>5.2f}  maxDD {vs['max_dd_pct']:>6.2f}%")
    print(f"    baseline ${base['realized']:>11,.2f} ({bs['realized_pct']:+.1f}%)  "
          f"SR {bs['sharpe']:>5.2f}  maxDD {bs['max_dd_pct']:>6.2f}%")

    # all fold-1 train Sharpes approximate the trial distribution
    trial_sharpes = [t['sharpe'] for f in grid['folds'] for t in f['top5_train']]
    sr0_ann = expected_max_sharpe(trial_sharpes)
    sr_daily = sharpe_of(vr) / math.sqrt(252)
    sr0_daily = sr0_ann / math.sqrt(252)
    dsr = deflated_sharpe(sr_daily, sr0_daily, vr)
    print(f"\n  expected MAX annualized Sharpe from {n_trials} trials on pure noise: {sr0_ann:.2f}")
    print(f"  variant annualized Sharpe                                     : {sharpe_of(vr):.2f}")
    print(f"  DEFLATED SHARPE (P[skill real], selection+non-normality adj.) : {dsr:.3f}")

    lo, hi, p_pos = block_bootstrap_diff(vr, br)
    print(f"\n  block-bootstrap 95% CI on mean DAILY return difference:")
    print(f"     [{lo*100:+.4f}%, {hi*100:+.4f}%]   P(variant > baseline) = {p_pos:.3f}")
    straddles = lo < 0 < hi
    msg = ('STRADDLES ZERO -> difference not distinguishable from noise'
           if straddles else 'excludes zero')
    print(f"     CI {msg}")

    verdict = ('NOT SUPPORTED' if (straddles or dsr < 0.95 or grid['test_folds_won'] <= len(grid['folds']) / 2)
               else 'SUPPORTED -- but confirm on fresh data before deploying')
    print('\n' + '=' * 84)
    print(f'VERDICT: {verdict}')
    print('Bar for "supported": majority of walk-forward test folds won, deflated')
    print('Sharpe >= 0.95, AND a bootstrap CI on the daily difference excluding zero.')
    print('=' * 84)
    out.update({'config': cfg, 'dsr': round(dsr, 4),
                'expected_max_sharpe_noise': round(sr0_ann, 3),
                'variant_sharpe': round(sharpe_of(vr), 3),
                'bootstrap_ci_daily': [lo, hi], 'p_variant_better': p_pos,
                'ci_straddles_zero': straddles, 'verdict': verdict,
                'variant_full': vs, 'baseline_full': bs})
    save('statistics.json', out)



# ==========================================================================
# RANKING -- "is what we run actually the best?" in one reproducible table
# ==========================================================================
def buy_and_hold(start, end, capital, cost_bps, daily=None, hourly=None):
    """Equal-weight buy at the first 17:00 check, hold to the last. The honest
    passive benchmark: same universe, same window, same friction."""
    daily = daily or DAILY_EXT
    hourly = hourly or HOURLY_EXT
    h = json.load(open(hourly))
    px = {r['symbol']: {b['begins_at'][:10]: float(b['close_price'])
                        for b in r['bars'] if b['begins_at'][11:19] == '17:00:00'}
          for r in h['data']['results']}
    days = sorted(set.intersection(*[set(v) for v in px.values()]))
    days = [d for d in days if start <= d <= end]
    d0, d1 = days[0], days[-1]
    c = cost_bps / 10000.0
    per = capital / len(px)
    tot = 0.0
    for sym in px:
        sh = per / (px[sym][d0] * (1 + c))
        tot += sh * px[sym][d1] * (1 - c)
    return tot - capital


def cmd_ranking(a):
    print('=' * 86)
    print('IS THE PRODUCTION CONFIGURATION THE BEST TESTED?')
    print(f'  engine {ENGINE} | {RESEARCH_START}..{RESEARCH_END} | $80,000 | {a.cost} bps/side')
    print('=' * 86)
    base = replay(tag='rkbase', cost_bps=a.cost)
    bh = buy_and_hold(RESEARCH_START, RESEARCH_END, CAPITAL, a.cost)

    rows = [('PRODUCTION (current rules)', base['realized'], summarize(base))]
    for lbl, params, patches in [
        ('Best grid-search config (rejected)',
         {'INTRADAY_STOP': -9.99, 'PEAK_SELL_PCT': 0.5, 'MAX_HOLD_DAYS': 8,
          'NORMAL_DIP_THRESHOLD': 0.002}, [patch_sell_epsilon]),
        ('Intraday stop -2.5% (looser)', {'INTRADAY_STOP': -0.025}, None),
        ('Intraday stop -1.0% (tighter)', {'INTRADAY_STOP': -0.010}, None),
        ('Trade cap 10% (was 25%)', {'MAX_TRADE_NOTIONAL_PCT': 0.10}, None),
        ('Symbol cap 25% (was 50%)', {'MAX_SYMBOL_ALLOCATION_PCT': 0.25}, None),
        ('Max 1 tranche per symbol', {'MAX_TRANCHES': 1}, None),
        ('Quality filter 3+ down days', {'QUALITY_MIN_DOWN_DAYS': 3}, [patch_quality_filter]),
        ('No intraday stop at all', {'INTRADAY_STOP': -9.99}, None),
    ]:
        r = replay(tag='rk' + lbl[:7].replace(' ', ''), cost_bps=a.cost,
                   params=params, src_patches=patches)
        rows.append((lbl, r['realized'], summarize(r)))

    rows.sort(key=lambda x: -x[1])
    print(f"\n{'rank':>4}  {'configuration':<38}{'realized':>13}{'return':>9}{'sharpe':>8}{'maxDD':>8}")
    out = []
    for i, (lbl, rz, s) in enumerate(rows, 1):
        mark = '  <-- LIVE' if lbl.startswith('PRODUCTION') else ''
        print(f"{i:>4}  {lbl:<38}{rz:>13,.0f}{s['realized_pct']:>8.1f}%"
              f"{s['sharpe']:>8.2f}{s['max_dd_pct']:>7.1f}%{mark}")
        out.append({'rank': i, 'config': lbl, 'realized': rz, 'return_pct': s['realized_pct'],
                    'sharpe': s['sharpe'], 'max_dd_pct': s['max_dd_pct'], 'live': mark != ''})
    print(f"\n{'ref':>4}  {'Buy & hold, equal weight, same universe':<38}"
          f"{bh:>13,.0f}{bh / CAPITAL * 100:>8.1f}%{'--':>8}{'--':>8}")

    # If anything outranked production on raw P&L, that is NOT yet a finding --
    # test it before reporting it as one. A rank-1 config whose daily-difference CI
    # straddles zero is a coin flip that happened to land well on this window.
    prod_rank = next(r['rank'] for r in out if r['live'])
    sig = None
    if prod_rank != 1:
        winner = rows[0]
        cfg = {'Intraday stop -2.5% (looser)': {'INTRADAY_STOP': -0.025},
               'Intraday stop -1.0% (tighter)': {'INTRADAY_STOP': -0.010},
               'Trade cap 10% (was 25%)': {'MAX_TRADE_NOTIONAL_PCT': 0.10},
               'Symbol cap 25% (was 50%)': {'MAX_SYMBOL_ALLOCATION_PCT': 0.25}}.get(winner[0])
        if cfg:
            w = replay(tag='rksig', cost_bps=a.cost, params=cfg)
            wr, br_ = daily_returns(w), daily_returns(base)
            lo, hi, p = block_bootstrap_diff(wr, br_)
            folds_won = 0
            sub = [('2026-04-30', '2026-06-16'), ('2026-06-17', '2026-08-04'),
                   ('2026-08-05', '2026-09-21')]
            deltas = []
            for i, (s0, e0) in enumerate(sub, 1):
                bb = replay(start=s0, end=e0, tag=f'rkb{i}', cost_bps=a.cost)
                ww = replay(start=s0, end=e0, tag=f'rkw{i}', cost_bps=a.cost, params=cfg)
                d = ww['realized'] - bb['realized']
                deltas.append({'window': [s0, e0], 'delta': round(d, 2)})
                folds_won += d > 0
            straddles = lo < 0 < hi
            sig = {'winner': winner[0], 'params': cfg,
                   'ci_daily': [lo, hi], 'p_better': p, 'ci_straddles_zero': straddles,
                   'sub_windows_won': folds_won, 'sub_window_deltas': deltas,
                   'real': (not straddles) and folds_won == len(sub)}
            print(f"\n  RANK-1 SIGNIFICANCE TEST -- {winner[0]}")
            print(f"    bootstrap 95% CI on mean daily difference [{lo*100:+.4f}%, {hi*100:+.4f}%]"
                  f"  P(better)={p:.3f}")
            for d in deltas:
                print(f"    {d['window'][0]}..{d['window'][1]}  delta ${d['delta']:>+10,.0f}")
            print(f"    sub-windows won {folds_won}/{len(sub)}"
                  f"   -> {'REAL' if sig['real'] else 'NOISE -- production stands'}")
    if prod_rank == 1:
        verdict = 'PRODUCTION IS RANK 1 of %d -- nothing tested beats it' % len(out)
    elif sig and not sig['real']:
        verdict = ('PRODUCTION IS RANK %d of %d on raw P&L, but the config above it '
                   'fails significance -- production stands' % (prod_rank, len(out)))
    else:
        verdict = ('PRODUCTION IS RANK %d of %d and the winner SURVIVED significance '
                   '-- investigate' % (prod_rank, len(out)))
    print('\n' + '=' * 86)
    print(verdict)
    print(f"vs passive buy & hold: {'+' if base['realized'] > bh else ''}"
          f"${base['realized'] - bh:,.0f} "
          f"({base['realized_pct'] - bh / CAPITAL * 100:+.1f}pp)")
    print('=' * 86)
    save('ranking.json', {'engine': ENGINE, 'cost_bps': a.cost,
                          'window': [RESEARCH_START, RESEARCH_END], 'capital': CAPITAL,
                          'rows': out, 'buy_and_hold': round(bh, 2),
                          'production_rank': prod_rank, 'verdict': verdict, 'rank1_significance': sig,
                          'method': 'MEASURED by full engine replay; buy&hold priced at the same 17:00 bars and same cost'})

if __name__ == '__main__':
    main()
