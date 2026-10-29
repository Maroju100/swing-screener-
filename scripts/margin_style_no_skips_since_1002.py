"""Counterfactual: the live account from the 10-02 run to 10-28 (extended 2026-10-29) if EVERY daily plan
had been executed -- no stalls, no denials, no holds (asked 2026-10-21).

Real engine (origin/main), starting from main's state after the 10-02 run (commit e9ba57b,
flat, cash $17,371.74). Each day's check price:
  10-05..10-09  open of the 17:34 UTC 1-minute bar (data/research/missed_week_2026-10-05_prices.json)
  10-12..10-15  open of the 17:34 UTC 1-minute bar (fetched 2026-10-21, inline below)
  10-16..10-28  the quotes the live runs themselves used (10-22: 18:14 UTC plan quotes)
Fills ASSUMED at the check price, no slippage or fees. Sale proceeds usable the next
trading day (T+1, cash account). The owner's own $500 WDC sale on 10-19 is left out.
Reproduce: python3 scripts/margin_style_no_skips_since_1002.py [--from-0922]

--from-0922 starts instead on 2026-09-22, the first clean point of the account: flat after
the 09-21 run, cash $17,693.63 (broker; CGC's $1.85 excluded), equity_peak 17,696.92, no
deposits or owner trades after it until the owner's own $500 WDC sale on 10-19 (left out).
09-22..10-02 check prices = open of the 17:34 UTC 1-minute bar (fetched 2026-10-21).
"""
import contextlib, datetime as _dt, io, json, os, subprocess, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, 'data', 'research')
src = subprocess.check_output(['git', 'show', 'origin/main:scripts/margin_style_live_engine.py'], cwd=ROOT).decode()
import sys
FROM_0922 = '--from-0922' in sys.argv
state0 = json.loads(subprocess.check_output(['git', 'show', 'e9ba57b:docs/margin_style_live_state.json'], cwd=ROOT))
START_CASH = 17371.74
if FROM_0922:
    state0 = {'open_positions': {}, 'pending_settlement': [], 'equity_peak': 17696.92,
              'kill_switch_active': False, 'kill_switch_triggered_date': None, 'trend_gate_active': False}
    START_CASH = 17693.63
SC = tempfile.mkdtemp()


class FD(_dt.datetime):
    now_ = None

    @classmethod
    def now(cls, tz=None):
        return cls.now_ if tz else cls.now_.replace(tzinfo=None)


ns = {'__file__': os.path.join(ROOT, 'scripts', 'margin_style_live_engine.py'), '__name__': 'cf'}
exec(compile(src, 'engine', 'exec'), ns)
ns['datetime'] = FD
ns['STATE_PATH'] = SC + '/state.json'
json.dump(state0, open(SC + '/state.json', 'w'))
hist = json.load(open(os.path.join(D, 'missed_runs_2026-10-14', 'daily_hist_to_2026-10-27.json')))
mw = json.load(open(os.path.join(D, 'missed_week_2026-10-05_prices.json')))['check_prices_1734utc']
S = ['AMD', 'MU', 'WDC', 'SNDK', 'TSM', 'INTC', 'LRCX', 'STX']
row = lambda *v: dict(zip(S, v))
quotes = {d: {s: mw[d][s] for s in S} for d in ['2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08', '2026-10-09']}
if FROM_0922:
    quotes['2026-09-22'] = row(616.565, 1080.96, 456.44, 1886.0, 447.71, 121.61, 306.955, 902.03)
    quotes['2026-09-23'] = row(613.12, 1070.70, 469.84, 1820.23, 445.52, 120.33, 305.70, 920.76)
    quotes['2026-09-24'] = row(624.37, 1075.38, 458.62, 1766.895, 450.42, 125.565, 303.79, 912.38)
    quotes['2026-09-25'] = row(629.625, 1081.74, 456.95, 1777.35, 451.1501, 124.485, 314.28, 918.53)
    quotes['2026-09-28'] = row(606.7694, 1056.1782, 449.9458, 1716.99, 453.346, 116.0, 314.58, 920.83)
    quotes['2026-09-29'] = row(612.735, 1070.18, 451.076, 1710.59, 458.05, 116.68, 320.43, 905.61)
    quotes['2026-09-30'] = row(605.3899, 1069.05, 459.09, 1732.375, 458.485, 119.35, 325.74, 922.37)
    quotes['2026-10-01'] = row(617.64, 1076.105, 455.14, 1795.8072, 460.07, 121.65, 339.385, 933.74)
    quotes['2026-10-02'] = row(630.73, 1081.52, 413.18, 1724.11, 469.95, 120.03, 349.04, 834.13)
quotes['2026-10-12'] = row(590.425, 991.29, 387.52, 1483.17, 446.6684, 101.3795, 311.24, 757.19)
quotes['2026-10-13'] = row(595.77, 935.12, 377.4934, 1445.95, 442.40, 101.7599, 295.08, 733.965)
quotes['2026-10-14'] = row(571.84, 923.50, 363.92, 1414.775, 430.31, 98.715, 286.00, 717.5659)
quotes['2026-10-15'] = row(549.7412, 911.33, 345.76, 1342.81, 419.92, 94.215, 273.655, 672.70)
quotes['2026-10-16'] = row(536.0, 894.725, 340.115, 1329.34, 413.5, 91.06, 268.375, 654.755)
quotes['2026-10-19'] = row(541.13, 904.6013, 347.76, 1376.822, 421.48, 92.66, 275.10, 658.6302)
quotes['2026-10-20'] = row(540.465, 909.99, 363.40, 1383.46, 426.7599, 92.4203, 264.48, 678.30)
quotes['2026-10-21'] = row(553.795, 917.985, 380.07, 1389.21, 429.955, 92.644, 263.65, 701.34)
quotes['2026-10-22'] = row(510.0601, 861.22, 351.0656, 1250.3766, 411.50, 86.0801, 231.55, 636.41)  # live plan quotes, 18:14 UTC
quotes['2026-10-23'] = row(516.005, 883.705, 345.39, 1267.01, 416.30, 86.63, 230.90, 643.64)    # live run quotes 17:44 UTC
quotes['2026-10-26'] = row(530.1885, 909.39, 359.585, 1264.88, 426.6144, 91.34, 239.3634, 659.70)
quotes['2026-10-27'] = row(559.845, 933.1063, 382.225, 1301.46, 437.42, 93.695, 240.545, 674.8889)
quotes['2026-10-28'] = row(568.37, 968.8199, 392.275, 1380.245, 438.23, 94.20, 253.08, 683.82)
CLOSE_1022 = row(507.77, 857.01, 354.22, 1261.72, 412.375, 85.4958, 230.16, 642.03)          # 10-22 4 PM close

settled, pending, realized = START_CASH, 0.0, 0.0
for day in sorted(quotes):
    q = quotes[day]
    settled += pending; pending = 0.0                       # yesterday's sales settle (T+1)
    FD.now_ = _dt.datetime.fromisoformat(day + 'T17:34:00+00:00')
    h = {'data': {'results': [{'symbol': r['symbol'], 'bars': [b for b in r['bars'] if b['begins_at'][:10] < day]}
                              for r in hist['data']['results']]}}
    json.dump(h, open(SC + '/h.json', 'w')); json.dump(q, open(SC + '/q.json', 'w'))
    st = json.load(open(SC + '/state.json'))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        ns['cmd_plan'](SC + '/h.json', SC + '/q.json', settled, [],
                       json.dumps({s: p['shares'] for s, p in st['open_positions'].items()}))
    plan = json.loads(buf.getvalue()[buf.getvalue().index('{'):])
    acts = {'sells': [{k: x[k] for k in ('symbol', 'shares', 'price', 'reason')} for x in plan['sells']],
            'buys': [{k: x[k] for k in ('symbol', 'shares', 'price', 'reason')} for x in plan['buys']],
            'peak_updates': plan['peak_updates'], 'risk_state': plan['risk_state']}
    json.dump(acts, open(SC + '/a.json', 'w'))
    with contextlib.redirect_stdout(io.StringIO()):
        ns['cmd_commit'](SC + '/a.json')
    for x in plan['sells']:
        pending += x['shares'] * x['price']; realized += (x['price'] - x['entry']) * x['shares']
    settled -= sum(x['shares'] * x['price'] for x in acts['buys'])
    st = json.load(open(SC + '/state.json'))
    eq = settled + pending + sum(p['shares'] * q[s] for s, p in st['open_positions'].items())
    fmt = lambda xs: ' '.join(f"{x['symbol']}:{x['reason']}" for x in xs) or '-'
    print(f"{day}  equity ${eq:>10,.2f}  sells [{fmt(acts['sells'])}]  buys [{fmt(acts['buys'])}]"
          f"  ks={plan['risk_state']['kill_switch_active']}")
st = json.load(open(SC + '/state.json'))
print(f"10-22 at 4 PM close (positions only matter if any are open): ${settled + pending + sum(p['shares'] * CLOSE_1022[s] for s, p in st['open_positions'].items()):,.2f}  open: {sorted(st['open_positions'])}")
print(f"\nrealized: ${realized:+,.2f}   ending equity ${eq:,.2f} vs start ${START_CASH:,.2f} "
      f"({eq - START_CASH:+,.2f})")
