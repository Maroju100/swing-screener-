#!/usr/bin/env python3
"""Margin-Style Live backtest using the CORRECT 17:00 UTC price basis.

This is scripts/margin_style_original_6month_backtest.py's methodology --
verbatim where it matters -- with the window, capital, engine revision and the
DAILY_STOP defect made configurable, so the other documented rows (holdout,
with-daily-stop) can be checked the same way the +155.10% row was.

PRICE BASIS (the thing that matters)
------------------------------------
"Today" is priced off the ACTUAL ~17:00 UTC hourly bar -- the moment the live
trigger fires -- falling back to that day's close only when an hourly bar is
missing. This is what the original did and it is the correct basis. Using the
daily close instead (as scripts/margin_style_baseline_backtest.py does) changes
which rules fire every single day, because PEAK_SELL_PCT trims on every new high
and INTRADAY_STOP compares against the prior close. Do not substitute it.

SELF-VALIDATION -- RUN THIS FIRST
----------------------------------
    python3 scripts/margin_style_17h_backtest.py --validate

reproduces the known reference ($124,080.90 realized / +155.10%) and fails loudly
if it does not. A harness is not entitled to overturn anything until it can
reproduce a result that is already trusted; skipping that step is exactly how a
correct figure got wrongly "retracted" on 2026-09-21.

ACCOUNTING (matches the original exactly)
------------------------------------------
  realized  = sum over sells of shares x (price - entry)
  unrealized= end-of-window (mark - cost) on whatever is still open
  total     = realized + unrealized;  return % = total / capital
  "+155.10%" is the REALIZED-only measure; "+158.42%" is total. Both are real.

WINDOWS
-------
Lookback is always cumulative from the start of the data (all_dates[:i]), so a
sub-window like the holdout gets full prior history -- unlike the original's
full-window run, whose data began at the window start and therefore ramped up
with incomplete HUGE_DIP (60d) / TREND_GATE_SMA (50d) lookback. --start is the
first day TRADED, not the first day of history.

DAILY_STOP DEFECT
-----------------
--patch-daily-stop-bug clears pending_peak_gain/peak_updates in the DAILY_STOP
branch, mirroring what KILL_SWITCH already does. Without it, a DAILY_STOP
liquidation is followed by a parked PEAK sell of the same position -- two sells
totalling ~174.3% of what is held. See CLAUDE.md under Key thresholds. Any
with-stop figure should be reported BOTH ways, since the defect inflates results.

Never touches docs/margin_style_live_state.json; STATE_PATH is redirected.
"""
import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
from datetime import datetime as real_datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(ROOT, '.backtest_scratch')
DAILY = os.path.join(ROOT, 'data', 'margin_live_daily_6mo_2026-03-06_2026-09-04.json')
HOURLY = os.path.join(ROOT, 'data', 'margin_live_hourly_6mo_2026-03-06_2026-09-04.json')

UNIVERSE = ['AMD', 'MU', 'WDC', 'SNDK', 'TSM', 'INTC', 'LRCX', 'STX']

# The original ran engine 859057e (live at 2026-09-06 01:55, last revision before
# the daily stop). bc814c4 is the commit that added DAILY_STOP.
ENGINE_NOSTOP = '859057e'
ENGINE_WITHSTOP = 'bc814c4'

# Known reference the harness must reproduce before it may be trusted.
REF_START = '2026-03-13'
REF_REALIZED = 124080.90
REF_CAPITAL = 80000.0

SIM_DAY = {'value': None}


class FakeDatetime(real_datetime):
    @classmethod
    def now(cls, tz=None):
        d = SIM_DAY['value']
        return real_datetime(d.year, d.month, d.day, 17, 0, 0, tzinfo=tz)


def load_engine_src(rev):
    """rev=None (or 'working') reads the CURRENT working-tree engine."""
    if rev in (None, 'working'):
        return open(os.path.join(ROOT, 'scripts', 'margin_style_live_engine.py')).read()
    return subprocess.check_output(
        ['git', 'show', f'{rev}:scripts/margin_style_live_engine.py'], cwd=ROOT, text=True)


def apply_daily_stop_patch(src):
    old = ("    if not daily_stop_active and daily_total_loss >= daily_loss_cap:\n"
           "        daily_stop_active = True\n"
           "        daily_stop_date = today\n")
    new = old + "        pending_peak_gain = {}\n        peak_updates = {}\n"
    if src.count(old) != 1:
        raise SystemExit(f'DAILY_STOP patch anchor matched {src.count(old)}x, expected 1')
    return src.replace(old, new)


def extract_plan(text):
    """Tolerate engines that print freshness warnings ahead of the JSON."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.rstrip() in ('{', '{'):
            return json.loads('\n'.join(lines[i:]))
    return json.loads(text)


def run(start, end, capital, engine_rev, patch_bug=False):
    os.makedirs(SCRATCH, exist_ok=True)
    state_path = os.path.join(SCRATCH, 'state_17h.json')
    if os.path.exists(state_path):
        os.remove(state_path)

    src = load_engine_src(engine_rev)
    if patch_bug:
        src = apply_daily_stop_patch(src)

    ns = {'__file__': os.path.join(ROOT, 'scripts', 'margin_style_live_engine.py')}
    exec(compile(src, 'margin_style_live_engine.py', 'exec'), ns)
    ns['SYMBOLS'] = UNIVERSE
    ns['STATE_PATH'] = state_path
    ns['datetime'] = FakeDatetime
    cmd_plan, cmd_commit = ns['cmd_plan'], ns['cmd_commit']

    daily = json.load(open(DAILY))
    daily_by_sym = {r['symbol']: {b['begins_at'][:10]: float(b['close_price']) for b in r['bars']}
                    for r in daily['data']['results']}
    all_dates = sorted(next(iter(daily_by_sym.values())).keys())

    hourly = json.load(open(HOURLY))
    q1700 = {}
    for r in hourly['data']['results']:
        q1700[r['symbol']] = {b['begins_at'][:10]: float(b['close_price'])
                              for b in r['bars'] if b['begins_at'][11:19] == '17:00:00'}

    hist_path = os.path.join(SCRATCH, 'h17_hist.json')
    quotes_path = os.path.join(SCRATCH, 'h17_quotes.json')
    actions_path = os.path.join(SCRATCH, 'h17_actions.json')

    cash = capital
    realized_total = 0.0
    traded_days = 0
    day_pnl, day_equity, trades = {}, {}, []
    stop_days = []

    for i, D in enumerate(all_dates):
        if D < start or D > end:
            continue
        traded_days += 1
        hist_results = []
        for sym in UNIVERSE:
            bars = [{'begins_at': dt + 'T00:00:00Z', 'close_price': str(daily_by_sym[sym][dt])}
                    for dt in all_dates[:i] if dt in daily_by_sym[sym]]
            hist_results.append({'symbol': sym, 'bars': bars})
        json.dump({'data': {'results': hist_results}}, open(hist_path, 'w'))

        quotes = {}
        for sym in UNIVERSE:
            if D in q1700.get(sym, {}):
                quotes[sym] = q1700[sym][D]
            elif D in daily_by_sym[sym]:
                quotes[sym] = daily_by_sym[sym][D]
        json.dump(quotes, open(quotes_path, 'w'))

        SIM_DAY['value'] = real_datetime.strptime(D, '%Y-%m-%d')

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_plan(hist_path, quotes_path, cash, [])
        plan = extract_plan(buf.getvalue())

        day_realized = 0.0
        actions = {'sells': [], 'buys': [],
                   'peak_updates': plan.get('peak_updates', {}),
                   'risk_state': plan['risk_state']}
        for s in plan['sells']:
            actions['sells'].append({k: s[k] for k in ('symbol', 'shares', 'price', 'reason', 'entry')})
            day_realized += s['shares'] * (s['price'] - s['entry'])
            cash += s['shares'] * s['price']
            trades.append({'date': D, 'side': 'sell', **{k: s[k] for k in ('symbol', 'shares', 'price', 'reason')}})
            if s['reason'] == 'DAILY_STOP' and D not in stop_days:
                stop_days.append(D)
        for b in plan['buys']:
            actions['buys'].append({k: b[k] for k in ('symbol', 'shares', 'price', 'reason')})
            cash -= b['shares'] * b['price']
            trades.append({'date': D, 'side': 'buy', **{k: b[k] for k in ('symbol', 'shares', 'price', 'reason')}})

        json.dump(actions, open(actions_path, 'w'))
        with contextlib.redirect_stdout(io.StringIO()):
            cmd_commit(actions_path)

        day_pnl[D] = day_realized
        realized_total += day_realized
        state = json.load(open(state_path))
        open_val = sum(p['shares'] * quotes.get(sym, daily_by_sym[sym].get(D, p['entry']))
                       for sym, p in state['open_positions'].items())
        day_equity[D] = cash + open_val

    state = json.load(open(state_path))
    last_traded = max(day_equity) if day_equity else end
    open_val = open_cost = 0.0
    for sym, p in state['open_positions'].items():
        px = q1700.get(sym, {}).get(last_traded, daily_by_sym[sym].get(last_traded, p['entry']))
        open_val += p['shares'] * px
        open_cost += p['shares'] * p['entry']
    unrealized = open_val - open_cost
    total = realized_total + unrealized

    return {
        'start': start, 'end': end, 'trading_days': traded_days,
        'engine_rev': engine_rev, 'daily_stop_bug_patched': patch_bug,
        'capital': capital,
        'realized': round(realized_total, 2),
        'unrealized': round(unrealized, 2),
        'total': round(total, 2),
        'realized_pct': round(realized_total / capital * 100, 2),
        'total_pct': round(total / capital * 100, 2),
        'trade_count': len(trades),
        'daily_stop_days': stop_days,
        'day_pnl': day_pnl, 'day_equity': day_equity, 'trades': trades,
    }


def show(label, r):
    print(f"--- {label}")
    print(f"    engine {r['engine_rev']}"
          f"{'  [DAILY_STOP bug PATCHED]' if r['daily_stop_bug_patched'] else ''}")
    print(f"    {r['start']} -> {r['end']}  ({r['trading_days']} trading days, "
          f"{r['trade_count']} trades, capital ${r['capital']:,.0f})")
    print(f"    realized   ${r['realized']:>13,.2f}   ({r['realized_pct']:+.2f}%)")
    print(f"    unrealized ${r['unrealized']:>13,.2f}")
    print(f"    TOTAL      ${r['total']:>13,.2f}   ({r['total_pct']:+.2f}%)")
    if r['daily_stop_days']:
        print(f"    DAILY_STOP fired on {len(r['daily_stop_days'])} days")
    print()


def validate():
    print('VALIDATION: reproduce the known reference before trusting anything else')
    print('=' * 70)
    r = run(REF_START, '2026-09-04', REF_CAPITAL, ENGINE_NOSTOP)
    show('6-month baseline, no stop (reference)', r)
    ok = abs(r['realized'] - REF_REALIZED) < 0.01
    print(f"expected realized ${REF_REALIZED:,.2f} / +155.10%")
    print(f"got      realized ${r['realized']:,.2f} / {r['realized_pct']:+.2f}%")
    print('PASS - harness reproduces the reference' if ok else 'FAIL - DO NOT TRUST THIS HARNESS')
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--validate', action='store_true')
    ap.add_argument('--start', default=REF_START)
    ap.add_argument('--end', default='2026-09-04')
    ap.add_argument('--capital', type=float, default=REF_CAPITAL)
    ap.add_argument('--engine-rev', default=ENGINE_NOSTOP)
    ap.add_argument('--patch-daily-stop-bug', action='store_true')
    ap.add_argument('--json')
    args = ap.parse_args()

    if args.validate:
        sys.exit(0 if validate() else 1)

    r = run(args.start, args.end, args.capital, args.engine_rev, args.patch_daily_stop_bug)
    show(f"{args.start} -> {args.end}", r)
    if args.json:
        json.dump(r, open(args.json, 'w'), indent=1)
        print(f"full results -> {args.json}")


if __name__ == '__main__':
    main()
