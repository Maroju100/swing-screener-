#!/usr/bin/env python3
"""Independent GPT audit: replay production B0 across account sizes.

Research-only. Each row is a fresh full-engine replay through the repository's
validated replay core; no P&L series is scaled and no production/live file is
modified.
"""
import argparse
import contextlib
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R

DEFAULT_CAPITALS = [5000, 10000, 15000, 17696.92, 20000, 40000, 80000]


def replay_at_capital(capital, cost_bps, tag):
    """Call the same validated H.run core used by margin_style_research.replay."""
    t0 = time.time()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        r = R.H.run(R.RESEARCH_START, R.RESEARCH_END, capital, R.ENGINE,
                    params=None, tag=tag, src_patches=None,
                    daily_path=R.DAILY_EXT, hourly_path=R.HOURLY_EXT,
                    cost_bps=cost_bps, price_field='close_price')
    r['seconds'] = round(time.time() - t0, 2)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--capitals', nargs='*', type=float, default=DEFAULT_CAPITALS)
    ap.add_argument('--cost-bps', type=float, default=R.DEFAULT_COST)
    ap.add_argument('--output', default=os.path.join(R.RESULTS, 'gpt_capital_sensitivity.json'))
    args = ap.parse_args()

    rows = []
    for capital in args.capitals:
        r = replay_at_capital(capital, args.cost_bps,
                              f'gpt_cap_{int(round(capital))}')
        s = R.summarize(r)
        rows.append({'starting_capital': capital, **s})
        print(f"${capital:>10,.2f}  return={s['realized_pct']:>8.2f}%  "
              f"sharpe={s['sharpe']:>6.3f}  maxDD={s['max_dd_pct']:>7.2f}%  "
              f"trades={s['trades']:>4}")

    base = next((x for x in rows if abs(x['starting_capital'] - 80000) < .01), None)
    if base:
        for x in rows:
            x['return_vs_80k_pp'] = round(x['realized_pct'] - base['realized_pct'], 4)
            x['trade_count_vs_80k'] = x['trades'] - base['trades']

    out = {
        '_meta': {
            'audit': 'GPT independent capital sensitivity',
            'engine': R.ENGINE,
            'window': [R.RESEARCH_START, R.RESEARCH_END],
            'cost_bps_per_side': args.cost_bps,
            'method': 'fresh full-engine replay at each starting capital; no P&L scaling',
            'production_modified': False,
        },
        'rows': rows,
    }
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, 'w') as f:
        json.dump(out, f, indent=1)
    print('wrote', args.output)


if __name__ == '__main__':
    main()
