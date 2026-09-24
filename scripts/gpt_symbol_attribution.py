#!/usr/bin/env python3
"""Independent GPT audit: symbol-level attribution for production B0 replay.

This does not claim causal leave-one-out effects. It first measures realized trade
P&L by symbol from a fresh full-engine baseline replay. A later causal test must
replay the engine with each symbol removed because capital competition makes
simple subtraction invalid.
"""
import argparse
import json
import os
import sys
from collections import defaultdict, deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R


def fifo_realized(trades):
    lots = defaultdict(deque)
    out = defaultdict(lambda: {'realized_pnl': 0.0, 'buy_notional': 0.0,
                               'sell_notional': 0.0, 'buys': 0, 'sells': 0,
                               'shares_sold': 0.0})
    unmatched = []
    for t in trades:
        sym = t['symbol']
        side = t['side']
        qty = float(t['shares'])
        px = float(t.get('price', t.get('avg_price', 0.0)))
        if side == 'buy':
            lots[sym].append([qty, px])
            out[sym]['buy_notional'] += qty * px
            out[sym]['buys'] += 1
            continue
        out[sym]['sell_notional'] += qty * px
        out[sym]['sells'] += 1
        out[sym]['shares_sold'] += qty
        left = qty
        while left > 1e-10 and lots[sym]:
            lot_qty, lot_px = lots[sym][0]
            take = min(left, lot_qty)
            out[sym]['realized_pnl'] += take * (px - lot_px)
            lot_qty -= take
            left -= take
            if lot_qty <= 1e-10:
                lots[sym].popleft()
            else:
                lots[sym][0][0] = lot_qty
        if left > 1e-8:
            unmatched.append({'symbol': sym, 'date': t.get('date'), 'shares': left})
    return out, lots, unmatched


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--capital', type=float, default=R.CAPITAL)
    ap.add_argument('--cost-bps', type=float, default=R.DEFAULT_COST)
    ap.add_argument('--output', default=os.path.join(R.RESULTS, 'gpt_symbol_attribution.json'))
    args = ap.parse_args()

    # Fresh baseline replay. Cost is included in the replay's execution prices.
    r = R.replay(tag='gpt_symbol_attr', cost_bps=args.cost_bps)
    if abs(args.capital - R.CAPITAL) > .01:
        raise SystemExit('non-default capital requires the capital-sensitivity replay helper; refusing implicit scaling')

    attr, open_lots, unmatched = fifo_realized(r['trades'])
    rows = []
    total_fifo = sum(v['realized_pnl'] for v in attr.values())
    for sym, v in attr.items():
        row = {'symbol': sym, **{k: round(x, 4) if isinstance(x, float) else x for k, x in v.items()}}
        row['share_of_fifo_realized_pct'] = round(v['realized_pnl'] / total_fifo * 100, 2) if total_fifo else None
        row['open_lot_shares'] = round(sum(q for q, _ in open_lots[sym]), 6)
        rows.append(row)
    rows.sort(key=lambda x: x['realized_pnl'], reverse=True)

    out = {
        '_meta': {
            'audit': 'GPT symbol attribution', 'engine': R.ENGINE,
            'window': [R.RESEARCH_START, R.RESEARCH_END],
            'starting_capital': args.capital, 'cost_bps_per_side': args.cost_bps,
            'method': 'FIFO attribution of a fresh full-engine B0 replay',
            'warning': 'descriptive attribution only; do not infer leave-one-out causal effect by subtraction',
        },
        'engine_realized': r['realized'], 'fifo_realized_sum': round(total_fifo, 4),
        'unmatched_sells': unmatched, 'rows': rows,
    }
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, 'w') as f:
        json.dump(out, f, indent=1)
    for x in rows:
        print(f"{x['symbol']:5s}  pnl=${x['realized_pnl']:>11,.2f}  share={x['share_of_fifo_realized_pct']:>7.2f}%  sells={x['sells']:>4}")
    print('wrote', args.output)


if __name__ == '__main__':
    main()
