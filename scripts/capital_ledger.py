"""Shared capital allocation ledger for the 3 real-money live systems on Agentic 2 (912291820).

Robinhood has no sub-account/bucket feature - this is a software-only convention,
not a broker-level segregation of cash. Each system is capped to
ALLOCATIONS[system] dollars (docs/capital_allocations.json); "used" is computed
from each system's own bookkeeping so the three ledgers never double-count the
same dollar. A symbol can only be held by one live system at a time (existing
cross-system exclusion rule already enforced by daytrade_live_engine.py and
margin_style_live_engine.py), so ownership is unambiguous:

  - daytrade "used"      = mark-to-market of docs/daytrade_live_state.json's
                            open_positions, plus its own pending_settlement
                            (still "its" money, just not usable yet).
  - margin_style "used"  = same pattern from docs/margin_style_live_state.json.
  - swing "used"         = mark-to-market of every currently-held basket
                            position that is NOT claimed by daytrade's or
                            margin_style's state files. The swing system has no
                            separate state file of its own - it uses whatever
                            get_equity_positions shows that the other two don't
                            own.

Usage: python3 scripts/capital_ledger.py available <swing|daytrade|margin_style> <positions.json> <prices.json>
  positions.json: raw get_equity_positions response (or its "data" object, or a
                  bare list of position dicts with "symbol"/"quantity" keys)
  prices.json:    {"AMD": 555.0, "MU": 972.86, ...} - live quotes for all 5 symbols

Prints: {"system":.., "allocation":.., "used":.., "pending_settlement":.., "available":..}
"available" is what that system's position-sizing should treat as its cash
ceiling THIS run, in place of the whole account's real cash/buying power.
"""
import json, sys, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER_PATH = os.path.join(ROOT, 'docs', 'capital_allocations.json')
DAYTRADE_STATE = os.path.join(ROOT, 'docs', 'daytrade_live_state.json')
MARGIN_STATE = os.path.join(ROOT, 'docs', 'margin_style_live_state.json')
SYMBOLS = ["AMD", "MU", "WDC", "SNDK", "TSM"]


def load_json(path, default):
    if os.path.exists(path):
        return json.load(open(path))
    return default


def extract_positions(raw):
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        if 'positions' in raw:
            return raw['positions']
        if 'data' in raw and isinstance(raw['data'], dict) and 'positions' in raw['data']:
            return raw['data']['positions']
    raise SystemExit("Unrecognized positions.json shape")


def compute(system, positions_path, prices_path):
    ledger = load_json(LEDGER_PATH, {'allocations': {}})
    allocation = ledger['allocations'].get(system)
    if allocation is None:
        raise SystemExit(f"Unknown system: {system} (expected swing|daytrade|margin_style)")

    raw_positions = json.load(open(positions_path))
    positions = extract_positions(raw_positions)
    prices = json.load(open(prices_path))

    real_qty = {}
    for p in positions:
        sym = p.get('symbol')
        if sym in SYMBOLS:
            real_qty[sym] = float(p['quantity'])

    daytrade_state = load_json(DAYTRADE_STATE, {'open_positions': {}, 'pending_settlement': []})
    margin_state = load_json(MARGIN_STATE, {'open_positions': {}, 'pending_settlement': []})
    daytrade_syms = set(daytrade_state.get('open_positions', {}).keys())
    margin_syms = set(margin_state.get('open_positions', {}).keys())

    if system == 'daytrade':
        used = sum(pos['shares'] * prices.get(sym, 0) for sym, pos in daytrade_state.get('open_positions', {}).items())
        pending = sum(p['amount'] for p in daytrade_state.get('pending_settlement', []))
    elif system == 'margin_style':
        used = sum(pos['shares'] * prices.get(sym, 0) for sym, pos in margin_state.get('open_positions', {}).items())
        pending = sum(p['amount'] for p in margin_state.get('pending_settlement', []))
    elif system == 'swing':
        swing_syms = [s for s in SYMBOLS if s in real_qty and s not in daytrade_syms and s not in margin_syms]
        used = sum(real_qty[s] * prices.get(s, 0) for s in swing_syms)
        pending = 0.0  # swing system has no settlement-tracking ledger of its own
    else:
        raise SystemExit(f"Unknown system: {system}")

    available = max(0.0, allocation - used - pending)
    print(json.dumps({'system': system, 'allocation': allocation, 'used': round(used, 2),
                      'pending_settlement': round(pending, 2), 'available': round(available, 2)}, indent=1))


if __name__ == '__main__':
    if len(sys.argv) != 5 or sys.argv[1] != 'available':
        print("Usage: python3 capital_ledger.py available <swing|daytrade|margin_style> <positions.json> <prices.json>")
        sys.exit(1)
    compute(sys.argv[2], sys.argv[3], sys.argv[4])
