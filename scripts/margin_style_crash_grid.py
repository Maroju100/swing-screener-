"""Crash-protection grid: can rule settings handle an Oct-Nov-style semis crash without
giving up the good months? (asked 2026-11-05)

Real engine (origin/main) + the committed protection patches (margin_style_protect_rules*,
margin_style_sizing_rules), $15,000, 5 bps/side, data through 2026-11-03.
INTRADAY_STOP is NOT varied (standing directive).

GRID, fixed before any run (* = live):
  KILL_SWITCH_DD          -6%, -8%, -10%, -12%, -15%*
  KILL_SWITCH_RESUME_DAYS 5, 10, 20*
  NO_TREND_GATE           off*, on      (drop the permanent SMA-50 re-entry gate)
  VOL_SIZE                off*, 3%      (scale buys by min(1, 3% / 20-day vol))
  CIRCUIT_BREAKER_STOP_COUNT 1, 2*
  EQ_FILTER_DAYS          0*, 10        (no buys while equity < its 10-run average)
  = 240 configs.
WINDOWS (each a fresh flat start): RISING Mar 13-Jun 19, FALLING Jun 22-Sep 30,
  CRASH Oct 1-Nov 3, FULL Mar 13-Nov 3.
PASS, fixed before any run: beat production in ALL FOUR windows AND a block-bootstrap CI on
  the FULL-window daily-return difference that excludes zero.
Also reported, to show the overfitting risk: the config that is best on the CRASH window
alone, and what it does elsewhere; and walk-forward both ways (pick on Mar-Sep, test on the
crash; pick on the crash, test on Mar-Sep).
Reproduce: python3 scripts/margin_style_crash_grid.py   (~4 cores)
"""
import itertools, json, os, sys
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_protect_rules as P1
import margin_style_protect_rules2 as P2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY = os.path.join(ROOT, 'data', 'margin_live_daily_ext_2025-11-03_2026-11-03.json')
HOURLY = os.path.join(ROOT, 'data', 'margin_live_hourly_ext_2026-03-06_2026-11-03.json')
CAP, COST = 15000.0, 5.0
W = {'rising': ('2026-03-13', '2026-06-19'), 'falling': ('2026-06-22', '2026-09-30'),
     'crash': ('2026-10-01', '2026-11-03'), 'full': ('2026-03-13', '2026-11-03')}
GRID = list(itertools.product([-0.06, -0.08, -0.10, -0.12, -0.15], [5, 10, 20], [False, True],
                              [False, True], [1, 2], [0, 10]))
LIVE = (-0.15, 20, False, False, 2, 0)


def params(c):
    dd, rd, ntg, vol, cb, eq = c
    p = {'KILL_SWITCH_DD': dd, 'KILL_SWITCH_RESUME_DAYS': rd, 'NO_TREND_GATE': ntg,
         'CIRCUIT_BREAKER_STOP_COUNT': cb, 'EQ_FILTER_DAYS': eq}
    if vol:
        p.update(VOL_SIZE=True, VOL_TARGET=0.03)
    return p


def label(c):
    dd, rd, ntg, vol, cb, eq = c
    return (f"kill {int(dd * 100)}%/{rd}d" + (" noSMA" if ntg else "") + (" vol3%" if vol else "")
            + f" cb{cb}" + (" eq10" if eq else ""))


def one(c):
    out = {}
    for w, (a, b) in W.items():
        r = R.replay(start=a, end=b, params=params(c), tag=f"cg_{'_'.join(map(str, c))}_{w}", cost_bps=COST,
                     capital=CAP, src_patches=P2.PATCHES, daily=DAILY, hourly=HOURLY)
        eq = [v for _, v in sorted(r['day_equity'].items())]
        pk, dd = 0, 0
        for v in eq:
            pk = max(pk, v); dd = min(dd, v / pk - 1)
        out[w] = {'ret': (eq[-1] / CAP - 1) * 100, 'dd': dd * 100}
        if w == 'full':
            out['rets'] = R.daily_returns(r)
    return c, out


def main():
    g = R.replay(start='2026-03-13', end='2026-09-21', params={}, tag='cg_gate', cost_bps=COST,
                 src_patches=P2.PATCHES, daily=DAILY, hourly=HOURLY)
    if abs(g['realized'] - 124289.71) > 0.005 or g['trade_count'] != 771:
        raise SystemExit(f"GATE FAILED: {g['realized']} / {g['trade_count']}")
    print('gate PASS: patches off reproduce production on the extended files\n', flush=True)
    with Pool(4) as pool:
        res = dict(pool.map(one, GRID))
    base = res[LIVE]
    rows = []
    for c, r in res.items():
        if c == LIVE:
            continue
        wins = {w: r[w]['ret'] > base[w]['ret'] for w in W}
        lo, hi, pb = R.block_bootstrap_diff(r['rets'], base['rets'])
        rows.append((c, r, wins, (lo, hi, pb)))
    passing = [x for x in rows if all(x[2].values()) and x[3][0] > 0]
    fmt = lambda r: '  '.join(f"{w} {r[w]['ret']:+6.1f}% (dd {r[w]['dd']:+5.1f})" for w in W)
    print(f"{'PRODUCTION':34} {fmt(base)}")
    print(f"\nconfigs beating production in all 4 windows: {sum(all(x[2].values()) for x in rows)} of {len(rows)};"
          f" also passing bootstrap: {len(passing)}")
    for c, r, wins, bs in sorted(rows, key=lambda x: -sum(x[2].values()) * 1000 - x[1]['full']['ret'])[:10]:
        print(f"{label(c):34} {fmt(r)}  wins {sum(wins.values())}/4  P={bs[2]:.2f}")
    crash_best = max(rows, key=lambda x: x[1]['crash']['ret'])
    print(f"\nBEST ON CRASH ONLY: {label(crash_best[0])}\n  {fmt(crash_best[1])}")
    train = max(rows + [(LIVE, base, {}, (0, 0, 0))],
                key=lambda x: (1 + x[1]['rising']['ret'] / 100) * (1 + x[1]['falling']['ret'] / 100))
    print(f"\nWALK-FORWARD pick on Mar-Sep (rising x falling) -> {label(train[0])}: crash {train[1]['crash']['ret']:+.1f}%"
          f" vs production {base['crash']['ret']:+.1f}%")
    print(f"WALK-FORWARD pick on crash -> {label(crash_best[0])}: rising {crash_best[1]['rising']['ret']:+.1f}% / falling "
          f"{crash_best[1]['falling']['ret']:+.1f}% vs production {base['rising']['ret']:+.1f}% / {base['falling']['ret']:+.1f}%")
    R.save('crash_grid.json', {'windows': W, 'production': {w: base[w] for w in W},
                               'results': [{'config': label(c), **{w: r[w] for w in W}, 'wins': wins,
                                            'bootstrap': bs} for c, r, wins, bs in rows],
                               'passing': [label(x[0]) for x in passing]})


if __name__ == '__main__':
    main()
