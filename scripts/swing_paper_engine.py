"""Incremental paper-trading engine for the 9 backtested swing-strategy candidates
(daily bars, multi-day holds - different mechanics from daytrade_paper_engine.py,
which is 30-min bars with forced end-of-day close).

Usage: python3 scripts/swing_paper_engine.py <fresh_daily_historicals.json>

Reads/writes docs/swing_paper_state.json (open paper positions + cash per strategy)
and appends to docs/swing_paper_log.json (trade-by-trade + per-run equity snapshot).
Places NO real orders - this only maintains simulated positions in JSON.
"""
import json, math, sys, os, statistics
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, 'docs', 'swing_paper_state.json')
LOG_PATH = os.path.join(ROOT, 'docs', 'swing_paper_log.json')
SYMBOLS = ["AMD", "MU", "WDC", "SNDK", "TSM"]
CAPITAL_PER_STRATEGY = 25000.0
MAXP = 5
MAXNEW_PER_BAR = 2
MIN_HOLD_FOR_TARGET = 2


def atr_series(bars, period=14):
    trs = [bars[0]['high'] - bars[0]['low']]
    for i in range(1, len(bars)):
        tr = max(bars[i]['high'] - bars[i]['low'],
                  abs(bars[i]['high'] - bars[i-1]['close']),
                  abs(bars[i]['low'] - bars[i-1]['close']))
        trs.append(tr)
    out = [None] * len(bars)
    if len(trs) < period: return out
    atr = sum(trs[:period]) / period
    out[period-1] = atr
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
        out[i] = atr
    return out


def rsi_n(closes, period):
    out = [None] * len(closes)
    if len(closes) < period + 1: return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        ch = closes[i] - closes[i-1]
        if ch >= 0: gains += ch
        else: losses -= ch
    avg_g, avg_l = gains / period, losses / period
    out[period] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    for i in range(period + 1, len(closes)):
        ch = closes[i] - closes[i-1]
        g = max(ch, 0); l = max(-ch, 0)
        avg_g = (avg_g * (period - 1) + g) / period
        avg_l = (avg_l * (period - 1) + l) / period
        out[i] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    return out


def connors_rsi_series(bars):
    closes = [b['close'] for b in bars]
    rsi3 = rsi_n(closes, 3)
    streak = [0] * len(closes)
    for i in range(1, len(closes)):
        if closes[i] > closes[i-1]:
            streak[i] = streak[i-1] + 1 if streak[i-1] > 0 else 1
        elif closes[i] < closes[i-1]:
            streak[i] = streak[i-1] - 1 if streak[i-1] < 0 else -1
        else:
            streak[i] = 0
    streak_rsi = rsi_n([float(s) for s in streak], 2)
    pct_rank = [None] * len(closes)
    for i in range(100, len(closes)):
        today_ret = (closes[i] - closes[i-1]) / closes[i-1]
        window_rets = [(closes[j] - closes[j-1]) / closes[j-1] for j in range(i-99, i+1)]
        rank = sum(1 for r in window_rets if r < today_ret) / len(window_rets) * 100
        pct_rank[i] = rank
    out = [None] * len(closes)
    for i in range(len(closes)):
        if rsi3[i] is not None and streak_rsi[i] is not None and pct_rank[i] is not None:
            out[i] = (rsi3[i] + streak_rsi[i] + pct_rank[i]) / 3
    return out


def find_pivot_lows(bars, strength=5):
    lows = [b['low'] for b in bars]
    pivots = []
    for i in range(strength, len(bars) - strength):
        window = lows[i-strength:i+strength+1]
        if lows[i] == min(window):
            pivots.append(i)
    return pivots


def ema_series(vals, period):
    k = 2 / (period + 1)
    out = [vals[0]]
    for v in vals[1:]: out.append(v * k + out[-1] * (1 - k))
    return out


def find_pivots_hl(bars, strength=2):
    pivots = []
    for i in range(strength, len(bars) - strength):
        whigh = [bars[j]['high'] for j in range(i-strength, i+strength+1)]
        wlow = [bars[j]['low'] for j in range(i-strength, i+strength+1)]
        if bars[i]['high'] == max(whigh): pivots.append(('H', i, bars[i]['high']))
        if bars[i]['low'] == min(wlow): pivots.append(('L', i, bars[i]['low']))
    pivots.sort(key=lambda x: x[1])
    return pivots


def resample(bars, key_fn):
    groups = {}
    for b in bars:
        k = key_fn(b['date'])
        groups.setdefault(k, []).append(b)
    out = []
    for k in sorted(groups.keys()):
        g = groups[k]
        out.append({'key': k, 'high': max(x['high'] for x in g), 'low': min(x['low'] for x in g),
                    'close': g[-1]['close'], 'last_date': g[-1]['date']})
    return out


def ichimoku_series(bars):
    def donch_mid(j, period):
        if j - period + 1 < 0: return None
        hh = max(bars[k]['high'] for k in range(j-period+1, j+1))
        ll = min(bars[k]['low'] for k in range(j-period+1, j+1))
        return (hh + ll) / 2
    n = len(bars)
    tenkan = [donch_mid(j, 9) for j in range(n)]
    kijun = [donch_mid(j, 26) for j in range(n)]
    senkouB_raw = [donch_mid(j, 52) for j in range(n)]
    senkouA_raw = [(tenkan[j] + kijun[j]) / 2 if tenkan[j] is not None and kijun[j] is not None else None for j in range(n)]
    return tenkan, kijun, senkouA_raw, senkouB_raw


def build_context(raw_path):
    d = json.load(open(raw_path))
    bars_by_sym = {}
    for r in d['data']['results']:
        sym = r['symbol']
        bars = []
        for b in r['bars']:
            bars.append({
                'date': b['begins_at'][:10],
                'open': float(b['open_price']), 'close': float(b['close_price']),
                'high': float(b['high_price']), 'low': float(b['low_price']),
                'volume': float(b.get('volume', 0) or 0),
            })
        bars_by_sym[sym] = bars
    ATR = {sym: atr_series(bars_by_sym[sym]) for sym in SYMBOLS if sym in bars_by_sym}
    CRSI = {sym: connors_rsi_series(bars_by_sym[sym]) for sym in SYMBOLS if sym in bars_by_sym}
    PIVOT_LOWS = {sym: find_pivot_lows(bars_by_sym[sym]) for sym in SYMBOLS if sym in bars_by_sym}
    WEEKLY = {sym: resample(bars_by_sym[sym], lambda dte: dte[:8] + str(int(dte[8:10]) // 7)) for sym in SYMBOLS if sym in bars_by_sym}
    MONTHLY = {sym: resample(bars_by_sym[sym], lambda dte: dte[:7]) for sym in SYMBOLS if sym in bars_by_sym}
    ICHI = {sym: ichimoku_series(bars_by_sym[sym]) for sym in SYMBOLS if sym in bars_by_sym}
    RSI14 = {sym: rsi_n([b['close'] for b in bars_by_sym[sym]], 14) for sym in SYMBOLS if sym in bars_by_sym}
    EMA21 = {sym: ema_series([b['close'] for b in bars_by_sym[sym]], 21) for sym in SYMBOLS if sym in bars_by_sym}
    EMA9 = {sym: ema_series([b['close'] for b in bars_by_sym[sym]], 9) for sym in SYMBOLS if sym in bars_by_sym}
    PIVOTS_HL = {sym: find_pivots_hl(bars_by_sym[sym]) for sym in SYMBOLS if sym in bars_by_sym}
    return bars_by_sym, ATR, CRSI, PIVOT_LOWS, WEEKLY, MONTHLY, ICHI, RSI14, EMA21, PIVOTS_HL, EMA9


def make_signals(ctx):
    bars_by_sym, ATR, CRSI, PIVOT_LOWS, WEEKLY, MONTHLY, ICHI, RSI14, EMA21, PIVOTS_HL, EMA9 = ctx

    def sig_bollinger_squeeze(sym, gi):
        bars = bars_by_sym[sym]
        if gi < 70: return None
        closes = [bars[j]['close'] for j in range(gi-19, gi+1)]
        ma20 = statistics.mean(closes); sd20 = statistics.pstdev(closes)
        upper, lower = ma20 + 2*sd20, ma20 - 2*sd20
        bw = (upper - lower) / ma20
        bw_hist = []
        for k in range(gi-49, gi):
            c2 = [bars[j]['close'] for j in range(k-19, k+1)]
            m2 = statistics.mean(c2); s2 = statistics.pstdev(c2)
            bw_hist.append((m2+2*s2 - (m2-2*s2)) / m2)
        if not bw_hist: return None
        if bw <= min(bw_hist) and bars[gi]['close'] > upper:
            atr = ATR[sym][gi]
            if not atr: return None
            return (bw, atr * 1.75, atr * 3.5)
        return None

    def sig_donchian_breakout(sym, gi, period=20):
        bars = bars_by_sym[sym]
        if gi < period + 15: return None
        prior_high = max(bars[j]['high'] for j in range(gi-period, gi))
        if bars[gi-1]['close'] <= prior_high and bars[gi]['close'] > prior_high:
            atr = ATR[sym][gi]
            if not atr: return None
            return ((bars[gi]['close'] - prior_high) / prior_high, atr * 1.75, atr * 3.5)
        return None

    def sig_probe_pullback(sym, gi, range_window=10):
        bars = bars_by_sym[sym]
        if gi < range_window + 20: return None
        for probe_back in range(2, 8):
            p = gi - probe_back
            if p - range_window < 0: continue
            range_high = max(bars[j]['high'] for j in range(p - range_window, p))
            if bars[p]['close'] <= range_high: continue
            held = all(bars[j]['low'] >= range_high * 0.985 for j in range(p+1, gi))
            resumed = bars[gi]['close'] > bars[gi-1]['close'] and bars[gi]['close'] > range_high
            if held and resumed:
                atr = ATR[sym][gi]
                if not atr: return None
                return ((bars[gi]['close'] - range_high) / range_high, atr * 1.75, atr * 3.5)
        return None

    def sig_midas(sym, gi):
        bars = bars_by_sym[sym]
        pivots = [p for p in PIVOT_LOWS[sym] if p + 5 <= gi and p < gi]
        if not pivots: return None
        launch = None
        for p in reversed(pivots):
            cum_pv = cum_v = 0.0
            broke = False
            for j in range(p, gi):
                cum_pv += bars[j]['close'] * bars[j]['volume']
                cum_v += bars[j]['volume']
                if cum_v <= 0: continue
                curve_j = cum_pv / cum_v
                if bars[j]['close'] < curve_j * 0.97:
                    broke = True
                    break
            if not broke:
                launch = p
                break
        if launch is None: return None
        cum_pv = sum(bars[j]['close'] * bars[j]['volume'] for j in range(launch, gi))
        cum_v = sum(bars[j]['volume'] for j in range(launch, gi))
        if cum_v <= 0: return None
        curve = cum_pv / cum_v
        touched = bars[gi-1]['low'] <= curve * 1.01 and bars[gi-1]['close'] >= curve * 0.99
        bounced = bars[gi]['close'] > curve and bars[gi]['close'] > bars[gi-1]['close']
        if touched and bounced:
            atr = ATR[sym][gi]
            if not atr: return None
            return ((bars[gi]['close'] - curve) / curve + 0.001, atr * 1.75, atr * 3.5)
        return None

    def sig_perfect_storm(sym, gi, daily_period=20, weekly_lookback=8, monthly_lookback=3):
        bars = bars_by_sym[sym]
        if gi < daily_period + 5: return None
        today_date = bars[gi]['date']
        prior_daily_high = max(bars[j]['high'] for j in range(gi-daily_period, gi))
        if bars[gi]['close'] <= prior_daily_high: return None
        wk = WEEKLY[sym]
        wk_idx = next((i for i, w in enumerate(wk) if w['last_date'] >= today_date), len(wk)-1)
        if wk_idx < weekly_lookback: return None
        prior_wk_high = max(w['high'] for w in wk[wk_idx-weekly_lookback:wk_idx])
        weekly_breakout = bars[gi]['close'] > prior_wk_high
        mo = MONTHLY[sym]
        mo_idx = next((i for i, m in enumerate(mo) if m['last_date'] >= today_date), len(mo)-1)
        if mo_idx < monthly_lookback: return None
        monthly_up = mo[max(0,mo_idx-1)]['close'] > mo[mo_idx-monthly_lookback]['close']
        if weekly_breakout and monthly_up:
            atr = ATR[sym][gi]
            if not atr: return None
            return ((bars[gi]['close'] - prior_daily_high) / prior_daily_high, atr * 1.75, atr * 3.5)
        return None

    def sig_connors_rsi(sym, gi, oversold=10):
        bars = bars_by_sym[sym]
        if gi < 105: return None
        crsi = CRSI[sym][gi]
        if crsi is None: return None
        sma50 = statistics.mean(bars[j]['close'] for j in range(gi-49, gi+1))
        if crsi < oversold and bars[gi]['close'] > sma50:
            atr = ATR[sym][gi]
            if not atr: return None
            return ((oversold - crsi) + 0.01, atr * 1.5, atr * 3.0)
        return None

    def sig_minervini_vcp(sym, gi, lookback=60):
        bars = bars_by_sym[sym]
        if gi < lookback + 5: return None
        swing_idx = list(range(gi-lookback, gi))
        pivots = []
        for i in range(2, len(swing_idx)-2):
            gi2 = swing_idx[i]
            if bars[gi2]['high'] > bars[gi2-1]['high'] and bars[gi2]['high'] > bars[gi2-2]['high'] and \
               bars[gi2]['high'] > bars[gi2+1]['high'] and bars[gi2]['high'] > bars[gi2+2]['high']:
                pivots.append(('H', gi2, bars[gi2]['high']))
            if bars[gi2]['low'] < bars[gi2-1]['low'] and bars[gi2]['low'] < bars[gi2-2]['low'] and \
               bars[gi2]['low'] < bars[gi2+1]['low'] and bars[gi2]['low'] < bars[gi2+2]['low']:
                pivots.append(('L', gi2, bars[gi2]['low']))
        pivots.sort(key=lambda x: x[1])
        contractions = []
        for i in range(len(pivots)-1):
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
            return ((bars[gi]['close'] - tightest_high) / tightest_high, atr * 1.75, atr * 3.5)
        return None

    def sig_ichimoku(sym, gi, shift=26):
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
            return ((bars[gi]['close'] - cloud_top) / cloud_top + 0.001, atr * 1.75, atr * 3.5)
        return None

    def sig_pivot_point_bounce(sym, gi):
        bars = bars_by_sym[sym]
        if gi < 3: return None
        y = bars[gi-1]
        P = (y['high'] + y['low'] + y['close']) / 3
        S1 = (P * 2) - y['high']
        touched = bars[gi-1]['low'] <= S1 * 1.01 or bars[gi]['low'] <= S1 * 1.01
        bounced = bars[gi]['close'] > S1 and bars[gi]['close'] > bars[gi-1]['close']
        trend_ok = bars[gi]['close'] > P
        if touched and bounced and trend_ok:
            atr = ATR[sym][gi]
            if not atr: return None
            return ((bars[gi]['close'] - S1) / S1 + 0.001, atr * 1.5, atr * 3.0)
        return None

    def sig_cup_and_handle(sym, gi):
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
            if handle_depth > cup_depth/3: continue
            rim = left_rim
            if bars[gi-1]['close'] > rim: continue
            if bars[gi]['close'] > rim:
                atr = ATR[sym][gi]
                if not atr: return None
                return ((bars[gi]['close']-rim)/rim, atr*1.75, atr*3.5)
        return None

    def sig_high_tight_flagpole(sym, gi):
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
                if gain < 0.90: continue
                flag_high = pole_high
                flag_low = min(bars[j]['low'] for j in range(pole_end, gi))
                pullback = (flag_high - flag_low) / flag_high
                if not (0.10 <= pullback <= 0.25): continue
                if bars[gi-1]['close'] > flag_high: continue
                if bars[gi]['close'] > flag_high:
                    atr = ATR[sym][gi]
                    if not atr: return None
                    return (gain, atr*1.75, atr*3.5)
        return None

    def sig_rs_leader_pullback(sym, gi):
        bars = bars_by_sym[sym]
        if gi < 25: return None
        rets = {}
        for s in SYMBOLS:
            b = bars_by_sym.get(s)
            if not b or gi >= len(b) or gi < 21: continue
            rets[s] = (b[gi-1]['close'] - b[gi-21]['close']) / b[gi-21]['close']
        if not rets or sym not in rets: return None
        if rets[sym] != max(rets.values()): return None
        r = RSI14[sym][gi]
        if r is None or not (40 <= r <= 55): return None
        ema21 = EMA21[sym][gi]
        if bars[gi]['close'] <= ema21: return None
        if not (bars[gi]['close'] > bars[gi-1]['close']): return None
        atr = ATR[sym][gi]
        if not atr: return None
        return (rets[sym], atr*1.75, atr*3.5)

    def sig_fib_618_retracement(sym, gi):
        bars = bars_by_sym[sym]
        if gi < 30: return None
        piv = [p for p in PIVOTS_HL[sym] if p[1] < gi]
        if len(piv) < 2: return None
        last2 = piv[-2:]
        if not (last2[0][0]=='L' and last2[1][0]=='H'): return None
        swing_low, swing_high = last2[0][2], last2[1][2]
        if swing_high <= swing_low: return None
        fib618 = swing_high - 0.618*(swing_high-swing_low)
        fib50 = swing_high - 0.5*(swing_high-swing_low)
        touched = bars[gi-1]['low'] <= fib50 and bars[gi-1]['low'] >= fib618*0.98
        bounced = bars[gi]['close'] > bars[gi-1]['high'] and bars[gi]['close'] > fib50
        if touched and bounced:
            atr = ATR[sym][gi]
            if not atr: return None
            return ((bars[gi]['close']-fib618)/fib618, atr*1.75, atr*3.5)
        return None

    def sig_rsi_bullish_divergence(sym, gi):
        bars = bars_by_sym[sym]
        r = RSI14[sym]
        if gi < 30: return None
        piv_lows = [p for p in PIVOTS_HL[sym] if p[0]=='L' and p[1] < gi]
        if len(piv_lows) < 2: return None
        p1, p2 = piv_lows[-2], piv_lows[-1]
        if p2[2] >= p1[2]: return None
        if r[p1[1]] is None or r[p2[1]] is None: return None
        if r[p2[1]] <= r[p1[1]]: return None
        piv_highs = [p for p in PIVOTS_HL[sym] if p[0]=='H' and p1[1] < p[1] < p2[1]]
        if not piv_highs: return None
        confirm_level = max(p[2] for p in piv_highs)
        if bars[gi-1]['close'] > confirm_level: return None
        if bars[gi]['close'] > confirm_level:
            atr = ATR[sym][gi]
            if not atr: return None
            return ((r[p2[1]]-r[p1[1]]) + 0.01, atr*1.75, atr*3.5)
        return None

    def sig_bull_flag_swing(sym, gi):
        bars = bars_by_sym[sym]
        if gi < 25: return None
        for flag_len in range(5, 16):
            pole_end = gi - flag_len
            if pole_end < 10: continue
            pole_start = pole_end - 10
            pole_low = min(bars[j]['low'] for j in range(pole_start, pole_end))
            pole_high = max(bars[j]['high'] for j in range(pole_start, pole_end))
            gain = (pole_high-pole_low)/pole_low
            if gain < 0.15: continue
            flag_low = min(bars[j]['low'] for j in range(pole_end, gi))
            pullback = (pole_high-flag_low)/pole_high
            if not (0.30 <= pullback <= 0.50): continue
            if bars[gi-1]['close'] > pole_high: continue
            if bars[gi]['close'] > pole_high:
                atr = ATR[sym][gi]
                if not atr: return None
                return (gain, atr*1.75, atr*3.5)
        return None

    def sig_ma_crossover(sym, gi):
        # Same math as live 9-Way Combo Signal H, using the completed daily bar as "today"
        # (no live-quote proxy needed in a daily-bar paper backtest).
        bars = bars_by_sym[sym]
        if gi < 22: return None
        e9, e21 = EMA9[sym], EMA21[sym]
        if e9[gi] is None or e21[gi] is None or e9[gi-1] is None or e21[gi-1] is None: return None
        if e9[gi] > e21[gi] and not (e9[gi-1] > e21[gi-1]):
            atr = ATR[sym][gi]
            if not atr: return None
            return ((e9[gi] - e21[gi]) / e21[gi], atr * 1.75, atr * 3.5)
        return None

    def sig_darvas_box(sym, gi):
        # Same math as live 9-Way Combo Signal I.
        bars = bars_by_sym[sym]
        if gi < 30: return None
        lookback_start = max(0, gi - 252)
        high_ref = max(bars[j]['high'] for j in range(lookback_start, gi))
        box_candidates = []
        for k_off in range(2, 12):
            k = gi - k_off
            if k < 0: continue
            if abs(bars[k]['high'] - high_ref) / high_ref <= 0.005:
                box_candidates.append(k)
        if not box_candidates: return None
        box_start = min(box_candidates)
        span = bars[box_start:gi]
        if not span: return None
        box_top = max(b['high'] for b in span)
        box_bottom = min(b['low'] for b in span)
        if box_top <= 0 or (box_top - box_bottom) / box_top > 0.08: return None
        if bars[gi-1]['close'] <= box_top and bars[gi]['close'] > box_top:
            atr = ATR[sym][gi]
            if not atr: return None
            return ((bars[gi]['close'] - box_top) / box_top, atr * 1.75, atr * 3.5)
        return None

    # Minervini VCP, Donchian, and Asymmetric Pullback graduated to the live 9-Way Combo -
    # removed here to avoid double-tracking. MA Crossover and Darvas Box (added 2026-07-22 to
    # the live combo directly, skipping paper-tracking per explicit user request) are added here
    # too so their behavior can now also be observed on an isolated $25k paper account, same as
    # every other not-yet-fully-vetted signal. The 6 setups below them (sourced from widely-cited
    # retail/YouTube trading content) are paper-only pending further validation; Relative Strength
    # Leader Pullback backtested negative (-$582, 0/5 windows) and is included here for continued
    # observation, not because it looked promising.
    return {
        'Bollinger Squeeze Breakout': sig_bollinger_squeeze,
        'Probe and Pullback': sig_probe_pullback,
        'MIDAS Anchored VWAP Bounce': sig_midas,
        'Perfect Storm (D/W/M alignment)': sig_perfect_storm,
        'ConnorsRSI Oversold Bounce': sig_connors_rsi,
        'Ichimoku Kumo Breakout': sig_ichimoku,
        'Pivot Point S1 Bounce': sig_pivot_point_bounce,
        'Cup and Handle': sig_cup_and_handle,
        'High Tight Flagpole': sig_high_tight_flagpole,
        'Relative Strength Leader Pullback': sig_rs_leader_pullback,
        'Fibonacci 61.8% Retracement Bounce': sig_fib_618_retracement,
        'RSI Bullish Divergence': sig_rsi_bullish_divergence,
        'Bull Flag Breakout': sig_bull_flag_swing,
        'MA Crossover (H)': sig_ma_crossover,
        'Darvas Box (I)': sig_darvas_box,
    }


def load_state(strategy_names):
    if os.path.exists(STATE_PATH):
        return json.load(open(STATE_PATH))
    return {name: {'cash': CAPITAL_PER_STRATEGY, 'positions': {}, 'last_processed_date': {}} for name in strategy_names}


def load_log(strategy_names):
    if os.path.exists(LOG_PATH):
        return json.load(open(LOG_PATH))
    return {'capital_per_strategy': CAPITAL_PER_STRATEGY, 'symbols': SYMBOLS,
            'strategies': strategy_names, 'note': 'PAPER TRADING ONLY - no real orders placed. Daily bars, multi-day holds.',
            'runs': []}


def run(raw_path):
    ctx = build_context(raw_path)
    bars_by_sym = ctx[0]
    signals = make_signals(ctx)
    state = load_state(list(signals.keys()))
    log = load_log(list(signals.keys()))
    run_trades = []
    now = datetime.now(timezone.utc).isoformat()

    for name, sig_fn in signals.items():
        st = state.setdefault(name, {'cash': CAPITAL_PER_STRATEGY, 'positions': {}, 'last_processed_date': {}})
        cash = st['cash']
        positions = st['positions']
        last_processed = st['last_processed_date']

        for sym in SYMBOLS:
            if sym not in bars_by_sym: continue
            bars = bars_by_sym[sym]
            last_dt = last_processed.get(sym)
            if last_dt is None:
                start_gi = max(0, len(bars) - 2)
            else:
                start_gi = next((i for i, b in enumerate(bars) if b['date'] > last_dt), len(bars))

            for gi in range(start_gi, len(bars)):
                bar = bars[gi]

                if sym in positions:
                    pos = positions[sym]
                    held_days = gi - pos['entry_gi']
                    exit_reason = None
                    if bar['low'] <= pos['stop']:
                        exit_reason = 'STOP'
                    elif held_days >= MIN_HOLD_FOR_TARGET and bar['high'] >= pos['target']:
                        exit_reason = 'TARGET'
                    if exit_reason:
                        exit_price = pos['stop'] if exit_reason == 'STOP' else pos['target']
                        pnl = pos['shares'] * (exit_price - pos['entry'])
                        cash += pos['shares'] * exit_price
                        run_trades.append({'strategy': name, 'date': bar['date'], 'symbol': sym, 'side': 'SELL',
                                            'reason': exit_reason, 'entry': round(pos['entry'], 2),
                                            'exit': round(exit_price, 2), 'shares': pos['shares'], 'pnl': round(pnl, 2)})
                        del positions[sym]

                if sym not in positions and len(positions) < MAXP:
                    r = sig_fn(sym, gi)
                    if r is not None:
                        score, stop_dist, target_dist = r
                        price = bar['close']
                        tv = cash + sum(positions[s]['shares'] * bars_by_sym[s][min(gi, len(bars_by_sym[s])-1)]['close'] for s in positions)
                        target_notional = tv / MAXP
                        shares = math.floor(target_notional / price)
                        if shares >= 1 and shares * price <= cash:
                            cash -= shares * price
                            positions[sym] = {'entry': price, 'shares': shares, 'entry_gi': gi,
                                               'stop': price - stop_dist, 'target': price + target_dist}
                            run_trades.append({'strategy': name, 'date': bar['date'], 'symbol': sym, 'side': 'BUY',
                                                'shares': shares, 'price': round(price, 2)})

                last_processed[sym] = bar['date']

        st['cash'] = cash
        st['positions'] = positions
        st['last_processed_date'] = last_processed

    snapshot = {}
    for name in signals:
        st = state[name]
        hv = 0.0
        for sym, pos in st['positions'].items():
            if sym in bars_by_sym:
                hv += pos['shares'] * bars_by_sym[sym][-1]['close']
        snapshot[name] = round(st['cash'] + hv - CAPITAL_PER_STRATEGY, 2)

    log['runs'].append({'timestamp': now, 'trades': run_trades, 'equity_snapshot': snapshot})
    json.dump(state, open(STATE_PATH, 'w'), indent=1)
    json.dump(log, open(LOG_PATH, 'w'), indent=1)

    print(f"Swing paper-trading run {now}: {len(run_trades)} new trade event(s)")
    for t in run_trades:
        print(f"  {t}")
    print("\nCumulative paper P&L by strategy (since state was initialized):")
    for name, pl in sorted(snapshot.items(), key=lambda x: -x[1]):
        print(f"  {name:36}{pl:>12,.2f}")


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python3 swing_paper_engine.py <fresh_daily_historicals.json>")
        sys.exit(1)
    run(sys.argv[1])
