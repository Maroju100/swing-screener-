"""Companion to walkforward_search_batch2.py: evaluates each strategy's CURRENT
(pre-change) hardcoded params through the same 5-window harness, for direct
before/after comparison. Not a live/paper tracker - writes no state.
"""
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
from walkforward_search import make_windows, backtest_daytrade_window, search_swing_general
from walkforward_search_batch2 import (build_swing_ctx, DT, gen_minervini_vcp, gen_bollinger_squeeze,
    gen_ichimoku, gen_bull_flag, gen_rsi_bullish_divergence, gen_fib_618, gen_high_tight_flagpole,
    gen_connors_rsi, gen_ma_crossover, gen_cup_and_handle, gen_rs_leader_pullback,
    gen_dt_swing_pullback, gen_dt_hybrid_scalping, gen_dt_gap_momentum, gen_dt_opening_range_breakout,
    gen_dt_id_nr4, gen_dt_relative_volume_leader, gen_dt_oversold_snapback, gen_dt_first_pullback_orb)

daily_path, intraday_path = sys.argv[1], sys.argv[2]
C = build_swing_ctx(daily_path)
daily_dates = sorted(set(b['date'] for bars in C['bars_by_sym'].values() for b in bars))
daily_windows = make_windows(daily_dates, 5)
atr_by_sym = C['ATR']

dt_bars_by_sym, IND, DAYIDX = DT.build_indicators(intraday_path)
intraday_dates = sorted(set(b['date'] for bars in dt_bars_by_sym.values() for b in bars))
intraday_windows = make_windows(intraday_dates, 5)

def swing_baseline(name, gen_fn, params):
    res = search_swing_general(name, lambda **p: gen_fn(C, **p), [params], C['bars_by_sym'], atr_by_sym, daily_windows, min_hold=2)
    r = res[0]
    print(f"BASELINE {name:42} {params}  windows_profitable={r['n_profit']}/5  total={r['total']:>10,.2f}  per_window={r['window_pls']}")

def dt_baseline(name, gen_fn, params, continuous):
    sig_fn = gen_fn(**params)
    window_pls = [backtest_daytrade_window(dt_bars_by_sym, DAYIDX, sig_fn, continuous, w[0], w[1]) for w in intraday_windows]
    n_profit = sum(1 for p in window_pls if p > 0)
    total = round(sum(window_pls), 2)
    print(f"BASELINE {name:42} {params}  windows_profitable={n_profit}/5  total={total:>10,.2f}  per_window={window_pls}")

swing_baseline('E: Minervini VCP', gen_minervini_vcp, {'lookback': 60, 'rr': (1.75, 3.5)})
swing_baseline('Bollinger Squeeze Breakout', gen_bollinger_squeeze, {'squeeze_lookback': 50, 'rr': (1.75, 3.5)})
swing_baseline('Ichimoku Kumo Breakout', gen_ichimoku, {'shift': 26, 'rr': (1.75, 3.5)})
swing_baseline('Bull Flag Breakout', gen_bull_flag, {'gain_thresh': 0.15, 'rr': (1.75, 3.5)})
swing_baseline('RSI Bullish Divergence', gen_rsi_bullish_divergence, {'rr': (1.75, 3.5)})
swing_baseline('Fibonacci 61.8% Retracement Bounce', gen_fib_618, {'tol': 0.98, 'rr': (1.75, 3.5)})
swing_baseline('High Tight Flagpole', gen_high_tight_flagpole, {'gain_thresh': 0.90, 'rr': (1.75, 3.5)})
swing_baseline('ConnorsRSI Oversold Bounce', gen_connors_rsi, {'oversold': 10, 'rr': (1.5, 3.0)})
swing_baseline('MA Crossover (H)', gen_ma_crossover, {'fast': 9, 'slow': 21, 'rr': (1.75, 3.5)})
swing_baseline('Cup and Handle', gen_cup_and_handle, {'handle_depth_frac': 1/3, 'rr': (1.75, 3.5)})
swing_baseline('Relative Strength Leader Pullback', gen_rs_leader_pullback, {'rsi_band': (40, 55), 'lookback': 21, 'rr': (1.75, 3.5)})

dt_baseline('Swing Pullback / Anti', lambda **p: gen_dt_swing_pullback(dt_bars_by_sym, IND, **p), {'touch_mult': 1.003, 'rr': (1, 2)}, True)
dt_baseline('Hybrid Disciplined Momentum Scalping', lambda **p: gen_dt_hybrid_scalping(dt_bars_by_sym, IND, **p), {'vol_mult': 1.5, 'rsi_band': (50, 75), 'rr': (1, 2)}, True)
dt_baseline('Gap / High Change Momentum', lambda **p: gen_dt_gap_momentum(dt_bars_by_sym, DAYIDX, **p), {'gap_thresh': 0.015, 'rr': (1, 2)}, False)
dt_baseline('Opening Range Breakout', lambda **p: gen_dt_opening_range_breakout(dt_bars_by_sym, DAYIDX, **p), {'or_bars': 2, 'rr': (1, 2)}, True)
dt_baseline('ID/NR4 Volatility Breakout', lambda **p: gen_dt_id_nr4(dt_bars_by_sym, DAYIDX, **p), {'nr_days': 5, 'breakout_window': 13, 'rr': (1, 2)}, True)
dt_baseline('Relative Volume Leader Momentum', lambda **p: gen_dt_relative_volume_leader(dt_bars_by_sym, DAYIDX, **p), {'min_i_in_day': 6, 'vol_ratio_thresh': 1.5, 'rr': (1, 2)}, True)
dt_baseline('Oversold Snapback Fade', lambda **p: gen_dt_oversold_snapback(dt_bars_by_sym, DAYIDX, **p), {'min_i_in_day': 4, 'lookback': 3, 'drop_thresh': 0.02, 'rr': (1, 2)}, True)
dt_baseline('First Pullback After ORB (H2)', lambda **p: gen_dt_first_pullback_orb(dt_bars_by_sym, DAYIDX, **p), {'rr': (0.5, 1)}, True)
