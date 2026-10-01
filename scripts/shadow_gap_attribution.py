#!/usr/bin/env python3
"""Where did the paper shadow's gap to live come from? (asked 2026-10-01)

The shadow (scripts/margin_style_instant_shadow.py) and the live account are both
valued at the start of each run, so the gap's change between two runs is exact:
    d_gap = (shadow_t1 - shadow_t0) - (live_t1 - live_t0)

For the 2026-09-25 -> 2026-09-28 interval, which carries almost all of the gap,
this attributes d_gap to the EXTRA shares the shadow held over the weekend
(shadow positions after the 09-25 run minus live positions after it), each
marked from its 09-25 trade price to its price at the 09-28 run.

Prices (all MEASURED from committed logs, except one):
  - 09-25 prices: the shadow's own 09-25 trade prices (buy WDC/STX, net SNDK).
  - 09-28 prices: the shadow's 09-28 trade prices for SNDK/STX/LRCX/MU/TSM.
  - WDC did not trade on 09-28, so its 09-28 price is INFERRED from the shadow's
    own equity identity: equity_pre_run = cash + sum(shares * price).
Live positions after 09-25 come from main's state commit c3a77e4.

Reproduce:
    python3 scripts/shadow_gap_attribution.py
"""
import json
import subprocess

LOG = 'docs/margin_style_instant_shadow_log.json'
LIVE_STATE_AFTER_0925 = 'c3a77e4'


def main():
    d = json.load(open(LOG))
    runs = d['runs'] if isinstance(d, dict) else d
    by = {r['date']: r for r in runs}

    print('gap change between consecutive runs (start-of-run values):')
    rows = []
    for a, b in zip(runs, runs[1:]):
        if a.get('live_broker_total_value_pre_run') is None or b.get('live_broker_total_value_pre_run') is None:
            continue
        ds = b['shadow_equity_pre_run'] - a['shadow_equity_pre_run']
        dl = b['live_broker_total_value_pre_run'] - a['live_broker_total_value_pre_run']
        rows.append((a['date'], b['date'], round(ds, 2), round(dl, 2), round(ds - dl, 2)))
        print(f"  {a['date']} -> {b['date']}: shadow {ds:+9.2f}  live {dl:+9.2f}  gap {ds - dl:+9.2f}")

    r0, r1 = by['2026-09-25'], by['2026-09-28']
    live = json.loads(subprocess.check_output(
        ['git', 'show', f'{LIVE_STATE_AFTER_0925}:docs/margin_style_live_state.json']))
    live_sh = {k: v['shares'] for k, v in live['open_positions'].items()}
    shadow_sh = r0['positions']

    p0 = {t['symbol']: t['price'] for t in r0.get('buys', []) + r0.get('sells', [])}
    p1 = {t['symbol']: t['price'] for t in r1.get('sells', []) + r1.get('buys', [])}
    # WDC: infer from the shadow's 09-28 pre-run equity identity.
    held = r1['cash_before']
    known = sum(sh * p1[s] for s, sh in shadow_sh.items() if s in p1)
    p1['WDC'] = (r1['shadow_equity_pre_run'] - held - known) / shadow_sh['WDC']

    print('\n09-25 -> 09-28 attribution (extra shares the shadow held over the weekend):')
    parts = []
    for s in sorted(shadow_sh):
        extra = shadow_sh[s] - live_sh.get(s, 0.0)
        if abs(extra) < 1e-6 or s not in p0:
            continue
        eff = extra * (p1[s] - p0[s])
        parts.append({'symbol': s, 'extra_shares': round(extra, 6), 'px_0925': round(p0[s], 4),
                      'px_0928': round(p1[s], 4), 'effect': round(eff, 2),
                      'px_0928_inferred': s == 'WDC'})
        print(f"  {s:5} {extra:+10.6f} sh  {p0[s]:9.2f} -> {p1[s]:9.2f}"
              f"{' (inferred)' if s == 'WDC' else ''}  {eff:+8.2f}")
    explained = sum(p['effect'] for p in parts)
    total = next(r[4] for r in rows if r[0] == '2026-09-25')
    print(f"  explained {explained:+.2f} of {total:+.2f}; residual {total - explained:+.2f} "
          f"(estimated 5 bps costs and fill-vs-quote differences)")
    json.dump({'intervals': rows, 'weekend_0925_0928': parts,
               'explained': round(explained, 2), 'total': total},
              open('data/research/shadow_gap_attribution.json', 'w'), indent=1)


if __name__ == '__main__':
    main()
