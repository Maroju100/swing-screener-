"""One-off ad hoc walk-forward validation (NOT a live/paper tracker - writes no state)
of the noon-swing / twice-daily-day-trading approach from master_table_noon_twice.py.

CORRECTED: the cached "1yr" 30-min file has flat, zero-volume placeholder data for
EVERY symbol from 2025-08-01 until 2026-01-30 (confirmed by checking AMD/MU/WDC/
SNDK/TSM directly - all 5 sit at one unchanging price for that entire stretch, not
just the 3 symbols fetched fresh this session). This is a data-availability
limitation, not a "persistent uptrend regime" as an earlier code comment guessed -
that guess was wrong. Restricted to the verified-real span (2026-01-30 to
2026-08-06, ~6.2 months), split into 3 non-overlapping windows (matching how the
Margin-Style timing comparison was already corrected for the same issue), scored by
the same (windows_profitable, total) convention as everywhere else in this project.

Usage: python3 scripts/validate_noon_twice_walkforward.py <intraday_5sym_1yr.json>
"""
import sys, os, json
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import swing_paper_engine as SWE
import daytrade_paper_engine as DT
from walkforward_search import make_windows
from master_table_noon_twice import (build_noon_daily_json, swing_1strategy_1month,
                                       daytrade_1strategy_1month_twice)

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python3 validate_noon_twice_walkforward.py <intraday_5sym_1yr.json>")
        sys.exit(1)

    intraday_path = sys.argv[1]
    REAL_START, REAL_END = '2026-01-30', '2026-08-06'

    # --- SWING: noon-only synthetic bars, real-data span only, 3 windows ---
    noon_json = build_noon_daily_json(intraday_path, set(SWE.SYMBOLS))
    noon_json['data']['results'] = [
        {'symbol': r['symbol'], 'bars': [b for b in r['bars'] if REAL_START <= b['begins_at'][:10] <= REAL_END]}
        for r in noon_json['data']['results']
    ]
    tmp_path = '/tmp/_swing_noon_synthetic_realonly.json'
    json.dump(noon_json, open(tmp_path, 'w'))
    ctx = SWE.build_context(tmp_path)
    bars_by_sym = ctx[0]
    swing_signals = SWE.make_signals(ctx)

    noon_dates = sorted(set(b['date'] for bars in bars_by_sym.values() for b in bars))
    swing_windows = make_windows(noon_dates, 3)
    print(f"Swing (noon) real-data span: {REAL_START} to {REAL_END}, split into 3 windows:", swing_windows)
    print()

    print("=== SWING (once/day at noon ET) - 3-window walk-forward (real data only), $5k/window, GFV-safe ===")
    swing_results = []
    for name, fn in swing_signals.items():
        pls = [swing_1strategy_1month(bars_by_sym, fn, w[0], w[1]) for w in swing_windows]
        n_profit = sum(1 for p in pls if p > 0)
        total = round(sum(pls), 2)
        swing_results.append((name, pls, n_profit, total))
    swing_results.sort(key=lambda r: (-r[2], -r[3]))
    for name, pls, n_profit, total in swing_results:
        print(f"  {name:42} windows_profitable={n_profit}/3  total={total:>10,.2f}  per_window={pls}")
    print()

    # --- DAY-TRADING: twice-daily, real-data span only, 3 windows ---
    dt_bars_by_sym_full, IND_full, DAYIDX_full = DT.build_indicators(intraday_path)
    dt_bars_by_sym = {s: [b for b in bars if REAL_START <= b['date'] <= REAL_END] for s, bars in dt_bars_by_sym_full.items()}
    # rebuild IND/DAYIDX against the filtered bars so indices line up
    tmp_dt_json = {'data': {'results': [
        {'symbol': s, 'bars': [{'begins_at': b['dt'], 'open_price': b['open'], 'close_price': b['close'],
                                 'high_price': b['high'], 'low_price': b['low'], 'volume': b['volume']} for b in bars]}
        for s, bars in dt_bars_by_sym.items()
    ]}}
    tmp_dt_path = '/tmp/_dt_twice_realonly.json'
    json.dump(tmp_dt_json, open(tmp_dt_path, 'w'))
    dt_bars_by_sym, IND, DAYIDX = DT.build_indicators(tmp_dt_path)
    dt_dates = sorted(set(b['date'] for bars in dt_bars_by_sym.values() for b in bars))
    dt_windows = make_windows(dt_dates, 3)
    print(f"Day-trading (twice/day) real-data span: {REAL_START} to {REAL_END}, split into 3 windows:", dt_windows)
    print()

    print("=== DAY-TRADING (twice/day: ~11am & ~2:30pm ET) - 3-window walk-forward (real data only), $5k/window, GFV-safe ===")
    dt_results = []
    for name, fn in DT.STRATEGIES.items():
        pls = [daytrade_1strategy_1month_twice(dt_bars_by_sym, IND, DAYIDX, fn, w[0], w[1]) for w in dt_windows]
        n_profit = sum(1 for p in pls if p > 0)
        total = round(sum(pls), 2)
        dt_results.append((name, pls, n_profit, total))
    dt_results.sort(key=lambda r: (-r[2], -r[3]))
    for name, pls, n_profit, total in dt_results:
        print(f"  {name:42} windows_profitable={n_profit}/3  total={total:>10,.2f}  per_window={pls}")
