"""Replay the real v3 day-trading engine over committed 1-minute bars.

METHOD (Evidence Rule 1 / .claude/skills/backtest-variant/SKILL.md)
This imports scripts/daytrading_v3_paper_engine.py and patches ONE rule at a time by
source-string surgery. It never edits the production file and never reimplements the
rules. Every variant below is byte-identical to the live engine except the named
change. State and log paths are redirected per variant so no run touches the real
paper ledger in docs/.

DRIVING AN INCREMENTAL ENGINE AS A BACKTEST
The engine is built to process only new bars: on a first run with empty state it sets
`start_gi = len(bars) - 2`, deliberately refusing to backfill history. To replay, the
harness seeds `last_processed_dt` to a timestamp before the window starts, so the same
loop walks every bar in order. Indicators (RSI, MACD, day-anchored VWAP) are causal --
each reads only bars at or before its own index -- so computing them over the whole
file introduces no look-ahead.

THE THREE THINGS MEASURED

1. ER GATE (--er-gate)
   Kaufman Efficiency Ratio = |net move| / sum(|bar-to-bar moves|), computed at BASKET
   level over the first --er-window minutes of each session, then held fixed for the
   rest of that day. Entries are blocked when the day's ER is below threshold; adds
   and exits on positions already open are untouched.

   ⚠️ This is NOT the same quantity as the dashboard's ER gauge. That gauge measures
   the session so far, which is fine as description but is unusable as a gate: it
   reads bars that have not happened yet at the moment the decision must be made.
   Gating on a whole-day ER is precisely the look-ahead error that turned the
   Trend-Gated Trail's "12/12" validation into 5/12 once a reachable entry price was
   used. Entries before the gate window completes are blocked too, because the gate
   genuinely is not known yet.

2. ROUND-TRIP COST (--cost-bps)
   Applied INSIDE the replay, not subtracted afterwards. Buys fill at
   price*(1+bps/10000) and sells at price*(1-bps/10000). This matters because the
   engine checks `notional <= cash` before every buy, so a cost change alters which
   trades are affordable and the path diverges. Post-processing a fixed trade list
   would assume the path is unchanged -- the same defect Evidence Rule 1 forbids.

   Reported as a break-even sweep: the question "is a spread readout worth screen
   space" is answered by how much cost v3 can absorb before its edge is gone, NOT by
   guessing historical spreads, which this data source does not carry.

3. RELATIVE STRENGTH (--rs / --mkt / --rs-sweep)
   RS = (symbol return since session open) - (benchmark return since session open),
   evaluated bar by bar. Entries are blocked unless RS > --rs-min. `--mkt` instead
   gates on the benchmark itself being up on the day. Both read only bars at or
   before the decision bar. SPY (broad market) and SMH (semis sector) are both
   tested, because the dashboard's existing breadth panels are computed WITHIN the
   basket -- and these three names essentially are the sector, so a sector benchmark
   is close to self-referential while a broad-market one is not.

4. WALK-FORWARD
   Every variant is reported on the full window and on each half. A variant that only
   wins on one half is a red flag, not a finding.

SAMPLE-SIZE WARNING -- READ BEFORE QUOTING ANY NUMBER FROM THIS
Robinhood serves real 1-minute bars for only ~6 trailing weeks, so the window is ~30
trading days (see scripts/fetch_semis_1min_data.py). A day-level gate therefore has a
sample of ~30, and each half-window ~15. That is small. Report direction and rough
magnitude; do not report a day-gate result to two decimal places and do not call a
single-window difference "validated" (Evidence Rule 3).

USAGE
    python3 scripts/v3_replay.py                        # baseline params, no gate, no cost
    python3 scripts/v3_replay.py --sweep                # full report: gate x cost grid
    python3 scripts/v3_replay.py --er-gate 0.30 --cost-bps 10
    python3 scripts/v3_replay.py --rs-sweep             # relative-strength grid
"""
import argparse
import inspect
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
SCRATCH = os.path.join(ROOT, '.backtest_scratch')

DATA = os.path.join(ROOT, 'data', 'semis_1min_2026-08-10_2026-09-21.json')
BENCH = os.path.join(ROOT, 'data', 'bench_1min_2026-08-10_2026-09-21.json')

# CLAUDE.md Strategy 2 describes two parameter sets. NOTE the discrepancy recorded in
# the report: daytrading_v3_paper_engine.py is titled "(tightened)" but its constants
# are the ones CLAUDE.md calls BASELINE. Variants are therefore named by parameters.
PARAMS = {
    'baseline':  dict(ADD_GAIN=0.006, COOLDOWN_MIN=2, EXHAUSTION_PEAK_RSI=65, TRIM_PCT=0.90),
    'tightened': dict(ADD_GAIN=0.003, COOLDOWN_MIN=1, EXHAUSTION_PEAK_RSI=70, TRIM_PCT=0.70),
}


def load_bars():
    d = json.load(open(DATA))
    return d['meta'], d['bars']


def to_raw_payload(bars, days=None):
    """Rebuild the {'data': {'results': [...]}} shape build_indicators expects."""
    results = []
    for sym in sorted(bars):
        rows = []
        for day in sorted(bars[sym]):
            if days is not None and day not in days:
                continue
            for hhmm, o, h, l, c, v in bars[sym][day]:
                rows.append({'begins_at': f'{day}T{hhmm}:00Z', 'open_price': o,
                             'high_price': h, 'low_price': l, 'close_price': c,
                             'volume': v})
        results.append({'symbol': sym, 'bars': rows})
    return {'data': {'results': results}}


def basket_er(bars, days, window_min):
    """Basket-level Kaufman ER over the first `window_min` bars of each day.

    Unsigned, matching the dashboard gauge's definition: |net| / sum(|deltas|).
    Averaged across symbols so one symbol's chop cannot decide the basket.
    """
    out = {}
    for day in days:
        per_sym = []
        for sym in bars:
            rows = bars[sym].get(day, [])[:window_min]
            if len(rows) < 3:
                continue
            closes = [r[4] for r in rows]
            net = abs(closes[-1] - closes[0])
            path = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))
            if path > 0:
                per_sym.append(net / path)
        out[day] = sum(per_sym) / len(per_sym) if per_sym else 0.0
    return out


def rs_tables(bars, bench_bars, bench_sym):
    """Causal intraday relative strength, keyed by (symbol, date, HH:MM).

    At each bar t: sym_ret = close(t)/first_close(day) - 1, same for the benchmark,
    and RS = sym_ret - bench_ret. Every term reads only bars at or before t, so the
    filter is decidable at the moment it would be acted on -- unlike a whole-session
    figure, which is the look-ahead trap that broke TGT's original validation.

    The benchmark is forward-filled within a day so a missing ETF minute cannot
    silently block an entry that the real rule would have allowed.
    """
    bench_ret, rs = {}, {}
    for day, rows in bench_bars[bench_sym].items():
        if not rows:
            continue
        base = rows[0][4]
        last = 0.0
        by_min = {r[0]: r[4] for r in rows}
        for hh in range(13, 21):
            for mm in range(60):
                t = f'{hh:02d}:{mm:02d}'
                if t in by_min:
                    last = by_min[t] / base - 1.0
                bench_ret[(day, t)] = last

    for sym in bars:
        for day, rows in bars[sym].items():
            if not rows:
                continue
            base = rows[0][4]
            for t, _o, _h, _l, c, _v in rows:
                rs[(sym, day, t)] = (c / base - 1.0) - bench_ret.get((day, t), 0.0)
    return rs, bench_ret


def build_variant(params, er_open, er_window_min, cost_bps, state_path, log_path,
                  rs=None, rs_min=0.0, bench_ret=None):
    """Import the real engine, patch only what the variant changes, return its run().

    state_path/log_path MUST be passed in and baked into the variant's namespace.
    An earlier version set V3.STATE_PATH after taking `ns = dict(V3.__dict__)`; the
    copy still held the real docs/ paths, so replays wrote backtest runs into the
    live paper ledger. The guard below makes that failure loud instead of silent.
    """
    import daytrading_v3_paper_engine as V3

    for p in (state_path, log_path):
        if os.path.abspath(p).startswith(os.path.join(ROOT, 'docs')):
            raise SystemExit(f'refusing to run: {p} is inside docs/ (the live paper ledger)')

    src = inspect.getsource(V3.run)
    c = cost_bps / 10000.0

    if cost_bps:
        # buys fill worse, sells fill worse -- both inside the loop, so `cash` and
        # therefore affordability change with cost, exactly as they would live.
        for old, new in [
            ("proceeds = pos['shares'] * price", "proceeds = pos['shares'] * price * (1 - COST_C)"),
            ("proceeds = sell_shares * price", "proceeds = sell_shares * price * (1 - COST_C)"),
        ]:
            assert src.count(old) == 1, f'anchor moved: {old}'
            src = src.replace(old, new)
        # two identical buy sites (ENTRY and ADD) -- both must be patched
        old_buy = 'sh = notional / price'
        assert src.count(old_buy) == 2, f'expected 2 buy sites, found {src.count(old_buy)}'
        src = src.replace(old_buy, 'sh = notional / (price * (1 + COST_C))')

    # compose every entry-side filter into the one anchor, so adding a second gate
    # cannot silently clobber the first
    extra = []
    if er_open is not None:
        extra.append('ER_OPEN.get(bar["date"], False) '
                     'and int(hhmm[:2]) * 60 + int(hhmm[3:]) >= ER_READY_MIN')
    if rs is not None:
        extra.append('RS.get((sym, bar["date"], hhmm), -9.9) > RS_MIN')
    if bench_ret is not None:
        extra.append('BENCH_RET.get((bar["date"], hhmm), -9.9) > 0.0')
    if extra:
        old = 'entry_ok = (vw[gi] is not None and price > vw[gi]'
        assert src.count(old) == 1, 'entry anchor moved'
        src = src.replace(old, 'entry_ok = (' + ' and '.join(extra)
                               + ' and vw[gi] is not None and price > vw[gi]')

    src = src.replace('def run(', 'def run_variant(', 1)

    ns = dict(V3.__dict__)
    ns.update(params)
    # bake the scratch paths into the variant's own globals -- run_variant resolves
    # STATE_PATH/LOG_PATH from here, not from the live module
    ns['STATE_PATH'] = state_path
    ns['LOG_PATH'] = log_path
    # run_variant resolves these from ns too, so the live module is never mutated
    ns['load_state'] = lambda: (json.load(open(state_path)) if os.path.exists(state_path)
                                else {'cash': V3.CAPITAL, 'positions': {}, 'last_processed_dt': {}})
    ns['load_log'] = lambda: (json.load(open(log_path)) if os.path.exists(log_path)
                              else {'capital': V3.CAPITAL, 'symbols': V3.SYMBOLS,
                                    'setup': 'replay', 'runs': []})
    ns['COST_C'] = c
    ns['RS'] = rs or {}
    ns['RS_MIN'] = rs_min
    ns['BENCH_RET'] = bench_ret or {}
    ns['ER_OPEN'] = er_open or {}
    # 13:30 UTC open + window; entries blocked until the gate is actually knowable
    ns['ER_READY_MIN'] = 13 * 60 + 30 + (er_window_min or 0)
    exec(compile(src, '<v3_run_variant>', 'exec'), ns)
    return V3, ns['run_variant']


def replay(tag, params, days, bars, er_open=None, er_window_min=30, cost_bps=0,
           rs=None, rs_min=0.0, bench_ret=None):
    os.makedirs(SCRATCH, exist_ok=True)
    state_path = os.path.join(SCRATCH, f'v3_{tag}_state.json')
    log_path = os.path.join(SCRATCH, f'v3_{tag}_log.json')
    for p in (state_path, log_path):
        if os.path.exists(p):
            os.remove(p)

    V3, run_variant = build_variant(params, er_open, er_window_min, cost_bps,
                                    state_path, log_path, rs, rs_min, bench_ret)
    raw_path = os.path.join(SCRATCH, f'v3_{tag}_raw.json')
    json.dump(to_raw_payload(bars, set(days)), open(raw_path, 'w'))

    # Seed last_processed_dt before the window so the incremental loop walks every bar
    # instead of evaluating only the newest one.
    seed = f'{days[0]}T00:00:00Z'
    json.dump({'cash': V3.CAPITAL, 'positions': {}, 'entry_cycles': {},
               'last_processed_dt': {s: seed for s in V3.SYMBOLS}},
              open(state_path, 'w'))

    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        trades, equity = run_variant(raw_path)

    buys = [t for t in trades if t['side'] == 'BUY']
    sells = [t for t in trades if t['side'] == 'SELL']
    notional = sum(t['shares'] * t['price'] for t in trades)
    traded_days = sorted({t['date'] for t in trades})
    return {
        'tag': tag, 'equity': round(equity, 2),
        'pnl': round(equity - V3.CAPITAL, 2),
        'ret_pct': round(100 * (equity - V3.CAPITAL) / V3.CAPITAL, 2),
        'trades': len(trades), 'buys': len(buys), 'sells': len(sells),
        'days_traded': len(traded_days), 'days_available': len(days),
        'notional': round(notional, 2),
        'realized': round(sum(t.get('pnl', 0.0) for t in sells), 2),
        'trade_list': trades,
    }


def fmt(r):
    return (f"{r['tag']:<34}{r['ret_pct']:>9.2f}%{r['pnl']:>11,.2f}"
            f"{r['trades']:>8}{r['days_traded']:>7}/{r['days_available']:<4}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--params', choices=sorted(PARAMS), default='baseline')
    ap.add_argument('--er-gate', type=float, default=None)
    ap.add_argument('--er-window', type=int, default=30)
    ap.add_argument('--cost-bps', type=float, default=0.0)
    ap.add_argument('--rs', choices=['SPY', 'SMH'], default=None,
                    help='block entries unless the symbol is outperforming this '
                         'benchmark since the session open')
    ap.add_argument('--rs-min', type=float, default=0.0)
    ap.add_argument('--mkt', choices=['SPY', 'SMH'], default=None,
                    help='block entries unless the benchmark itself is up on the day')
    ap.add_argument('--sweep', action='store_true')
    ap.add_argument('--rs-sweep', action='store_true')
    args = ap.parse_args()

    meta, bars = load_bars()
    bench_meta, bench_bars = (lambda d: (d['meta'], d['bars']))(json.load(open(BENCH)))
    if bench_meta['window_start'] != meta['window_start'] or \
       bench_meta['window_end'] != meta['window_end']:
        sys.exit('benchmark window does not match the semis window -- refusing to run')
    days = sorted(next(iter(bars.values())))
    half = len(days) // 2
    windows = {'full': days, 'first half': days[:half], 'second half': days[half:]}

    print(f"MEASURED -- replay of scripts/daytrading_v3_paper_engine.py")
    print(f"Window {meta['window_start']} -> {meta['window_end']} "
          f"({meta['trading_days']} trading days, {meta['total_bars']:,} real 1-min bars)")
    print(f"Symbols {', '.join(meta['symbols'])} | capital $5,000 | params: {args.params}")
    print(f"\n⚠️  {len(days)} trading days is a SMALL sample for a day-level gate "
          f"(~{half} per half-window).\n    Read direction, not decimal places.\n")

    er_all = basket_er(bars, days, args.er_window)
    print(f"Basket ER over first {args.er_window} min -- "
          f"min {min(er_all.values()):.3f}, median "
          f"{sorted(er_all.values())[len(er_all)//2]:.3f}, max {max(er_all.values()):.3f}")

    report = {'meta': meta, 'params': args.params, 'er_window_min': args.er_window,
              'basket_er_by_day': {d: round(v, 4) for d, v in er_all.items()},
              'results': {}}

    if args.rs_sweep:
        # (label, rs_bench, rs_min, mkt_bench) -- one filter at a time, then the
        # best RS variant combined with the ER gate
        combos = [('no filter', None, 0.0, None)]
        for b in ('SPY', 'SMH'):
            combos.append((f'RS>0 vs {b}', b, 0.0, None))
            combos.append((f'RS>+0.25% vs {b}', b, 0.0025, None))
            combos.append((f'{b} up on day', None, 0.0, b))
        costs = [0.0, 5.0, 10.0]
        for wname, wdays in windows.items():
            print(f"\n=== {wname}: {wdays[0]} -> {wdays[-1]} ({len(wdays)} days) ===")
            print(f"{'variant':<34}{'return':>10}{'P&L':>11}{'trades':>8}{'days':>12}")
            print('-' * 75)
            for label, rb, rmin, mb in combos:
                rs_t = bench_t = None
                if rb:
                    rs_t, _ = rs_tables(bars, bench_bars, rb)
                if mb:
                    _, bench_t = rs_tables(bars, bench_bars, mb)
                for cb in costs:
                    tag = f'{label} | {cb:.0f}bp'
                    r = replay(f'rs_{wname[:4]}_{label[:12]}_{cb}', PARAMS[args.params],
                               wdays, bars, None, args.er_window, cb,
                               rs_t, rmin, bench_t)
                    r['tag'] = tag
                    print(fmt(r))
                    report['results'].setdefault(wname, []).append(
                        {k: v for k, v in r.items() if k != 'trade_list'})
        dest = os.path.join(ROOT, 'data', 'v3_rs_results.json')
        json.dump(report, open(dest, 'w'), indent=1)
        print(f"\nwrote {os.path.relpath(dest, ROOT)}")
        return

    if args.sweep:
        gates = [None, 0.18, 0.30]
        costs = [0.0, 5.0, 10.0, 20.0, 40.0]
    else:
        gates, costs = [args.er_gate], [args.cost_bps]

    for wname, wdays in windows.items():
        print(f"\n=== {wname}: {wdays[0]} -> {wdays[-1]} ({len(wdays)} days) ===")
        print(f"{'variant':<34}{'return':>10}{'P&L':>11}{'trades':>8}{'days':>12}")
        print('-' * 75)
        rs_t = rs_tables(bars, bench_bars, args.rs)[0] if args.rs else None
        bench_t = rs_tables(bars, bench_bars, args.mkt)[1] if args.mkt else None
        for g in gates:
            er_open = None if g is None else {d: v >= g for d, v in er_all.items()}
            for cb in costs:
                tag = f"ER {'off' if g is None else f'>={g:.2f}'} | cost {cb:.0f}bp"
                r = replay(f'{wname[:4]}_{g}_{cb}', PARAMS[args.params], wdays, bars,
                           er_open, args.er_window, cb, rs_t, args.rs_min, bench_t)
                r['tag'] = tag
                print(fmt(r))
                report['results'].setdefault(wname, []).append(
                    {k: v for k, v in r.items() if k != 'trade_list'})

    dest = os.path.join(ROOT, 'data', 'v3_replay_results.json')
    json.dump(report, open(dest, 'w'), indent=1)
    print(f"\nwrote {os.path.relpath(dest, ROOT)}")


if __name__ == '__main__':
    main()
