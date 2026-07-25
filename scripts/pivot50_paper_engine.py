"""Incremental paper-trading engine for Pivot Point S1 Bounce on the TOP-50 S&P
large-cap universe (PAPER ONLY - places no real orders, ever).

Why this exists (2026-07-25): after the rigorous-validation session, Pivot Point
S1 Bounce emerged as the stable's best generalizer - the only strategy that
stayed meaningfully profitable when moved to universes it was never tuned for
(+$30,771 on the 5-semi basket, +$6,701 on the top-50 S&P, 6-quarter honest
harness) and it survived the 2025->2026 train/test split (+$18,281 OOS). This
tracker builds a live paper record of the top-50 variant so it can be compared
against the basket-5 variant already covered by swing_paper_engine.py, and
against its own backtest, before any real-money decision.

NVDA note: NVDA is in this paper universe for research completeness. It remains
PROHIBITED for real trading in this account per standing rules - this engine
never places orders, so no conflict, but never graduate NVDA entries to live.

Mechanics (identical math to swing_paper_engine.sig_pivot_point_bounce and the
validated universe-comparison harness):
  - yesterday's pivot P=(H+L+C)/3, S1=2P-yesterday's high
  - entry when yesterday's or today's low touched S1*1.01, today's close back
    above S1 and above yesterday's close, and close > P (trend filter)
  - stop = entry - 1.5*ATR14 (honest fill: min(stop, close) when low breaches),
    target = entry + 3.0*ATR14 (only after 2-day minimum hold)
  - $25,000 isolated capital, max 5 concurrent positions, position size = TV/5

Usage: python3 scripts/pivot50_paper_engine.py <fresh_daily_historicals.json>
State: docs/pivot50_paper_state.json   Log: docs/pivot50_paper_log.json
Idempotent/incremental via last_processed_date per symbol.
"""
import json, math, sys, os
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, 'docs', 'pivot50_paper_state.json')
LOG_PATH = os.path.join(ROOT, 'docs', 'pivot50_paper_log.json')

SYMBOLS = ["NVDA", "MSFT", "AAPL", "GOOGL", "AMZN", "META", "AVGO", "TSLA", "LLY", "JPM",
           "WMT", "V", "XOM", "UNH", "MA", "ORCL", "COST", "HD", "PG", "JNJ",
           "NFLX", "BAC", "ABBV", "CRM", "CVX", "KO", "AMD", "MRK", "PEP", "TMO",
           "ADBE", "WFC", "CSCO", "LIN", "ACN", "MCD", "IBM", "GE", "ABT", "DHR",
           "AXP", "QCOM", "CAT", "TXN", "PM", "INTU", "DIS", "VZ", "AMAT", "GS"]
CAPITAL = 25000.0
MAXP = 5
MIN_HOLD_FOR_TARGET = 2
WARMUP = 30


def atr_series(bars, period=14):
    trs = [bars[0]['high'] - bars[0]['low']]
    for i in range(1, len(bars)):
        tr = max(bars[i]['high'] - bars[i]['low'],
                  abs(bars[i]['high'] - bars[i-1]['close']),
                  abs(bars[i]['low'] - bars[i-1]['close']))
        trs.append(tr)
    out = [None] * len(bars)
    if len(trs) < period:
        return out
    atr = sum(trs[:period]) / period
    out[period-1] = atr
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
        out[i] = atr
    return out


def sig_pivot_point_bounce(bars, atr, gi):
    if gi < WARMUP or atr[gi] is None:
        return None
    y = bars[gi-1]
    P = (y['high'] + y['low'] + y['close']) / 3
    S1 = (P * 2) - y['high']
    touched = y['low'] <= S1 * 1.01 or bars[gi]['low'] <= S1 * 1.01
    bounced = bars[gi]['close'] > S1 and bars[gi]['close'] > y['close']
    trend_ok = bars[gi]['close'] > P
    if touched and bounced and trend_ok:
        return (atr[gi] * 1.5, atr[gi] * 3.0)
    return None


def load_bars(raw_path):
    d = json.load(open(raw_path))
    bars_by_sym = {}
    for r in d['data']['results']:
        bars_by_sym[r['symbol']] = [{
            'date': b['begins_at'][:10],
            'open': float(b['open_price']), 'close': float(b['close_price']),
            'high': float(b['high_price']), 'low': float(b['low_price']),
            'volume': float(b.get('volume', 0) or 0),
        } for b in r['bars']]
    return bars_by_sym


def run(raw_path):
    bars_by_sym = load_bars(raw_path)
    atr_by_sym = {s: atr_series(bars_by_sym[s]) for s in bars_by_sym}

    if os.path.exists(STATE_PATH):
        state = json.load(open(STATE_PATH))
    else:
        state = {'cash': CAPITAL, 'positions': {}, 'last_processed_date': {}}
    if os.path.exists(LOG_PATH):
        log = json.load(open(LOG_PATH))
    else:
        log = {'strategy': 'Pivot Point S1 Bounce (Top-50 S&P universe)',
               'capital': CAPITAL, 'symbols': SYMBOLS,
               'note': 'PAPER TRADING ONLY - no real orders placed, ever. NVDA paper-only, prohibited live.',
               'runs': []}

    cash = state['cash']
    positions = state['positions']
    last_processed = state['last_processed_date']
    run_trades = []
    now = datetime.now(timezone.utc).isoformat()

    # chronological event walk across all symbols, only unprocessed bars
    events = []
    for sym in SYMBOLS:
        if sym not in bars_by_sym:
            continue
        bars = bars_by_sym[sym]
        last_dt = last_processed.get(sym)
        if last_dt is None:
            start_gi = max(WARMUP, len(bars) - 2)
        else:
            start_gi = next((i for i, b in enumerate(bars) if b['date'] > last_dt), len(bars))
        for gi in range(start_gi, len(bars)):
            events.append((bars[gi]['date'], sym, gi))
    events.sort()

    for date, sym, gi in events:
        bars = bars_by_sym[sym]
        bar = bars[gi]

        if sym in positions:
            pos = positions[sym]
            held = gi - next((i for i, b in enumerate(bars) if b['date'] == pos['entry_date']), gi)
            exit_reason = None
            if bar['low'] <= pos['stop']:
                exit_reason = 'STOP'
                exit_price = min(pos['stop'], bar['close'])  # honest: no better than the close if it gapped
            elif held >= MIN_HOLD_FOR_TARGET and bar['high'] >= pos['target']:
                exit_reason = 'TARGET'
                exit_price = pos['target']
            if exit_reason:
                pnl = pos['shares'] * (exit_price - pos['entry'])
                cash += pos['shares'] * exit_price
                run_trades.append({'date': date, 'symbol': sym, 'side': 'SELL', 'reason': exit_reason,
                                    'entry': round(pos['entry'], 2), 'exit': round(exit_price, 2),
                                    'shares': pos['shares'], 'pnl': round(pnl, 2)})
                del positions[sym]

        if sym not in positions and len(positions) < MAXP:
            r = sig_pivot_point_bounce(bars, atr_by_sym[sym], gi)
            if r is not None:
                stop_dist, target_dist = r
                price = bar['close']
                tv = cash + sum(positions[s]['shares'] * bars_by_sym[s][-1]['close']
                                 for s in positions if s in bars_by_sym)
                shares = math.floor((tv / MAXP) / price)
                if shares >= 1 and shares * price <= cash:
                    cash -= shares * price
                    positions[sym] = {'entry': price, 'shares': shares, 'entry_date': date,
                                       'stop': round(price - stop_dist, 4), 'target': round(price + target_dist, 4)}
                    run_trades.append({'date': date, 'symbol': sym, 'side': 'BUY',
                                        'shares': shares, 'price': round(price, 2)})

        last_processed[sym] = date

    state['cash'] = cash
    state['positions'] = positions
    state['last_processed_date'] = last_processed

    hv = sum(pos['shares'] * bars_by_sym[sym][-1]['close']
             for sym, pos in positions.items() if sym in bars_by_sym)
    equity_pl = round(cash + hv - CAPITAL, 2)
    log['runs'].append({'timestamp': now, 'trades': run_trades, 'cumulative_pl': equity_pl,
                         'open_positions': {s: p['shares'] for s, p in positions.items()}})

    json.dump(state, open(STATE_PATH, 'w'), indent=1)
    json.dump(log, open(LOG_PATH, 'w'), indent=1)

    print(f"Pivot50 paper run {now}: {len(run_trades)} new trade event(s)")
    for t in run_trades:
        print(f"  {t}")
    print(f"\nCumulative paper P&L (Pivot Point S1 Bounce, Top-50): {equity_pl:,.2f}")
    print(f"Open positions: {list(positions.keys()) or 'none'}")


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python3 pivot50_paper_engine.py <fresh_daily_historicals.json>")
        sys.exit(1)
    run(sys.argv[1])
