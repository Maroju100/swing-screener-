#!/usr/bin/env python3
"""Reproducible baseline backtest for Margin-Style Live.

WHY THIS EXISTS
---------------
The headline baseline figure for this strategy (+155.10% / $124,080.90 over
Mar 6 - Sep 4 2026) traced only to /tmp/margin_live_full_backtest_v2_results.json
-- a bare pair of dicts (day_pnl, day_equity) with no trades, no parameters, no
provenance, and no record of what produced it. /tmp is wiped when the container
recycles, after which the number outlives its evidence and cannot be checked.
Every other result in this project is measured against that number, so it needs
to rest on committed, re-runnable code. See CLAUDE.md "Evidence rules", Rule 2.

METHOD (Evidence Rule 1: replay, never multiply a P&L series)
-------------------------------------------------------------
Follows .claude/skills/backtest-variant/SKILL.md. The production engine is
IMPORTED, not copied, and NOTHING in it is patched -- this measures the engine
exactly as it runs live:

  * margin_style_live_engine is imported as MS.
  * MS.datetime is swapped for a FakeDatetime so the engine's "today" walks
    forward through history. This is the only monkeypatch.
  * MS.STATE_PATH is redirected to a scratch file, so docs/margin_style_live_state.json
    is never read or written.
  * For each trading day: truncate bars to that day, call MS.cmd_plan, feed the
    plan straight into MS.cmd_commit as the executed actions, mark equity.

MEASURED vs ASSUMED (Evidence Rule 3)
-------------------------------------
MEASURED: every entry/exit decision, sizing, tranche indexing, netting,
settlement lockup, kill-switch/trend-gate and circuit-breaker behaviour -- all
of it is the live engine's own code operating on real split-adjusted bars.

ASSUMED, and this is the one material approximation:
  * LIVE-QUOTE PROXY. The live system runs at 17:00 UTC and prices "today" off
    a live intraday quote. A daily-bar backtest has no intraday data, so today's
    CLOSE stands in for that quote, for entries, exits and fills alike. This is
    the same convention the rest of this repo uses for daily-bar work (see
    scripts/margin_style_timing_comparison.py, which substitutes real intraday
    quotes precisely because this proxy is an approximation). It cuts both ways
    and is not tuned: it does not systematically favour the strategy.
  * Fills are at the plan's own price with no slippage or commission.

Neither assumption is a free parameter. There is no multiplier anywhere in this
script, and no knob that could be turned to move the result.

CASH LEDGER
-----------
The engine's state tracks positions and pending settlement but NOT cash -- live,
cash comes from get_portfolio. So this harness keeps the ledger and passes it in
as real_cash, mirroring the broker: a sell credits cash immediately, and the
engine's own pending_settlement subtraction is what enforces T+1 on *deployable*
cash. Equity is marked as cash + shares x that day's close.

USAGE
-----
  python3 scripts/margin_style_baseline_backtest.py
  python3 scripts/margin_style_baseline_backtest.py --start 2026-07-06 --end 2026-08-03
  python3 scripts/margin_style_baseline_backtest.py --capital 30000 --json out.json

Default window and capital reproduce the figure CLAUDE.md cites.

KNOWN ENGINE BUG THIS REPLAY EXPOSED (2026-09-21)
--------------------------------------------------
Running the engine unmodified produces an absurd +17,437% because of a real
defect in cmd_plan, not in this harness:

  1. PEAK/GAIN sells are decided early (~line 560) and PARKED in the
     `pending_peak_gain` dict. They are not appended to `sells` until ~line 787.
  2. The DAILY_STOP block (~line 622) guards itself with
     `closed_symbols = {s['symbol'] for s in sells}` -- which cannot see the
     parked sells, because they are not in `sells` yet. So it liquidates the
     FULL position of a symbol that already has a PEAK sell pending.
  3. Line 787 then appends that parked PEAK sell anyway -> two sells, same
     symbol, same day, totalling ~174.3% of the position. cmd_commit applies
     the first (deleting the position), then the second finds pos=None and
     books its proceeds against nothing.

The KILL_SWITCH block (~line 651) handles this correctly -- it does
`pending_peak_gain = {}` and `peak_updates = {}` before liquidating. The
DAILY_STOP block simply omits those two lines. That asymmetry is the whole bug.

Measured over Mar 6 - Sep 4 2026: 63 days with a duplicate same-symbol sell,
$13,808,086 of phantom proceeds -- essentially the entire fake "profit".
cmd_commit's pre-commit validation does not catch it because it checks each
sell independently against the pre-mutation position, never the running total.

As of 2026-09-21 DAILY_STOP has never fired in live trading (0 occurrences in
docs/margin_style_live_log.json since it was deployed 2026-09-06), so no real
money has been affected -- but the defect is latent.

--patch-daily-stop-bug adds 'DAILY_STOP' to that tuple IN MEMORY only, via
inspect.getsource + targeted string replacement per the backtest-variant skill.
scripts/margin_style_live_engine.py is never modified. Use it to see what the
baseline looks like once the double-sell is removed.
"""
import argparse
import contextlib
import datetime as _dt
import importlib.util
import inspect
import io
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import margin_style_live_engine as MS  # noqa: E402

DATA_PATH = os.path.join(ROOT, 'data', 'margin_style_daily_bars_2025-11-03_2026-09-04.json')
SCRATCH = os.path.join(ROOT, '.backtest_scratch')

DEFAULT_START = '2026-03-06'
DEFAULT_END = '2026-09-04'
DEFAULT_CAPITAL = 80000.0


class FakeDatetime(_dt.datetime):
    """Lets the engine's datetime.now() walk forward through history."""
    _fake_now = None

    @classmethod
    def now(cls, tz=None):
        if cls._fake_now is None:
            raise RuntimeError('simulated day not set')
        return cls._fake_now if tz else cls._fake_now.replace(tzinfo=None)


def set_sim_day(day_str):
    FakeDatetime._fake_now = _dt.datetime.strptime(day_str, '%Y-%m-%d').replace(
        tzinfo=_dt.timezone.utc)


def load_bars():
    """Return {symbol: [{date, close, raw_bar}, ...]} sorted by date."""
    d = json.load(open(DATA_PATH))
    out = {}
    for r in d['data']['results']:
        bars = [{'date': b['begins_at'][:10], 'close': float(b['close_price']), 'raw': b}
                for b in r['bars']]
        out[r['symbol']] = sorted(bars, key=lambda x: x['date'])
    return out


def extract_plan_json(stdout_text):
    """cmd_plan prints indent=1 JSON, possibly after plain-text warnings."""
    lines = stdout_text.splitlines()
    for i, line in enumerate(lines):
        if line.rstrip() == '{':
            return json.loads('\n'.join(lines[i:]))
    raise ValueError('no JSON object found in cmd_plan output:\n' + stdout_text[:500])


def load_engine(rev=None):
    """Load the production engine, optionally as of a past git revision.

    Lets us ask whether a documented figure was produced by an OLDER engine.
    The historical copy is written into .backtest_scratch/, whose parent is the
    repo root, so the engine's own ROOT/STATE_PATH resolution matches what it
    saw in scripts/ -- STATE_PATH is redirected in run() before any call.
    """
    if rev is None:
        return MS
    src = subprocess.check_output(
        ['git', 'show', f'{rev}:scripts/margin_style_live_engine.py'],
        cwd=ROOT, text=True)
    os.makedirs(SCRATCH, exist_ok=True)
    path = os.path.join(SCRATCH, f'engine_{rev}.py')
    with open(path, 'w') as fh:
        fh.write(src)
    spec = importlib.util.spec_from_file_location(f'engine_{rev}', path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def patched_cmd_plan():
    """Return a cmd_plan whose DAILY_STOP branch clears pending_peak_gain.

    Mirrors what the KILL_SWITCH branch already does, so a DAILY_STOP
    liquidation cannot be followed by a parked PEAK/GAIN sell of the same
    position. Patches the real source in memory per
    .claude/skills/backtest-variant/SKILL.md -- scripts/margin_style_live_engine.py
    is never written to. Must be called AFTER MS.datetime / MS.STATE_PATH are
    set, since the patched function resolves globals through the namespace
    copied here.
    """
    src = inspect.getsource(MS.cmd_plan)
    old = ("    if not daily_stop_active and daily_total_loss >= daily_loss_cap:\n"
           "        daily_stop_active = True\n"
           "        daily_stop_date = today\n")
    new = ("    if not daily_stop_active and daily_total_loss >= daily_loss_cap:\n"
           "        daily_stop_active = True\n"
           "        daily_stop_date = today\n"
           "        pending_peak_gain = {}\n"
           "        peak_updates = {}\n")
    if src.count(old) != 1:
        raise SystemExit(
            f'anchor block for the DAILY_STOP patch matched {src.count(old)} times, '
            'expected 1 - cmd_plan has changed; re-check the patch before trusting it.')
    ns = dict(MS.__dict__)
    exec(compile(src.replace(old, new), '<cmd_plan_daily_stop_patched>', 'exec'), ns)
    return ns['cmd_plan']


def run(start, end, capital, verbose=False, patch_bug=False, no_daily_stop=False,
        engine_rev=None):
    global MS
    MS = load_engine(engine_rev)
    bars_by_sym = load_bars()

    os.makedirs(SCRATCH, exist_ok=True)
    state_path = os.path.join(SCRATCH, 'state.json')
    hist_path = os.path.join(SCRATCH, 'hist.json')
    quotes_path = os.path.join(SCRATCH, 'quotes.json')
    actions_path = os.path.join(SCRATCH, 'actions.json')

    # Never touch the live state file.
    MS.STATE_PATH = state_path
    MS.datetime = FakeDatetime
    if os.path.exists(state_path):
        os.remove(state_path)

    if no_daily_stop:
        # Reproduces CLAUDE.md's "Baseline (no stop)" row. Setting the cap
        # unreachably high means DAILY_STOP never fires, which also means the
        # double-sell defect cannot trigger - no source patch needed.
        MS.DAILY_STOP_PCT = 1e9

    plan_fn = patched_cmd_plan() if patch_bug else MS.cmd_plan

    all_dates = sorted({b['date'] for s in bars_by_sym for b in bars_by_sym[s]})
    window = [d for d in all_dates if start <= d <= end]
    if not window:
        raise SystemExit(f'no trading days in {start}..{end}')

    cash = capital
    day_pnl, day_equity, trades = {}, {}, []
    prev_equity = capital

    for day in window:
        set_sim_day(day)

        # Bars up to and including today. Lookback reaches back past `start`,
        # so signals are warm on day one rather than ramping up.
        results = []
        todays_close = {}
        for sym, bars in bars_by_sym.items():
            upto = [b for b in bars if b['date'] <= day]
            if not upto or upto[-1]['date'] != day:
                continue  # symbol did not trade today
            results.append({'symbol': sym, 'bars': [b['raw'] for b in upto]})
            todays_close[sym] = upto[-1]['close']
        if not results:
            continue

        json.dump({'data': {'results': results}}, open(hist_path, 'w'))
        # LIVE-QUOTE PROXY: today's close stands in for the 17:00 UTC quote.
        json.dump(todays_close, open(quotes_path, 'w'))

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            plan_fn(hist_path, quotes_path, cash, [])
        plan = extract_plan_json(buf.getvalue())

        sells = plan.get('sells', [])
        buys = plan.get('buys', [])
        for s in sells:
            cash += s['shares'] * s['price']
        for b in buys:
            cash -= b['shares'] * b['price']

        actions = {'sells': sells, 'buys': buys,
                   'peak_updates': plan.get('peak_updates', {}),
                   'risk_state': plan.get('risk_state', {})}
        json.dump(actions, open(actions_path, 'w'))
        with contextlib.redirect_stdout(io.StringIO()):
            MS.cmd_commit(actions_path)

        state = json.load(open(state_path))
        positions_value = sum(p['shares'] * todays_close.get(sym, p['entry'])
                              for sym, p in state['open_positions'].items())
        equity = cash + positions_value

        day_equity[day] = round(equity, 2)
        day_pnl[day] = round(equity - prev_equity, 2)
        prev_equity = equity

        for t in sells:
            trades.append({'date': day, 'side': 'sell', **{k: t[k] for k in ('symbol', 'shares', 'price', 'reason')}})
        for t in buys:
            trades.append({'date': day, 'side': 'buy', **{k: t[k] for k in ('symbol', 'shares', 'price', 'reason')}})

        if verbose and (sells or buys):
            print(f"{day}  equity={equity:12,.2f}  {len(buys)}B/{len(sells)}S")

    total_pnl = prev_equity - capital
    return {
        'window': {'start': start, 'end': end, 'trading_days': len(day_equity)},
        'daily_stop_bug_patched': patch_bug,
        'daily_stop_disabled': no_daily_stop,
        'engine_rev': engine_rev or 'working tree',
        'capital': capital,
        'final_equity': round(prev_equity, 2),
        'total_pnl': round(total_pnl, 2),
        'return_pct': round(total_pnl / capital * 100, 2),
        'trade_count': len(trades),
        'days_traded': sum(1 for d in day_pnl if any(t['date'] == d for t in trades)),
        'best_day': max(day_pnl.items(), key=lambda kv: kv[1]) if day_pnl else None,
        'worst_day': min(day_pnl.items(), key=lambda kv: kv[1]) if day_pnl else None,
        'day_pnl': day_pnl,
        'day_equity': day_equity,
        'trades': trades,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--start', default=DEFAULT_START)
    ap.add_argument('--end', default=DEFAULT_END)
    ap.add_argument('--capital', type=float, default=DEFAULT_CAPITAL)
    ap.add_argument('--json', help='write full results (incl. every trade) to this path')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--patch-daily-stop-bug', action='store_true',
                    help="in-memory only: add 'DAILY_STOP' to full_exit_symbols so the "
                         "PEAK block stops re-selling positions DAILY_STOP already closed "
                         "(see module docstring). Production engine is not modified.")
    ap.add_argument('--no-daily-stop', action='store_true',
                    help="raise DAILY_STOP_PCT out of reach so the daily stop never "
                         "fires - reproduces CLAUDE.md's 'Baseline (no stop)' row")
    ap.add_argument('--engine-rev',
                    help='replay a PAST version of the engine (git rev), to test whether '
                         'a documented figure came from an older engine')
    args = ap.parse_args()

    r = run(args.start, args.end, args.capital, verbose=args.verbose,
            patch_bug=args.patch_daily_stop_bug, no_daily_stop=args.no_daily_stop,
            engine_rev=args.engine_rev)

    print('=' * 72)
    print('MARGIN-STYLE LIVE - BASELINE BACKTEST (engine replay, no rule patched)')
    print('=' * 72)
    print(f"Engine          {r['engine_rev']}")
    print(f"Window          {r['window']['start']} -> {r['window']['end']} "
          f"({r['window']['trading_days']} trading days)")
    print(f"Capital         ${r['capital']:,.2f}")
    print(f"Final equity    ${r['final_equity']:,.2f}")
    print(f"Total P&L       ${r['total_pnl']:,.2f}")
    print(f"Return          {r['return_pct']:+.2f}%")
    print(f"Trades          {r['trade_count']} across {r['days_traded']} days")
    if r['best_day']:
        print(f"Best day        {r['best_day'][0]}  ${r['best_day'][1]:,.2f}")
        print(f"Worst day       {r['worst_day'][0]}  ${r['worst_day'][1]:,.2f}")
    print()
    print('Price basis: LIVE-QUOTE PROXY (daily close stands in for the 17:00 UTC')
    print('quote). No slippage or commission. See module docstring.')
    if r['daily_stop_bug_patched']:
        print("DAILY_STOP double-sell patched IN MEMORY. Production engine unmodified.")
    else:
        print("UNPATCHED engine: result includes the DAILY_STOP double-sell defect")
        print("documented in the module docstring. Not a usable baseline.")

    if args.json:
        json.dump(r, open(args.json, 'w'), indent=1)
        print(f"\nFull results -> {args.json}")


if __name__ == '__main__':
    main()
