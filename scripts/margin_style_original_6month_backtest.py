"""THE ORIGINAL 6-month backtest that produced the +155.10% figure.

PRESERVED VERBATIM 2026-09-21 from /tmp/margin_live_full_universe_backtest_v2.py
(written 2026-09-06 01:54). Only three things changed: the engine source is
pinned to the revision that was live when it ran, and the two data inputs now
point at committed copies in data/. All logic is byte-identical to the original.

IT REPRODUCES THE DOCUMENTED NUMBERS EXACTLY:

    Realized P&L: $+124,080.90          <- CLAUDE.md's $124,080.90
    124,080.90 / 80,000 = +155.10%      <- CLAUDE.md's +155.10%
    Total incl. mark-to-market: +$126,737.07 (+158.42%)
    80,000 + 126,737.04 = $206,737.04   <- CLAUDE.md's ending equity

So the two figures in CLAUDE.md are BOTH real outputs of this one run, just
different measures: +155.10% is REALIZED P&L only; +158.42% (and the $206,737
ending equity) adds end-of-window unrealized mark-to-market. They are not in
conflict; they answer different questions.

WHY THE ENGINE REVISION IS PINNED
This ran 2026-09-06 01:55, BEFORE bc814c4 (2026-09-06 20:29) added the daily
stop -- so the live engine at that moment was 859057e. That is why CLAUDE.md
correctly labels the result "Baseline (no stop)". Against today's engine the
original aborts, because cmd_plan now prints data-freshness warnings ahead of
its JSON (added 2026-09-16) and line ~90's json.loads chokes on them.

WHAT MAKES THIS MORE ACCURATE THAN scripts/margin_style_baseline_backtest.py
It prices "today" off the ACTUAL ~17:00 UTC hourly bar -- the same moment the
live trigger fires -- falling back to the daily close only when an hourly bar
is missing. margin_style_baseline_backtest.py instead used the daily close as a
proxy and got +64.12% for this same window. That proxy is NOT harmless: PEAK_SELL
fires on every new high and INTRADAY_STOP compares against the prior close, so
the price source changes which rules fire every single day. The 17:00 quote is
the correct one. Treat THIS script as the reference for the 6-month figure.

Two further differences from that harness, recorded so nobody re-derives them:
  * Lookback: data/margin_live_daily_6mo_*.json starts exactly at the window
    start, so the first ~60 days ran with incomplete HUGE_DIP (60d) and
    TREND_GATE_SMA (50d) lookback, ramping up. START_IDX=5 skips only 5 days.
  * day_pnl here is REALIZED-ONLY (line ~97). day_equity does include
    mark-to-market. Do not compare this day_pnl against an equity-change series.

Run: python3 scripts/margin_style_original_6month_backtest.py
Writes its results to /tmp; it never touches docs/margin_style_live_state.json
(STATE_PATH is redirected at line ~15).
"""
import json, os, io, contextlib
from datetime import datetime as real_datetime, timezone

import subprocess as _sp
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# engine as of 859057e -- the revision live when this backtest was first run
SRC = _sp.check_output(['git', 'show', '859057e:scripts/margin_style_live_engine.py'],
                       cwd=_ROOT, text=True)

SCRATCH_STATE = '/tmp/mslive_full_backtest_v2_state.json'
if os.path.exists(SCRATCH_STATE):
    os.remove(SCRATCH_STATE)

ns = {'__file__': '/home/user/swing-screener-/scripts/margin_style_live_engine.py'}
exec(compile(SRC, 'margin_style_live_engine.py', 'exec'), ns)

UNIVERSE = ['AMD', 'MU', 'WDC', 'SNDK', 'TSM', 'INTC', 'LRCX', 'STX']
ns['SYMBOLS'] = UNIVERSE
ns['STATE_PATH'] = SCRATCH_STATE

SIM_DAY = {'value': None}

class FakeDatetime(real_datetime):
    @classmethod
    def now(cls, tz=None):
        d = SIM_DAY['value']
        return real_datetime(d.year, d.month, d.day, 17, 0, 0, tzinfo=tz)

ns['datetime'] = FakeDatetime

cmd_plan = ns['cmd_plan']
cmd_commit = ns['cmd_commit']

# ---- daily closes (for the historicals cmd_plan looks back over) ----
daily = json.load(open(os.path.join(_ROOT, 'data', 'margin_live_daily_6mo_2026-03-06_2026-09-04.json')))
daily_by_sym = {}
for r in daily['data']['results']:
    daily_by_sym[r['symbol']] = {b['begins_at'][:10]: float(b['close_price']) for b in r['bars']}
all_dates = sorted(next(iter(daily_by_sym.values())).keys())

# ---- hourly bars (for the actual ~17:00 UTC live quote each day) ----
hourly = json.load(open(os.path.join(_ROOT, 'data', 'margin_live_hourly_6mo_2026-03-06_2026-09-04.json')))
quote_1700_by_sym = {}
for r in hourly['data']['results']:
    sym = r['symbol']
    q = {}
    for b in r['bars']:
        if b['begins_at'][11:19] == '17:00:00':
            q[b['begins_at'][:10]] = float(b['close_price'])
    quote_1700_by_sym[sym] = q

missing = {sym: [d for d in all_dates if d not in quote_1700_by_sym.get(sym, {})] for sym in UNIVERSE}
for sym, miss in missing.items():
    if miss:
        print(f"WARNING: {sym} missing a 17:00 UTC bar on {len(miss)} days: {miss[:5]}{'...' if len(miss)>5 else ''}")

CAPITAL = 10000.0 * len(UNIVERSE)
cash = CAPITAL
realized_total = 0.0
day_pnl = {}
day_equity = {}
START_IDX = 5

for i, D in enumerate(all_dates):
    if i < START_IDX:
        day_pnl[D] = 0.0
        continue
    hist_dates = all_dates[:i]

    hist_results = []
    for sym in UNIVERSE:
        bars = [{'begins_at': dt + 'T00:00:00Z', 'close_price': str(daily_by_sym[sym][dt])}
                 for dt in hist_dates if dt in daily_by_sym[sym]]
        hist_results.append({'symbol': sym, 'bars': bars})
    hist_path = '/tmp/_msfullv2_hist_tmp.json'
    json.dump({'data': {'results': hist_results}}, open(hist_path, 'w'))

    # live quote = the actual ~17:00 UTC intraday price that day, falling back
    # to the daily close only on the rare day with a missing 17:00 bar
    quotes = {}
    for sym in UNIVERSE:
        if D in quote_1700_by_sym.get(sym, {}):
            quotes[sym] = quote_1700_by_sym[sym][D]
        elif D in daily_by_sym[sym]:
            quotes[sym] = daily_by_sym[sym][D]
    quotes_path = '/tmp/_msfullv2_quotes_tmp.json'
    json.dump(quotes, open(quotes_path, 'w'))

    SIM_DAY['value'] = real_datetime.strptime(D, '%Y-%m-%d')

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cmd_plan(hist_path, quotes_path, cash, [])
    plan = json.loads(buf.getvalue())

    day_realized = 0.0
    actions = {'sells': [], 'buys': [], 'peak_updates': plan.get('peak_updates', {}), 'risk_state': plan['risk_state']}
    for s in plan['sells']:
        actions['sells'].append({'symbol': s['symbol'], 'shares': s['shares'], 'price': s['price'],
                                  'reason': s['reason'], 'entry': s['entry']})
        day_realized += s['shares'] * (s['price'] - s['entry'])
        cash += s['shares'] * s['price']
    for b in plan['buys']:
        actions['buys'].append({'symbol': b['symbol'], 'shares': b['shares'], 'price': b['price'], 'reason': b['reason']})
        cash -= b['shares'] * b['price']

    actions_path = '/tmp/_msfullv2_actions_tmp.json'
    json.dump(actions, open(actions_path, 'w'))
    with contextlib.redirect_stdout(buf):
        cmd_commit(actions_path)

    day_pnl[D] = day_realized
    realized_total += day_realized

    state = json.load(open(SCRATCH_STATE))
    open_val = sum(pos['shares'] * quotes.get(sym, daily_by_sym[sym].get(D, pos['entry'])) for sym, pos in state['open_positions'].items())
    day_equity[D] = cash + open_val

    if plan['risk_state'].get('kill_switch_active'):
        print(f"  KILL SWITCH active on {D}")

state = json.load(open(SCRATCH_STATE))
last_D = all_dates[-1]
open_val = 0.0
open_cost = 0.0
for sym, pos in state['open_positions'].items():
    px = quote_1700_by_sym.get(sym, {}).get(last_D, daily_by_sym[sym][last_D])
    open_val += pos['shares'] * px
    open_cost += pos['shares'] * pos['entry']
unrealized = open_val - open_cost

bh_total = 0.0
for sym in UNIVERSE:
    first = quote_1700_by_sym.get(sym, {}).get(all_dates[START_IDX], daily_by_sym[sym][all_dates[START_IDX]])
    last = quote_1700_by_sym.get(sym, {}).get(last_D, daily_by_sym[sym][last_D])
    bh_total += 10000.0 * (last - first) / first

print(f"\nBacktest window: {all_dates[START_IDX]} to {last_D} ({len(all_dates)-START_IDX} trading days)")
print(f"Live-quote source: actual ~17:00 UTC intraday price each day (not the daily close)")
print(f"Starting capital: ${CAPITAL:,.2f} (${10000.0:,.0f}/symbol x {len(UNIVERSE)} symbols)")
print(f"\nRealized P&L: ${realized_total:+,.2f}")
print(f"Open positions at end: value ${open_val:,.2f}, cost ${open_cost:,.2f}, unrealized ${unrealized:+,.2f}")
print(f"TOTAL (realized + mark-to-market): ${realized_total + unrealized:+,.2f}  ({100*(realized_total+unrealized)/CAPITAL:+.2f}%)")
print(f"\nBuy & hold comparison (equal $10k/symbol, held the whole window): ${bh_total:+,.2f}  ({100*bh_total/CAPITAL:+.2f}%)")
print(f"\nRisk state at end: kill_switch={state.get('kill_switch_active')}, trend_gate={state.get('trend_gate_active')}")

json.dump({'day_pnl': day_pnl, 'day_equity': day_equity}, open('/tmp/margin_live_full_backtest_v2_results.json', 'w'))
