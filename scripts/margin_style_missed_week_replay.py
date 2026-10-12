#!/usr/bin/env python3
"""What would the week of 2026-10-05..10-09 have done if the live runs had completed?

FACTS (from the run log and the broker's order list): the scheduled live runs of
10-05, 10-06, 10-07, 10-08 and 10-09 did not complete, so no orders were placed
between the 10-02 run and the 10-12 run. This replays the production engine as
if each of those runs HAD completed, and compares it with what actually happened.

METHOD (Evidence Rule 1: engine replay, not day_pnl post-processing)
  * Engine: production source at ENGINE_REV, exec'd in memory with its STATE_PATH
    pointed at a scratch file and `datetime` replaced by a fake clock. No rule is
    patched. Real-money state/log files are only READ (via git show).
  * Start: production state as committed after the 10-02 run (ENGINE_REV), cash
    = the broker's buying power at the 10-05 check, 17,371.74 (the 10-02 proceeds
    had settled; unsettled_funds 0).
  * Prices: the price at 17:34 UTC each day (open of the 1-minute bar starting
    17:34:00), i.e. the live trigger's check instant, from
    data/research/missed_week_2026-10-05_prices.json. Daily bars = completed
    closes strictly before the day, as the live run uses.
  * Cash: settled + unsettled tracked together and passed as real_cash; the
    engine subtracts its own pending_settlement (T+1), exactly as live.
  * Fills: at the check price. COST_BPS per side is charged (ESTIMATED; live
    fills on these names have cost ~0-3 bps).
  * Gate: the "actual" path (skip 10-05..10-09, run 10-12) must reproduce the live
    10-12 plan -- STOP on INTC, MU and AMD, same shares, no buys -- or the script
    refuses to report.

Reproduce:
    python3 scripts/margin_style_missed_week_replay.py [--cost-bps 5]
"""
import argparse
import contextlib
import datetime as _dt
import io
import json
import os
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENGINE_REV = 'e9ba57b'   # main after the 10-02 run, before the 10-12 run
PRICES = os.path.join(ROOT, 'data', 'research', 'missed_week_2026-10-05_prices.json')
OUT = os.path.join(ROOT, 'data', 'research', 'missed_week_replay.json')
START_CASH = 17371.74
DAYS = ['2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08', '2026-10-09', '2026-10-12']
REAL_MONEY_FILES = ('margin_style_live_state.json', 'margin_style_live_log.json')
# Optional hooks for rule studies: a source patch and module-level settings.
# Left as None/{} this script replays production unmodified.
SRC_PATCH = None
PARAMS = {}


def git_show(rev, path):
    return subprocess.run(['git', 'show', f'{rev}:{path}'], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout


class FakeDatetime(_dt.datetime):
    _now = None

    @classmethod
    def now(cls, tz=None):
        return cls._now if tz else cls._now.replace(tzinfo=None)


def load_engine(state_path):
    ns = {'__name__': 'replay_engine', '__file__': os.path.join(ROOT, 'scripts', 'x.py')}
    src = git_show(ENGINE_REV, 'scripts/margin_style_live_engine.py')
    if SRC_PATCH:
        src = SRC_PATCH(src)
    exec(compile(src, f'<{ENGINE_REV} engine>', 'exec'), ns)
    ns.update(PARAMS)
    ns['STATE_PATH'] = state_path
    ns['datetime'] = FakeDatetime
    assert not any(state_path.endswith(f) for f in REAL_MONEY_FILES)
    return ns


def run_path(days, data, cost_bps, tmp):
    state_path = os.path.join(tmp, 'state.json')
    json.dump(json.loads(git_show(ENGINE_REV, 'docs/margin_style_live_state.json')), open(state_path, 'w'))
    E = load_engine(state_path)
    c = cost_bps / 10000.0
    cash = START_CASH
    out = []
    for day in days:
        FakeDatetime._now = _dt.datetime.strptime(day + ' 17:34', '%Y-%m-%d %H:%M').replace(tzinfo=_dt.timezone.utc)
        q = data['check_prices_1734utc'][day]
        hist = {'data': {'results': [
            {'symbol': s, 'bars': [{'begins_at': d + 'T00:00:00Z', 'close_price': str(px)}
                                   for d, px in sorted(data['daily_closes'][s].items()) if d < day]}
            for s in q]}}
        hp, qp = os.path.join(tmp, 'h.json'), os.path.join(tmp, 'q.json')
        json.dump(hist, open(hp, 'w')); json.dump(q, open(qp, 'w'))
        state = json.load(open(state_path))
        eq_pre = cash + sum(p['shares'] * q[s] for s, p in state['open_positions'].items())
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            E['cmd_plan'](hp, qp, cash, [])
        t = buf.getvalue(); plan = json.loads(t[t.index('{'):t.rindex('}') + 1])
        realized = 0.0
        for s in plan['sells']:
            cash += s['shares'] * s['price'] * (1 - c)
            realized += s['shares'] * (s['price'] * (1 - c) - s['entry'])
        for b in plan['buys']:
            cash -= b['shares'] * b['price'] * (1 + c)
        assert cash > -1.0, f'{day}: cash negative {cash}'
        ap = os.path.join(tmp, 'a.json')
        json.dump({'sells': [{k: s[k] for k in ('symbol', 'shares', 'price', 'reason')} for s in plan['sells']],
                   'buys': [{k: b[k] for k in ('symbol', 'shares', 'price', 'reason')} for b in plan['buys']],
                   'peak_updates': plan.get('peak_updates', {}), 'risk_state': plan['risk_state']}, open(ap, 'w'))
        with contextlib.redirect_stdout(io.StringIO()):
            E['cmd_commit'](ap)
        state = json.load(open(state_path))
        pos = {s: round(p['shares'], 6) for s, p in state['open_positions'].items()}
        eq_post = cash + sum(p['shares'] * q[s] for s, p in state['open_positions'].items())
        out.append({'date': day, 'equity_pre_run': round(eq_pre, 2), 'equity_post_run': round(eq_post, 2),
                    'cash_after': round(cash, 2), 'realized_vs_entry': round(realized, 2),
                    'circuit_breaker': plan['circuit_breaker_triggered'],
                    'sells': [{k: s[k] for k in ('symbol', 'shares', 'price', 'reason')} for s in plan['sells']],
                    'buys': [{k: b[k] for k in ('symbol', 'shares', 'price', 'reason')} for b in plan['buys']],
                    'positions_after': pos})
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--cost-bps', type=float, default=0.0)
    a = ap.parse_args()
    data = json.load(open(PRICES))
    with tempfile.TemporaryDirectory() as tmp:
        actual = run_path(['2026-10-12'], data, a.cost_bps, tmp)
    g = actual[0]
    want = {('INTC', 2.504016), ('MU', 0.184444), ('AMD', 0.016123)}
    got = {(s['symbol'], round(s['shares'], 6)) for s in g['sells'] if s['reason'] == 'STOP'}
    if got != want or g['buys'] or len(g['sells']) != 3:
        raise SystemExit(f'GATE FAILED: replay of the actual 10-12 run gave {g["sells"]} / {g["buys"]}')
    print('gate PASS: actual path reproduces the live 10-12 plan (INTC/MU/AMD STOP, no buys)\n')

    with tempfile.TemporaryDirectory() as tmp:
        cf = run_path(DAYS, data, a.cost_bps, tmp)

    for r in cf:
        print(f"{r['date']}  equity pre {r['equity_pre_run']:>10,.2f}  post {r['equity_post_run']:>10,.2f}"
              f"  cash {r['cash_after']:>10,.2f}  realized {r['realized_vs_entry']:>+8.2f}"
              f"{'  [circuit breaker]' if r['circuit_breaker'] else ''}")
        for s in r['sells']:
            print(f"      SELL {s['symbol']:5} {s['shares']:>11.6f} @ {s['price']:>10.4f}  {s['reason']}")
        for b in r['buys']:
            print(f"      BUY  {b['symbol']:5} {b['shares']:>11.6f} @ {b['price']:>10.4f}  {b['reason']}"
                  f"  (${b['shares'] * b['price']:,.2f})")
    a_end, c_end = g['equity_post_run'], cf[-1]['equity_post_run']
    a_pre = actual[0]['equity_pre_run']
    print(f"\nat the 10-12 17:34 UTC check, after that run's trades:")
    print(f"  actual (runs missed):      {a_end:>10,.2f}   (pre-run {a_pre:,.2f})")
    print(f"  counterfactual (all ran):  {c_end:>10,.2f}   still holding {cf[-1]['positions_after']}")
    print(f"  difference:                {c_end - a_end:>+10,.2f}  (cost {a.cost_bps:g} bps/side)")
    json.dump({'engine_rev': ENGINE_REV, 'cost_bps': a.cost_bps, 'start_cash': START_CASH,
               'gate_actual_1012_reproduced': True, 'actual': actual, 'counterfactual': cf,
               'actual_equity_after_1012': a_end, 'counterfactual_equity_after_1012': c_end,
               'difference': round(c_end - a_end, 2)}, open(OUT, 'w'), indent=1)
    print(f'wrote {OUT}')


if __name__ == '__main__':
    main()
