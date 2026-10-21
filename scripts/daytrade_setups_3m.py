#!/usr/bin/env python3
"""Ten well-known day-trading setups vs everything explored here, $15k, Jul 13 -> Oct 21 2026
(asked 2026-10-21: "backtest the 10 best day trading setups out there and the ideas explored
over the last 3 months on a 15k account and see P&L by today").

DATA: real 5-minute bars, data/semis_5min_2026-07-10_2026-10-21.json (72 trading days from
07-13, 0 missing, interpolated bars dropped). Same 8 chip stocks as the live system.

RULES FOR EVERY SETUP -- FIXED BEFORE ANY RUN, textbook parameters, nothing tuned:
  * long only (a cash account cannot short); flat by the close every day
  * $15k split equally across the 8 stocks each morning (equity compounds day to day)
  * ONE round trip per stock per day: in a cash account, re-buying with that day's unsettled
    sale proceeds and selling again the same day is a good-faith violation
  * signal on a bar's CLOSE, entry at the NEXT bar's open (no look-ahead)
  * stops/targets checked inside each bar; if both could hit in one bar the STOP is assumed
    first; a bar opening through the stop fills at its open
  * 5 bps per side (ESTIMATED cost)
Times are UTC (the whole window is daylight time: session 13:30-20:00 UTC).

  1 ORB-15      15-min opening range; first close above its high (by 15:30) -> buy; stop OR low
  2 ORB-30 2R   30-min opening range; close above high (by 16:00); stop OR low; target 2R
  3 VWAP reclaim  close crosses back above session VWAP (14:00-19:00); stop = signal-bar low;
                exit on a close back below VWAP
  4 Gap-and-go  opens >= +2% vs prior close and first bar green -> buy bar 2; stop bar-1 low
  5 Gap-fill    opens <= -1.5% vs prior close -> buy bar 2; target prior close; stop -1.5%
  6 EMA 9/20    5-min EMA9 crosses above EMA20 (13:45-19:00); exit on the cross back down
  7 Bollinger   close below the 20-bar lower band (2 sd) -> buy; exit at the middle band;
                stop -1.5%
  8 PDH break   close above the prior day's high -> buy; stop prior day's close
  9 Last-30 momentum  prior close -> 10:00 ET return > 0 -> buy 15:30 ET, sell at the close
                (Gao, Han, Li & Zhou intraday momentum)
 10 Red-to-green  opens below prior close; first close back above it (by 16:00) -> buy;
                stop = day's low so far

Ideas explored earlier, on the same window and $15k (engine replays, hourly 17:00 basis):
Margin-Style Live (production), volatility sizing 3% (D), C1, buy & hold; v3 baseline /
tightened come from data/research/v3_weekly_pnl_15000*.json (Aug 10 -> Oct 16 only).

Reproduce:  python3 scripts/daytrade_setups_3m.py            # 3 months, Jul 13 -> Oct 21
            python3 scripts/daytrade_setups_3m.py --6m       # 6 months, Apr 21 -> Oct 21
                (data/semis_5min_2026-04-17_2026-10-21.json; same rules, nothing re-tuned)
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
DATA = os.path.join(ROOT, 'data', 'semis_5min_2026-07-10_2026-10-21.json')
CAP, COST, START, END = 15000.0, 5e-4, '2026-07-13', '2026-10-21'
SIX = '--6m' in sys.argv
if SIX:
    DATA = os.path.join(ROOT, 'data', 'semis_5min_2026-04-17_2026-10-21.json')
    START = '2026-04-21'


def ema(xs, n):
    k, out, e = 2 / (n + 1), [], None
    for x in xs:
        e = x if e is None else e + k * (x - e)
        out.append(e)
    return out


class Day:
    """One symbol-day plus context the setups may read (all causal)."""
    def __init__(self, rows, prev_rows, hist_closes):
        self.t = [r[0] for r in rows]
        self.o = [r[1] for r in rows]; self.h = [r[2] for r in rows]
        self.l = [r[3] for r in rows]; self.c = [r[4] for r in rows]; self.v = [r[5] for r in rows]
        self.pc = prev_rows[-1][4]
        self.pdh = max(r[2] for r in prev_rows)
        pv = cv = 0.0
        self.vwap = []
        for i in range(len(rows)):
            tp = (self.h[i] + self.l[i] + self.c[i]) / 3
            pv += tp * self.v[i]; cv += self.v[i]
            self.vwap.append(pv / cv if cv else self.c[i])
        allc = hist_closes + self.c                       # indicators warm up across days
        k = len(hist_closes)
        self.e9 = ema(allc, 9)[k:]; self.e20 = ema(allc, 20)[k:]
        self.mid, self.lo = [], []
        for i in range(len(rows)):
            w = allc[k + i - 19:k + i + 1]
            m = sum(w) / len(w); sd = math.sqrt(sum((x - m) ** 2 for x in w) / len(w))
            self.mid.append(m); self.lo.append(m - 2 * sd)

    def idx(self, hhmm):
        return next((i for i, t in enumerate(self.t) if t >= hhmm), None)


def trade(d, entry_i, stop=None, target=None, exit_when=None):
    """Run one long position from bar entry_i's open. exit_when(i) -> True exits at the next open.
    Returns gross return (fraction) or None."""
    if entry_i is None or entry_i >= len(d.t):
        return None
    px = d.o[entry_i]
    if target is not None and callable(target):
        target = target(px)
    if stop is not None and callable(stop):
        stop = stop(px)
    for i in range(entry_i, len(d.t)):
        if stop is not None and d.l[i] <= stop:
            return min(stop, d.o[i]) / px - 1
        if target is not None and d.h[i] >= target:
            return max(target, d.o[i]) / px - 1
        if exit_when and i + 1 < len(d.t) and exit_when(i):
            return d.o[i + 1] / px - 1
    return d.c[-1] / px - 1


def first(d, cond, lo='00:00', hi='23:59'):
    for i, t in enumerate(d.t):
        if lo <= t <= hi and cond(i):
            return i
    return None


def s1(d):
    hi, lo = max(d.h[:3]), min(d.l[:3])
    i = first(d, lambda i: i >= 3 and d.c[i] > hi, hi='15:30')
    return trade(d, i + 1 if i is not None else None, stop=lo)


def s2(d):
    hi, lo = max(d.h[:6]), min(d.l[:6])
    i = first(d, lambda i: i >= 6 and d.c[i] > hi, hi='16:00')
    return trade(d, i + 1 if i is not None else None, stop=lo, target=lambda px: px + 2 * (px - lo))


def s3(d):
    i = first(d, lambda i: i > 0 and d.c[i - 1] < d.vwap[i - 1] and d.c[i] > d.vwap[i], lo='14:00', hi='19:00')
    if i is None:
        return None
    return trade(d, i + 1, stop=d.l[i], exit_when=lambda j: j > i and d.c[j] < d.vwap[j])


def s4(d):
    if d.o[0] >= d.pc * 1.02 and d.c[0] > d.o[0]:
        return trade(d, 1, stop=d.l[0])
    return None


def s5(d):
    if d.o[0] <= d.pc * 0.985:
        return trade(d, 1, stop=lambda px: px * 0.985, target=d.pc)
    return None


def s6(d):
    i = first(d, lambda i: i > 0 and d.e9[i - 1] <= d.e20[i - 1] and d.e9[i] > d.e20[i], lo='13:45', hi='19:00')
    if i is None:
        return None
    return trade(d, i + 1, exit_when=lambda j: j > i and d.e9[j] < d.e20[j])


def s7(d):
    i = first(d, lambda i: d.c[i] < d.lo[i], lo='13:45', hi='19:00')
    if i is None:
        return None
    return trade(d, i + 1, stop=lambda px: px * 0.985, exit_when=lambda j: j > i and d.c[j] >= d.mid[j])


def s8(d):
    i = first(d, lambda i: d.c[i] > d.pdh, hi='19:00')
    return trade(d, i + 1, stop=d.pc) if i is not None else None


def s9(d):
    k = d.idx('13:55')
    if k is not None and d.c[k] > d.pc:
        return trade(d, d.idx('19:30'))
    return None


def s10(d):
    if d.o[0] >= d.pc:
        return None
    i = first(d, lambda i: d.c[i] > d.pc, hi='16:00')
    if i is None:
        return None
    return trade(d, i + 1, stop=min(d.l[:i + 1]))


SETUPS = {'1 ORB-15': s1, '2 ORB-30, 2R target': s2, '3 VWAP reclaim': s3, '4 Gap-and-go': s4,
          '5 Gap-fill': s5, '6 EMA 9/20 cross': s6, '7 Bollinger reversion': s7,
          '8 Prior-day-high break': s8, '9 Last-30-min momentum': s9, '10 Red-to-green': s10}


def run_setups():
    raw = json.load(open(DATA))['bars']
    syms = sorted(raw)
    days = sorted(raw[syms[0]])
    res = {}
    for name, fn in SETUPS.items():
        eq, curve, trades, wins = CAP, {}, 0, 0
        for di, day in enumerate(days):
            if day < START or day > END or di == 0:
                continue
            slice_ = eq / len(syms)
            pnl = 0.0
            for s in syms:
                hist = [r[4] for dd in days[max(0, di - 2):di] for r in raw[s][dd]]
                g = fn(Day(raw[s][day], raw[s][days[di - 1]], hist))
                if g is None:
                    continue
                net = (1 + g) * (1 - COST) / (1 + COST) - 1
                pnl += slice_ * net; trades += 1; wins += net > 0
            eq += pnl
            curve[day] = round(eq, 2)
        res[name] = {'curve': curve, 'trades': trades, 'win_rate': round(wins / trades * 100, 1) if trades else 0}
    return res, [d for d in days if START <= d <= END]


def engine_rows(days):
    """Margin-Style Live and its variants, same window, $15k, data through 10-21."""
    import margin_style_protect_rules as P1
    import margin_style_protect_rules2 as P2
    P1.DAILY = os.path.join(ROOT, 'data', 'margin_live_daily_ext_2025-11-03_2026-10-21.json')
    P1.HOURLY = os.path.join(ROOT, 'data', 'margin_live_hourly_ext_2026-03-06_2026-10-21.json')
    out = {}
    for name, key in [('Margin-Style Live (production)', 'PRODUCTION'),
                      ('Margin-Style + volatility sizing 3%', 'D volatility sizing 3%'),
                      ('C1: fast kill-switch + vol sizing', 'C1 fast switch + vol sizing (round 1)')]:
        r = P2.run(START, END, P2.VARIANTS[key], CAP, f"dt{'6' if SIX else '3'}m_{key.split()[0]}")
        out[name] = {'curve': r['day_equity'], 'trades': r['trades'], 'win_rate': None}
    hd = json.load(open(P1.HOURLY))
    chk = {x['symbol']: {b['begins_at'][:10]: float(b['close_price']) for b in x['bars'] if b['begins_at'][11:16] == '17:00'}
           for x in hd['data']['results']}
    d0 = min(d for d in chk['AMD'] if d >= START)
    sh = {s: CAP / 8 * (1 - COST) / chk[s][d0] for s in chk}
    out['Buy & hold the 8 stocks'] = {'curve': {d: round(sum(sh[s] * chk[s][d] for s in chk), 2)
                                                for d in sorted(chk['AMD']) if START <= d <= END},
                                      'trades': 8, 'win_rate': None}
    for name, f in [('v3 day-trading, baseline*', 'v3_weekly_pnl_15000.json'),
                    ('v3 day-trading, tightened*', 'v3_weekly_pnl_15000_tightened.json')]:
        w = json.load(open(os.path.join(ROOT, 'data', 'research', f)))['weeks']
        out[name] = {'curve': {x['last_day']: x['end_equity'] for x in w}, 'trades': w[-1]['cum_trades'],
                     'win_rate': None, 'partial': 'Aug 10 -> Oct 16 only (1-minute data limit)'}
    return out


def stats(curve, cap=CAP):
    v = [x for _, x in sorted(curve.items())]
    peak, dd = cap, 0.0
    for x in v:
        peak = max(peak, x); dd = min(dd, x / peak - 1)
    return v[-1], (v[-1] / cap - 1) * 100, dd * 100, max(v)


def half(curve, mid):
    a = [x for d, x in sorted(curve.items()) if d <= mid]
    b = [x for d, x in sorted(curve.items()) if d > mid]
    if not a or not b:
        return None, None
    return (a[-1] / CAP - 1) * 100, (b[-1] / a[-1] - 1) * 100


def main():
    res, days = run_setups()
    res.update(engine_rows(days))
    mid = days[len(days) // 2 - 1]
    rows = []
    for name, r in res.items():
        end, ret, dd, pk = stats(r['curve'])
        h1, h2 = half(r['curve'], mid)
        rows.append((ret, name, end, dd, pk, h1, h2, r['trades'], r['win_rate'], r.get('partial')))
    rows.sort(reverse=True)
    print(f"{START} -> {END}, $15,000, 5 bps/side. Halves split after {mid}.\n")
    print(f"{'setup':38}{'ends at':>10}{'return':>9}{'worst dd':>10}{'1st half':>10}{'2nd half':>10}{'trades':>8}{'win%':>7}")
    for ret, name, end, dd, pk, h1, h2, n, wr, part in rows:
        f = lambda x: f"{x:+.1f}%" if x is not None else '-'
        print(f"{name:38}{end:>10,.0f}{ret:>+8.1f}%{dd:>+9.1f}%{f(h1):>10}{f(h2):>10}{n:>8}{(str(wr) if wr is not None else '-'):>7}")
    json.dump({'window': [START, END], 'capital': CAP, 'cost_per_side': COST, 'half_split_after': mid,
               'results': {name: {'end': end, 'return_pct': round(ret, 2), 'max_dd_pct': round(dd, 2),
                                  'first_half_pct': h1, 'second_half_pct': h2, 'trades': n, 'win_rate': wr,
                                  'note': part, 'curve': res[name]['curve']}
                           for ret, name, end, dd, pk, h1, h2, n, wr, part in rows}},
              open(os.path.join(ROOT, 'data', 'research', 'daytrade_setups_6m.json' if SIX else 'daytrade_setups_3m.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
