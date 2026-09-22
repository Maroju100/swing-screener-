#!/usr/bin/env python3
"""Rebuild the live dashboard's daily-P&L series from BROKER data, not the run log.

WHY
---
`margin_live_dashboard.html` used to derive its daily-P&L chart, its daily table
and its headline `total_realized` from `docs/margin_style_live_log.json`. That
log is an append-only record of RUNS, not a ledger, and it has holes: six trading
days with real fills (2026-09-08, 09, 10, 16, 17, 18) are absent from it
entirely — the 2026-09-17 run committed state but wrote no log entry at all — and
the entry prices it does carry come from the strategy's own state file rather
than the broker's cost basis.

The visible symptom: the dashboard showed **$1,211.81** realized where the broker
said **$2,674.92**, and for "since 2026-09-15" it showed **$546.56** against an
actual **$1,297.86**.

This script replaces that derivation with the broker's own per-trade realized
P&L (`data/broker_realized_pnl_912291820_all.csv`, from `get_pnl_trade_history`
with `span="all"`), aggregated per day.

SCOPE CAVEAT, stated rather than silently applied
-------------------------------------------------
The broker's history covers the ACCOUNT, which is not the same set as
Margin-Style Live's trades. By default this script reports the account total,
because that is what the dashboard's headline claims to be and what the owner
compares against Robinhood. `--strategy-only` instead excludes the two closing
trades that clearly sit outside the strategy (NVDA 2026-07-07, prohibited for
this system, and MU 2026-07-02, which predates it) — it does NOT attempt to
separate the owner's own manual sells from the engine's, because those are
genuine closes of positions the two shared and splitting them would require an
attribution rule this project has not agreed on.

Usage:
    python3 scripts/rebuild_dashboard_pnl.py                 # print the series
    python3 scripts/rebuild_dashboard_pnl.py --since 2026-09-15
    python3 scripts/rebuild_dashboard_pnl.py --json          # emit MS_DATA.daily
"""
import argparse
import csv
import json
import sys
from collections import defaultdict

PNL_CSV = 'data/broker_realized_pnl_912291820_all.csv'

# Closing trades that are not Margin-Style Live's. Kept as an explicit, auditable
# list rather than a date cutoff, so adding to it is a visible decision.
NON_STRATEGY = {
    ('2026-07-07T18:18:51Z', 'NVDA'),   # NVDA is prohibited for this system
    ('2026-07-02T19:25:16Z', 'MU'),     # predates the strategy going live
}


def load(path=PNL_CSV):
    rows = []
    with open(path) as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            ts, sym, side, qty, px, gain = next(csv.reader([line]))
            rows.append({'ts': ts, 'symbol': sym, 'side': side,
                         'qty': float(qty), 'price': float(px),
                         'gain': float(gain)})
    rows.sort(key=lambda r: r['ts'])
    return rows


def daily_series(rows):
    by = defaultdict(float)
    cnt = defaultdict(int)
    for r in rows:
        by[r['ts'][:10]] += r['gain']
        cnt[r['ts'][:10]] += 1
    return [{'date': d, 'pnl': round(by[d], 2), 'trades': cnt[d]}
            for d in sorted(by)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', help='only days on/after this YYYY-MM-DD')
    ap.add_argument('--strategy-only', action='store_true',
                    help='drop the two closing trades outside Margin-Style Live')
    ap.add_argument('--json', action='store_true',
                    help='emit the MS_DATA.daily array (date/pnl only)')
    args = ap.parse_args()

    rows = load()
    if args.strategy_only:
        rows = [r for r in rows if (r['ts'], r['symbol']) not in NON_STRATEGY]
    if args.since:
        rows = [r for r in rows if r['ts'][:10] >= args.since]

    series = daily_series(rows)
    total = round(sum(r['gain'] for r in rows), 2)

    if args.json:
        json.dump([{'date': d['date'], 'pnl': d['pnl']} for d in series],
                  sys.stdout)
        return 0

    print(f'source: {PNL_CSV}  (broker ground truth)')
    if args.strategy_only:
        print('filter: --strategy-only (NVDA 2026-07-07, MU 2026-07-02 removed)')
    if args.since:
        print(f'window: from {args.since}')
    print(f'closing trades: {len(rows)}')
    print()
    run = 0.0
    for d in series:
        run += d['pnl']
        print(f"  {d['date']}  {d['trades']:2d} trades  {d['pnl']:+10.2f}   cum {run:+10.2f}")
    print()
    print(f'TOTAL REALIZED: {total:+,.2f}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
