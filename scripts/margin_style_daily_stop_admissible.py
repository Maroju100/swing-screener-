#!/usr/bin/env python3
"""The 1% daily stop, replayed on every basis the rest of the research uses.

CLAUDE.md already records the daily stop as harmful (+79.71% vs +155.10%), but
only at ZERO cost on the 122-day anchor window. Every other variant has since
been measured at 5 bps/side on the 132-day window AND on the admissible 30-minute
series. This puts the daily stop on the same footing so it can sit in the same
table as everything else.

METHOD
  * Engine f170602: the only revision carrying the daily stop with its
    double-sell defect FIXED, gated by DAILY_STOP_ENABLED. Comparing flag OFF
    against flag ON on that one engine isolates the stop and nothing else.
  * Flag OFF is then checked against origin/main (production) on each basis.
    If they match, the OFF column IS production and the stop's delta is a delta
    against the live rules. If they do not, that is reported, not smoothed over.
  * Bases: hourly 132 days (the committed ranking's basis, priced ~1 PM CDT);
    30-minute 64 days at 17:00 and at 17:30 UTC (the admissible series,
    bracketing the ~17:14 live fire). $80k, 5 bps/side.

Reproduce:
    python3 scripts/margin_style_daily_stop_admissible.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import margin_style_17h_backtest as H
import margin_style_intraday_study as I
import margin_style_research as R

OUT = os.path.join(I.RESULTS, 'daily_stop.json')
STOP_ENGINE = 'f170602'
PROD_ENGINE = 'origin/main'
CAPITAL = 80000.0
COST = 5.0
FULL = ('2026-03-13', '2026-09-21')
FINE = ('2026-06-22', '2026-09-21')


def hourly(engine, params, tag):
    r = H.run(FULL[0], FULL[1], CAPITAL, engine, tag=tag, daily_path=R.DAILY_EXT,
              hourly_path=R.HOURLY_EXT, cost_bps=COST, params=params)
    stops = sum(1 for t in r['trades'] if t.get('reason') == 'DAILY_STOP')
    return {'realized': r['realized'], 'return_pct': r['realized_pct'],
            'trades': r['trade_count'], 'daily_stop_sells': stops,
            'daily_stop_days': len(r['daily_stop_days'])}


def fine(engine, params, mark, tag):
    saved = I.ENGINE
    I.ENGINE = engine
    try:
        r = I.replay_intraday(FINE[0], FINE[1], check_times=(mark,), tag=tag,
                              params=params, cost_bps=COST, capital=CAPITAL,
                              use_hourly_at_1700=False, exact_open=True)
    finally:
        I.ENGINE = saved
    return {'realized': round(r['realized'], 2),
            'return_pct': round(r['realized'] / CAPITAL * 100, 2), 'trades': r['trades']}


def main():
    v = H.run('2026-03-13', '2026-09-04', 80000.0, '859057e', tag='ds_anchor')
    if v['realized'] != 124080.90:
        raise SystemExit('ANCHOR FAILED -- refusing to emit.')
    print('anchor PASS ($124,080.90)')

    out = {'generated': '2026-09-23', 'stop_engine': STOP_ENGINE,
           'prod_engine': PROD_ENGINE, 'capital': CAPITAL, 'cost_bps': COST,
           'DAILY_STOP_PCT': 0.01, 'bases': {}}

    bases = [('hourly_132d', 'hourly bars, 2026-03-13..09-21, priced ~1:00 PM CDT', None),
             ('min30_64d_1700', '30-min bars, 2026-06-22..09-21, 12:00 PM CDT', '17:00'),
             ('min30_64d_1730', '30-min bars, 2026-06-22..09-21, 12:30 PM CDT', '17:30')]
    for key, desc, mark in bases:
        if mark is None:
            prod = hourly(PROD_ENGINE, None, 'ds_h_prod')
            off = hourly(STOP_ENGINE, {'DAILY_STOP_ENABLED': False}, 'ds_h_off')
            on = hourly(STOP_ENGINE, {'DAILY_STOP_ENABLED': True}, 'ds_h_on')
        else:
            m = mark.replace(':', '')
            prod = fine(PROD_ENGINE, None, mark, f'ds_{m}_prod')
            off = fine(STOP_ENGINE, {'DAILY_STOP_ENABLED': False}, mark, f'ds_{m}_off')
            on = fine(STOP_ENGINE, {'DAILY_STOP_ENABLED': True}, mark, f'ds_{m}_on')
        out['bases'][key] = {
            'description': desc, 'production': prod,
            'stop_engine_flag_off': off, 'daily_stop_on': on,
            'flag_off_matches_production': abs(off['realized'] - prod['realized']) < 0.01,
            'stop_delta_vs_production': round(on['realized'] - prod['realized'], 2),
        }
        b = out['bases'][key]
        print(f"\n{desc}")
        print(f"  production         ${prod['realized']:>12,.2f}  {prod['return_pct']:+.2f}%")
        print(f"  f170602 flag OFF   ${off['realized']:>12,.2f}  "
              f"{'== production' if b['flag_off_matches_production'] else '!! DIFFERS from production'}")
        print(f"  1% daily stop ON   ${on['realized']:>12,.2f}  {on['return_pct']:+.2f}%  "
              f"(delta {b['stop_delta_vs_production']:+,.2f})")

    json.dump(out, open(OUT, 'w'), indent=1)
    print(f'\nwrote {OUT}')


if __name__ == '__main__':
    main()
