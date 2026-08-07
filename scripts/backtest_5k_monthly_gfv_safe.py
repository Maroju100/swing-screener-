"""One-off ad hoc backtest (NOT a live/paper tracker - writes no state): every
currently-optimized swing and day-trading signal, run through its REAL production
code, independently for each named calendar month, starting fresh from $5,000 each
month (same non-overlapping-window convention as the 5-window walk-forward search),
with GFV-safe T+1 settlement (sale proceeds unusable for a new buy until the next
business day). Also includes Margin-Style Live's current config for comparison.

Usage: python3 scripts/backtest_5k_monthly_gfv_safe.py <daily_hist.json> <30min_hist.json>
"""
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import swing_paper_engine as SWE
import daytrade_paper_engine as DT
import margin_style_live_engine as MS
from backtest_5k_1mo_gfv_safe import backtest_swing_1strategy, backtest_daytrade_1strategy
from walkforward_search import backtest_margin_style_window, load_daily

MONTHS = [
    ('March 2026', '2026-03-01', '2026-03-31'),
    ('April 2026', '2026-04-01', '2026-04-30'),
    ('May 2026', '2026-05-01', '2026-05-31'),
    ('June 2026', '2026-06-01', '2026-06-30'),
    ('July 2026', '2026-07-01', '2026-07-31'),
]

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python3 backtest_5k_monthly_gfv_safe.py <daily_hist.json> <30min_hist.json>")
        sys.exit(1)

    daily_path, intraday_path = sys.argv[1], sys.argv[2]

    ctx = SWE.build_context(daily_path)
    bars_by_sym = ctx[0]
    swing_signals = SWE.make_signals(ctx)

    print("=== SWING - $5,000 fresh start per month, GFV-safe (T+1 settlement) ===")
    for name, fn in swing_signals.items():
        row = [name]
        for label, start, end in MONTHS:
            pnl, n_trades, open_pos = backtest_swing_1strategy(bars_by_sym, fn, start, end)
            row.append(f"{pnl:>9,.2f}({n_trades}t)")
        print(f"  {name:42} " + "  ".join(f"{label}:{v}" for (label, *_), v in zip(MONTHS, row[1:])))
    print()

    dt_bars_by_sym, IND, DAYIDX = DT.build_indicators(intraday_path)
    print("=== DAY-TRADING - $5,000 fresh start per month, GFV-safe (T+1 settlement) ===")
    for name, fn in DT.STRATEGIES.items():
        row = [name]
        for label, start, end in MONTHS:
            pnl, n_trades, open_pos = backtest_daytrade_1strategy(dt_bars_by_sym, IND, DAYIDX, fn, start, end)
            row.append(f"{pnl:>9,.2f}({n_trades}t)")
        print(f"  {name:42} " + "  ".join(f"{label}:{v}" for (label, *_), v in zip(MONTHS, row[1:])))
    print()

    ms_bars_by_sym, _ = load_daily(daily_path, universe=MS.SYMBOLS)
    print("=== MARGIN-STYLE LIVE (current config) - $5,000 fresh start per month, GFV-safe ===")
    row = []
    for label, start, end in MONTHS:
        pnl = backtest_margin_style_window(ms_bars_by_sym, start, end, MS.SYMBOLS, MS.INTRADAY_STOP,
                                            MS.PEAK_SELL_PCT, max_trade_notional=MS.MAX_TRADE_NOTIONAL)
        row.append(f"{pnl:>9,.2f}")
    print("  " + "  ".join(f"{label}:{v}" for (label, *_), v in zip(MONTHS, row)))
