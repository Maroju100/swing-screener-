"""Incremental paper-trading engine for "Trend-Gated Trail (TGT)".

Usage: python3 scripts/trend_gated_trail_paper_engine.py <fresh_1min_historicals.json>

Reads/writes docs/trend_gated_trail_paper_state.json (open paper position + cash)
and appends to docs/trend_gated_trail_paper_log.json (trade-by-trade + per-run
equity snapshot). Places NO real orders - this only maintains simulated
positions in JSON, same convention as scripts/daytrading_v3_paper_engine.py.

RULES (long-only, one position per symbol, SNDK/WDC/MU/TSM, $5,000 total split
evenly across the 4 symbols):
  MORNING GATE (once per symbol per day, checked as soon as GATE_WINDOW_MIN
    minutes of bars exist since that day's open): compute the Signed Efficiency
    Ratio over those first GATE_WINDOW_MIN minutes -
      signed_ER = (last_close - first_close) / sum(|bar-to-bar close changes|)
    - the SIGNED net move (not absolute value) divided by the total path length.
    If signed_ER >= GATE_THRESHOLD (0.0 - i.e. the morning is net UP, however
    choppy), the day is "open" for entry; otherwise skip the symbol entirely
    for the rest of that day. This is deliberately signed, not absolute: an
    earlier unsigned "Efficiency Ratio" gate (>=0.18, used elsewhere in this
    project for a basket-level day-trading gauge) was tested here and found to
    only weakly relate to trade outcome (42% correct predicting up-vs-down
    days, worse than a coin flip) precisely because it can't tell a cleanly
    UP morning from a cleanly DOWN one. Signing it fixes exactly that.
  ENTRY: once the gate passes, buy immediately at the current price with the
    symbol's full capital slice (one entry per day - no scale-in tranches).
  TRAILING STOP: sell the entire position if price falls TRAIL_PCT (3%) below
    the highest price seen since entry (or since the last re-entry).
  RE-ENTRY: after a trailing-stop exit, wait until price closes back above
    the day-anchored VWAP, then re-buy the full capital slice at that price.
    No re-check of the morning gate - once a day is "open", it stays open;
    only the VWAP-reclaim condition gates re-entry.
  EOD CLOSE: any position still open at/after 19:55 UTC (near the actual
    ~20:00 UTC session close - deliberately later than v3's 19:30 cutoff,
    since this setup is meant to hold through the full session, not scalp
    intraday bursts) is force-closed.

VALIDATION HISTORY - CORRECTED 2026-09-05, NOT VALIDATED: motivated by a
real, documented flaw in an existing basket-level Efficiency Ratio gauge
(unsigned - can't distinguish up-trending from down-trending mornings), but
the original "12/12 split-half checks favored the gate" claim (and the
"MU beats even buy-and-hold" / "WDC flips a loss into a gain" framing) was
WRONG. It came from a backtest script that entered gated trades at the
day's OPENING price - a look-ahead error, since the gate itself can't be
confirmed until GATE_WINDOW_MIN minutes after the open, by which point the
achievable entry price has already moved. Re-run with the actual,
achievable entry price (this script's real mechanic: buy at the close of
the bar where the gate first confirms, not the day's open), the same
12 checks come out 5/12 in the gate's favor - worse than a coin flip. A
follow-up grid search over window/trail/threshold, trained ONLY on SNDK's
Jul6-Aug3 window and evaluated out-of-sample on the rest, didn't do better
either (6/10) - and the win/loss pattern was 100% explained by which half
of the calendar each check fell in (every symbol's 1st half won, almost
every 2nd half lost), meaning it's tracking shared cross-symbol market
regime timing, not a genuine per-day directional signal.
CONCLUSION: no validated edge has been found for this gate, at the
original threshold or any of the searched variants. This script is kept
running for live paper observation only, not as a proven strategy - do not
describe its output as validated performance.

HARD RULE: this is a paper tracker. Never call review_equity_order or
place_equity_order for anything this script does.
"""
import json, sys, os
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, 'docs', 'trend_gated_trail_paper_state.json')
LOG_PATH = os.path.join(ROOT, 'docs', 'trend_gated_trail_paper_log.json')
SYMBOLS = ["SNDK", "WDC", "MU", "TSM"]
CAPITAL = 5000.0
PER_SYMBOL_SLICE = CAPITAL / len(SYMBOLS)
TRAIL_PCT = 0.03
GATE_WINDOW_MIN = 30
GATE_THRESHOLD = 0.0
EOD_HHMM = "19:55"


def day_anchored_vwap(bars, dates):
    out = [None] * len(bars)
    cum_pv = cum_v = 0.0
    cur_date = None
    for i, b in enumerate(bars):
        if dates[i] != cur_date:
            cur_date = dates[i]
            cum_pv = cum_v = 0.0
        tp = (b['high'] + b['low'] + b['close']) / 3.0
        cum_pv += tp * b['volume']
        cum_v += b['volume']
        out[i] = cum_pv / cum_v if cum_v > 0 else None
    return out


def signed_efficiency_ratio(day_closes):
    if len(day_closes) < 2:
        return None
    net = day_closes[-1] - day_closes[0]
    path = sum(abs(day_closes[i] - day_closes[i - 1]) for i in range(1, len(day_closes)))
    return net / path if path > 0 else 0.0


def build_bars(raw_path):
    d = json.load(open(raw_path))
    bars_by_sym, dates_by_sym, vwap_by_sym = {}, {}, {}
    for r in d['data']['results']:
        sym = r['symbol']
        if sym not in SYMBOLS:
            continue
        bars = [{'dt': b['begins_at'], 'date': b['begins_at'][:10], 'open': float(b['open_price']),
                  'close': float(b['close_price']), 'high': float(b['high_price']),
                  'low': float(b['low_price']), 'volume': float(b.get('volume', 0) or 0)}
                 for b in r['bars'] if not b.get('interpolated')]
        dates = [b['date'] for b in bars]
        bars_by_sym[sym] = bars
        dates_by_sym[sym] = dates
        vwap_by_sym[sym] = day_anchored_vwap(bars, dates)
    return bars_by_sym, dates_by_sym, vwap_by_sym


def load_state():
    if os.path.exists(STATE_PATH):
        return json.load(open(STATE_PATH))
    return {'cash': CAPITAL, 'positions': {}, 'last_processed_dt': {},
            'gate_result': {}}  # gate_result[sym][date] = True/False, decided once


def load_log():
    if os.path.exists(LOG_PATH):
        return json.load(open(LOG_PATH))
    return {'capital': CAPITAL, 'symbols': SYMBOLS, 'setup': 'Trend-Gated Trail (TGT)',
            'note': 'PAPER TRADING ONLY - no real orders placed.', 'runs': []}


def run(raw_path):
    bars_by_sym, dates_by_sym, vwap_by_sym = build_bars(raw_path)
    state = load_state()
    log = load_log()
    run_trades = []
    now = datetime.now(timezone.utc).isoformat()

    cash = state['cash']
    positions = state['positions']
    last_processed = state['last_processed_dt']
    gate_result = state.setdefault('gate_result', {})

    for sym in SYMBOLS:
        if sym not in bars_by_sym:
            continue
        bars = bars_by_sym[sym]
        dates = dates_by_sym[sym]
        vw = vwap_by_sym[sym]
        sym_gates = gate_result.setdefault(sym, {})

        last_dt = last_processed.get(sym)
        if last_dt is None:
            start_gi = max(0, len(bars) - 2)
        else:
            start_gi = next((i for i, b in enumerate(bars) if b['dt'] > last_dt), len(bars))

        pos = positions.get(sym)

        for gi in range(max(start_gi, 0), len(bars)):
            bar = bars[gi]
            price = bar['close']
            date = bar['date']
            hhmm = bar['dt'][11:16]
            is_eod = hhmm >= EOD_HHMM

            if pos:
                pos['since_entry_high'] = max(pos['since_entry_high'], price)

                if is_eod:
                    proceeds = pos['shares'] * price
                    pnl = proceeds - pos['cost']
                    cash += proceeds
                    run_trades.append({'symbol': sym, 'date': date, 'side': 'SELL', 'reason': 'EOD-CLOSE',
                                        'shares': round(pos['shares'], 6), 'price': round(price, 4), 'pnl': round(pnl, 2)})
                    pos = None
                    positions.pop(sym, None)
                    last_processed[sym] = bar['dt']
                    continue

                stop_level = pos['since_entry_high'] * (1 - TRAIL_PCT)
                if bar['low'] <= stop_level:
                    exit_price = stop_level
                    proceeds = pos['shares'] * exit_price
                    pnl = proceeds - pos['cost']
                    cash += proceeds
                    run_trades.append({'symbol': sym, 'date': date, 'side': 'SELL', 'reason': 'TRAIL-STOP',
                                        'shares': round(pos['shares'], 6), 'price': round(exit_price, 4), 'pnl': round(pnl, 2)})
                    positions.pop(sym, None)
                    pos = None
                    # waiting for VWAP reclaim - set immediately so a re-entry can
                    # fire on a later bar within this same processing batch
                    state.setdefault('stopped_today', {})[sym] = date
                    last_processed[sym] = bar['dt']
                    continue

                last_processed[sym] = bar['dt']
                continue

            if is_eod:
                last_processed[sym] = bar['dt']
                continue

            # Determine the morning gate for this date, once, as soon as enough
            # bars exist since that day's open.
            if date not in sym_gates:
                day_start_gi = next(k for k in range(gi, -1, -1) if k == 0 or dates[k - 1] != date)
                elapsed = gi - day_start_gi + 1
                if elapsed < GATE_WINDOW_MIN:
                    last_processed[sym] = bar['dt']
                    continue
                window_closes = [bars[k]['close'] for k in range(day_start_gi, day_start_gi + GATE_WINDOW_MIN)]
                ser = signed_efficiency_ratio(window_closes)
                sym_gates[date] = ser is not None and ser >= GATE_THRESHOLD
                if not sym_gates[date]:
                    last_processed[sym] = bar['dt']
                    continue
                # gate just passed on this bar - fall through to entry/re-entry check below

            if not sym_gates.get(date, False):
                last_processed[sym] = bar['dt']
                continue

            # Gate is open for today. Enter now if this is the first opportunity
            # today, or re-enter on a VWAP reclaim after a same-day trailing stop.
            entered_today = state.setdefault('entered_today', {}).get(sym) == date
            stopped_today = state.setdefault('stopped_today', {}).get(sym) == date

            if not entered_today:
                notional = PER_SYMBOL_SLICE
                if notional <= cash:
                    sh = notional / price
                    pos = {'shares': sh, 'cost': notional, 'since_entry_high': price}
                    positions[sym] = pos
                    cash -= notional
                    state['entered_today'][sym] = date
                    run_trades.append({'symbol': sym, 'date': date, 'side': 'BUY', 'reason': 'GATE-ENTRY',
                                        'shares': round(sh, 6), 'price': round(price, 4)})
            elif stopped_today and vw[gi] is not None and price > vw[gi]:
                notional = PER_SYMBOL_SLICE
                if notional <= cash:
                    sh = notional / price
                    pos = {'shares': sh, 'cost': notional, 'since_entry_high': price}
                    positions[sym] = pos
                    cash -= notional
                    state['stopped_today'][sym] = None
                    run_trades.append({'symbol': sym, 'date': date, 'side': 'BUY', 'reason': 'VWAP-RECLAIM',
                                        'shares': round(sh, 6), 'price': round(price, 4)})
            last_processed[sym] = bar['dt']

    state['cash'] = cash
    state['positions'] = positions
    state['last_processed_dt'] = last_processed
    state['gate_result'] = gate_result

    equity = cash + sum(p['shares'] * bars_by_sym[s][-1]['close'] for s, p in positions.items() if s in bars_by_sym)
    log['runs'].append({'timestamp': now, 'trades': run_trades, 'equity_snapshot': round(equity, 2)})

    json.dump(state, open(STATE_PATH, 'w'), indent=1)
    json.dump(log, open(LOG_PATH, 'w'), indent=1)

    print(f"TGT paper-trading run {now}: {len(run_trades)} new trade event(s)")
    for t in run_trades:
        print(" ", t)
    total_pnl = equity - CAPITAL
    print(f"\nEquity: ${equity:,.2f}  Net P&L: ${total_pnl:+,.2f} ({100*total_pnl/CAPITAL:+.2f}%)")
    return run_trades, equity


if __name__ == '__main__':
    run(sys.argv[1])
