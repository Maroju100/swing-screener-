#!/usr/bin/env python3
"""Re-rank every Margin-Style configuration on ADMISSIBLE price data.

WHY THIS EXISTS (2026-09-23)
`margin_style_research.py ranking` ranks nine configurations on the HOURLY vendor
series. `margin_style_check_time.py referee` then showed that series is wrong at
~7% of the instants it reads (the 30-minute series matches 1-minute prints 18
times out of 21), and that a 7% price-error rate can move this engine's P&L by
~37% because it trades on 0.4% and -1.51% thresholds. So the committed ranking
is on an input the project no longer trusts, and "is production the best
configuration tested?" has to be asked again on the series that survived.

METHOD (Evidence Rule 1 -- full engine replay of origin/main, nothing scaled)
  * Real 30-minute bars, 2026-06-22 -> 2026-09-21 (64 days), $80k, 5 bps/side.
  * Every config priced at the 30-minute OPEN of each mark (exact_open=True),
    i.e. at a genuine clock instant.
  * Two marks: 17:00 and 17:30 UTC. The live trigger fires ~17:14 UTC, BETWEEN
    them. A ranking that is a property of the rules should look the same at
    both; a ranking that reshuffles between two instants 30 minutes apart is
    telling you the ordering is noise at this sample size.
  * Same nine configs as the hourly ranking, same params and source patches,
    plus equal-weight buy & hold on the same basis.
  * Whatever outranks production is tested (block bootstrap on the daily P&L
    difference), not reported as a finding on sight.

The intraday harness self-validates against the shared harness ($30,622.59 /
371 trades) before anything is emitted, and the script exits if it cannot.

Reproduce:
    python3 scripts/margin_style_rank_admissible.py
"""
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import margin_style_intraday_study as I
import margin_style_research as R

OUT = os.path.join(I.RESULTS, 'ranking_admissible.json')
WIN = ('2026-06-22', '2026-09-21')
MARKS = ('17:00', '17:30')
CAPITAL = 80000.0
COST = 5.0

CONFIGS = [
    ('PRODUCTION (current rules)', {}, None),
    ('Intraday stop -2.5% (looser)', {'INTRADAY_STOP': -0.025}, None),
    ('Intraday stop -1.0% (tighter)', {'INTRADAY_STOP': -0.010}, None),
    ('Trade cap 10% (was 25%)', {'MAX_TRADE_NOTIONAL_PCT': 0.10}, None),
    ('Symbol cap 25% (was 50%)', {'MAX_SYMBOL_ALLOCATION_PCT': 0.25}, None),
    ('Max 1 tranche per symbol', {'MAX_TRANCHES': 1}, None),
    ('Best grid-search config (rejected)',
     {'INTRADAY_STOP': -9.99, 'PEAK_SELL_PCT': 0.5, 'MAX_HOLD_DAYS': 8,
      'NORMAL_DIP_THRESHOLD': 0.002}, [R.patch_sell_epsilon]),
    ('Quality filter 3+ down days', {'QUALITY_MIN_DOWN_DAYS': 3}, [R.patch_quality_filter]),
    ('No intraday stop at all', {'INTRADAY_STOP': -9.99}, None),
]


def validate():
    r = I.replay_intraday(WIN[0], WIN[1], tag='ra_validate')
    if round(r['realized'], 2) != 30622.59 or r['trades'] != 371:
        raise SystemExit(f"INTRADAY HARNESS FAILED VALIDATION: {r['realized']} / {r['trades']} "
                         '-- refusing to emit.')


def daily_returns(r):
    out, eq = {}, CAPITAL
    for d in sorted(r['day_pnl']):
        out[d] = r['day_pnl'][d] / eq if eq else 0.0
        eq = r['day_equity'].get(d, eq)
    return out


def summarize(r):
    rets = list(daily_returns(r).values())
    sd = statistics.pstdev(rets) if len(rets) > 2 else 0
    peak, dd = -1e18, 0.0
    for d in sorted(r['day_equity']):
        peak = max(peak, r['day_equity'][d])
        dd = min(dd, r['day_equity'][d] / peak - 1)
    return {'realized': round(r['realized'], 2),
            'return_pct': round(r['realized'] / CAPITAL * 100, 2),
            'sharpe': round(statistics.fmean(rets) / sd * 252 ** 0.5, 2) if sd else None,
            'max_dd_pct': round(dd * 100, 2), 'trades': r['trades']}


def buy_and_hold(mark):
    op30, _ = I.load_min30()
    c = COST / 10000.0
    days = sorted({ts[:10] for ts in next(iter(op30.values()))})
    days = [d for d in days if WIN[0] <= d <= WIN[1]]
    per = CAPITAL / len(I.UNIVERSE)
    tot = 0.0
    for s in I.UNIVERSE:
        p0 = op30[s].get(f'{days[0]}T{mark}:00Z')
        p1 = op30[s].get(f'{days[-1]}T{mark}:00Z')
        tot += per / (p0 * (1 + c)) * p1 * (1 - c)
    return round(tot - CAPITAL, 2)


def bootstrap(a, b):
    ra, rb = daily_returns(a), daily_returns(b)
    days = sorted(set(ra) & set(rb))
    diff = [ra[d] - rb[d] for d in days]
    lo, hi, p = R.block_bootstrap_diff(diff, [0.0] * len(diff))
    return {'ci_daily': [lo, hi], 'p_better': p, 'straddles_zero': lo < 0 < hi}


def regime_diagnosis():
    """Evidence Rule 4: the admissible ranking REVERSES two committed findings.

    On 30-minute bars over 2026-06-22..09-21, the 3+-down-day quality filter and
    the -1.0% stop both beat production, where the committed 132-day hourly
    ranking found the filter harmful (-$91,886) and the tighter stop costly
    (-$14,943). Two things changed at once -- the price series AND the window --
    so the reversal is undiagnosed until they are separated.

    This holds the series fixed (hourly, the committed ranking's basis) and
    splits the 132 days into the EARLY window (Mar 13..Jun 19, basket rising,
    buy & hold +155%) and the LATE window (Jun 22..Sep 21, basket falling, buy
    & hold -16%). If a config's advantage appears only in one regime, it is a
    regime bet, not an improvement.
    """
    import margin_style_17h_backtest as H
    wins = {'early_up_market': ('2026-03-13', '2026-06-19'),
            'late_down_market': ('2026-06-22', '2026-09-21')}
    out = {}
    for wn, (s, e) in wins.items():
        rows = []
        for lbl, params, patches in CONFIGS:
            r = H.run(s, e, CAPITAL, I.ENGINE, tag='rg_' + lbl[:8].replace(' ', ''),
                      daily_path=R.DAILY_EXT, hourly_path=R.HOURLY_EXT, cost_bps=COST,
                      params=params or None, src_patches=patches)
            rows.append({'config': lbl, 'realized': r['realized'],
                         'return_pct': r['realized_pct'], 'trades': r['trade_count']})
        rows.sort(key=lambda x: -x['realized'])
        for i, row in enumerate(rows, 1):
            row['rank'] = i
        out[wn] = {'window': [s, e], 'series': 'hourly 17:00 bar close',
                   'rows': rows,
                   'buy_and_hold': round(R.buy_and_hold(s, e, CAPITAL, COST), 2)}
    return out


def main():
    print('validating intraday harness ...')
    validate()
    print('  PASS ($30,622.59 / 371 trades)\n')

    out = {'generated': '2026-09-23', 'engine': I.ENGINE, 'window': list(WIN),
           'capital': CAPITAL, 'cost_bps': COST, 'basis': '30-minute OPEN at each mark',
           'marks': {}}
    for mark in MARKS:
        runs, rows = {}, []
        for lbl, params, patches in CONFIGS:
            r = I.replay_intraday(WIN[0], WIN[1], check_times=(mark,),
                                  tag=f'ra_{mark.replace(":", "")}_{lbl[:10].replace(" ", "")}',
                                  params=params or None, src_patches=patches,
                                  cost_bps=COST, capital=CAPITAL,
                                  use_hourly_at_1700=False, exact_open=True)
            runs[lbl] = r
            rows.append({'config': lbl, **summarize(r)})
        rows.sort(key=lambda x: -x['realized'])
        for i, row in enumerate(rows, 1):
            row['rank'] = i
        prod = next(r for r in rows if r['config'].startswith('PRODUCTION'))
        sig = None
        if prod['rank'] != 1:
            sig = {'winner': rows[0]['config'],
                   **bootstrap(runs[rows[0]['config']], runs['PRODUCTION (current rules)'])}
        out['marks'][mark] = {'rows': rows, 'production_rank': prod['rank'],
                              'rank1_significance': sig,
                              'buy_and_hold': buy_and_hold(mark)}

    # rank stability between the two instants that bracket the live fire
    r0 = {r['config']: r['rank'] for r in out['marks'][MARKS[0]]['rows']}
    r1 = {r['config']: r['rank'] for r in out['marks'][MARKS[1]]['rows']}
    out['rank_shift'] = {k: r1[k] - r0[k] for k in r0}
    out['max_rank_shift'] = max(abs(v) for v in out['rank_shift'].values())

    out['regime_diagnosis'] = regime_diagnosis()

    json.dump(out, open(OUT, 'w'), indent=1)
    print(f'wrote {OUT}\n')

    for mark in MARKS:
        m = out['marks'][mark]
        print(f'=== priced at {mark} UTC ({I.utc_to_cdt(mark)})')
        print(f"{'#':>3}  {'configuration':<38}{'realized':>12}{'return':>9}{'sharpe':>8}{'maxDD':>8}{'trades':>7}")
        for r in m['rows']:
            tag = '  <-- LIVE' if r['config'].startswith('PRODUCTION') else ''
            print(f"{r['rank']:>3}  {r['config']:<38}{r['realized']:>12,.0f}{r['return_pct']:>8.1f}%"
                  f"{str(r['sharpe']):>8}{r['max_dd_pct']:>7.1f}%{r['trades']:>7}{tag}")
        print(f"ref  {'Buy & hold, equal weight':<38}{m['buy_and_hold']:>12,.0f}"
              f"{m['buy_and_hold'] / CAPITAL * 100:>8.1f}%")
        if m['rank1_significance']:
            s = m['rank1_significance']
            print(f"  rank-1 test {s['winner']}: CI {s['ci_daily']}  P(better)={s['p_better']}  "
                  f"{'STRADDLES ZERO' if s['straddles_zero'] else 'excludes zero'}")
        print()
    print('rank shift 17:00 -> 17:30:', out['rank_shift'], ' max', out['max_rank_shift'])


if __name__ == '__main__':
    main()
