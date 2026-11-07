#!/usr/bin/env python3
"""Margin-Style Live v3 candidate: grid-optimized rules for NON-SEMI stocks (asked 2026-11-07).

NOT A LIVE CHANGE. Research candidate only.
Grid (fixed before any run; 162 configs per universe):
  NORMAL_DIP_THRESHOLD  0.2% / 0.4%* / 0.8%
  PEAK_SELL_PCT         50% / 74.3%* / 100%
  MAX_HOLD_DAYS         4 / 6* / 10
  KILL_SWITCH_DD        -8%* / -12% / -15%
  KILL_SWITCH_RESUME    10* / 20 trading days
  (* = v2 live value).  INTRADAY_STOP is FIXED at -1.51% (standing directive); all other rules untouched.
Universes: BIG TECH (6), NON-TECH 8, SECTOR ETFs (8), ALL NON-SEMI (22). Semis are excluded.
Windows:
  TRAIN    2026-03-13 -> 2026-06-19   the ONLY window the grid is selected on
  TEST     2026-06-22 -> 2026-09-21   chosen config evaluated, not used to choose
  HOLDOUT  2026-09-22 -> 2026-11-05   evaluated last, not used to choose (incl. the Oct sell-off)
Selection: max TRAIN return per universe. Baseline: v2 live values, same universe.
Pre-set pass rule (per universe): v3 beats v2 on TEST AND on HOLDOUT, and the block-bootstrap 95% CI on
the combined TEST+HOLDOUT daily-return difference excludes zero.
Also reported: how many of the 162 configs beat v2 on TRAIN (multiple-testing context).
Engine origin/main; $15k; 5 bps/side; 17:00 UTC hourly check price. MEASURED by full engine replay.
Caveat: XLF/XLV daily closes after Oct 16 are last regular hourly close (see data README in v1v2 study).
Reproduce: python3 scripts/margin_style_v3_grid_other.py
"""
import itertools, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_17h_backtest as H
import margin_style_instant_settlement as IS
import margin_style_v1v2_other_stocks as O

CAP, COST = 15000.0, 5.0
PATCHES = [R.patch_sell_epsilon, IS.patch_instant]
W = {'TRAIN': ('2026-03-13', '2026-06-19'), 'TEST': ('2026-06-22', '2026-09-21'), 'HOLDOUT': ('2026-09-22', '2026-11-05')}
GRID = list(itertools.product([0.002, 0.004, 0.008], [0.5, 0.743, 1.0], [4, 6, 10],
                              [-0.08, -0.12, -0.15], [10, 20]))
V2 = (0.004, 0.743, 6, -0.08, 10)
UNIVERSES = {'BIG TECH': O.BASKETS['BIG TECH'], 'NON-TECH 8': O.BASKETS['NON-TECH 8'],
             'SECTOR ETFs': O.BASKETS['SECTOR ETFs'],
             'ALL NON-SEMI (22)': O.BASKETS['BIG TECH'] + O.BASKETS['NON-TECH 8'] + O.BASKETS['SECTOR ETFs']}


def params(c):
    dip, peak, hold, kdd, kres = c
    return {'NORMAL_DIP_THRESHOLD': dip, 'PEAK_SELL_PCT': peak, 'MAX_HOLD_DAYS': hold,
            'KILL_SWITCH_DD': kdd, 'KILL_SWITCH_RESUME_DAYS': kres, 'KILL_SWITCH_RESET_PEAK_ON_RELEASE': True,
            'KILL_SWITCH_TREND_LOCK': False, 'MIN_NOTIONAL': 500.0}


def replay(univ, c, win):
    s, e = W[win]
    H.UNIVERSE = list(univ)
    r = R.replay(start=s, end=e, params=params(c), tag='v3', engine='origin/main', cost_bps=COST, capital=CAP,
                 src_patches=PATCHES, daily=O.DAILY, hourly=O.HOURLY)
    de = sorted(r['day_equity'].items()); eq = [v for _, v in de]
    pk = dd = 0
    for v in eq:
        pk = max(pk, v); dd = min(dd, v / pk - 1)
    rets = [eq[i] / eq[i-1] - 1 for i in range(1, len(eq))]
    return {'ret': (eq[-1] / CAP - 1) * 100, 'dd': dd * 100, 'trades': r['trade_count'], 'rets': rets}


def main():
    g = None
    H.UNIVERSE = list(O.SEMIS)
    g = R.replay(start='2026-03-13', end='2026-09-21', params=dict(O.V['v1']), tag='v3gate', engine='origin/main', cost_bps=5.0,
                 capital=80000.0, src_patches=PATCHES, daily=O.DAILY, hourly=O.HOURLY)
    assert abs(g['realized'] - 124289.71) < 0.005 and g['trade_count'] == 771, 'GATE FAILED'
    print('gate PASS: v1 params reproduce production on these files', flush=True)
    out = {}
    for name, univ in UNIVERSES.items():
        train = {}
        for c in GRID:
            train[c] = replay(univ, c, 'TRAIN')['ret']
        best = max(train, key=train.get)
        beat_v2_train = sum(1 for c in GRID if train[c] > train[V2])
        res = {'v2_train': train[V2], 'best_cfg': dict(zip(['dip', 'peak', 'hold', 'kill_dd', 'kill_resume'], best)),
               'best_train': train[best], 'configs_beating_v2_on_train': beat_v2_train, 'grid_size': len(GRID)}
        for win in ('TEST', 'HOLDOUT'):
            v3 = replay(univ, best, win); v2 = replay(univ, V2, win)
            res[win] = {'v3': v3['ret'], 'v2': v2['ret'], 'v3_dd': v3['dd'], 'v2_dd': v2['dd'],
                        'hold': O.hold(univ) if False else None,
                        'v3_rets': v3['rets'], 'v2_rets': v2['rets']}
        n = min(len(res['TEST']['v3_rets']), len(res['TEST']['v2_rets']))
        a = res['TEST']['v3_rets'] + res['HOLDOUT']['v3_rets']
        b = res['TEST']['v2_rets'] + res['HOLDOUT']['v2_rets']
        lo, hi, pb = R.block_bootstrap_diff(a, b)
        res['boot_TEST_HOLDOUT'] = [round(lo * 100, 3), round(hi * 100, 3), round(pb, 3)]
        res['passed'] = (res['TEST']['v3'] > res['TEST']['v2'] and res['HOLDOUT']['v3'] > res['HOLDOUT']['v2'] and lo > 0)
        for win in ('TEST', 'HOLDOUT'):
            res[win].pop('v3_rets'); res[win].pop('v2_rets'); res[win].pop('hold')
        out[name] = res
        print(f"{name:18} TRAIN best {res['best_cfg']} -> {res['best_train']:+6.1f}% (v2 {res['v2_train']:+6.1f}%, "
              f"{beat_v2_train}/{len(GRID)} beat v2) | TEST v3 {res['TEST']['v3']:+6.1f} v2 {res['TEST']['v2']:+6.1f} | "
              f"HOLDOUT v3 {res['HOLDOUT']['v3']:+6.1f} v2 {res['HOLDOUT']['v2']:+6.1f} | "
              f"boot {res['boot_TEST_HOLDOUT']} | PASS={res['passed']}", flush=True)
    R.save('v3_grid_other.json', {'grid': GRID, 'v2': V2, 'windows': W, 'results': out})


if __name__ == '__main__':
    main()
