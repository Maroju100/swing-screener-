"""Incremental paper-trading engine for the "Scaled Dip-Buy / Scaled Peak-Sell"
strategy (the "Winner" joint-search-optimized config) - the one signal in this
whole project that went straight from backtest to real money (scripts/
margin_style_live_engine.py) without ever being paper-tracked first. This
engine exists so it can ALSO be observed on an isolated $25k paper account,
same as every other not-yet-fully-vetted signal, purely for comparison against
its real-money performance - it does not feed into or affect the live engine.

Uses DAILY bars (same convention the strategy was backtested and optimized
on) - no live-quote proxy; the completed daily bar's close stands in for
"today" throughout, since this is a paper backtest run once/day after close,
identical in spirit to swing_paper_engine.py.

Usage: python3 scripts/margin_style_paper_engine.py <fresh_daily_historicals.json>

Reads/writes docs/margin_style_paper_state.json (single $25k simulated
account - one strategy, not per-strategy like the other paper trackers) and
appends to docs/margin_style_paper_log.json. Places NO real orders.
"""
import json, sys, os
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, 'docs', 'margin_style_paper_state.json')
LOG_PATH = os.path.join(ROOT, 'docs', 'margin_style_paper_log.json')
SYMBOLS = ["AMD", "MU", "WDC", "SNDK", "TSM"]
CAPITAL = 25000.0

# "Winner" config (joint random-search + walk-forward validated, 2026-07-22)
HUGE_DIP_DRAWDOWN = -0.255
LOOKBACK_DAYS = 22
TRANCHE_PCT = 0.446
MAX_TRANCHES = 5
HUGE_DIP_PCT = 0.743
INTRADAY_STOP = -0.0151
PEAK_SELL_PCT = 0.743
GAIN_TIERS = [(0.20, 0.90), (0.10, 0.50), (0.05, 0.20)]


def build_context(raw_path):
    d = json.load(open(raw_path))
    bars_by_sym = {}
    for r in d['data']['results']:
        bars = [{'date': b['begins_at'][:10], 'high': float(b['high_price']),
                 'low': float(b['low_price']), 'close': float(b['close_price'])} for b in r['bars']]
        bars_by_sym[r['symbol']] = bars
    return bars_by_sym


def load_state():
    if os.path.exists(STATE_PATH):
        return json.load(open(STATE_PATH))
    return {'cash': CAPITAL, 'positions': {}, 'last_processed_date': {}}


def load_log():
    if os.path.exists(LOG_PATH):
        return json.load(open(LOG_PATH))
    return {'capital': CAPITAL, 'symbols': SYMBOLS,
            'strategy': 'Scaled Dip-Buy / Scaled Peak-Sell (Winner config)',
            'note': 'PAPER TRADING ONLY - no real orders placed. Daily bars. '
                     'This strategy is otherwise LIVE on real money (scripts/margin_style_live_engine.py); '
                     'this paper track is a separate, non-connected comparison only.',
            'runs': []}


def run(raw_path):
    bars_by_sym = build_context(raw_path)
    state = load_state()
    log = load_log()
    run_trades = []
    now = datetime.now(timezone.utc).isoformat()

    cash = state['cash']
    positions = state['positions']
    last_processed = state['last_processed_date']

    # Determine the common set of new global indices to process, per symbol independently
    # (mirrors swing_paper_engine.py's per-symbol incremental catch-up).
    for sym in SYMBOLS:
        if sym not in bars_by_sym:
            continue
        bars = bars_by_sym[sym]
        last_dt = last_processed.get(sym)
        if last_dt is None:
            start_gi = max(2, len(bars) - 2)  # first run: only evaluate the newest bar, don't backfill fake history
        else:
            start_gi = next((i for i, b in enumerate(bars) if b['date'] > last_dt), len(bars))
        start_gi = max(start_gi, 2)

        for gi in range(start_gi, len(bars)):
            bar = bars[gi]
            prev_close = bars[gi - 1]['close']
            close = bar['close']

            # SELL side (priority: intraday stop > new peak > gain tiers)
            if sym in positions:
                p = positions[sym]
                if bar['low'] <= prev_close * (1 + INTRADAY_STOP):
                    fill = prev_close * (1 + INTRADAY_STOP)
                    pnl = p['shares'] * (fill - p['avg_cost'])
                    cash += p['shares'] * fill
                    run_trades.append({'symbol': sym, 'date': bar['date'], 'side': 'SELL', 'reason': 'STOP',
                                        'entry': round(p['avg_cost'], 4), 'exit': round(fill, 4),
                                        'shares': p['shares'], 'pnl': round(pnl, 2)})
                    del positions[sym]
                elif close > p['peak']:
                    sell_shares = round(p['shares'] * PEAK_SELL_PCT, 6)
                    if sell_shares > 0:
                        pnl = sell_shares * (close - p['avg_cost'])
                        cash += sell_shares * close
                        run_trades.append({'symbol': sym, 'date': bar['date'], 'side': 'SELL', 'reason': 'PEAK',
                                            'entry': round(p['avg_cost'], 4), 'exit': round(close, 4),
                                            'shares': sell_shares, 'pnl': round(pnl, 2)})
                        p['shares'] -= sell_shares
                    p['peak'] = close
                    if p['shares'] <= 1e-9:
                        del positions[sym]
                else:
                    gain_pct = (close - p['avg_cost']) / p['avg_cost']
                    for thresh, pct in GAIN_TIERS:
                        if gain_pct >= thresh:
                            sell_shares = round(p['shares'] * pct, 6)
                            if sell_shares > 0:
                                pnl = sell_shares * (close - p['avg_cost'])
                                cash += sell_shares * close
                                run_trades.append({'symbol': sym, 'date': bar['date'], 'side': 'SELL',
                                                    'reason': f'GAIN{int(pct*100)}', 'entry': round(p['avg_cost'], 4),
                                                    'exit': round(close, 4), 'shares': sell_shares, 'pnl': round(pnl, 2)})
                                p['shares'] -= sell_shares
                                if p['shares'] <= 1e-9:
                                    del positions[sym]
                            break

            # BUY side (uses the day-1/day-2-ago return+drawdown, executed at today's close -
            # same convention as the original backtest, since there is no live-quote proxy here).
            p = positions.get(sym)
            if p and p.get('tranches', 0) >= MAX_TRANCHES:
                continue
            if gi < LOOKBACK_DAYS + 2:
                continue
            prev_prev_close = bars[gi - 2]['close']
            day_return = (prev_close - prev_prev_close) / prev_prev_close
            lb_start = max(0, gi - 1 - LOOKBACK_DAYS)
            trailing_high = max(bars[j]['close'] for j in range(lb_start, gi - 1))
            drawdown = (prev_close - trailing_high) / trailing_high

            deploy = None
            if drawdown <= HUGE_DIP_DRAWDOWN:
                deploy = cash * HUGE_DIP_PCT
            elif day_return < 0 and (not p or p.get('tranches', 0) < MAX_TRANCHES):
                deploy = cash * TRANCHE_PCT
            if deploy and deploy >= 25.0 and cash > 1.0:
                shares = round(deploy / close, 6)
                if shares > 0:
                    if p:
                        new_shares = p['shares'] + shares
                        p['avg_cost'] = (p['avg_cost'] * p['shares'] + deploy) / new_shares
                        p['shares'] = new_shares
                        p['peak'] = max(p['peak'], close)
                        p['tranches'] = p.get('tranches', 0) + 1
                    else:
                        positions[sym] = {'shares': shares, 'avg_cost': close, 'peak': close, 'tranches': 1}
                    cash -= deploy
                    run_trades.append({'symbol': sym, 'date': bar['date'], 'side': 'BUY',
                                        'reason': 'HUGE_DIP' if drawdown <= HUGE_DIP_DRAWDOWN else 'NORMAL_DIP',
                                        'shares': shares, 'price': round(close, 4)})

            last_processed[sym] = bar['date']

    state['cash'] = cash
    state['positions'] = positions
    state['last_processed_date'] = last_processed

    hv = sum(p['shares'] * bars_by_sym[sym][-1]['close'] for sym, p in positions.items() if sym in bars_by_sym)
    cum_pl = round(cash + hv - CAPITAL, 2)

    log['runs'].append({'timestamp': now, 'trades': run_trades, 'cumulative_pl': cum_pl})
    json.dump(state, open(STATE_PATH, 'w'), indent=1)
    json.dump(log, open(LOG_PATH, 'w'), indent=1)

    print(f"Margin-Style paper-trading run {now}: {len(run_trades)} new trade event(s)")
    for t in run_trades:
        print(f"  {t}")
    print(f"\nCumulative paper P&L (Scaled Dip-Buy/Scaled Peak-Sell, Winner config): {cum_pl:,.2f}")


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python3 margin_style_paper_engine.py <fresh_daily_historicals.json>")
        sys.exit(1)
    run(sys.argv[1])
