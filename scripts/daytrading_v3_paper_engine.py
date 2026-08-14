"""Incremental paper-trading engine for "Opening Momentum Scale-In v3 (tightened)".

Usage: python3 scripts/daytrading_v3_paper_engine.py <fresh_1min_historicals.json>

Reads/writes docs/daytrading_v3_paper_state.json (open paper position + cash) and
appends to docs/daytrading_v3_paper_log.json (trade-by-trade + per-run equity
snapshot). Places NO real orders - this only maintains simulated positions in JSON.

RULES (long-only, one position per symbol, WDC/MU/SNDK, $5,000 total / ~$1,667 per
symbol slice, up to 3 roughly-equal tranches per entry cycle):
  ENTRY: price > VWAP (day-anchored), RSI(14) crosses UP through 55, MACD(12,26,9)
    histogram > 0. Max 2 entry cycles/day (initial + 1 re-entry after a trim).
  ADD: already holding, < 3 tranches so far, price >= the last tranche's own price
    * 1.006 (0.6% gate - forces real spacing instead of firing on every tick), RSI(14)
    >= 55, at least a 2-minute cooldown since the last action on this symbol.
  EXHAUSTION TRIM: only once RSI(14) has reached >=65 at some point since entry -
    then RSI crosses back below 60, OR MACD histogram flips negative -> sell 90% of
    the position immediately (fast reaction, no multi-bar confirmation).
  EOD CLOSE: any position still open at/after 2:30pm CDT (19:30 UTC) is force-closed,
    and the day's entry-cycle counter resets for the next session.

VALIDATION HISTORY (see conversation record, 2026-08-13): derived from the real
Margin account's (410961445, read-only) actual order history for WDC/MU/SNDK that
day, tightened via a parameter search (entry threshold, add-gate, cooldown, tranche
cap, re-entry cap) to cut a much noisier first draft down near the real account's own
~27-trade-per-day frequency, then validated on TWO out-of-sample windows with the
derivation day excluded: +5.81% over the prior ~4 weeks (1-minute bars, 3/3 sub-
windows profitable) and +6.30% over 6 months (30-minute-bar adaptation, 2/3 sub-
windows profitable) - the only one of several candidate setups built that day to
survive removing the day it was built from. A separate, more aggressive variant
("v4") was later re-optimized directly on that one day specifically to chase closer
to the real account's $2,441.89 same-day profit; it was REJECTED after it LOST money
out-of-sample (-0.53% over the same 4 weeks, only 1/3 windows) - a clean demonstration
of overfitting a single day. This engine implements the SURVIVING (tightened, not
further re-optimized) rule set - do not swap in v4's looser exhaustion threshold
(RSI>=70) or bigger trim (65% vs 90%) without re-running that same out-of-sample check.

Compared against the real-money Margin-Style Live system on the same real 2-week
window (2026-07-30 to 2026-08-13), Margin-Style Live returned +15.38% vs this
setup's +6.79% (backtested) - this is a SEPARATE, SMALLER, COMPLEMENTARY sleeve,
not a replacement. It exists to capture same-day intraday moves (like 2026-08-13's
WDC/SNDK/MU rally) that a once-daily system structurally cannot react to - not to
out-return the primary system.

HARD RULE: this is a paper tracker. Never call review_equity_order or
place_equity_order for anything this script does.
"""
import json, sys, os
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, 'docs', 'daytrading_v3_paper_state.json')
LOG_PATH = os.path.join(ROOT, 'docs', 'daytrading_v3_paper_log.json')
SYMBOLS = ["WDC", "MU", "SNDK"]
CAPITAL = 5000.0
PER_SYMBOL_SLICE = CAPITAL / len(SYMBOLS)
ENTRY_RSI = 55
MAX_TRANCHES = 3
TRANCHE_SIZE = PER_SYMBOL_SLICE / MAX_TRANCHES
ADD_GAIN = 0.006
COOLDOWN_MIN = 2
MAX_ENTRY_CYCLES = 2
EXHAUSTION_PEAK_RSI = 65
TRIM_PCT = 0.90
EOD_HHMM = "19:30"  # 2:30pm CDT cutoff, UTC HH:MM


def rsi_series(closes, period=14):
    out = [None] * len(closes)
    avg_gain = avg_loss = None
    gains, losses = [], []
    for i in range(1, len(closes)):
        chg = closes[i] - closes[i-1]
        gains.append(max(chg, 0))
        losses.append(max(-chg, 0))
        if i >= period:
            if i == period:
                avg_gain = sum(gains[:period]) / period
                avg_loss = sum(losses[:period]) / period
            else:
                avg_gain = (avg_gain * (period - 1) + gains[-1]) / period
                avg_loss = (avg_loss * (period - 1) + losses[-1]) / period
            rs = avg_gain / avg_loss if avg_loss > 0 else float('inf')
            out[i] = 100 - (100 / (1 + rs)) if avg_loss > 0 else 100.0
    return out

def ema_series(vals, period):
    out = [None] * len(vals)
    k = 2 / (period + 1)
    e = None
    for i, v in enumerate(vals):
        if v is None:
            continue
        e = v if e is None else v * k + e * (1 - k)
        out[i] = e
    return out

def macd_hist(closes, fast=12, slow=26, signal=9):
    ef, es = ema_series(closes, fast), ema_series(closes, slow)
    macd_line = [None if (a is None or b is None) else a - b for a, b in zip(ef, es)]
    sig = ema_series(macd_line, signal)
    return [None if (m is None or s is None) else m - s for m, s in zip(macd_line, sig)]

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

def build_indicators(raw_path):
    d = json.load(open(raw_path))
    bars_by_sym, dates_by_sym, ind = {}, {}, {}
    for r in d['data']['results']:
        sym = r['symbol']
        if sym not in SYMBOLS:
            continue
        bars = [{'dt': b['begins_at'], 'date': b['begins_at'][:10], 'open': float(b['open_price']),
                  'close': float(b['close_price']), 'high': float(b['high_price']),
                  'low': float(b['low_price']), 'volume': float(b.get('volume', 0) or 0)}
                 for b in r['bars']]
        dates = [b['date'] for b in bars]
        bars_by_sym[sym] = bars
        dates_by_sym[sym] = dates
        closes = [b['close'] for b in bars]
        ind[sym] = {'rsi': rsi_series(closes), 'hist': macd_hist(closes),
                     'vwap': day_anchored_vwap(bars, dates)}
    return bars_by_sym, dates_by_sym, ind

def load_state():
    if os.path.exists(STATE_PATH):
        return json.load(open(STATE_PATH))
    return {'cash': CAPITAL, 'positions': {}, 'last_processed_dt': {}}

def load_log():
    if os.path.exists(LOG_PATH):
        return json.load(open(LOG_PATH))
    return {'capital': CAPITAL, 'symbols': SYMBOLS, 'setup': 'Opening Momentum Scale-In v3 (tightened)',
            'note': 'PAPER TRADING ONLY - no real orders placed.', 'runs': []}

def run(raw_path):
    bars_by_sym, dates_by_sym, ind = build_indicators(raw_path)
    state = load_state()
    log = load_log()
    run_trades = []
    now = datetime.now(timezone.utc).isoformat()

    cash = state['cash']
    positions = state['positions']
    last_processed = state['last_processed_dt']

    for sym in SYMBOLS:
        if sym not in bars_by_sym:
            continue
        bars = bars_by_sym[sym]
        dates = dates_by_sym[sym]
        r, h, vw = ind[sym]['rsi'], ind[sym]['hist'], ind[sym]['vwap']

        last_dt = last_processed.get(sym)
        if last_dt is None:
            start_gi = max(0, len(bars) - 2)  # first run: only evaluate the newest bar, don't backfill history
        else:
            start_gi = next((i for i, b in enumerate(bars) if b['dt'] > last_dt), len(bars))

        pos = positions.get(sym)

        for gi in range(max(start_gi, 1), len(bars)):
            bar = bars[gi]
            price = bar['close']
            hhmm = bar['dt'][11:16]
            is_eod = hhmm >= EOD_HHMM

            if pos:
                pos['since_entry_high'] = max(pos['since_entry_high'], price)
                if r[gi] is not None:
                    pos['entry_peak_rsi'] = max(pos['entry_peak_rsi'], r[gi])

                last_action_dt = pos.get('last_action_dt')
                cooling = last_action_dt is not None and (
                    datetime.fromisoformat(bar['dt'].replace('Z', '+00:00')) -
                    datetime.fromisoformat(last_action_dt.replace('Z', '+00:00'))
                ) < timedelta(minutes=COOLDOWN_MIN)

                exhaustion = None
                if not cooling and pos['entry_peak_rsi'] >= EXHAUSTION_PEAK_RSI:
                    if r[gi] is not None and r[gi-1] is not None and r[gi-1] >= 60 and r[gi] < 60:
                        exhaustion = 'RSI-ROLLOVER'
                    elif h[gi] is not None and h[gi-1] is not None and h[gi-1] >= 0 and h[gi] < 0:
                        exhaustion = 'MACD-FLIP'

                if is_eod:
                    proceeds = pos['shares'] * price
                    pnl = proceeds - pos['cost']
                    cash += proceeds
                    run_trades.append({'symbol': sym, 'date': bar['date'], 'side': 'SELL', 'reason': 'EOD-CLOSE',
                                        'shares': round(pos['shares'], 6), 'price': round(price, 4), 'pnl': round(pnl, 2)})
                    pos = None
                    positions.pop(sym, None)
                    last_processed[sym] = bar['dt']
                    continue

                if exhaustion:
                    sell_shares = pos['shares'] * TRIM_PCT
                    avg_cost = pos['cost'] / pos['shares']
                    proceeds = sell_shares * price
                    pnl = proceeds - sell_shares * avg_cost
                    pos['shares'] -= sell_shares
                    pos['cost'] -= sell_shares * avg_cost
                    cash += proceeds
                    run_trades.append({'symbol': sym, 'date': bar['date'], 'side': 'SELL', 'reason': exhaustion,
                                        'shares': round(sell_shares, 6), 'price': round(price, 4), 'pnl': round(pnl, 2)})
                    pos.update({'tranches': 0, 'entry_peak_rsi': r[gi] if r[gi] is not None else 0.0,
                                'since_entry_high': price, 'last_tranche_price': price, 'last_action_dt': bar['dt']})
                    last_processed[sym] = bar['dt']
                    continue

                if cooling:
                    last_processed[sym] = bar['dt']
                    continue

                add_ok = (pos['tranches'] < MAX_TRANCHES and pos['last_tranche_price'] is not None
                          and price >= pos['last_tranche_price'] * (1 + ADD_GAIN)
                          and r[gi] is not None and r[gi] >= 55)
                if add_ok:
                    notional = TRANCHE_SIZE
                    if notional <= cash:
                        sh = notional / price
                        pos['shares'] += sh
                        pos['cost'] += notional
                        pos['tranches'] += 1
                        pos['last_tranche_price'] = price
                        pos['last_action_dt'] = bar['dt']
                        cash -= notional
                        run_trades.append({'symbol': sym, 'date': bar['date'], 'side': 'BUY', 'reason': 'ADD',
                                            'shares': round(sh, 6), 'price': round(price, 4)})
                last_processed[sym] = bar['dt']
                continue

            if is_eod:
                last_processed[sym] = bar['dt']
                continue

            entry_cycles_today = state.setdefault('entry_cycles', {}).setdefault(sym, {}).get(bar['date'], 0)
            if entry_cycles_today >= MAX_ENTRY_CYCLES:
                last_processed[sym] = bar['dt']
                continue

            entry_ok = (vw[gi] is not None and price > vw[gi]
                        and r[gi] is not None and r[gi-1] is not None and r[gi-1] < ENTRY_RSI <= r[gi]
                        and h[gi] is not None and h[gi] > 0)
            if entry_ok:
                notional = TRANCHE_SIZE
                if notional <= cash:
                    sh = notional / price
                    pos = {'shares': sh, 'cost': notional, 'tranches': 1, 'entry_peak_rsi': r[gi],
                           'since_entry_high': price, 'last_tranche_price': price, 'last_action_dt': bar['dt']}
                    positions[sym] = pos
                    cash -= notional
                    state['entry_cycles'][sym][bar['date']] = entry_cycles_today + 1
                    run_trades.append({'symbol': sym, 'date': bar['date'], 'side': 'BUY', 'reason': 'ENTRY',
                                        'shares': round(sh, 6), 'price': round(price, 4)})
            last_processed[sym] = bar['dt']

    state['cash'] = cash
    state['positions'] = positions
    state['last_processed_dt'] = last_processed

    equity = cash + sum(p['shares'] * bars_by_sym[s][-1]['close'] for s, p in positions.items() if s in bars_by_sym)
    log['runs'].append({'timestamp': now, 'trades': run_trades, 'equity_snapshot': round(equity, 2)})

    json.dump(state, open(STATE_PATH, 'w'), indent=1)
    json.dump(log, open(LOG_PATH, 'w'), indent=1)

    print(f"v3 paper-trading run {now}: {len(run_trades)} new trade event(s)")
    for t in run_trades:
        print(" ", t)
    total_pnl = equity - CAPITAL
    print(f"\nEquity: ${equity:,.2f}  Net P&L: ${total_pnl:+,.2f} ({100*total_pnl/CAPITAL:+.2f}%)")
    return run_trades, equity


if __name__ == '__main__':
    run(sys.argv[1])
