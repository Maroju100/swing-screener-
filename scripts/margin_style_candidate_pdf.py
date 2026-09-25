#!/usr/bin/env python3
"""Validate the "optimized candidate" from the user's uploaded PDF (2026-09-25).

The PDF ("Margin-live rule comparison") proposes three changes to production:
  1. TRANCHE_SCHEDULE  [95,55,35,20,10]%  ->  [50,30,20,10,5]%
  2. PEAK_SELL_PCT     74.3%              ->  100%  (full exit on a new high)
  3. daily check       17:30 UTC          ->  18:00 UTC
and reports, on the hourly basis over 2026-03-13 -> 2026-09-04 at $80k:
  0 bps: $124,080.90 (+155.10%) -> $128,438.15 (+160.55%)
  5 bps: $116,932.14 (+146.17%) -> $120,675.15 (+150.84%)
It states itself that this is in-sample and not independent validation. The
candidate is one point in the 972-config grid (scripts/margin_style_grid_entry_exit.py:
dip 0.4%, tranche half x5, cap 25%, peak 100%, live tiers, hold 6d), so it was
selected from ~972 trials.

STEP 1  Reproduce the PDF's four numbers exactly. If they do not reproduce,
        stop: the claim and this harness disagree and neither can be trusted.
STEP 2  Same battery as scripts/margin_style_rule_ideas.py, fixed in advance:
        full 132-day window, each third from a flat start, rising vs falling
        half, 30-minute bars, bootstrap. The check-time change is measured
        separately on 30-minute bars at 17:30 vs 18:00, because the hourly
        basis (~18:00) cannot see it at all -- as the PDF itself notes.
STEP 3  Attribution: each rule change on its own.

PASS CRITERIA (same as every study since 2026-09-24): beat production on the
full window, all three thirds, both halves, both 30-minute marks, and a
bootstrap CI excluding zero.

Reproduce:
    python3 scripts/margin_style_candidate_pdf.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import margin_style_17h_backtest as H
import margin_style_intraday_study as I
import margin_style_research as R

OUT = os.path.join(R.RESULTS, 'candidate_pdf.json')
CAPITAL = 80000.0
COST = 5.0
FULL = (R.RESEARCH_START, R.RESEARCH_END)
HALVES = {'rising': ('2026-03-13', '2026-06-19'), 'falling': ('2026-06-22', '2026-09-21')}
FINE = ('2026-06-22', '2026-09-21')
MARKS = ('17:30', '18:00')
HALF = [0.50, 0.30, 0.20, 0.10, 0.05]

VARIANTS = {
    'CANDIDATE (both rule changes)': {'TRANCHE_SCHEDULE': HALF, 'PEAK_SELL_PCT': 1.0},
    'Smaller tranches only': {'TRANCHE_SCHEDULE': HALF},
    'Full exit on new high only': {'PEAK_SELL_PCT': 1.0},
}
PATCH = [R.patch_sell_epsilon]


def hourly(start, end, params, tag, engine=R.ENGINE, cost=COST):
    return R.replay(start=start, end=end, params=params, tag=tag, engine=engine,
                    src_patches=PATCH, cost_bps=cost)


def fine(mark, params, tag):
    return I.replay_intraday(FINE[0], FINE[1], check_times=(mark,), tag=tag,
                             params=params, src_patches=PATCH, cost_bps=COST,
                             capital=CAPITAL, use_hourly_at_1700=False, exact_open=True)


def pct(x):
    return round(x / CAPITAL * 100, 2)


def main():
    # STEP 1 -- reproduce the PDF on its own stated basis: anchor window and data,
    # engine origin/main (the PDF names main @ 3bc7930; main reproduces the
    # $124,080.90 anchor to the cent at 0 bps, so this is the same basis).
    claims = {}
    for cost in (0.0, 5.0):
        b = H.run('2026-03-13', '2026-09-04', CAPITAL, R.ENGINE, tag=f'pdf_b{int(cost)}',
                  cost_bps=cost, src_patches=PATCH)
        c = H.run('2026-03-13', '2026-09-04', CAPITAL, R.ENGINE, tag=f'pdf_c{int(cost)}',
                  cost_bps=cost, src_patches=PATCH,
                  params=VARIANTS['CANDIDATE (both rule changes)'])
        claims[f'{cost:g}bps'] = {'baseline': b['realized'], 'candidate': c['realized']}
    expected = {'0bps': (124080.90, 128438.15), '5bps': (116932.14, 120675.15)}
    repro = {k: (abs(claims[k]['baseline'] - v[0]) < 0.01 and abs(claims[k]['candidate'] - v[1]) < 0.01)
             for k, v in expected.items()}
    print('STEP 1  reproduce the PDF:')
    for k, v in expected.items():
        print(f"  {k}: baseline ${claims[k]['baseline']:,.2f} (PDF ${v[0]:,.2f})  "
              f"candidate ${claims[k]['candidate']:,.2f} (PDF ${v[1]:,.2f})  "
              f"{'REPRODUCED' if repro[k] else 'MISMATCH'}")
    if not all(repro.values()):
        raise SystemExit('PDF figures do not reproduce -- refusing to evaluate further.')

    # STEP 2 -- the standard battery, on production's own engine and window
    base = hourly(FULL[0], FULL[1], None, 'pdf_base')
    days = sorted(base['day_pnl'])
    k = len(days) // 3
    thirds = [(days[0], days[k - 1]), (days[k], days[2 * k - 1]), (days[2 * k], days[-1])]
    prod = {'full': base,
            'thirds': [hourly(s, e, None, f'pdf_pt{i}') for i, (s, e) in enumerate(thirds)],
            'halves': {h: hourly(s, e, None, f'pdf_ph{h}') for h, (s, e) in HALVES.items()},
            'fine': {m: fine(m, None, f'pdf_pf{m[:2]}{m[3:]}') for m in MARKS}}

    out = {'generated': '2026-09-25', 'source': 'user-uploaded PDF "Margin-live rule comparison"',
           'pdf_reproduction': {'claims': claims, 'reproduced': repro},
           'engine': R.ENGINE, 'window': list(FULL), 'capital': CAPITAL, 'cost_bps': COST,
           'thirds': thirds,
           'production': {'full_pct': pct(base['realized']), 'summary': R.summarize(base),
                          'thirds_pct': [pct(r['realized']) for r in prod['thirds']],
                          'halves_pct': {h: pct(r['realized']) for h, r in prod['halves'].items()},
                          'fine_pct': {m: pct(r['realized']) for m, r in prod['fine'].items()}},
           'variants': []}

    for i, (lbl, params) in enumerate(VARIANTS.items()):
        vf = hourly(FULL[0], FULL[1], params, f'pdf_v{i}f')
        vt = [hourly(s, e, params, f'pdf_v{i}t{j}') for j, (s, e) in enumerate(thirds)]
        vh = {h: hourly(s, e, params, f'pdf_v{i}h{h}') for h, (s, e) in HALVES.items()}
        vn = {m: fine(m, params, f'pdf_v{i}m{m[:2]}{m[3:]}') for m in MARKS}
        lo, hi, p = R.block_bootstrap_diff(R.daily_returns(vf), R.daily_returns(base))
        checks = {
            'full window': vf['realized'] > base['realized'],
            'all 3 thirds': all(v['realized'] > b['realized'] for v, b in zip(vt, prod['thirds'])),
            'both halves': all(vh[h]['realized'] > prod['halves'][h]['realized'] for h in HALVES),
            'both 30-min marks (same time)': all(vn[m]['realized'] > prod['fine'][m]['realized'] for m in MARKS),
            'bootstrap CI excludes 0': lo > 0,
        }
        out['variants'].append({
            'variant': lbl, 'params': {k2: v2 for k2, v2 in params.items()},
            'full_pct': pct(vf['realized']), 'summary': R.summarize(vf),
            'full_delta': round(vf['realized'] - base['realized'], 2),
            'thirds_pct': [pct(r['realized']) for r in vt],
            'halves_pct': {h: pct(r['realized']) for h, r in vh.items()},
            'fine_pct': {m: pct(r['realized']) for m, r in vn.items()},
            'bootstrap': {'ci_daily': [lo, hi], 'p_better': p},
            'checks': checks, 'checks_passed': sum(checks.values()),
            'verdict': 'PASS' if all(checks.values()) else 'NOT AN IMPROVEMENT'})

    # The deployment comparison the PDF actually proposes: candidate rules at
    # 18:00 vs production rules at 17:30 (live since 2026-09-25), 30-min bars.
    cand = next(v for v in out['variants'] if v['variant'].startswith('CANDIDATE'))
    out['deployment_comparison_30min'] = {
        'production_at_1730': out['production']['fine_pct']['17:30'],
        'production_at_1800': out['production']['fine_pct']['18:00'],
        'candidate_at_1730': cand['fine_pct']['17:30'],
        'candidate_at_1800': cand['fine_pct']['18:00'],
    }
    json.dump(out, open(OUT, 'w'), indent=1)
    print(f'\nwrote {OUT}\n')
    report(out)


def report(o):
    P = o['production']
    hk = list(o['production']['halves_pct'])
    print(f"{'':36}{'6mo':>8}{'T1':>8}{'T2':>8}{'T3':>8}{'rise':>8}{'fall':>8}{'17:30':>8}{'18:00':>8}  pass")
    def line(n, f, t, h, m, x=''):
        print(f"{n[:36]:36}{f:>+8.1f}" + ''.join(f"{v:>+8.1f}" for v in t)
              + ''.join(f"{h[k]:>+8.1f}" for k in hk) + ''.join(f"{m[k]:>+8.1f}" for k in MARKS) + f"  {x}")
    line('PRODUCTION', P['full_pct'], P['thirds_pct'], P['halves_pct'], P['fine_pct'])
    for v in o['variants']:
        line(v['variant'], v['full_pct'], v['thirds_pct'], v['halves_pct'], v['fine_pct'],
             f"{v['checks_passed']}/5")
    for v in o['variants']:
        b = v['bootstrap']
        print(f"  {v['variant'][:34]:34} CI [{b['ci_daily'][0]*100:+.3f}%, {b['ci_daily'][1]*100:+.3f}%] "
              f"P={b['p_better']:.3f}  Sharpe {v['summary']['sharpe']:.2f} (prod {P['summary']['sharpe']:.2f})  "
              f"maxDD {v['summary']['max_dd_pct']:.1f}% (prod {P['summary']['max_dd_pct']:.1f}%)")
    d = o['deployment_comparison_30min']
    print(f"\nDEPLOYMENT (30-min bars, 64 days): production@17:30 {d['production_at_1730']:+.1f}%  "
          f"production@18:00 {d['production_at_1800']:+.1f}%  candidate@17:30 {d['candidate_at_1730']:+.1f}%  "
          f"candidate@18:00 {d['candidate_at_1800']:+.1f}%")


if __name__ == '__main__':
    main()
