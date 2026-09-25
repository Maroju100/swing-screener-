#!/usr/bin/env python3
"""PAPER shadow of Margin-Style Live on a limited-margin, two-step routine.

PAPER ONLY. This script never places, reviews or cancels an order, and never
reads or writes docs/margin_style_live_state.json or docs/margin_style_live_log.json
except to READ the live log for the day's comparison figure.

WHAT IT SHADOWS
  The live system (cash account) sizes every buy off cash as it stood BEFORE the
  run's own sells, so a day's sale proceeds sit idle until the next business day.
  The two-step routine that limited margin would allow is: place sells, wait for
  fills, re-read buying power, then size buys -- i.e. today's proceeds fund
  today's buys. scripts/margin_style_instant_settlement.py measured this by replay
  (+159.2% vs +155.4% over 132 days, 2 of 5 checks, NOT an improvement); this
  shadow tracks it FORWARD on live quotes so the question can be revisited on
  data that did not exist when the replay was run.

HOW
  * Engine: production's own source, read from `origin/main` (never the working
    tree), with exactly one anchored patch -- patch_instant from
    margin_style_instant_settlement.py -- switched on. Everything else is
    byte-identical to what trades real money.
  * State: docs/margin_style_instant_shadow_state.json, a separate file. The
    engine's STATE_PATH is redirected to it in memory.
  * Cash: tracked here as `shadow_cash` (paper). Fills are the plan's own quote
    prices with COST_BPS per side charged (ESTIMATED friction; live fills differ
    slightly). Equity = shadow_cash + sum(shares * quote).
  * Quotes/bars: the SAME /tmp files the live run just used, so both are priced at
    the same instant. If they are not from today, the run refuses unless given
    fresh files explicitly -- a shadow priced at a different minute would compare
    check times, not settlement models.

COMMANDS
  init --from-rev REV --cash X     start from the live state at git REV with X cash
  run  HIST QUOTES [--force]       one daily shadow step (refuses a second run per day)
  status                           print shadow vs live
"""
import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import margin_style_instant_settlement as S  # noqa: E402

SHADOW_STATE = os.path.join(ROOT, 'docs', 'margin_style_instant_shadow_state.json')
SHADOW_LOG = os.path.join(ROOT, 'docs', 'margin_style_instant_shadow_log.json')
ENGINE_REV = 'origin/main'
ENGINE_FILE = 'scripts/margin_style_live_engine.py'
COST_BPS = 5.0
REAL_MONEY_FILES = ('margin_style_live_state.json', 'margin_style_live_log.json')


def git_show(rev, path):
    return subprocess.run(['git', 'show', f'{rev}:{path}'], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout


def load_engine():
    src = S.patch_instant(git_show(ENGINE_REV, ENGINE_FILE))
    ns = {'__name__': 'shadow_engine', '__file__': os.path.join(ROOT, ENGINE_FILE)}
    exec(compile(src, f'<{ENGINE_REV}:{ENGINE_FILE} + instant patch>', 'exec'), ns)
    ns['STATE_PATH'] = SHADOW_STATE
    ns['INSTANT_SETTLEMENT'] = True
    assert not any(ns['STATE_PATH'].endswith(f) for f in REAL_MONEY_FILES)
    return ns


def extract_json(text):
    start = text.index('{')
    return json.loads(text[start:text.rindex('}') + 1])


def today():
    return datetime.now(timezone.utc).date().isoformat()


def load_log():
    if os.path.exists(SHADOW_LOG):
        return json.load(open(SHADOW_LOG))
    return {'description': 'PAPER shadow: Margin-Style Live on limited margin with a sell-then-buy '
                           'two-step routine. Never real money. See scripts/margin_style_instant_shadow.py.',
            'runs': []}


def live_today():
    """Today's live run from the real-money log, read-only; None if not there yet."""
    subprocess.run(['git', 'fetch', '-q', 'origin', 'main'], cwd=ROOT, check=False)
    runs = json.loads(git_show('origin/main', 'docs/margin_style_live_log.json'))['runs']
    last = runs[-1]
    return last if last.get('timestamp', '')[:10] == today() else None


def cmd_init(rev, cash):
    if os.path.exists(SHADOW_STATE):
        sys.exit(f'{SHADOW_STATE} already exists; refusing to overwrite a running shadow.')
    state = json.loads(git_show(rev, 'docs/margin_style_live_state.json'))
    state['shadow_cash'] = round(cash, 2)
    state['shadow_started_from'] = {'rev': rev, 'cash': cash, 'at': datetime.now(timezone.utc).isoformat()}
    json.dump(state, open(SHADOW_STATE, 'w'), indent=1)
    log = load_log()
    log['runs'] = []
    json.dump(log, open(SHADOW_LOG, 'w'), indent=1)
    print(f'shadow initialised from live state @ {rev} with ${cash:,.2f} cash, '
          f'{len(state["open_positions"])} positions')


def fresh(path):
    return datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).date().isoformat() == today()


def cmd_run(hist, quotes_path, force=False):
    for p in (hist, quotes_path):
        if not fresh(p):
            sys.exit(f'{p} is not from today (UTC) -- refusing: the shadow must be priced at the '
                     f'live run\'s instant. Pass freshly fetched files explicitly if intended.')
    log = load_log()
    if log['runs'] and log['runs'][-1]['date'] == today() and not force:
        sys.exit(f'shadow already ran on {today()}; pass --force to redo.')

    E = load_engine()
    state = json.load(open(SHADOW_STATE))
    cash_before = state['shadow_cash']
    quotes = json.load(open(quotes_path))
    # Valued BEFORE this run's trades, at the same quotes -- the like-for-like
    # comparison with the live log's broker_total_value, which step 3 of the live
    # run reads before any order is placed.
    equity_pre = round(cash_before + sum(p['shares'] * quotes[s] for s, p in state['open_positions'].items()), 2)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        E['cmd_plan'](hist, quotes_path, cash_before, [])
    plan = extract_json(buf.getvalue())

    c = COST_BPS / 10000.0
    cash = cash_before
    realized = 0.0
    for s in plan['sells']:
        cash += s['shares'] * s['price'] * (1 - c)
        realized += s['shares'] * (s['price'] * (1 - c) - s['entry'] * (1 + c))
    for b in plan['buys']:
        cash -= b['shares'] * b['price'] * (1 + c)
    if cash < -1.0:
        sys.exit(f'shadow cash would go negative ({cash:,.2f}) -- patch/netting defect; nothing committed.')

    actions = {'sells': [{k: s[k] for k in ('symbol', 'shares', 'price', 'reason')} for s in plan['sells']],
               'buys': [{k: b[k] for k in ('symbol', 'shares', 'price', 'reason')} for b in plan['buys']],
               'peak_updates': plan.get('peak_updates', {}), 'risk_state': plan['risk_state']}
    apath = os.path.join(ROOT, 'docs', '.shadow_actions.json')
    json.dump(actions, open(apath, 'w'))
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            E['cmd_commit'](apath)
    finally:
        os.remove(apath)

    state = json.load(open(SHADOW_STATE))
    state['shadow_cash'] = round(cash, 2)
    json.dump(state, open(SHADOW_STATE, 'w'), indent=1)
    pos_val = sum(p['shares'] * quotes[s] for s, p in state['open_positions'].items())
    equity = round(cash + pos_val, 2)

    live = live_today()
    entry = {
        'date': today(), 'timestamp': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'engine': f'{ENGINE_REV} + patch_instant', 'cost_bps_estimated': COST_BPS,
        'cash_before': round(cash_before, 2),
        'same_run_proceeds_credited': round(sum(s['shares'] * s['price'] for s in plan['sells']), 2),
        'sells': plan['sells'], 'buys': plan['buys'],
        'realized_estimated': round(realized, 2), 'cash_after': round(cash, 2),
        'positions': {s: round(p['shares'], 6) for s, p in state['open_positions'].items()},
        'shadow_equity_pre_run': equity_pre, 'shadow_equity': equity,
        'live_broker_total_value_pre_run': live.get('broker_total_value') if live else None,
        'live_run_found': bool(live),
    }
    log['runs'].append(entry)
    json.dump(log, open(SHADOW_LOG, 'w'), indent=1)
    json.load(open(SHADOW_LOG))
    print(json.dumps({k: entry[k] for k in ('date', 'cash_before', 'same_run_proceeds_credited',
                                            'realized_estimated', 'cash_after', 'shadow_equity_pre_run',
                                            'live_broker_total_value_pre_run', 'shadow_equity')}, indent=1))
    for s in plan['sells']:
        print(f"  PAPER SELL {s['symbol']} {s['shares']} @ {s['price']} ({s['reason']})")
    for b in plan['buys']:
        print(f"  PAPER BUY  {b['symbol']} {b['shares']} @ {b['price']} ({b['reason']})")


def cmd_status():
    log = load_log()
    if not log['runs']:
        print('no shadow runs yet')
        return
    print('equity valued at the start of each day\'s run, before its trades')
    print(f"{'date':12}{'shadow (paper)':>16}{'live (broker)':>16}{'diff':>12}")
    for r in log['runs']:
        lv = r.get('live_broker_total_value_pre_run')
        d = f"{r['shadow_equity_pre_run'] - lv:+12,.2f}" if lv else f"{'n/a':>12}"
        print(f"{r['date']:12}{r['shadow_equity_pre_run']:>16,.2f}{(lv or 0):>16,.2f}{d}")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest='cmd', required=True)
    i = sp.add_parser('init'); i.add_argument('--from-rev', required=True); i.add_argument('--cash', type=float, required=True)
    r = sp.add_parser('run'); r.add_argument('hist'); r.add_argument('quotes'); r.add_argument('--force', action='store_true')
    sp.add_parser('status')
    a = ap.parse_args()
    if a.cmd == 'init':
        cmd_init(a.from_rev, a.cash)
    elif a.cmd == 'run':
        cmd_run(a.hist, a.quotes, a.force)
    else:
        cmd_status()
