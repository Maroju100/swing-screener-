"""One-off ad hoc walk-forward parameter search (NOT a live/paper tracker - writes no
state, touches no other system's files) for the Margin-Style "Scaled Dip-Buy / Scaled
Peak-Sell" strategy's intraday_stop and peak_sell_pct, on the live 8-symbol universe.
Uses the same 5-window/$5k methodology as every other round in this project, via
walkforward_search.backtest_margin_style_window.

Round 2 (widened grid + out-of-sample check): the first pass (stop -0.75%..-3%,
peak-sell 20%..90%) found totals rising monotonically toward its edge (-0.75%/20%),
an overfitting tell rather than a real interior optimum. This pass widens the grid
down to -0.3% stop / 5% peak-sell to see whether it actually plateaus or keeps
climbing, and adds a train/holdout split (windows 1-4 pick the config, window 5 -
the most recent ~3.5 months - grades it out-of-sample) to check whether whatever
wins in-sample actually generalizes forward, rather than trusting the full-sample
ranking alone.

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
for i, w in enumerate(windows, 1):
    print(f"  Window {i}: {w[0]} to {w[1]}")
print()


def window_pls_for(stop, peak, cap=1000.0, use_windows=None):
    ws = use_windows if use_windows is not None else windows
    return [backtest_margin_style_window(bars_by_sym, w[0], w[1], MS_SYMBOLS, stop, peak, max_trade_notional=cap) for w in ws]


def run(name, stop, peak, cap=1000.0, use_windows=None, verbose=True):
    pls = window_pls_for(stop, peak, cap, use_windows)
    n_profit = sum(1 for p in pls if p > 0)
    total = round(sum(pls), 2)
    if verbose:
        print(f"{name:20} stop={stop:+.4f} peak={peak:.3f} cap=${cap:.0f}  "
              f"profitable={n_profit}/{len(pls)}  total={total:>10,.2f}  per_window={pls}")
    return total, n_profit, pls


print("=== BASELINE (current live config, full 5 windows) ===")
run('Current live', MS.INTRADAY_STOP, MS.PEAK_SELL_PCT, MS.MAX_TRADE_NOTIONAL)
print()

STOPS = (-0.003, -0.005, -0.0075, -0.010, -0.0125, -0.0151, -0.02, -0.025, -0.03)
PEAKS = (0.05, 0.10, 0.15, 0.20, 0.30, 0.446, 0.60, 0.743, 0.90)

print(f"=== Widened grid search: {len(STOPS)} stops x {len(PEAKS)} peak-sells = {len(STOPS)*len(PEAKS)} combos (full 5 windows, cap=$1000) ===")
results = []
for stop in STOPS:
    for peak in PEAKS:
        total, n_profit, pls = run(f's={stop} p={peak}', stop, peak, MS.MAX_TRADE_NOTIONAL, verbose=False)
        results.append({'stop': stop, 'peak': peak, 'total': total, 'n_profit': n_profit, 'pls': pls})
results.sort(key=lambda r: (-r['n_profit'], -r['total']))
print("Top 15 by (windows_profitable, total), full 5-window sample:")
for r in results[:15]:
    print(f"  stop={r['stop']:+.4f}  peak_sell={r['peak']:.3f}  profitable={r['n_profit']}/5  total={r['total']:>10,.2f}")
print()
print("Bottom 5 of that top group, to see if the grid plateaus or is still climbing at the edge:")
edge_stop, edge_peak = min(STOPS), min(PEAKS)
edge = next(r for r in results if r['stop'] == edge_stop and r['peak'] == edge_peak)
print(f"  Grid edge (stop={edge_stop}, peak={edge_peak}): profitable={edge['n_profit']}/5  total={edge['total']:>10,.2f}")
print()

print("=== Out-of-sample check: pick best config on windows 1-4 (train), grade on window 5 (holdout) ===")
train_windows, holdout_window = windows[:4], [windows[4]]
print(f"Train: windows 1-4 ({train_windows[0][0]} to {train_windows[-1][1]})")
print(f"Holdout: window 5 ({holdout_window[0][0]} to {holdout_window[0][1]}, most recent ~3.5 months)")
print()

train_results = []
for stop in STOPS:
    for peak in PEAKS:
        total, n_profit, pls = run(f's={stop} p={peak}', stop, peak, MS.MAX_TRADE_NOTIONAL, use_windows=train_windows, verbose=False)
        train_results.append({'stop': stop, 'peak': peak, 'train_total': total, 'train_n_profit': n_profit})
train_results.sort(key=lambda r: (-r['train_n_profit'], -r['train_total']))

print("Top 5 configs picked using ONLY windows 1-4 (train), then graded on window 5 (holdout):")
for r in train_results[:5]:
    holdout_total, holdout_n, holdout_pls = run('', r['stop'], r['peak'], MS.MAX_TRADE_NOTIONAL, use_windows=holdout_window, verbose=False)
    print(f"  stop={r['stop']:+.4f}  peak={r['peak']:.3f}  train: {r['train_n_profit']}/4 total={r['train_total']:>9,.2f}   "
          f"HOLDOUT (window 5): {'PROFIT' if holdout_total>0 else 'LOSS  '} {holdout_total:>9,.2f}")
print()

print("Current live config's own train/holdout split, for direct comparison:")
cur_train_total, cur_train_n, _ = run('', MS.INTRADAY_STOP, MS.PEAK_SELL_PCT, MS.MAX_TRADE_NOTIONAL, use_windows=train_windows, verbose=False)
cur_holdout_total, cur_holdout_n, _ = run('', MS.INTRADAY_STOP, MS.PEAK_SELL_PCT, MS.MAX_TRADE_NOTIONAL, use_windows=holdout_window, verbose=False)
print(f"  Current live (stop={MS.INTRADAY_STOP}, peak={MS.PEAK_SELL_PCT})  train: {cur_train_n}/4 total={cur_train_total:>9,.2f}   "
      f"HOLDOUT (window 5): {'PROFIT' if cur_holdout_total>0 else 'LOSS  '} {cur_holdout_total:>9,.2f}")
print()

print("Previously-flagged edge-of-grid config (stop=-0.75%, peak=20%) and your originally-cited config (stop=-1.0%, peak=30%), train/holdout:")
for label, stop, peak in [('Edge config (-0.75%/20%)', -0.0075, 0.20), ('Cited config (-1.0%/30%)', -0.010, 0.30)]:
    t_total, t_n, _ = run('', stop, peak, MS.MAX_TRADE_NOTIONAL, use_windows=train_windows, verbose=False)
    h_total, h_n, _ = run('', stop, peak, MS.MAX_TRADE_NOTIONAL, use_windows=holdout_window, verbose=False)
    print(f"  {label:28} train: {t_n}/4 total={t_total:>9,.2f}   HOLDOUT (window 5): {'PROFIT' if h_total>0 else 'LOSS  '} {h_total:>9,.2f}")

print()
print("=== Ranking using ONLY window 5 (most recent ~3.5mo) as if it were the sole sample - regime-stability check ===")
recent_only = []
for stop in STOPS:
    for peak in PEAKS:
        total, n_profit, pls = run('', stop, peak, MS.MAX_TRADE_NOTIONAL, use_windows=holdout_window, verbose=False)
        recent_only.append({'stop': stop, 'peak': peak, 'total': total})
recent_only.sort(key=lambda r: -r['total'])
print("Top 5 by window-5-only total (compare against the full-sample top 15 above):")
for r in recent_only[:5]:
    print(f"  stop={r['stop']:+.4f}  peak_sell={r['peak']:.3f}  window-5-only total={r['total']:>10,.2f}")
