"""Out-of-sample test of the v3 filters already reported in CLAUDE.md (asked 2026-10-30).

The filter results in CLAUDE.md (ER>=0.30, SPY up on day, RS>0 vs SPY) were measured on
2026-08-10 -> 2026-09-21. Since then 28 new trading days of real 1-minute bars exist
(2026-09-22 -> 2026-10-29), which none of those studies saw. This replays the SAME
variants, unchanged, on the new window only -- a genuine holdout, nothing re-tuned.
Pre-set pass rule: on the holdout at 5 bps/side a variant must (a) be positive and
(b) beat the unfiltered engine. $5,000 (the engine's own capital), MU/SNDK/WDC.
Real engine (scripts/daytrading_v3_paper_engine.py) via scripts/v3_replay.py.
Reproduce: python3 scripts/v3_holdout.py
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v3_replay as VR

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOWS = {
    'in-sample Aug 10-Sep 21': (['semis_1min_2026-08-10_2026-09-21.json'], 'bench_1min_2026-08-10_2026-09-21.json'),
    'HOLDOUT Sep 22-Oct 29': (['semis_1min_2026-09-22_2026-10-16.json', 'semis_1min_2026-10-19_2026-10-29.json'],
                              'bench_1min_2026-09-22_2026-10-29.json'),
}
VARIANTS = [('no filter', None, None, None), ('ER >= 0.30', 0.30, None, None),
            ('SPY up on day', None, None, 'SPY'), ('RS > 0 vs SPY', None, 'SPY', None)]
COST = 5.0


def load(files, bench):
    bars = {}
    for f in files:
        for s, days in json.load(open(os.path.join(ROOT, 'data', f)))['bars'].items():
            bars.setdefault(s, {}).update(days)
    bb = json.load(open(os.path.join(ROOT, 'data', bench)))['bars']
    return bars, bb


out = {}
for params in ('baseline', 'tightened'):
    print(f"\n=== v3 {params}, $5,000, {COST:.0f} bps/side ===")
    for wname, (files, bench) in WINDOWS.items():
        bars, bb = load(files, bench)
        days = sorted(next(iter(bars.values())))
        er = VR.basket_er(bars, days, 30)
        print(f"  {wname} ({len(days)} days)")
        res = {}
        for label, g, rsb, mb in VARIANTS:
            er_open = None if g is None else {d: v >= g for d, v in er.items()}
            rs_t = VR.rs_tables(bars, bb, rsb)[0] if rsb else None
            bt = VR.rs_tables(bars, bb, mb)[1] if mb else None
            r = VR.replay(f'ho_{params}_{wname[:4]}_{label[:6]}', VR.PARAMS[params], days, bars, er_open, 30, COST,
                          rs_t, 0.0, bt)
            ret = (r['equity'] / 5000 - 1) * 100
            res[label] = ret
            print(f"    {label:16} {ret:+6.2f}%  (${r['equity'] - 5000:+,.0f}, {r['trades']} trades)")
        out.setdefault(params, {})[wname] = res
    h = out[params]['HOLDOUT Sep 22-Oct 29']
    for label in h:
        if label != 'no filter':
            ok = h[label] > 0 and h[label] > h['no filter']
            print(f"  HOLDOUT verdict {label:16}: {'PASS' if ok else 'fail'}")
json.dump(out, open(os.path.join(ROOT, 'data', 'research', 'v3_holdout.json'), 'w'), indent=1)
