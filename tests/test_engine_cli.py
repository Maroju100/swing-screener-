#!/usr/bin/env python3
"""CLI-path regression tests for scripts/margin_style_live_engine.py.

WHY THIS EXISTS
---------------
On 2026-09-22 the guardrail port (294328d) left TWO `if __name__ == '__main__':`
blocks in the engine. Both execute, so every CLI invocation ran its command
TWICE. `cmd_plan` is read-only, so that only duplicated its JSON on stdout - but
`cmd_commit` WRITES STATE, and double-applying it doubled every position and
every tranche count: a 2.524805-share buy landed in state as 5.04961 with
tranches=2. Tranche count drives sizing, so the damage compounds.

It was caught by running the daily procedure by hand rather than by any test.
The 6-month replay used to validate that port called `cmd_plan` AS A FUNCTION
and never went through the CLI, so it could not have seen this: the harness
imports the module and calls into it directly. **Validating the library path is
not validating the path production uses.** These tests exercise the CLI.

Run:  python3 tests/test_engine_cli.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(ROOT, 'scripts', 'margin_style_live_engine.py')

FLAT = {"pending_settlement": [], "open_positions": {}, "equity_peak": 17696.92,
        "kill_switch_active": False, "kill_switch_triggered_date": None,
        "trend_gate_active": False}


def sandbox():
    """A copy of the engine whose STATE_PATH points into a temp dir."""
    tmp = tempfile.mkdtemp()
    src = open(ENGINE).read()
    needle = "STATE_PATH = os.path.join(ROOT, 'docs', 'margin_style_live_state.json')"
    assert needle in src, 'STATE_PATH definition moved - update this test'
    src = src.replace(needle, f"STATE_PATH = {json.dumps(os.path.join(tmp, 'state.json'))}")
    eng = os.path.join(tmp, 'engine.py')
    open(eng, 'w').write(src)
    json.dump(FLAT, open(os.path.join(tmp, 'state.json'), 'w'))
    return tmp, eng


def run(eng, *args):
    return subprocess.run([sys.executable, eng, *args], capture_output=True, text=True)


def main():
    failures = []

    def check(cond, label):
        print(('PASS  ' if cond else 'FAIL  ') + label)
        if not cond:
            failures.append(label)

    # --- exactly one dispatch block in the source -----------------------------
    src = open(ENGINE).read()
    n = src.count("if __name__ == '__main__':")
    check(n == 1, f'engine has exactly ONE __main__ block (found {n})')

    tmp, eng = sandbox()
    try:
        # --- commit must apply its actions exactly once -----------------------
        actions = {"sells": [], "peak_updates": {}, "risk_state": FLAT,
                   "buys": [{"symbol": "SNDK", "shares": 2.524805,
                             "price": 1751.98, "reason": "NORMAL_DIP"}]}
        ap = os.path.join(tmp, 'actions.json')
        json.dump(actions, open(ap, 'w'))
        r = run(eng, 'commit', ap)
        st = json.load(open(os.path.join(tmp, 'state.json')))
        pos = st['open_positions'].get('SNDK', {})
        check(r.stdout.count('Committed') == 1,
              f"commit reports once (got {r.stdout.count('Committed')})")
        check(abs(pos.get('shares', 0) - 2.524805) < 1e-9,
              f"commit applies ONCE: shares={pos.get('shares')} (want 2.524805)")
        check(pos.get('tranches') == 1,
              f"tranche count not double-incremented: {pos.get('tranches')} (want 1)")

        # --- verify / reconcile run once and exit cleanly ---------------------
        r = run(eng, 'verify')
        check(r.stdout.count('PASSED - no logical errors') == 1 and r.returncode == 0,
              f'verify runs once, exit {r.returncode}')

        bp = os.path.join(tmp, 'broker.json')
        json.dump({"SNDK": {"quantity": 2.524805, "average_buy_price": 1751.98}},
                  open(bp, 'w'))
        r = run(eng, 'reconcile', bp)
        check(r.stdout.count('RECONCILIATION PASSED') == 1 and r.returncode == 0,
              f'reconcile runs once, exit {r.returncode}')

        # --- plan emits ONE parseable JSON document ---------------------------
        # A second document concatenated after the closing brace is unparseable,
        # and is how the run log was corrupted on 2026-09-21.
        hist = os.path.join(tmp, 'hist.json')
        quotes = os.path.join(tmp, 'quotes.json')
        bars = [{'begins_at': f'2026-0{6 + i // 30}-{1 + i % 28:02d}T00:00:00Z',
                 'close_price': str(1700 + i)} for i in range(70)]
        json.dump({'data': {'results': [{'symbol': 'SNDK', 'bars': bars}]}}, open(hist, 'w'))
        json.dump({'SNDK': 1751.98}, open(quotes, 'w'))
        r = run(eng, 'plan', hist, quotes, '17693.63', '[]', '{}')
        try:
            json.loads(r.stdout)
            parses = True
            why = ''
        except Exception as e:
            parses = False
            why = f' -- {e}'
        check(parses, 'plan stdout is ONE valid JSON document' + why)
        check(r.stdout.count('"real_cash"') == 1, 'plan prints its result once')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print(f'FAILED ({len(failures)}):')
        for f in failures:
            print('  -', f)
        return 1
    print('ALL CLI PATHS PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
