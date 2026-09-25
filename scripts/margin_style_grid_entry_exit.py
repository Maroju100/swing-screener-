#!/usr/bin/env python3
"""Grid search over Margin-Style Live's NORMAL_DIP entry and exit parameters.

Asked 2026-09-25: "can u do a grid search on normal dip entry and find best
margin live setup parameter of exits".

WHAT IS NEW VS THE 2026-09-22 GRID (research.py grid)
That grid searched INTRADAY_STOP x PEAK_SELL_PCT x MAX_HOLD_DAYS x
NORMAL_DIP_THRESHOLD and found nothing that generalized. It never touched how
LARGE each dip buy is, how many times a name can be added to, the per-trade
cap, or the profit-taking tiers. This grid does, and keeps INTRADAY_STOP fixed
at -1.51% (standing user directive: do not modify the stop).

  entry  NORMAL_DIP_THRESHOLD  0.2% / 0.4%* / 0.8%          yesterday's drop needed
         TRANCHE_SCHEDULE      live* [95,55,35,20,10]% / half [50,30,20,10,5]%
         MAX_TRANCHES          3 / 5*
         first-two-tranche cap 15% / 25%* / 35% of equity per trade
  exit   PEAK_SELL_PCT         50% / 74.3%* / 100%          trim on a new high
         GAIN_TIERS            live* / wider (+30/+15/+8%) / none
         MAX_HOLD_DAYS         4 / 6* / 10
  (* = live value)  3x2x2x3x3x3x3 = 972 configurations. The live configuration
  is one grid point, and it must reproduce production exactly (gate).

METHOD (Evidence Rule 1 -- every number is a full replay of origin/main)
  1. Full window 2026-03-13 -> 2026-09-21, hourly bars, $80k, 5 bps/side:
     all 972 configs. This is the in-sample landscape.
  2. Anchored walk-forward, 3 folds, each an INDEPENDENT flat-start replay:
     pick the best config on the train slice (by Sharpe, and separately by
     realized P&L), then measure it on the untouched test slice vs production.
  3. The in-sample winner is then put through everything the project uses:
     deflated Sharpe against the expected max of 972 noise trials, block
     bootstrap vs production, rising vs falling half, 30-minute bars at 17:00
     and 17:30 UTC (17:30 is the live check time from 2026-09-25), and a
     plateau check (do its one-step neighbours also beat production?).

PASS CRITERIA (fixed before running): walk-forward picks beat production on a
MAJORITY of test folds under BOTH selection rules, AND the in-sample winner
beats production in both halves and at both 30-minute marks, with a bootstrap
CI excluding zero and deflated Sharpe > 0.95. Anything less is reported as
"not an improvement", however large its in-sample number.

Reproduce:
    python3 scripts/margin_style_grid_entry_exit.py
"""
import itertools
import json
import math
import os
import sys
import time
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import margin_style_17h_backtest as H
import margin_style_intraday_study as I
import margin_style_research as R

OUT = os.path.join(R.RESULTS, 'grid_entry_exit.json')
CAPITAL = 80000.0
COST = 5.0
FULL = (R.RESEARCH_START, R.RESEARCH_END)
HALVES = {'rising': ('2026-03-13', '2026-06-19'), 'falling': ('2026-06-22', '2026-09-21')}
FINE = ('2026-06-22', '2026-09-21')
MARKS = ('17:00', '17:30')

SPACE = {
    'dip': [0.002, 0.004, 0.008],
    'tranche': ['live', 'half'],
    'max_tranches': [3, 5],
    'cap': [0.15, 0.25, 0.35],
    'peak': [0.50, 0.743, 1.00],
    'tiers': ['live', 'wider', 'none'],
    'hold': [4, 6, 10],
}
LIVE = {'dip': 0.004, 'tranche': 'live', 'max_tranches': 5, 'cap': 0.25,
        'peak': 0.743, 'tiers': 'live', 'hold': 6}
TRANCHES = {'live': [0.95, 0.55, 0.35, 0.20, 0.10], 'half': [0.50, 0.30, 0.20, 0.10, 0.05]}
TIERS = {'live': [(0.20, 0.90), (0.10, 0.50), (0.05, 0.20)],
         'wider': [(0.30, 0.90), (0.15, 0.50), (0.08, 0.20)],
         'none': []}


def to_params(c):
    return {'NORMAL_DIP_THRESHOLD': c['dip'],
            'TRANCHE_SCHEDULE': TRANCHES[c['tranche']],
            'MAX_TRANCHES': c['max_tranches'],
            'TRADE_CAP_SCHEDULE': [c['cap'], c['cap'], 0.15, 0.10, 0.05],
            'PEAK_SELL_PCT': c['peak'],
            'GAIN_TIERS': TIERS[c['tiers']],
            'MAX_HOLD_DAYS': c['hold']}


def label(c):
    return (f"dip {c['dip']*100:.1f}% | tranche {c['tranche']} x{c['max_tranches']} | "
            f"cap {c['cap']*100:.0f}% | peak {c['peak']*100:.1f}% | tiers {c['tiers']} | "
            f"hold {c['hold']}d")


def _run(job):
    """Worker: one replay. Tag carries the pid so parallel workers never share
    a scratch file (the race that crashed the first grid on 2026-09-22)."""
    start, end, cfg = job
    r = R.replay(start=start, end=end, params=to_params(cfg) if cfg else None,
                 tag=f'gee{os.getpid()}', cost_bps=COST,
                 src_patches=[R.patch_sell_epsilon])
    rets = R.daily_returns(r)
    return {'realized': r['realized'], 'sharpe': R.sharpe_of(rets), 'rets': rets,
            'trades': r['trade_count'], 'max_dd': R.summarize(r)['max_dd_pct']}


def run_many(pool, start, end, cfgs):
    return pool.map(_run, [(start, end, c) for c in cfgs], chunksize=8)


def neighbours(c):
    out = []
    for k, vals in SPACE.items():
        i = vals.index(c[k])
        for j in (i - 1, i + 1):
            if 0 <= j < len(vals):
                n = dict(c)
                n[k] = vals[j]
                out.append(n)
    return out


def main():
    t0 = time.time()
    a = H.run('2026-03-13', '2026-09-04', 80000.0, '859057e', tag='gee_anchor')
    if a['realized'] != 124080.90:
        raise SystemExit('ANCHOR FAILED -- refusing to emit.')

    keys = list(SPACE)
    combos = [dict(zip(keys, v)) for v in itertools.product(*(SPACE[k] for k in keys))]
    live_i = combos.index(LIVE)

    with Pool(4) as pool:
        prod = _run((FULL[0], FULL[1], None))
        print(f'grid: {len(combos)} configs; full-window landscape ...', flush=True)
        full = run_many(pool, FULL[0], FULL[1], combos)
        if abs(full[live_i]['realized'] - prod['realized']) > 0.01:
            raise SystemExit(f"LIVE GRID POINT != PRODUCTION: {full[live_i]['realized']} "
                             f"vs {prod['realized']} -- parameter mapping is wrong, refusing.")
        print(f"gates PASS: anchor $124,080.90; live grid point == production "
              f"${prod['realized']:,.2f}  [{time.time()-t0:.0f}s]", flush=True)

        dates = sorted(R.replay(tag='gee_dates', cost_bps=COST)['day_equity'])
        fl = R.folds(dates, 3)
        folds = []
        for fi, (tr, te) in enumerate(fl, 1):
            train = run_many(pool, tr[0], tr[1], combos)
            pick_s = max(range(len(combos)), key=lambda i: train[i]['sharpe'])
            pick_p = max(range(len(combos)), key=lambda i: train[i]['realized'])
            test = dict(zip(['base', 'sharpe', 'pnl'],
                            pool.map(_run, [(te[0], te[1], None),
                                            (te[0], te[1], combos[pick_s]),
                                            (te[0], te[1], combos[pick_p])])))
            folds.append({
                'fold': fi, 'train': tr, 'test': te,
                'pick_by_sharpe': combos[pick_s], 'pick_by_pnl': combos[pick_p],
                'test_prod': test['base']['realized'],
                'test_pick_sharpe': test['sharpe']['realized'],
                'test_pick_pnl': test['pnl']['realized'],
                'sharpe_pick_won': test['sharpe']['realized'] > test['base']['realized'],
                'pnl_pick_won': test['pnl']['realized'] > test['base']['realized'],
            })
            f = folds[-1]
            print(f"fold {fi} test {te[0]}..{te[1]}: prod ${f['test_prod']:,.0f} | "
                  f"sharpe-pick ${f['test_pick_sharpe']:,.0f} | pnl-pick ${f['test_pick_pnl']:,.0f}"
                  f"  [{time.time()-t0:.0f}s]", flush=True)

        # In-sample winner and its checks
        bi = max(range(len(combos)), key=lambda i: full[i]['realized'])
        best = combos[bi]
        halves = {k: pool.map(_run, [(s, e, None), (s, e, best)]) for k, (s, e) in HALVES.items()}
        nb = neighbours(best)
        nb_res = run_many(pool, FULL[0], FULL[1], nb)

    fine = {}
    for m in MARKS:
        rp = I.replay_intraday(FINE[0], FINE[1], check_times=(m,), tag='gee_fp',
                               cost_bps=COST, capital=CAPITAL, use_hourly_at_1700=False,
                               exact_open=True)
        rb = I.replay_intraday(FINE[0], FINE[1], check_times=(m,), tag='gee_fb',
                               params=to_params(best), src_patches=[R.patch_sell_epsilon],
                               cost_bps=COST, capital=CAPITAL, use_hourly_at_1700=False,
                               exact_open=True)
        fine[m] = {'prod': round(rp['realized'], 2), 'best': round(rb['realized'], 2)}

    lo, hi, pbetter = R.block_bootstrap_diff(full[bi]['rets'], prod['rets'])
    trial_sr = [x['sharpe'] / math.sqrt(252) for x in full]       # daily units
    emax = R.expected_max_sharpe(trial_sr)
    dsr = R.deflated_sharpe(full[bi]['sharpe'] / math.sqrt(252), emax, full[bi]['rets'])

    wf_s = sum(f['sharpe_pick_won'] for f in folds)
    wf_p = sum(f['pnl_pick_won'] for f in folds)
    checks = {
        'walk-forward: Sharpe-selected pick wins majority of test folds': wf_s >= 2,
        'walk-forward: P&L-selected pick wins majority of test folds': wf_p >= 2,
        'in-sample winner beats production in rising half':
            halves['rising'][1]['realized'] > halves['rising'][0]['realized'],
        'in-sample winner beats production in falling half':
            halves['falling'][1]['realized'] > halves['falling'][0]['realized'],
        'in-sample winner beats production at 17:00 (30-min bars)':
            fine['17:00']['best'] > fine['17:00']['prod'],
        'in-sample winner beats production at 17:30 (30-min bars, live time)':
            fine['17:30']['best'] > fine['17:30']['prod'],
        'bootstrap CI on daily difference excludes zero': lo > 0,
        'deflated Sharpe > 0.95': dsr > 0.95,
    }
    beat = sorted(range(len(combos)), key=lambda i: -full[i]['realized'])
    rank_live = beat.index(live_i) + 1
    out = {
        'generated': '2026-09-25', 'engine': 'origin/main', 'capital': CAPITAL,
        'cost_bps': COST, 'window': list(FULL), 'n_configs': len(combos),
        'space': SPACE, 'live_config': LIVE,
        'production': {'realized': prod['realized'], 'pct': round(prod['realized'] / CAPITAL * 100, 2),
                       'sharpe': round(prod['sharpe'], 3), 'max_dd': prod['max_dd'],
                       'rank_of_live_in_grid': rank_live},
        'n_configs_beating_production_in_sample':
            sum(1 for x in full if x['realized'] > prod['realized']),
        'top10_in_sample': [{'config': combos[i], 'label': label(combos[i]),
                             'realized': full[i]['realized'],
                             'pct': round(full[i]['realized'] / CAPITAL * 100, 2),
                             'sharpe': round(full[i]['sharpe'], 3),
                             'max_dd': full[i]['max_dd'], 'trades': full[i]['trades']}
                            for i in beat[:10]],
        'walk_forward': folds,
        'in_sample_winner': {
            'config': best, 'label': label(best),
            'realized': full[bi]['realized'], 'pct': round(full[bi]['realized'] / CAPITAL * 100, 2),
            'halves': {k: {'prod': v[0]['realized'], 'best': v[1]['realized']} for k, v in halves.items()},
            'fine': fine,
            'bootstrap': {'ci_daily': [lo, hi], 'p_better': pbetter},
            'deflated_sharpe': round(dsr, 4),
            'expected_max_sharpe_annualized': round(emax * math.sqrt(252), 3),
            'observed_sharpe_annualized': round(full[bi]['sharpe'], 3),
            'plateau': {'neighbours': len(nb),
                        'neighbours_beating_production':
                            sum(1 for x in nb_res if x['realized'] > prod['realized'])},
        },
        'checks': checks, 'checks_passed': sum(checks.values()),
        'verdict': ('PASS -- forward-track candidate, not yet a change' if all(checks.values())
                    else 'NOT AN IMPROVEMENT -- production stays'),
        'runtime_seconds': round(time.time() - t0),
    }
    json.dump(out, open(OUT, 'w'), indent=1)
    print(f'\nwrote {OUT}  [{time.time()-t0:.0f}s]')
    report(out)


def report(o):
    P = o['production']
    print(f"\nPRODUCTION  ${P['realized']:,.2f} ({P['pct']:+.1f}%)  Sharpe {P['sharpe']}  "
          f"maxDD {P['max_dd']}%  -> rank {P['rank_of_live_in_grid']} of {o['n_configs']}")
    print(f"{o['n_configs_beating_production_in_sample']} configs beat production IN-SAMPLE\n")
    print('TOP 10 IN-SAMPLE')
    for i, t in enumerate(o['top10_in_sample'], 1):
        print(f"  {i:>2} {t['pct']:+7.1f}%  SR {t['sharpe']:.2f}  DD {t['max_dd']:6.1f}%  {t['label']}")
    print('\nWALK-FORWARD (each test slice replayed flat)')
    for f in o['walk_forward']:
        print(f"  fold {f['fold']} test {f['test'][0]}..{f['test'][1]}: prod ${f['test_prod']:>10,.0f} | "
              f"Sharpe-pick ${f['test_pick_sharpe']:>10,.0f} {'WIN' if f['sharpe_pick_won'] else 'loss'} | "
              f"P&L-pick ${f['test_pick_pnl']:>10,.0f} {'WIN' if f['pnl_pick_won'] else 'loss'}")
        print(f"     sharpe-pick: {label(f['pick_by_sharpe'])}")
        print(f"     pnl-pick:    {label(f['pick_by_pnl'])}")
    w = o['in_sample_winner']
    print(f"\nIN-SAMPLE WINNER {w['pct']:+.1f}%: {w['label']}")
    for k, v in w['halves'].items():
        print(f"  {k:8} half: prod ${v['prod']:>10,.0f}  winner ${v['best']:>10,.0f}")
    for m, v in w['fine'].items():
        print(f"  30-min {m}: prod ${v['prod']:>10,.0f}  winner ${v['best']:>10,.0f}")
    b = w['bootstrap']
    print(f"  bootstrap CI [{b['ci_daily'][0]*100:+.3f}%, {b['ci_daily'][1]*100:+.3f}%] P={b['p_better']:.3f}")
    print(f"  Sharpe {w['observed_sharpe_annualized']} vs expected-max-on-noise "
          f"{w['expected_max_sharpe_annualized']}; deflated Sharpe {w['deflated_sharpe']}")
    print(f"  plateau: {w['plateau']['neighbours_beating_production']}/{w['plateau']['neighbours']} "
          f"one-step neighbours beat production")
    print('\nCHECKS')
    for k, v in o['checks'].items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")
    print(f"\n=> {o['verdict']}")


if __name__ == '__main__':
    main()
