"""One-off ad hoc walk-forward parameter search (NOT a live/paper tracker - writes no
state, touches no other system's files), round 2: covers every remaining strategy that
hadn't yet been through a walk-forward search -

Swing (daily bars, 5-symbol basket AMD/MU/WDC/SNDK/TSM):
  Cup and Handle, Bollinger Squeeze Breakout, Ichimoku Kumo Breakout, Bull Flag Breakout,
  RSI Bullish Divergence, Fibonacci 61.8% Retracement Bounce, High Tight Flagpole,
  ConnorsRSI Oversold Bounce, MA Crossover (H), E: Minervini VCP Breakout (currently
  orphaned - graduated to the live 9-Way Combo, which was disabled 2026-07-24, and never
  re-added to paper tracking), Relative Strength Leader Pullback.

Day-trading (30-min bars, same 5-symbol basket):
  Swing Pullback / Anti, Hybrid Disciplined Momentum Scalping, Gap / High Change
  Momentum, Opening Range Breakout, ID/NR4 Volatility Breakout, Relative Volume Leader
  Momentum, Oversold Snapback Fade, First Pullback After ORB (H2).

Methodology matches every prior round: non-overlapping windows (capital reset to $5,000
each window), scored by (windows_profitable, total_pnl). 5 windows each, using ~1.5yr of
daily bars (swing) and ~1yr of 30-min bars (day-trading). Structural logic for each
signal is copied verbatim from swing_paper_engine.py / daytrade_paper_engine.py, with
stop/target sizing (and, where cheap, one structural knob) exposed as search params.

Usage: python3 scripts/walkforward_search_batch2.py <daily_hist.json> <thirty_min_1yr_hist.json>
"""
import json, sys, os, statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import swing_paper_engine as SWE
import daytrade_paper_engine as DT
from walkforward_search import (make_windows, backtest_swing_window, backtest_daytrade_window,
                                 search_swing_general, search_daytrade)

SWING_SYMBOLS = ["AMD", "MU", "WDC", "SNDK", "TSM"]

# ---------------------------------------------------------------------------
# Swing generators - close over the SAME precomputed series swing_paper_engine.py
# uses (via SWE.build_context), reproducing each signal's structural logic exactly,
# with stop/target ATR multipliers (and one structural knob per signal) as search params.
# ---------------------------------------------------------------------------

def build_swing_ctx(daily_path):
    ctx = SWE.build_context(daily_path)
    bars_by_sym, ATR, CRSI, PIVOT_LOWS, WEEKLY, MONTHLY, ICHI, RSI14, EMA21, PIVOTS_HL, EMA9 = ctx
    return dict(bars_by_sym=bars_by_sym, ATR=ATR, CRSI=CRSI, PIVOT_LOWS=PIVOT_LOWS, WEEKLY=WEEKLY,
                MONTHLY=MONTHLY, ICHI=ICHI, RSI14=RSI14, EMA21=EMA21, PIVOTS_HL=PIVOTS_HL, EMA9=EMA9)


def gen_minervini_vcp(C, lookback, rr):
    stop_atr, target_atr = rr
    bars_by_sym, ATR = C['bars_by_sym'], C['ATR']
    def sig(sym, gi):
        bars = bars_by_sym[sym]
        if gi < lookback + 5: return None
        swing_idx = list(range(gi - lookback, gi))
        pivots = []
        for i in range(2, len(swing_idx) - 2):
            gi2 = swing_idx[i]
            if bars[gi2]['high'] > bars[gi2-1]['high'] and bars[gi2]['high'] > bars[gi2-2]['high'] and \
               bars[gi2]['high'] > bars[gi2+1]['high'] and bars[gi2]['high'] > bars[gi2+2]['high']:
                pivots.append(('H', gi2, bars[gi2]['high']))
            if bars[gi2]['low'] < bars[gi2-1]['low'] and bars[gi2]['low'] < bars[gi2-2]['low'] and \
               bars[gi2]['low'] < bars[gi2+1]['low'] and bars[gi2]['low'] < bars[gi2+2]['low']:
                pivots.append(('L', gi2, bars[gi2]['low']))
        pivots.sort(key=lambda x: x[1])
        contractions = []
        for i in range(len(pivots) - 1):
            if pivots[i][0] == 'H' and pivots[i+1][0] == 'L':
                pct = (pivots[i][2] - pivots[i+1][2]) / pivots[i][2]
                contractions.append((pivots[i][1], pivots[i+1][1], pivots[i][2], pct))
        if len(contractions) < 2: return None
        last_two = contractions[-2:]
        if not (last_two[0][3] > last_two[1][3]): return None
        tightest_high = last_two[-1][2]
        if bars[gi-1]['close'] <= tightest_high and bars[gi]['close'] > tightest_high:
            atr = ATR[sym][gi]
            if not atr: return None
            return (atr * stop_atr, atr * target_atr)
        return None
    return sig


def gen_bollinger_squeeze(C, squeeze_lookback, rr):
    stop_atr, target_atr = rr
    bars_by_sym, ATR = C['bars_by_sym'], C['ATR']
    def sig(sym, gi):
        bars = bars_by_sym[sym]
        if gi < squeeze_lookback + 20: return None
        closes = [bars[j]['close'] for j in range(gi-19, gi+1)]
        ma20 = statistics.mean(closes); sd20 = statistics.pstdev(closes)
        upper, lower = ma20 + 2*sd20, ma20 - 2*sd20
        bw = (upper - lower) / ma20
        bw_hist = []
        for k in range(gi - squeeze_lookback + 1, gi):
            c2 = [bars[j]['close'] for j in range(k-19, k+1)]
            m2 = statistics.mean(c2); s2 = statistics.pstdev(c2)
            bw_hist.append((m2+2*s2 - (m2-2*s2)) / m2)
        if not bw_hist: return None
        if bw <= min(bw_hist) and bars[gi]['close'] > upper:
            atr = ATR[sym][gi]
            if not atr: return None
            return (atr * stop_atr, atr * target_atr)
        return None
    return sig


def gen_ichimoku(C, shift, rr):
    stop_atr, target_atr = rr
    bars_by_sym, ATR, ICHI = C['bars_by_sym'], C['ATR'], C['ICHI']
    def sig(sym, gi):
        bars = bars_by_sym[sym]
        tenkan, kijun, senkouA, senkouB = ICHI[sym]
        if gi < shift + 55: return None
        cloud_src = gi - shift
        sa, sb = senkouA[cloud_src], senkouB[cloud_src]
        if sa is None or sb is None: return None
        cloud_top = max(sa, sb)
        bullish_cloud = sa > sb
        if tenkan[gi] is None or kijun[gi] is None or tenkan[gi-1] is None or kijun[gi-1] is None: return None
        cross_up = tenkan[gi-1] <= kijun[gi-1] and tenkan[gi] > kijun[gi]
        above_cloud = bars[gi]['close'] > cloud_top
        if cross_up and above_cloud and bullish_cloud:
            atr = ATR[sym][gi]
            if not atr: return None
            return (atr * stop_atr, atr * target_atr)
        return None
    return sig


def gen_bull_flag(C, gain_thresh, rr):
    stop_atr, target_atr = rr
    bars_by_sym, ATR = C['bars_by_sym'], C['ATR']
    def sig(sym, gi):
        bars = bars_by_sym[sym]
        if gi < 25: return None
        for flag_len in range(5, 16):
            pole_end = gi - flag_len
            if pole_end < 10: continue
            pole_start = pole_end - 10
            pole_low = min(bars[j]['low'] for j in range(pole_start, pole_end))
            pole_high = max(bars[j]['high'] for j in range(pole_start, pole_end))
            gain = (pole_high - pole_low) / pole_low
            if gain < gain_thresh: continue
            flag_low = min(bars[j]['low'] for j in range(pole_end, gi))
            pullback = (pole_high - flag_low) / pole_high
            if not (0.30 <= pullback <= 0.50): continue
            if bars[gi-1]['close'] > pole_high: continue
            if bars[gi]['close'] > pole_high:
                atr = ATR[sym][gi]
                if not atr: return None
                return (atr * stop_atr, atr * target_atr)
        return None
    return sig


def gen_rsi_bullish_divergence(C, rr):
    stop_atr, target_atr = rr
    bars_by_sym, ATR, RSI14, PIVOTS_HL = C['bars_by_sym'], C['ATR'], C['RSI14'], C['PIVOTS_HL']
    def sig(sym, gi):
        bars = bars_by_sym[sym]
        r = RSI14[sym]
        if gi < 30: return None
        piv_lows = [p for p in PIVOTS_HL[sym] if p[0] == 'L' and p[1] < gi]
        if len(piv_lows) < 2: return None
        p1, p2 = piv_lows[-2], piv_lows[-1]
        if p2[2] >= p1[2]: return None
        if r[p1[1]] is None or r[p2[1]] is None: return None
        if r[p2[1]] <= r[p1[1]]: return None
        piv_highs = [p for p in PIVOTS_HL[sym] if p[0] == 'H' and p1[1] < p[1] < p2[1]]
        if not piv_highs: return None
        confirm_level = max(p[2] for p in piv_highs)
        if bars[gi-1]['close'] > confirm_level: return None
        if bars[gi]['close'] > confirm_level:
            atr = ATR[sym][gi]
            if not atr: return None
            return (atr * stop_atr, atr * target_atr)
        return None
    return sig


def gen_fib_618(C, tol, rr):
    stop_atr, target_atr = rr
    bars_by_sym, ATR, PIVOTS_HL = C['bars_by_sym'], C['ATR'], C['PIVOTS_HL']
    def sig(sym, gi):
        bars = bars_by_sym[sym]
        if gi < 30: return None
        piv = [p for p in PIVOTS_HL[sym] if p[1] < gi]
        if len(piv) < 2: return None
        last2 = piv[-2:]
        if not (last2[0][0] == 'L' and last2[1][0] == 'H'): return None
        swing_low, swing_high = last2[0][2], last2[1][2]
        if swing_high <= swing_low: return None
        fib618 = swing_high - 0.618 * (swing_high - swing_low)
        fib50 = swing_high - 0.5 * (swing_high - swing_low)
        touched = bars[gi-1]['low'] <= fib50 and bars[gi-1]['low'] >= fib618 * tol
        bounced = bars[gi]['close'] > bars[gi-1]['high'] and bars[gi]['close'] > fib50
        if touched and bounced:
            atr = ATR[sym][gi]
            if not atr: return None
            return (atr * stop_atr, atr * target_atr)
        return None
    return sig


def gen_high_tight_flagpole(C, gain_thresh, rr):
    stop_atr, target_atr = rr
    bars_by_sym, ATR = C['bars_by_sym'], C['ATR']
    def sig(sym, gi):
        bars = bars_by_sym[sym]
        if gi < 50: return None
        for pole_len in (40, 30, 20):
            pole_start = gi - pole_len - 15
            if pole_start < 0: continue
            for flag_len in range(5, 16):
                pole_end = gi - flag_len
                if pole_end - pole_start < 10: continue
                pole_low = min(bars[j]['low'] for j in range(pole_start, pole_end))
                pole_high = max(bars[j]['high'] for j in range(pole_start, pole_end))
                gain = (pole_high - pole_low) / pole_low
                if gain < gain_thresh: continue
                flag_high = pole_high
                flag_low = min(bars[j]['low'] for j in range(pole_end, gi))
                pullback = (flag_high - flag_low) / flag_high
                if not (0.10 <= pullback <= 0.25): continue
                if bars[gi-1]['close'] > flag_high: continue
                if bars[gi]['close'] > flag_high:
                    atr = ATR[sym][gi]
                    if not atr: return None
                    return (atr * stop_atr, atr * target_atr)
        return None
    return sig


def gen_connors_rsi(C, oversold, rr):
    stop_atr, target_atr = rr
    bars_by_sym, ATR, CRSI = C['bars_by_sym'], C['ATR'], C['CRSI']
    def sig(sym, gi):
        bars = bars_by_sym[sym]
        if gi < 105: return None
        crsi = CRSI[sym][gi]
        if crsi is None: return None
        sma50 = statistics.mean(bars[j]['close'] for j in range(gi-49, gi+1))
        if crsi < oversold and bars[gi]['close'] > sma50:
            atr = ATR[sym][gi]
            if not atr: return None
            return (atr * stop_atr, atr * target_atr)
        return None
    return sig


def gen_ma_crossover(C, fast, slow, rr):
    stop_atr, target_atr = rr
    bars_by_sym, ATR = C['bars_by_sym'], C['ATR']
    ema_fast = {sym: SWE.ema_series([b['close'] for b in bars_by_sym[sym]], fast) for sym in bars_by_sym}
    ema_slow = {sym: SWE.ema_series([b['close'] for b in bars_by_sym[sym]], slow) for sym in bars_by_sym}
    def sig(sym, gi):
        bars = bars_by_sym[sym]
        if gi < slow + 1: return None
        ef, es = ema_fast[sym], ema_slow[sym]
        if ef[gi] > es[gi] and not (ef[gi-1] > es[gi-1]):
            atr = ATR[sym][gi]
            if not atr: return None
            return (atr * stop_atr, atr * target_atr)
        return None
    return sig


def gen_cup_and_handle(C, handle_depth_frac, rr):
    stop_atr, target_atr = rr
    bars_by_sym, ATR = C['bars_by_sym'], C['ATR']
    def sig(sym, gi):
        bars = bars_by_sym[sym]
        if gi < 90: return None
        for cup_len in (90, 70, 50, 40):
            cup_start = gi - cup_len
            if cup_start < 0: continue
            left_rim = max(bars[j]['high'] for j in range(cup_start, cup_start+5))
            cup_bottom_idx = min(range(cup_start, gi), key=lambda j: bars[j]['low'])
            cup_bottom = bars[cup_bottom_idx]['low']
            if cup_bottom_idx - cup_start < cup_len*0.25 or gi - cup_bottom_idx < cup_len*0.15: continue
            cup_depth = left_rim - cup_bottom
            if cup_depth <= 0: continue
            handle_start = cup_bottom_idx + int(cup_len*0.5)
            if handle_start >= gi - 2: continue
            handle_low = min(bars[j]['low'] for j in range(handle_start, gi))
            handle_depth = left_rim - handle_low
            if handle_depth > cup_depth * handle_depth_frac: continue
            rim = left_rim
            if bars[gi-1]['close'] > rim: continue
            if bars[gi]['close'] > rim:
                atr = ATR[sym][gi]
                if not atr: return None
                return (atr*stop_atr, atr*target_atr)
        return None
    return sig


def gen_rs_leader_pullback(C, rsi_band, lookback, rr):
    stop_atr, target_atr = rr
    lo, hi = rsi_band
    bars_by_sym, ATR, EMA21 = C['bars_by_sym'], C['ATR'], C['EMA21']
    RSI_N = {sym: SWE.rsi_n([b['close'] for b in bars_by_sym[sym]], 14) for sym in bars_by_sym}
    def sig(sym, gi):
        bars = bars_by_sym[sym]
        if gi < lookback + 5: return None
        rets = {}
        for s in SWING_SYMBOLS:
            b = bars_by_sym.get(s)
            if not b or gi >= len(b) or gi < lookback + 1: continue
            rets[s] = (b[gi-1]['close'] - b[gi-1-lookback]['close']) / b[gi-1-lookback]['close']
        if not rets or sym not in rets: return None
        if rets[sym] != max(rets.values()): return None
        r = RSI_N[sym][gi]
        if r is None or not (lo <= r <= hi): return None
        ema21 = EMA21[sym][gi]
        if bars[gi]['close'] <= ema21: return None
        if not (bars[gi]['close'] > bars[gi-1]['close']): return None
        atr = ATR[sym][gi]
        if not atr: return None
        return (atr*stop_atr, atr*target_atr)
    return sig


# ---------------------------------------------------------------------------
# Day-trading generators - close over the SAME precomputed IND swing_paper_engine.py
# uses (via DT.build_indicators), reproducing structural logic exactly.
# ---------------------------------------------------------------------------

def gen_dt_swing_pullback(bars_by_sym, IND, touch_mult, rr):
    stop_mult, target_mult = rr
    def sig(bbs, DAYIDX, sym, gi):
        bars = bars_by_sym[sym]
        if gi < 15: return None
        e9 = IND[sym]['ema9']
        if e9[gi] <= e9[gi-2]: return None
        touched = bars[gi-1]['low'] <= e9[gi-1] * touch_mult
        bounced = bars[gi]['close'] > e9[gi] and bars[gi]['close'] > bars[gi-1]['close']
        if touched and bounced:
            rng = sum(bars[j]['high'] - bars[j]['low'] for j in range(gi-5, gi+1)) / 6
            if rng <= 0: return None
            return (rng * stop_mult, rng * target_mult)
        return None
    return sig


def gen_dt_hybrid_scalping(bars_by_sym, IND, vol_mult, rsi_band, rr):
    stop_mult, target_mult = rr
    lo, hi = rsi_band
    def sig(bbs, DAYIDX, sym, gi):
        bars = bars_by_sym[sym]
        if gi < 20: return None
        r = IND[sym]['rsi14']
        if r[gi] is None or r[gi-1] is None: return None
        vol_avg5 = sum(bars[j]['volume'] for j in range(gi-5, gi)) / 5
        if vol_avg5 <= 0: return None
        vol_surge = bars[gi]['volume'] > vol_mult * vol_avg5
        rsi_ok = lo <= r[gi] <= hi and r[gi] > r[gi-1]
        breakout = bars[gi]['close'] > max(bars[j]['high'] for j in range(gi-3, gi))
        if vol_surge and rsi_ok and breakout:
            rng = sum(bars[j]['high'] - bars[j]['low'] for j in range(gi-5, gi+1)) / 6
            if rng <= 0: return None
            return (rng * stop_mult, rng * target_mult)
        return None
    return sig


def gen_dt_gap_momentum(bars_by_sym, DAYIDX, gap_thresh, rr):
    stop_mult, target_mult = rr
    def sig(bbs, dayidx, sym, gi):
        bars = bars_by_sym[sym]
        meta = DAYIDX[sym][gi]
        if meta['i_in_day'] != 1: return None
        pc = meta['prev_day_close']
        if pc is None or pc <= 0: return None
        open_bar = bars[gi - 1]
        gap_pct = (open_bar['open'] - pc) / pc
        if gap_pct < gap_thresh: return None
        holds_gap = bars[gi]['close'] > open_bar['open'] * 0.995
        confirms = bars[gi]['close'] > open_bar['close'] or bars[gi]['volume'] > open_bar['volume']
        if holds_gap and confirms:
            rng = open_bar['high'] - open_bar['low']
            if rng <= 0: return None
            return (rng * stop_mult, rng * target_mult)
        return None
    return sig


def gen_dt_opening_range_breakout(bars_by_sym, DAYIDX, or_bars, rr):
    stop_mult, target_mult = rr
    def sig(bbs, dayidx, sym, gi):
        bars = bars_by_sym[sym]
        meta = DAYIDX[sym][gi]
        i_in_day = meta['i_in_day']
        if i_in_day != or_bars: return None
        day_start = gi - i_in_day
        or_high = max(bars[j]['high'] for j in range(day_start, day_start + or_bars))
        or_low = min(bars[j]['low'] for j in range(day_start, day_start + or_bars))
        or_range = or_high - or_low
        if or_range <= 0: return None
        vol_avg = sum(bars[j]['volume'] for j in range(max(0, gi-10), gi)) / max(1, gi - max(0, gi-10))
        if vol_avg <= 0: return None
        if bars[gi]['close'] > or_high and bars[gi]['volume'] > vol_avg:
            return (or_range * stop_mult, or_range * target_mult)
        return None
    return sig


def gen_dt_id_nr4(bars_by_sym, DAYIDX, nr_days, breakout_window, rr):
    stop_mult, target_mult = rr
    def sig(bbs, dayidx, sym, gi):
        meta = DAYIDX[sym][gi]
        if meta['i_in_day'] != 0: return None
        bars = bars_by_sym[sym]
        j = gi - 1
        days_ranges = {}
        while j >= 0 and len(days_ranges) < nr_days:
            dt = bars[j]['date']
            days_ranges.setdefault(dt, {'high': -1e18, 'low': 1e18})
            days_ranges[dt]['high'] = max(days_ranges[dt]['high'], bars[j]['high'])
            days_ranges[dt]['low'] = min(days_ranges[dt]['low'], bars[j]['low'])
            j -= 1
        ordered_dates = sorted(days_ranges.keys())
        if len(ordered_dates) < nr_days: return None
        last_n = ordered_dates[-nr_days:]
        d_yest, d_prior = last_n[-1], last_n[:-1]
        yest, prior_days = days_ranges[d_yest], [days_ranges[d] for d in d_prior]
        yest_range = yest['high'] - yest['low']
        if yest_range <= 0: return None
        is_inside = yest['high'] < prior_days[-1]['high'] and yest['low'] > prior_days[-1]['low']
        is_narrowest = all(yest_range < (p['high'] - p['low']) for p in prior_days)
        if not (is_inside and is_narrowest): return None
        for k in range(gi, min(gi + breakout_window, len(bars))):
            if bars[k]['close'] > yest['high']:
                return (yest_range * stop_mult, yest_range * target_mult)
        return None
    return sig


def gen_dt_relative_volume_leader(bars_by_sym, DAYIDX, min_i_in_day, vol_ratio_thresh, rr):
    stop_mult, target_mult = rr
    def sig(bbs, dayidx, sym, gi):
        meta = DAYIDX[sym][gi]
        if meta['i_in_day'] < min_i_in_day: return None
        bars = bars_by_sym[sym]
        ratios = {}
        for s in bars_by_sym:
            b2 = bars_by_sym[s]; m2 = DAYIDX[s]
            if gi >= len(b2) or m2[gi]['i_in_day'] < min_i_in_day: continue
            avg5 = sum(b2[j]['volume'] for j in range(gi-5, gi)) / 5
            if avg5 <= 0: continue
            ratios[s] = b2[gi]['volume'] / avg5
        if not ratios or sym not in ratios: return None
        if ratios[sym] != max(ratios.values()) or ratios[sym] < vol_ratio_thresh: return None
        if bars[gi]['close'] <= max(bars[j]['high'] for j in range(gi-3, gi)): return None
        rng = sum(bars[j]['high']-bars[j]['low'] for j in range(gi-5, gi+1)) / 6
        if rng <= 0: return None
        return (rng * stop_mult, rng * target_mult)
    return sig


def gen_dt_oversold_snapback(bars_by_sym, DAYIDX, min_i_in_day, lookback, drop_thresh, rr):
    stop_mult, target_mult = rr
    def sig(bbs, dayidx, sym, gi):
        meta = DAYIDX[sym][gi]
        if meta['i_in_day'] < min_i_in_day: return None
        bars = bars_by_sym[sym]
        start_price = bars[gi-lookback]['close']
        low_price = min(bars[j]['low'] for j in range(gi-lookback, gi))
        drop = (start_price - low_price) / start_price
        if drop < drop_thresh: return None
        midpoint = (start_price+low_price)/2
        if bars[gi]['close'] > midpoint and bars[gi]['close'] > bars[gi-1]['close']:
            rng = sum(bars[j]['high']-bars[j]['low'] for j in range(gi-lookback, gi+1)) / (lookback+1)
            if rng <= 0: return None
            return (rng * stop_mult, rng * target_mult)
        return None
    return sig


def gen_dt_first_pullback_orb(bars_by_sym, DAYIDX, rr):
    stop_mult, target_mult = rr
    def sig(bbs, dayidx, sym, gi):
        bars = bars_by_sym[sym]
        meta = DAYIDX[sym][gi]
        day_start = gi - meta['i_in_day']
        if meta['i_in_day'] < 3: return None
        or_high = max(bars[day_start]['high'], bars[day_start + 1]['high'])
        broke_out = any(bars[j]['close'] > or_high for j in range(day_start + 2, gi))
        if not broke_out: return None
        if bars[gi - 1]['close'] <= or_high: return None
        pulled_back = gi - 2 >= day_start and bars[gi - 1]['low'] <= bars[gi - 2]['high']
        bounced = bars[gi]['close'] > bars[gi - 1]['close'] and bars[gi]['close'] > or_high
        if pulled_back and bounced:
            rng = or_high - min(bars[day_start]['low'], bars[day_start + 1]['low'])
            if rng <= 0: return None
            return (rng * stop_mult, rng * target_mult)
        return None
    return sig


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def report(name, res, n=5):
    print(f"=== {name} - top {n} ===")
    for r in res[:n]:
        print(f"  {r['params']}  windows_profitable={r['n_profit']}/5  total={r['total']:>10,.2f}  per_window={r['window_pls']}")
    print()


def baseline_row(name, gen_fn, params, bars_by_sym, atr_or_dayidx, windows, **kwargs):
    pass


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python3 walkforward_search_batch2.py <daily_hist.json> <thirty_min_1yr_hist.json>")
        sys.exit(1)

    daily_path, intraday_path = sys.argv[1], sys.argv[2]

    C = build_swing_ctx(daily_path)
    daily_dates = sorted(set(b['date'] for b in next(iter(C['bars_by_sym'].values()))))
    # need dates per-symbol union, not just first symbol
    daily_dates = sorted(set(b['date'] for bars in C['bars_by_sym'].values() for b in bars))
    daily_windows = make_windows(daily_dates, 5)
    atr_by_sym = C['ATR']  # for search_swing_general's unused atr_by_sym positional arg

    dt_bars_by_sym, IND, DAYIDX = DT.build_indicators(intraday_path)
    intraday_dates = sorted(set(b['date'] for bars in dt_bars_by_sym.values() for b in bars))
    intraday_windows = make_windows(intraday_dates, 5)

    print("Daily windows:", daily_windows)
    print("Intraday windows:", intraday_windows)
    print()

    # ============================= SWING =============================

    grid = [{'lookback': lb, 'rr': rr} for lb in (40, 60, 80) for rr in ((1.75, 3.5), (2.0, 4.0), (2.0, 5.0), (2.5, 4.5))]
    res = search_swing_general('E: Minervini VCP', lambda **p: gen_minervini_vcp(C, **p), grid, C['bars_by_sym'], atr_by_sym, daily_windows, min_hold=2)
    report('E: Minervini VCP Breakout', res)

    grid = [{'squeeze_lookback': sl, 'rr': rr} for sl in (30, 50, 70) for rr in ((1.75, 3.5), (2.0, 4.0), (2.0, 5.0), (2.5, 4.5))]
    res = search_swing_general('Bollinger Squeeze Breakout', lambda **p: gen_bollinger_squeeze(C, **p), grid, C['bars_by_sym'], atr_by_sym, daily_windows, min_hold=2)
    report('Bollinger Squeeze Breakout', res)

    grid = [{'shift': sh, 'rr': rr} for sh in (9, 26) for rr in ((1.75, 3.5), (2.0, 4.0), (2.0, 5.0), (2.5, 4.5))]
    res = search_swing_general('Ichimoku Kumo Breakout', lambda **p: gen_ichimoku(C, **p), grid, C['bars_by_sym'], atr_by_sym, daily_windows, min_hold=2)
    report('Ichimoku Kumo Breakout', res)

    grid = [{'gain_thresh': gt, 'rr': rr} for gt in (0.10, 0.15, 0.20) for rr in ((1.75, 3.5), (2.0, 4.0), (2.0, 5.0), (2.5, 4.5))]
    res = search_swing_general('Bull Flag Breakout', lambda **p: gen_bull_flag(C, **p), grid, C['bars_by_sym'], atr_by_sym, daily_windows, min_hold=2)
    report('Bull Flag Breakout', res)

    grid = [{'rr': rr} for rr in ((1.5, 3.0), (1.75, 3.5), (2.0, 4.0), (2.0, 5.0), (2.5, 4.5), (2.5, 5.0))]
    res = search_swing_general('RSI Bullish Divergence', lambda **p: gen_rsi_bullish_divergence(C, **p), grid, C['bars_by_sym'], atr_by_sym, daily_windows, min_hold=2)
    report('RSI Bullish Divergence', res)

    grid = [{'tol': tol, 'rr': rr} for tol in (0.97, 0.98, 0.99) for rr in ((1.75, 3.5), (2.0, 4.0), (2.0, 5.0), (2.5, 4.5))]
    res = search_swing_general('Fibonacci 61.8% Retracement Bounce', lambda **p: gen_fib_618(C, **p), grid, C['bars_by_sym'], atr_by_sym, daily_windows, min_hold=2)
    report('Fibonacci 61.8% Retracement Bounce', res)

    grid = [{'gain_thresh': gt, 'rr': rr} for gt in (0.70, 0.90, 1.10) for rr in ((1.75, 3.5), (2.0, 4.0), (2.0, 5.0), (2.5, 4.5))]
    res = search_swing_general('High Tight Flagpole', lambda **p: gen_high_tight_flagpole(C, **p), grid, C['bars_by_sym'], atr_by_sym, daily_windows, min_hold=2)
    report('High Tight Flagpole', res)

    grid = [{'oversold': ov, 'rr': rr} for ov in (5, 10, 15, 20) for rr in ((1.5, 3.0), (1.75, 3.5), (2.0, 4.0), (2.0, 5.0))]
    res = search_swing_general('ConnorsRSI Oversold Bounce', lambda **p: gen_connors_rsi(C, **p), grid, C['bars_by_sym'], atr_by_sym, daily_windows, min_hold=2)
    report('ConnorsRSI Oversold Bounce', res)

    grid = [{'fast': f, 'slow': s, 'rr': rr} for f, s in ((5, 20), (9, 21), (12, 26)) for rr in ((1.75, 3.5), (2.0, 4.0), (2.0, 5.0), (2.5, 4.5))]
    res = search_swing_general('MA Crossover (H)', lambda **p: gen_ma_crossover(C, **p), grid, C['bars_by_sym'], atr_by_sym, daily_windows, min_hold=2)
    report('MA Crossover (H)', res)

    grid = [{'handle_depth_frac': hdf, 'rr': rr} for hdf in (1/2, 1/3, 1/4) for rr in ((1.75, 3.5), (2.0, 4.0), (2.0, 5.0), (2.5, 4.5))]
    res = search_swing_general('Cup and Handle', lambda **p: gen_cup_and_handle(C, **p), grid, C['bars_by_sym'], atr_by_sym, daily_windows, min_hold=2)
    report('Cup and Handle', res)

    grid = [{'rsi_band': band, 'lookback': lb, 'rr': rr} for band in ((40, 55), (35, 60), (45, 65)) for lb in (10, 21, 34) for rr in ((1.75, 3.5), (2.0, 4.0))]
    res = search_swing_general('Relative Strength Leader Pullback', lambda **p: gen_rs_leader_pullback(C, **p), grid, C['bars_by_sym'], atr_by_sym, daily_windows, min_hold=2)
    report('Relative Strength Leader Pullback', res)

    # ============================= DAY-TRADING =============================

    def dt_search(name, gen_fn, grid, continuous):
        results = []
        for params in grid:
            sig_fn = gen_fn(**params)
            window_pls = [backtest_daytrade_window(dt_bars_by_sym, DAYIDX, sig_fn, continuous, w[0], w[1]) for w in intraday_windows]
            n_profit = sum(1 for p in window_pls if p > 0)
            total = round(sum(window_pls), 2)
            results.append({'params': params, 'window_pls': window_pls, 'n_profit': n_profit, 'total': total})
        results.sort(key=lambda r: (-r['n_profit'], -r['total']))
        return results

    grid = [{'touch_mult': tm, 'rr': rr} for tm in (1.002, 1.003, 1.005) for rr in ((1, 2), (1, 3), (1.5, 3))]
    res = dt_search('Swing Pullback / Anti', lambda **p: gen_dt_swing_pullback(dt_bars_by_sym, IND, **p), grid, continuous=True)
    report('Swing Pullback / Anti', res)

    grid = [{'vol_mult': vm, 'rsi_band': band, 'rr': rr} for vm in (1.5, 2.0, 2.5) for band in ((50, 75), (45, 80)) for rr in ((1, 2), (1, 3))]
    res = dt_search('Hybrid Disciplined Momentum Scalping', lambda **p: gen_dt_hybrid_scalping(dt_bars_by_sym, IND, **p), grid, continuous=True)
    report('Hybrid Disciplined Momentum Scalping', res)

    grid = [{'gap_thresh': gt, 'rr': rr} for gt in (0.010, 0.015, 0.020) for rr in ((1, 2), (1, 3), (0.75, 2))]
    res = dt_search('Gap / High Change Momentum', lambda **p: gen_dt_gap_momentum(dt_bars_by_sym, DAYIDX, **p), grid, continuous=False)
    report('Gap / High Change Momentum', res)

    grid = [{'or_bars': ob, 'rr': rr} for ob in (2, 3, 4) for rr in ((1, 2), (1, 3), (0.75, 2))]
    res = dt_search('Opening Range Breakout', lambda **p: gen_dt_opening_range_breakout(dt_bars_by_sym, DAYIDX, **p), grid, continuous=True)
    report('Opening Range Breakout', res)

    grid = [{'nr_days': nd, 'breakout_window': bw, 'rr': rr} for nd in (4, 5, 6) for bw in (8, 13, 20) for rr in ((1, 2), (1, 3))]
    res = dt_search('ID/NR4 Volatility Breakout', lambda **p: gen_dt_id_nr4(dt_bars_by_sym, DAYIDX, **p), grid, continuous=True)
    report('ID/NR4 Volatility Breakout', res)

    grid = [{'min_i_in_day': mi, 'vol_ratio_thresh': vt, 'rr': rr} for mi in (4, 6, 8) for vt in (1.3, 1.5, 2.0) for rr in ((1, 2), (1, 3))]
    res = dt_search('Relative Volume Leader Momentum', lambda **p: gen_dt_relative_volume_leader(dt_bars_by_sym, DAYIDX, **p), grid, continuous=True)
    report('Relative Volume Leader Momentum', res)

    grid = [{'min_i_in_day': mi, 'lookback': lb, 'drop_thresh': dt_, 'rr': rr} for mi in (4,) for lb in (2, 3, 4) for dt_ in (0.015, 0.02, 0.03) for rr in ((1, 2), (1, 3))]
    res = dt_search('Oversold Snapback Fade', lambda **p: gen_dt_oversold_snapback(dt_bars_by_sym, DAYIDX, **p), grid, continuous=True)
    report('Oversold Snapback Fade', res)

    grid = [{'rr': rr} for rr in ((0.5, 1), (0.5, 1.5), (0.75, 2), (1, 2))]
    res = dt_search('First Pullback After ORB (H2)', lambda **p: gen_dt_first_pullback_orb(dt_bars_by_sym, DAYIDX, **p), grid, continuous=True)
    report('First Pullback After ORB (H2)', res)
