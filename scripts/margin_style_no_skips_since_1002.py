"""Counterfactual: the live account from the 10-02 run to today (10-21) if EVERY daily plan
had been executed -- no stalls, no denials, no holds (asked 2026-10-21).

Real engine (origin/main), starting from main's state after the 10-02 run (commit e9ba57b,
flat, cash $17,371.74). Each day's check price:
  10-05..10-09  open of the 17:34 UTC 1-minute bar (data/research/missed_week_2026-10-05_prices.json)
  10-12..10-15  open of the 17:34 UTC 1-minute bar (fetched 2026-10-21, inline below)
  10-16..10-21  the quotes the live runs themselves used
Fills ASSUMED at the check price, no slippage or fees. Sale proceeds usable the next
trading day (T+1, cash account). The owner's own $500 WDC sale on 10-19 is left out.
Reproduce: python3 scripts/margin_style_no_skips_since_1002.py
"""
import contextlib, datetime as _dt, io, json, os, subprocess, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, 'data', 'research')
src = subprocess.check_output(['git', 'show', 'origin/main:scripts/margin_style_live_engine.py'], cwd=ROOT).decode()
state0 = json.loads(subprocess.check_output(['git', 'show', 'e9ba57b:docs/margin_style_live_state.json'], cwd=ROOT))
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
hist = json.load(open(os.path.join(D, 'missed_runs_2026-10-14', 'daily_hist_to_2026-10-20.json')))
mw = json.load(open(os.path.join(D, 'missed_week_2026-10-05_prices.json')))['check_prices_1734utc']
S = ['AMD', 'MU', 'WDC', 'SNDK', 'TSM', 'INTC', 'LRCX', 'STX']
row = lambda *v: dict(zip(S, v))
quotes = {d: {s: mw[d][s] for s in S} for d in ['2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08', '2026-10-09']}
quotes['2026-10-12'] = row(590.425, 991.29, 387.52, 1483.17, 446.6684, 101.3795, 311.24, 757.19)
quotes['2026-10-13'] = row(595.77, 935.12, 377.4934, 1445.95, 442.40, 101.7599, 295.08, 733.965)
quotes['2026-10-14'] = row(571.84, 923.50, 363.92, 1414.775, 430.31, 98.715, 286.00, 717.5659)
quotes['2026-10-15'] = row(549.7412, 911.33, 345.76, 1342.81, 419.92, 94.215, 273.655, 672.70)
quotes['2026-10-16'] = row(536.0, 894.725, 340.115, 1329.34, 413.5, 91.06, 268.375, 654.755)
quotes['2026-10-19'] = row(541.13, 904.6013, 347.76, 1376.822, 421.48, 92.66, 275.10, 658.6302)
quotes['2026-10-20'] = row(540.465, 909.99, 363.40, 1383.46, 426.7599, 92.4203, 264.48, 678.30)
quotes['2026-10-21'] = row(553.795, 917.985, 380.07, 1389.21, 429.955, 92.644, 263.65, 701.34)

settled, pending, realized = 17371.74, 0.0, 0.0
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
print(f"\nrealized since 10-02: ${realized:+,.2f}   ending equity ${eq:,.2f} vs start $17,371.74 "
      f"({eq - 17371.74:+,.2f})")
