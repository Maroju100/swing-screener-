"""One-off ad hoc backtest (NOT a live/paper tracker - writes no state, touches no
other system's files) covering all 30 candidate strategies:
  - 22 "swing" (daily-bar) strategies, checked ONCE PER DAY (conceptually "at noon"
    -- irrelevant to a daily-bar backtest since there's only one decision point per
    day regardless of clock time; included for parity with the live noon-check cadence).
  - 8 "day-trading" (30-min-bar) strategies, checked TWICE PER DAY at two fixed
    intraday checkpoints (late morning / mid-afternoon) instead of continuously.

Each of the 30 strategies gets its OWN isolated $5,000 starting capital (not $25k
like the existing paper trackers) and its own settled-cash / GFV-safe bookkeeping:
sale proceeds go into pending_settlement and are not usable for a new buy until the
next business day, exactly like daytrade_live_engine.py / margin_style_live_engine.py.

Reuses the exact signal-detection code already used by the live paper trackers
(imported from swing_paper_engine.py and daytrade_paper_engine.py) for every
strategy that already has an implementation. The 5 strategies that only ever
existed as prose in the live 9-Way Combo's rules (A: 2B Reversal+Bollinger whipsaw,
B: 1-2-3 low breakout, C: Bressert RSI-3M3, D: Elder Impulse, G: Asymmetric
Pullback), plus Minervini VCP (E) and Donchian (F) which exist in swing_paper_engine.py
as functions but are excluded from its live dict (graduated to the 9-Way Combo,
tracked there instead), are (re)implemented here from their documented rules.

Usage: python3 scripts/backtest_5k_30d.py <daily_hist.json> <thirty_min_hist.json>
Prints a Net P&L (last 30 calendar days) table for all 30 strategies. No files written.
"""
import json, math, statistics, sys, os
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import swing_paper_engine as SW
import daytrade_paper_engine as DT

CAPITAL = 5000.0
SWING_SYMBOLS = SW.SYMBOLS
DT_SYMBOLS = DT.SYMBOLS
MAXP_SWING = 5
MAXP_DT = 3
MIN_HOLD_FOR_TARGET = 2

DT_CHECK_IDX = (3, 10)  # 11:00am ET and 2:30pm ET (bars start 9:30am ET, 30-min steps)


def next_business_day(d):
    d2 = d + timedelta(days=1)
    while d2.weekday() >= 5:
        d2 += timedelta(days=1)
    return d2


# ---------------------------------------------------------------------------
# Extra indicator series needed only by the 7 reimplemented signals (A,B,C,D,E,F,G)
# ---------------------------------------------------------------------------

def sma_series(closes, period):
    out = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        out[i] = sum(closes[i - period + 1:i + 1]) / period
    return out


def rsi2_series(closes):
    return SW.rsi_n(closes, 2)


def rsi3m3_series(closes):
    rsi3 = SW.rsi_n(closes, 3)
    out = [None] * len(closes)
    for i in range(2, len(closes)):
        if rsi3[i] is not None and rsi3[i - 1] is not None and rsi3[i - 2] is not None:
            out[i] = (rsi3[i] + rsi3[i - 1] + rsi3[i - 2]) / 3
    return out


def macd_hist_series(closes):
    ema12 = SW.ema_series(closes, 12)
    ema26 = SW.ema_series(closes, 26)
    macd = [a - b for a, b in zip(ema12, ema26)]
    sig = SW.ema_series(macd, 9)
    return [m - s for m, s in zip(macd, sig)]


def ema13_series(closes):
    return SW.ema_series(closes, 13)


def bollinger(bars, gi, period=20, mult=2.0):
    if gi < period - 1:
        return None, None
    closes = [bars[j]['close'] for j in range(gi - period + 1, gi + 1)]
    m = statistics.mean(closes)
    s = statistics.pstdev(closes)
    return m + mult * s, m - mult * s


def build_extra_context(bars_by_sym):
    SMA20, RSI2, RSI3M3, EMA13, MACDH = {}, {}, {}, {}, {}
    for sym in SWING_SYMBOLS:
        if sym not in bars_by_sym:
            continue
        closes = [b['close'] for b in bars_by_sym[sym]]
        SMA20[sym] = sma_series(closes, 20)
        RSI2[sym] = rsi2_series(closes)
        RSI3M3[sym] = rsi3m3_series(closes)
        EMA13[sym] = ema13_series(closes)
        MACDH[sym] = macd_hist_series(closes)
    return SMA20, RSI2, RSI3M3, EMA13, MACDH


def make_reimplemented_signals(bars_by_sym, ATR, PIVOTS_HL, extra):
    SMA20, RSI2, RSI3M3, EMA13, MACDH = extra

    def sig_A_2b_reversal(sym, gi):
        bars = bars_by_sym[sym]
        if gi < 15:
            return None
        for back in range(1, 4):
            k = gi - back
            if k < 12:
                continue
            prior_low = min(bars[j]['low'] for j in range(k - 10, k))
            upper, lower = bollinger(bars, k)
            fakeout = bars[k]['low'] < prior_low or (lower is not None and bars[k]['low'] < lower)
            if not fakeout:
                continue
            if bars[gi]['close'] > prior_low and bars[gi]['close'] > bars[k]['close'] and bars[gi]['volume'] >= bars[k]['volume']:
                atr = ATR[sym][gi]
                if not atr:
                    return None
                return ((bars[gi]['close'] - prior_low) / prior_low, atr * 1.75, atr * 3.5)
        return None

    def sig_B_123_breakout(sym, gi):
        bars = bars_by_sym[sym]
        if gi < 45:
            return None
        piv = [p for p in PIVOTS_HL[sym] if p[1] < gi]
        if len(piv) < 3:
            return None
        trio = piv[-3:]
        if not (trio[0][0] == 'L' and trio[1][0] == 'H' and trio[2][0] == 'L'):
            return None
        P1, P2, P3 = trio
        if not (P3[2] > P1[2] and (gi - P3[1]) <= 15 and (gi - P1[1]) <= 45):
            return None
        if bars[gi - 1]['close'] <= P2[2] and bars[gi]['close'] > P2[2]:
            atr = ATR[sym][gi]
            if not atr:
                return None
            return ((bars[gi]['close'] - P2[2]) / P2[2], atr * 1.75, atr * 3.5)
        return None

    def sig_C_bressert(sym, gi):
        bars = bars_by_sym[sym]
        if gi < 10:
            return None
        r = RSI3M3[sym]
        for back in range(1, 4):
            k = gi - back
            if k < 1 or r[k] is None or r[k - 1] is None:
                continue
            setup = r[k - 1] < 30 and r[k] > r[k - 1]
            if setup and bars[gi]['close'] > bars[k]['high']:
                atr = ATR[sym][gi]
                if not atr:
                    return None
                return ((bars[gi]['close'] - bars[k]['high']) / bars[k]['high'] + 0.001, atr * 1.75, atr * 3.5)
        return None

    def sig_D_elder_impulse(sym, gi):
        bars = bars_by_sym[sym]
        if gi < 16:
            return None
        e13, mh = EMA13[sym], MACDH[sym]
        if None in (e13[gi], e13[gi - 1], e13[gi - 2], mh[gi], mh[gi - 1], mh[gi - 2]):
            return None
        green_today = e13[gi] > e13[gi - 1] and mh[gi] > mh[gi - 1]
        green_yest = e13[gi - 1] > e13[gi - 2] and mh[gi - 1] > mh[gi - 2]
        if green_today and not green_yest:
            atr = ATR[sym][gi]
            if not atr:
                return None
            return (mh[gi] - mh[gi - 1] + 0.01, atr * 1.75, atr * 3.5)
        return None

    def sig_E_minervini_vcp(sym, gi, lookback=60):
        bars = bars_by_sym[sym]
        if gi < lookback + 5:
            return None
        swing_idx = list(range(gi - lookback, gi))
        pivots = []
        for i in range(2, len(swing_idx) - 2):
            gi2 = swing_idx[i]
            if bars[gi2]['high'] > bars[gi2 - 1]['high'] and bars[gi2]['high'] > bars[gi2 - 2]['high'] and \
               bars[gi2]['high'] > bars[gi2 + 1]['high'] and bars[gi2]['high'] > bars[gi2 + 2]['high']:
                pivots.append(('H', gi2, bars[gi2]['high']))
            if bars[gi2]['low'] < bars[gi2 - 1]['low'] and bars[gi2]['low'] < bars[gi2 - 2]['low'] and \
               bars[gi2]['low'] < bars[gi2 + 1]['low'] and bars[gi2]['low'] < bars[gi2 + 2]['low']:
                pivots.append(('L', gi2, bars[gi2]['low']))
        pivots.sort(key=lambda x: x[1])
        contractions = []
        for i in range(len(pivots) - 1):
            if pivots[i][0] == 'H' and pivots[i + 1][0] == 'L':
                pct = (pivots[i][2] - pivots[i + 1][2]) / pivots[i][2]
                contractions.append((pivots[i][1], pivots[i + 1][1], pivots[i][2], pct))
        if len(contractions) < 2:
            return None
        last_two = contractions[-2:]
        if not (last_two[0][3] > last_two[1][3]):
            return None
        tightest_high = last_two[-1][2]
        if bars[gi - 1]['close'] <= tightest_high and bars[gi]['close'] > tightest_high:
            atr = ATR[sym][gi]
            if not atr:
                return None
            return ((bars[gi]['close'] - tightest_high) / tightest_high, atr * 1.75, atr * 3.5)
        return None

    def sig_F_donchian(sym, gi, period=20):
        bars = bars_by_sym[sym]
        if gi < period + 15:
            return None
        prior_high = max(bars[j]['high'] for j in range(gi - period, gi))
        if bars[gi - 1]['close'] <= prior_high and bars[gi]['close'] > prior_high:
            atr = ATR[sym][gi]
            if not atr:
                return None
            return ((bars[gi]['close'] - prior_high) / prior_high, atr * 1.75, atr * 3.5)
        return None

    def sig_G_asymmetric_pullback(sym, gi):
        bars = bars_by_sym[sym]
        if gi < 20:
            return None
        sma20, r2 = SMA20[sym][gi], RSI2[sym][gi]
        if sma20 is None or r2 is None:
            return None
        if bars[gi]['close'] > sma20 and r2 <= 40:
            atr = ATR[sym][gi]
            if not atr:
                return None
            return (40 - r2, atr * 1.75, atr * 3.5)
        return None

    return {
        'A: 2B Reversal + Bollinger Whipsaw': sig_A_2b_reversal,
        'B: Joe Ross 1-2-3 Low Breakout': sig_B_123_breakout,
        'C: Bressert RSI-3M3 Cycle Buy': sig_C_bressert,
        'D: Elder Impulse Green-Turn': sig_D_elder_impulse,
        'E: Minervini VCP Breakout': sig_E_minervini_vcp,
        'F: Donchian/Turtle Channel Breakout': sig_F_donchian,
        'G: Asymmetric Pullback': sig_G_asymmetric_pullback,
    }


# ---------------------------------------------------------------------------
# Swing backtest: ONE check per trading day, $5,000 isolated capital, settled cash
# ---------------------------------------------------------------------------

def run_swing_backtest(daily_path, window_days=30):
    ctx = SW.build_context(daily_path)
    bars_by_sym, ATR = ctx[0], ctx[1]
    PIVOTS_HL = ctx[9]
    live_signals = SW.make_signals(ctx)
    extra = build_extra_context(bars_by_sym)
    reimplemented = make_reimplemented_signals(bars_by_sym, ATR, PIVOTS_HL, extra)
    signals = {}
    signals.update(reimplemented)  # A,B,C,D,E,F,G first (canonical order)
    signals.update(live_signals)   # 15 more (includes H, I)

    dates = sorted(set(b['date'] for bars in bars_by_sym.values() for b in bars))
    date_idx = {sym: {b['date']: i for i, b in enumerate(bars_by_sym[sym])} for sym in bars_by_sym}
    today = dates[-1]
    cutoff_dt = (datetime.strptime(today, '%Y-%m-%d') - timedelta(days=window_days)).strftime('%Y-%m-%d')

    results = {}
    for name, sig_fn in signals.items():
        cash = CAPITAL
        pending = []  # list of [settle_date_str, amount]
        positions = {}
        equity_at_cutoff = None
        equity_final = None

        for dt in dates:
            released = [p for p in pending if p[0] <= dt]
            for p in released:
                cash += p[1]
            pending = [p for p in pending if p[0] > dt]

            for sym in list(positions.keys()):
                gi = date_idx.get(sym, {}).get(dt)
                if gi is None:
                    continue
                bars = bars_by_sym[sym]
                pos = positions[sym]
                held_days = gi - pos['entry_gi']
                exit_reason = None
                if bars[gi]['low'] <= pos['stop']:
                    exit_reason = 'STOP'
                elif held_days >= MIN_HOLD_FOR_TARGET and bars[gi]['high'] >= pos['target']:
                    exit_reason = 'TARGET'
                if exit_reason:
                    exit_price = pos['stop'] if exit_reason == 'STOP' else pos['target']
                    proceeds = pos['shares'] * exit_price
                    pending.append([next_business_day(datetime.strptime(dt, '%Y-%m-%d')).strftime('%Y-%m-%d'), proceeds])
                    del positions[sym]

            if len(positions) < MAXP_SWING:
                for sym in SWING_SYMBOLS:
                    if sym in positions or len(positions) >= MAXP_SWING:
                        continue
                    gi = date_idx.get(sym, {}).get(dt)
                    if gi is None:
                        continue
                    r = sig_fn(sym, gi)
                    if r is None:
                        continue
                    score, stop_dist, target_dist = r
                    price = bars_by_sym[sym][gi]['close']
                    pending_total = sum(p[1] for p in pending)
                    posval = sum(positions[s]['shares'] * bars_by_sym[s][date_idx[s].get(dt, positions[s]['entry_gi'])]['close'] for s in positions)
                    tv = cash + pending_total + posval
                    target_notional = tv / MAXP_SWING
                    shares = target_notional / price
                    cost = shares * price
                    if shares > 0 and cost <= cash:
                        cash -= cost
                        positions[sym] = {'entry': price, 'shares': shares, 'entry_gi': gi,
                                           'stop': price - stop_dist, 'target': price + target_dist}

            pending_total = sum(p[1] for p in pending)
            posval = sum(positions[s]['shares'] * bars_by_sym[s][date_idx[s].get(dt, positions[s]['entry_gi'])]['close'] for s in positions)
            equity = cash + pending_total + posval
            if dt <= cutoff_dt:
                equity_at_cutoff = equity
            equity_final = equity

        base = equity_at_cutoff if equity_at_cutoff is not None else CAPITAL
        results[name] = {'net_pl_30d': round(equity_final - base, 2), 'equity_final': round(equity_final, 2)}
    return results


# ---------------------------------------------------------------------------
# Day-trading backtest: TWO checks per trading day, $5,000 isolated capital, settled cash
# ---------------------------------------------------------------------------

def run_daytrade_backtest(thirtymin_path, window_days=30):
    bars_by_sym, IND, DAYIDX = DT.build_indicators(thirtymin_path)
    names = ['Swing Pullback / Anti', 'Hybrid Disciplined Momentum Scalping', 'Gap / High Change Momentum',
              'Turtle Soup Reversal', 'Momentum Breakout', 'Mid-Range Reversion Rule',
              'Opening Range Breakout', 'ID/NR4 Volatility Breakout']
    signals = {n: DT.STRATEGIES[n] for n in names}

    all_dates = sorted(set(b['date'] for bars in bars_by_sym.values() for b in bars))
    today = all_dates[-1]
    cutoff_date = (datetime.strptime(today, '%Y-%m-%d') - timedelta(days=window_days)).strftime('%Y-%m-%d')

    # per-symbol: day -> list of global indices for that day, in order
    day_bars = {}
    for sym in DT_SYMBOLS:
        if sym not in bars_by_sym:
            continue
        day_bars[sym] = {}
        for gi, b in enumerate(bars_by_sym[sym]):
            day_bars[sym].setdefault(b['date'], []).append(gi)

    results = {}
    for name, sig_fn in signals.items():
        cash = CAPITAL
        pending = []
        positions = {}
        equity_at_cutoff = None
        equity_final = None

        for date in all_dates:
            released = [p for p in pending if p[0] <= date]
            for p in released:
                cash += p[1]
            pending = [p for p in pending if p[0] > date]

            for check_num, day_idx_target in enumerate(DT_CHECK_IDX):
                for sym in DT_SYMBOLS:
                    if sym not in day_bars or date not in day_bars[sym]:
                        continue
                    idxs = day_bars[sym][date]
                    if day_idx_target >= len(idxs):
                        check_gi = idxs[-1]
                        is_final_check = True
                    else:
                        check_gi = idxs[day_idx_target]
                        is_final_check = (check_num == len(DT_CHECK_IDX) - 1)
                    bars = bars_by_sym[sym]
                    day_start = idxs[0]

                    if sym in positions:
                        pos = positions[sym]
                        exit_reason = None
                        exit_price = None
                        for j in range(pos['last_checked_gi'] + 1, check_gi + 1):
                            if bars[j]['low'] <= pos['stop']:
                                exit_reason, exit_price = 'STOP', pos['stop']
                                break
                            if bars[j]['high'] >= pos['target']:
                                exit_reason, exit_price = 'TARGET', pos['target']
                                break
                        if exit_reason is None and is_final_check:
                            exit_reason, exit_price = 'EOD_CLOSE', bars[check_gi]['close']
                        if exit_reason:
                            proceeds = pos['shares'] * exit_price
                            pending.append([next_business_day(datetime.strptime(date, '%Y-%m-%d')).strftime('%Y-%m-%d'), proceeds])
                            del positions[sym]
                        else:
                            pos['last_checked_gi'] = check_gi

                    if sym not in positions and len(positions) < MAXP_DT:
                        fired = None
                        for j in range(day_start, check_gi + 1):
                            r = sig_fn(bars_by_sym, IND, DAYIDX, sym, j)
                            if r is not None:
                                fired = r
                        if fired is not None:
                            score, stop_dist, target_dist = fired
                            price = bars[check_gi]['close']
                            pending_total = sum(p[1] for p in pending)
                            posval = sum(positions[s]['shares'] * bars_by_sym[s][positions[s]['last_checked_gi']]['close'] for s in positions)
                            tv = cash + pending_total + posval
                            target_notional = tv / MAXP_DT
                            shares = target_notional / price
                            cost = shares * price
                            if shares > 0 and cost <= cash:
                                cash -= cost
                                positions[sym] = {'entry': price, 'shares': shares, 'stop': price - stop_dist,
                                                    'target': price + target_dist, 'last_checked_gi': check_gi}

            pending_total = sum(p[1] for p in pending)
            posval = sum(positions[s]['shares'] * bars_by_sym[s][positions[s]['last_checked_gi']]['close'] for s in positions)
            equity = cash + pending_total + posval
            if date <= cutoff_date:
                equity_at_cutoff = equity
            equity_final = equity

        base = equity_at_cutoff if equity_at_cutoff is not None else CAPITAL
        results[name] = {'net_pl_30d': round(equity_final - base, 2), 'equity_final': round(equity_final, 2)}
    return results


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python3 backtest_5k_30d.py <daily_hist.json> <thirty_min_hist.json>")
        sys.exit(1)
    swing_results = run_swing_backtest(sys.argv[1])
    dt_results = run_daytrade_backtest(sys.argv[2])

    print(f"\n=== SWING strategies (daily bars, 1 check/day, $5,000 isolated capital each) ===")
    for name, r in sorted(swing_results.items(), key=lambda x: -x[1]['net_pl_30d']):
        pct = r['net_pl_30d'] / CAPITAL * 100
        print(f"  {name:42} net_pl_30d={r['net_pl_30d']:>10,.2f}  ({pct:>6.2f}%)  equity={r['equity_final']:>10,.2f}")

    print(f"\n=== DAY-TRADING strategies (30-min bars, 2 checks/day, $5,000 isolated capital each) ===")
    for name, r in sorted(dt_results.items(), key=lambda x: -x[1]['net_pl_30d']):
        pct = r['net_pl_30d'] / CAPITAL * 100
        print(f"  {name:42} net_pl_30d={r['net_pl_30d']:>10,.2f}  ({pct:>6.2f}%)  equity={r['equity_final']:>10,.2f}")

    combined = {}
    combined.update({k: v['net_pl_30d'] for k, v in swing_results.items()})
    combined.update({k: v['net_pl_30d'] for k, v in dt_results.items()})
    print(json.dumps(combined))
