"""Fetch harness for building a REAL broad-universe daily_hist.json (e.g. the
full S&P 500), for use with research_volume_price_spike_backtest.py or any
other script in this repo that reads the standard
{"data": {"results": [{"symbol": .., "bars": [...]}]}} shape.

WHY THIS IS TWO STEPS, NOT ONE SCRIPT: the actual market-data fetch has to go
through the mcp__RobinhoodClaude__get_equity_historicals tool, which only an
agent session (not a standalone `python3 foo.py`) can call - there is no
local API client for it. So this file does the two things that ARE plain
Python: (1) turn a universe list into an exact, reviewable batch plan, and
(2) merge the raw responses an agent collected back into one file. The fetch
loop itself is a short, mechanical runbook for whichever agent session runs
it (see RUNBOOK below) - deliberately dumb and auditable rather than clever,
so anyone can re-run or spot-check it.

get_equity_historicals takes at most 10 symbols per call, and its response
shape for interday bars is ALREADY IDENTICAL to this repo's daily_hist.json
convention (verified against a live 2-symbol call, 2026-08-24) - a batch
response's "data.results" list can be concatenated directly onto the merged
file's "data.results" list, no field translation needed.

RUNBOOK (what an agent session with RobinhoodClaude MCP access actually does):
  1. python3 scripts/fetch_broad_universe_daily_hist.py plan data/sp500_constituents.json
     -> prints one JSON array of symbols per line, one line per batch (<=10
        symbols each). This is the exact, deterministic call plan - review it
        before spending API calls on it.
  2. For each batch line, call:
       mcp__RobinhoodClaude__get_equity_historicals(
         symbols=<the batch's symbols>, start_time=<window start, RFC3339 UTC>,
         interval="day", bounds="regular", adjustment_type="split")
     and save that call's raw JSON response verbatim to its own file under a
     scratch batches directory (e.g. batches/0000.json, batches/0001.json, ...
     - filename doesn't matter, every *.json in the directory is read).
     A failed/empty batch is fine to skip - step 3 reports whatever went
     missing, nothing is silently required to succeed.
  3. python3 scripts/fetch_broad_universe_daily_hist.py assemble <batches_dir> <out.json> \
         --universe data/sp500_constituents.json
     -> merges every batch file into one combined daily_hist.json at <out.json>,
        de-duplicating by symbol (first occurrence wins, later duplicates are
        reported, not silently dropped), and - if --universe is given - reports
        exactly which requested symbols never showed up in any batch (a
        delisted/renamed ticker, a failed call, a typo), so the final
        universe size is honest rather than assumed to equal the request.

Universe snapshot note: data/sp500_constituents.json is a POINT-IN-TIME
membership snapshot (see its own "note" field) - re-fetch it before a run
where staleness matters. Running today's membership list against historical
prices is a mild look-ahead/survivorship simplification (true point-in-time
historical membership isn't available from this free source); acceptable for
a research track, worth stating plainly rather than glossing over.
"""
import argparse
import glob
import json
import os


def cmd_plan(universe_path, batch_size):
    d = json.load(open(universe_path))
    symbols = [c['symbol'] for c in d['constituents']] if 'constituents' in d else d['symbols']
    for i in range(0, len(symbols), batch_size):
        print(json.dumps(symbols[i:i + batch_size]))
    print(f"# {len(symbols)} symbols, {(len(symbols) + batch_size - 1) // batch_size} batches of <= {batch_size}",
          file=__import__('sys').stderr)


def cmd_assemble(batches_dir, out_path, universe_path):
    combined = {}  # symbol -> bars, first occurrence wins
    duplicate_symbols = []
    batch_files = sorted(glob.glob(os.path.join(batches_dir, '*.json')))
    if not batch_files:
        raise SystemExit(f"No *.json files found in {batches_dir}")

    for path in batch_files:
        try:
            d = json.load(open(path))
        except (json.JSONDecodeError, OSError) as e:
            print(f"WARNING: skipping unreadable batch file {path}: {e}")
            continue
        for r in d.get('data', {}).get('results', []):
            sym = r.get('symbol')
            if not sym or not r.get('bars'):
                continue
            if sym in combined:
                duplicate_symbols.append(sym)
                continue
            combined[sym] = r['bars']

    out = {'data': {'results': [{'symbol': sym, 'bars': bars} for sym, bars in combined.items()]}}
    with open(out_path, 'w') as f:
        json.dump(out, f)

    print(f"Assembled {len(combined)} symbols from {len(batch_files)} batch file(s) -> {out_path}")
    if duplicate_symbols:
        print(f"NOTE: {len(duplicate_symbols)} duplicate symbol occurrence(s) across batch files "
              f"(kept first, ignored later): {sorted(set(duplicate_symbols))}")

    if universe_path:
        ud = json.load(open(universe_path))
        requested = {c['symbol'] for c in ud['constituents']} if 'constituents' in ud else set(ud['symbols'])
        missing = sorted(requested - set(combined))
        print(f"Requested {len(requested)} symbols, got {len(combined)}, missing {len(missing)}")
        if missing:
            print(f"MISSING (not fetched - failed call, delisted, renamed, or typo'd ticker): {missing}")


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    p_plan = sub.add_parser('plan', help='print the batch call plan for a universe list')
    p_plan.add_argument('universe_path')
    p_plan.add_argument('--batch-size', type=int, default=10)

    p_asm = sub.add_parser('assemble', help='merge raw batch response files into one daily_hist.json')
    p_asm.add_argument('batches_dir')
    p_asm.add_argument('out_path')
    p_asm.add_argument('--universe', default=None, help='universe list to cross-check for missing symbols')

    args = ap.parse_args()
    if args.cmd == 'plan':
        cmd_plan(args.universe_path, args.batch_size)
    elif args.cmd == 'assemble':
        cmd_assemble(args.batches_dir, args.out_path, args.universe)
