#!/usr/bin/env python3
"""Audit the Margin-Style Live run log for equity figures inflated by phantom positions.

WHY THIS EXISTS
---------------
On 2026-09-22 `equity_peak` was found to be overstated by $3,970.69: the 2026-09-16
run placed a sell (LRCX 14.755994 sh) whose state commit left the position in
`open_positions` and recorded no `pending_settlement`, so from the next run the
engine counted those shares twice - once as cash that had arrived from the sale,
once as a holding it still believed it had. `cmd_plan` derives `total_equity` (and
therefore `equity_peak`, the concentration cap and the kill-switch drawdown) from
the state file, so every figure it reports inherits any state error.

This script answers "which OTHER logged numbers are inflated the same way?"

METHOD - BROKER GROUND TRUTH, NOT SELF-COMPARISON
--------------------------------------------------
An earlier version of this audit compared each state commit against the orders the
log claims were placed. That was abandoned: the log's field naming is inconsistent
across older runs and its entry dates do not always line up with the state commit
that carried them, so the check produced mirror-image false positives (the same
shares reported "overstated" one day and "understated" the next).

This version instead uses the broker's own filled-order history as truth:

  1. Start from the account's KNOWN holdings at the anchor date (flat in every
     universe symbol on 2026-09-22 - verified by get_equity_positions, which
     returns only CGC).
  2. Replay the committed fills BACKWARD to recover what the account actually held
     at each point. No starting guess is needed and nothing is assumed.
  3. Compare against the state file reconstructed from git history at the same
     point (this repo's `git log --reverse` + `git show <sha>:<path>` convention).
  4. Price the difference off the fills themselves to state each figure's error.

The reconstruction SELF-CHECKS against two state commits whose share counts are
known to have matched the broker (the 2026-09-16 and 2026-09-17 commits). If the
replay does not reproduce them exactly the script fails loudly rather than
reporting numbers - per the lesson recorded in CLAUDE.md, a new measurement tool
must be validated against a known reference before it is allowed to overturn
anything.

Manual trades matter and are reported separately: `placed_agent == "user"` fills
are trades the account owner made directly, which the engine never learns about,
so they desynchronise state from reality without any engine defect at all.

Usage:
    python3 scripts/audit_phantom_equity.py
    python3 scripts/audit_phantom_equity.py --rev HEAD --json out.json
    python3 scripts/audit_phantom_equity.py --divergence   # why state != broker

WHY STATE AND BROKER DIVERGE (--divergence)
--------------------------------------------
`open_positions` is a record of what the ENGINE BELIEVES IT DID; the broker is
what actually happened. Every divergence is a write that did not complete, and
the SIGN says which kind:

  broker > state  - the engine missed a BUY
      (a) the owner bought the symbol themselves - the engine only ever learns
          about orders it placed (2026-09-18: STX +5.887547, WDC +2.276165)
      (b) the engine bought, but its state commit never reached the branch the
          next run reads (2026-09-15's buys were committed to the development
          branch; `main`, which production checks out, still showed zero)

  broker < state  - the engine missed a SELL
      (c) the owner sold the symbol themselves (2026-09-09: WDC -4.131460,
          MU -1.957520)
      (d) the engine sold, but its state commit did not record it
          (2026-09-16: LRCX 14.755994 - the phantom behind the equity_peak bug)

(a)/(c) are outside the engine's knowledge; (b)/(d) are the engine's own write
path failing. They are NOT distinguishable from the share counts alone - but
they ARE distinguishable from the broker, because `get_equity_orders` stamps
every fill with `placed_agent` ("user" vs "agentic"). That field is what turns
"should a sell be capped at the state quantity?" from a judgement call into a
lookup.

Every number printed is MEASURED from committed files. Where the fill history does
not cover a date the script says so and reports nothing for it, rather than
substituting an assumption (CLAUDE.md Evidence Rule 6).
"""
import argparse
import csv
import json
import subprocess
import sys

STATE_PATH = 'docs/margin_style_live_state.json'
LOG_PATH = 'docs/margin_style_live_log.json'
FILLS_PATH = 'data/broker_fills_912291820_2026-09-08_2026-09-21.csv'
UNIVERSE = ('AMD', 'MU', 'WDC', 'SNDK', 'TSM', 'INTC', 'LRCX', 'STX')

# The anchor: get_equity_positions on 912291820 returned only CGC (2 sh) on
# 2026-09-22, i.e. zero universe symbols. Every universe holding is therefore 0
# at this instant, and the backward replay needs no other input.
ANCHOR_TS = '2026-09-22T00:00:00Z'

# State commits whose share counts are independently known to have matched the
# broker; the backward replay must reproduce them or the script refuses to report.
SELF_CHECKS = (
    ('2026-09-16T20:00:00Z', {'WDC': 9.953850, 'SNDK': 2.682303,
                              'INTC': 10.227838, 'STX': 0.254996, 'LRCX': 0.0}),
    ('2026-09-17T18:00:00Z', {'WDC': 2.558139, 'SNDK': 2.804823,
                              'INTC': 2.628554, 'STX': 0.065534,
                              'LRCX': 3.600952}),
)
SHARE_EPS = 1e-5

# Figures cmd_plan derives from the STATE FILE, so they inherit state errors.
# real_cash_* fields are excluded on purpose: those come straight from
# get_portfolio and are broker-sourced inputs, not state-derived outputs.
STATE_DERIVED = ('total_equity', 'equity_peak', 'drawdown_from_peak')


def git(*args):
    return subprocess.run(['git'] + list(args), capture_output=True, text=True,
                          check=True).stdout


def load_fills():
    rows = []
    with open(FILLS_PATH) as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            ts, sym, side, qty, px, agent, oid = next(csv.reader([line]))
            rows.append({'ts': ts, 'symbol': sym.upper(), 'side': side,
                         'qty': float(qty), 'price': float(px),
                         'agent': agent, 'order_id': oid})
    rows.sort(key=lambda r: r['ts'])
    return rows


def broker_holdings_at(fills, ts):
    """Actual holdings strictly BEFORE `ts`, by replaying backward from the anchor."""
    h = {s: 0.0 for s in UNIVERSE}          # anchor: flat on 2026-09-22
    for f in reversed(fills):               # undo every fill at or after ts
        if f['ts'] < ts:
            break
        if f['symbol'] not in h:
            continue
        # undo: a buy added shares, so remove them; a sell removed them, so add back
        h[f['symbol']] += f['qty'] if f['side'] == 'sell' else -f['qty']
    return {k: v for k, v in h.items() if abs(v) > SHARE_EPS}


def self_check(fills):
    ok = True
    for ts, expected in SELF_CHECKS:
        got = broker_holdings_at(fills, ts)
        for sym in set(expected) | set(got):
            e, g = expected.get(sym, 0.0), got.get(sym, 0.0)
            if abs(e - g) > 1e-4:
                print(f'  FAIL {ts} {sym}: replay {g:.6f} vs known {e:.6f}')
                ok = False
    print('  PASS - backward replay reproduces both known references'
          if ok else '  FAIL - DO NOT TRUST THIS AUDIT')
    return ok


def price_near(fills, sym, ts):
    """(price, fill_date) - the fill for `sym` closest in date to `ts`.

    Prices come from actual fills, so a same-day fill is an exact mark and a
    nearby one is clearly labelled by its own date in the output.
    """
    cand = [f for f in fills if f['symbol'] == sym]
    if not cand:
        return None, None
    day = int(ts[:10].replace('-', ''))
    best = min(cand, key=lambda f: abs(int(f['ts'][:10].replace('-', '')) - day))
    return best['price'], best['ts'][:10]


def positions_of(state):
    res = {}
    for sym, p in (state.get('open_positions') or {}).items():
        sh = p.get('shares', p.get('quantity')) if isinstance(p, dict) else p
        try:
            res[sym.upper()] = float(sh)
        except (TypeError, ValueError):
            pass
    return res


def state_before(rev, date):
    """The state file `cmd_plan` would have READ on `date`.

    That is the state committed by the PREVIOUS run, so this takes the last
    commit STRICTLY BEFORE `date`. Using the commit made on `date` itself would
    compare post-run state against pre-run broker holdings and mis-attribute the
    run's own fills as divergence.
    """
    lines = git('log', '--reverse', '--format=%H|%ad|%s', '--date=short',
                rev, '--', STATE_PATH).strip().splitlines()
    hit = None
    for line in lines:
        sha, d, subject = line.split('|', 2)
        if d < date:
            hit = (sha, d, subject)
        else:
            break
    if not hit:
        return None
    sha, d, subject = hit
    try:
        return sha[:7], d, subject, json.loads(git('show', f'{sha}:{STATE_PATH}'))
    except Exception:
        return None


def report_divergence(rev, fills):
    """Every state-vs-broker gap, with the fill that explains it."""
    hist = []
    for line in git('log', '--reverse', '--format=%H|%ad|%s', '--date=short',
                    rev, '--', STATE_PATH).strip().splitlines():
        sha, d, sub = line.split('|', 2)
        if d < fills[0]['ts'][:10]:
            continue
        try:
            hist.append((sha[:7], d, sub,
                         json.loads(git('show', f'{sha}:{STATE_PATH}'))))
        except Exception:
            pass

    print('-' * 86)
    print('STATE THE RUN READ  vs  BROKER HOLDINGS AT START OF DAY')
    print('-' * 86)
    print(f"{'date':11} {'sym':5} {'state':>12} {'broker':>12} {'broker-state':>13}  explained by")
    seen, found = set(), 0
    for sha, d, sub, st in hist:
        if d in seen:
            continue
        seen.add(d)
        prev = [h for h in hist if h[1] < d]
        if not prev:
            continue
        sp, bk = positions_of(prev[-1][3]), broker_holdings_at(fills, f'{d}T00:00:00Z')
        for sym in sorted(set(sp) | set(bk)):
            delta = bk.get(sym, 0.0) - sp.get(sym, 0.0)
            if abs(delta) <= SHARE_EPS:
                continue
            found += 1
            cand = [f for f in fills if f['symbol'] == sym and f['ts'][:10] < d
                    and abs(f['qty'] - abs(delta)) < 1e-4]
            who = ', '.join(sorted({f"{f['agent']} {f['side']} {f['ts'][:10]}"
                                    for f in cand})) or 'no single fill matches'
            print(f"{d:11} {sym:5} {sp.get(sym,0.0):12.6f} {bk.get(sym,0.0):12.6f} "
                  f"{delta:+13.6f}  {who}")
    print()
    print(f'{found} divergences. Read the sign per the docstring: broker > state means')
    print('a missed BUY (owner bought, or an engine buy not committed to this branch);')
    print('broker < state means a missed SELL (owner sold, or an engine sell not recorded).')
    print('placed_agent on each fill separates the owner\'s trades from the engine\'s.')
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rev', default='origin/main')
    ap.add_argument('--json', dest='json_out')
    ap.add_argument('--divergence', action='store_true',
                    help='classify every state-vs-broker gap by direction and cause')
    args = ap.parse_args()

    fills = load_fills()
    runs = json.loads(git('show', f'{args.rev}:{LOG_PATH}')).get('runs', [])

    print('=' * 72)
    print(f'PHANTOM-EQUITY AUDIT   rev={args.rev}')
    print('=' * 72)
    print(f'broker fills: {len(fills)}  ({fills[0]["ts"][:10]} .. {fills[-1]["ts"][:10]})')
    print(f'log runs: {len(runs)}')
    print()
    print('HARNESS SELF-CHECK')
    if not self_check(fills):
        return 2
    print()

    covered_from = fills[0]['ts'][:10]

    if args.divergence:
        return report_divergence(args.rev, fills)

    # ---- manual trades: state desync with no engine defect involved ----
    print('-' * 72)
    print('MANUAL TRADES BY THE ACCOUNT OWNER (engine never learns about these)')
    print('-' * 72)
    manual = [f for f in fills if f['agent'] == 'user']
    if not manual:
        print('  none in the covered window')
    for f in manual:
        print(f'  {f["ts"][:10]}  {f["side"]:4s} {f["symbol"]:5s} {f["qty"]:.6f} sh '
              f'@ {f["price"]:,.4f}  = ${f["qty"] * f["price"]:,.2f}   [{f["order_id"]}]')
    print()

    # ---- the audit proper ----
    print('-' * 72)
    print('STATE-DERIVED EQUITY FIGURES IN THE LOG, vs BROKER REALITY')
    print('-' * 72)
    findings = []
    for r in runs:
        if not isinstance(r, dict):
            continue
        found = {k: r[k] for k in STATE_DERIVED if k in r}
        rs = r.get('risk_state')
        if isinstance(rs, dict):
            for k in STATE_DERIVED:
                if k in rs:
                    found.setdefault(k, rs[k])
        if not found:
            continue

        ts = str(r.get('timestamp', ''))
        date = ts[:10]
        vals = ', '.join(f'{k}={v}' for k, v in found.items())

        if date < covered_from:
            print(f'  {date}  {vals}')
            print(f'      NOT CHECKABLE - fill history starts {covered_from}')
            findings.append({'date': date, 'figures': found,
                             'status': 'not_checkable'})
            continue

        st = state_before(args.rev, date)
        if not st:
            print(f'  {date}  {vals}')
            print('      NOT CHECKABLE - no state commit before this date')
            findings.append({'date': date, 'figures': found,
                             'status': 'no_state'})
            continue

        sha, sdate, _, state = st
        st_pos = positions_of(state)
        # Holdings at the START of the run day. A run's own log timestamp is the
        # time of its LAST fill, so using it would place the comparison in the
        # middle of the run and mis-attribute that run's own earlier fills.
        bk_pos = broker_holdings_at(fills, f'{date}T00:00:00Z')
        diffs, total = [], 0.0
        for sym in sorted(set(st_pos) | set(bk_pos)):
            d = st_pos.get(sym, 0.0) - bk_pos.get(sym, 0.0)
            if abs(d) <= SHARE_EPS:
                continue
            px, pxd = price_near(fills, sym, f'{date}T00:00:00Z')
            dollars = d * px if px else None
            if dollars is not None:
                total += dollars
            diffs.append((sym, st_pos.get(sym, 0.0), bk_pos.get(sym, 0.0),
                          d, px, pxd, dollars))

        status = 'clean' if not diffs else (
            'INFLATED' if total > 0 else 'understated')
        print(f'  {date}  {vals}')
        print(f'      read state {sha} (committed {sdate})  ->  {status}')
        for sym, s, b, d, px, pxd, dollars in diffs:
            amt = f'${dollars:+,.2f} @ {px:,.4f} ({pxd} fill)' if px else 'unpriced'
            print(f'        {sym:5s} state {s:.6f} vs broker {b:.6f}  '
                  f'= {d:+.6f} sh  {amt}')
        if diffs:
            print(f'        net effect on total_equity: ${total:+,.2f}')
            for k, v in found.items():
                if k in ('total_equity',) and isinstance(v, (int, float)):
                    print(f'        so {k} {v:,.2f} should have been '
                          f'~{v - total:,.2f}')
        findings.append({'date': date, 'figures': found, 'status': status,
                         'state_sha': sha, 'net_dollars': round(total, 2),
                         'diffs': [{'symbol': s, 'state': a, 'broker': b,
                                    'delta_shares': d, 'price': px,
                                    'dollars': dollars}
                                   for s, a, b, d, px, _, dollars in diffs]})
    print()
    bad = [f for f in findings if f['status'] in ('INFLATED', 'understated')]
    nc = [f for f in findings if f['status'].startswith(('not_', 'no_'))]
    print(f'SUMMARY: {len(bad)} figure-sets diverge from broker reality, '
          f'{len(nc)} not checkable from the committed fill window.')

    if args.json_out:
        json.dump({'rev': args.rev, 'findings': findings},
                  open(args.json_out, 'w'), indent=1)
        print(f'wrote {args.json_out}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
