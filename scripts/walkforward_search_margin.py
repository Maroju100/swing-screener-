"""One-off ad hoc walk-forward parameter search (NOT a live/paper tracker - writes no
state, touches no other system's files) for the Margin-Style "Scaled Dip-Buy / Scaled
Peak-Sell" strategy's intraday_stop and peak_sell_pct, on the live 8-symbol universe.
Uses the same 5-window/$5k methodology as every other round in this project, via
walkforward_search.backtest_margin_style_window (added in an earlier commit but never
actually run to completion before this).

Usage: python3 scripts/walkforward_search_margin.py <daily_hist_8sym.json>
"""
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
from walkforward_search import make_windows, backtest_margin_style_window, load_daily
import margin_style_live_engine as MS

MS_SYMBOLS = MS.SYMBOLS  # AMD, MU, WDC, SNDK, TSM, INTC, LRCX, STX

daily_path = sys.argv[1]
bars_by_sym, _ = load_daily(daily_path, universe=MS_SYMBOLS)
dates = sorted(set(b['date'] for bars in bars_by_sym.values() for b in bars))
windows = make_windows(dates, 5)
print("Windows:", windows)
print()

def run(name, intraday_stop, peak_sell_pct, max_trade_notional=1000.0):
    window_pls = [backtest_margin_style_window(bars_by_sym, w[0], w[1], MS_SYMBOLS,
                                                 intraday_stop, peak_sell_pct,
                                                 max_trade_notional=max_trade_notional)
                  for w in windows]
    n_profit = sum(1 for p in window_pls if p > 0)
    total = round(sum(window_pls), 2)
    print(f"{name:45} stop={intraday_stop:+.3f} peak_sell={peak_sell_pct:.2f} cap=${max_trade_notional:.0f}  "
          f"windows_profitable={n_profit}/5  total={total:>10,.2f}  per_window={window_pls}")
    return total, n_profit

print("=== BASELINE (current live config) ===")
run('Current live (Winner + $1k cap)', MS.INTRADAY_STOP, MS.PEAK_SELL_PCT, MS.MAX_TRADE_NOTIONAL)
print()

print("=== Grid search: intraday_stop x peak_sell_pct (cap=$1000, matching live) ===")
results = []
for stop in (-0.0075, -0.010, -0.0125, -0.0151, -0.02, -0.025, -0.03):
    for peak in (0.20, 0.30, 0.446, 0.60, 0.743, 0.90):
        total, n_profit = run(f'stop={stop} peak={peak}', stop, peak, MS.MAX_TRADE_NOTIONAL)
        results.append({'stop': stop, 'peak': peak, 'total': total, 'n_profit': n_profit})

results.sort(key=lambda r: (-r['n_profit'], -r['total']))
print()
print("=== Top 10 by (windows_profitable, total) ===")
for r in results[:10]:
    print(f"  stop={r['stop']:+.4f}  peak_sell={r['peak']:.3f}  windows_profitable={r['n_profit']}/5  total={r['total']:>10,.2f}")

print()
print("=== Specifically checking stop=-1.0%, peak_sell=30% (as claimed) ===")
run('Claimed best', -0.010, 0.30, MS.MAX_TRADE_NOTIONAL)
