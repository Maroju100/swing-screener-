#!/usr/bin/env python3
"""Does the dashboard's "reversal check" tell you anything? (asked 2026-11-13)

The check, computed from DAILY bars only (the same definition the dashboard's JavaScript uses):
  buy share of a day   = sum over stocks of volume*close*(close-low)/(high-low)  /  sum of volume*close
                         (an ESTIMATE of buying vs selling pressure from where each stock closed in its range;
                          the broker gives no true buy/sell volume)
  basket index         = equal-weight average daily return, compounded
  C1 price   index above its own 10-day average
  C2 volume  5-day buy share above 50%
  C3 breadth at least 60% of the stocks above their own 10-day average
  C4 higher low   lowest index of the last 5 days above the lowest of the 5 days before
  score = number of conditions true (0-4).  "In a pullback" = index was 8%+ below its 60-day high at some point
  in the last 20 days.
Measured, for every pullback day and for the FIRST day the score reaches 4 in each pullback episode:
  index return over the next 10 trading days, share of cases positive, and the share where the index went on to
  fall a further 5%+ at some point in those 10 days ("put money in and watch it go lower").
Data: data/long_daily_2021-01-04_2026-11-12.json, Jul 2021 -> Nov 2026.  MEASURED, descriptive: the conditions were
chosen from standard practice before looking at these results and were NOT tuned; no trading rule was replayed.
Reproduce: python3 scripts/reversal_check_study.py
"""
import json, os, statistics as st
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = {r['symbol']: r['bars'] for r in json.load(open(os.path.join(ROOT, 'data', 'long_daily_2021-01-04_2026-11-12.json')))['data']['results']}
GROUPS = {'LIVE SEMIS 8': ['AMD', 'MU', 'WDC', 'SNDK', 'TSM', 'INTC', 'LRCX', 'STX'], 'OTHER CHIPS 7': ['AVGO', 'AMAT', 'KLAC', 'MRVL', 'QCOM', 'ASML', 'SMH'],
          'HIGH BETA 7': ['TSLA', 'COIN', 'PLTR', 'MSTR', 'SMCI', 'SHOP', 'NFLX'], 'LARGE CAPS 8': ['AAPL', 'MSFT', 'AMZN', 'META', 'GOOGL', 'JPM', 'XOM', 'CAT']}


def series(syms):
    bars = {s: {b['begins_at'][:10]: b for b in RAW[s]} for s in syms}
    days = sorted({d for s in syms for d in bars[s] if d <= '2026-11-11'})
    idx, buy, tot, breadth, I = [], [], [], [], 100.0
    hist = {s: [] for s in syms}
    for d in days:
        rs, bs, ts, ab, n = [], 0.0, 0.0, 0, 0
        for s in syms:
            b = bars[s].get(d)
            if not b:
                continue
            c, h, l, v = float(b['close_price']), float(b['high_price']), float(b['low_price']), float(b['volume'] or 0)
            if hist[s]:
                rs.append(c / hist[s][-1] - 1)
            f = (c - l) / (h - l) if h > l else 0.5
            bs += v * c * f; ts += v * c
            hist[s].append(c)
            if len(hist[s]) >= 10:
                n += 1; ab += c > sum(hist[s][-10:]) / 10
        I *= 1 + (sum(rs) / len(rs) if rs else 0)
        idx.append(I); buy.append(bs); tot.append(ts); breadth.append(ab / n if n else 0)
    return days, idx, buy, tot, breadth


def score(i, idx, buy, tot, breadth):
    c1 = idx[i] > sum(idx[i - 9:i + 1]) / 10
    c2 = sum(buy[i - 4:i + 1]) / max(1e-9, sum(tot[i - 4:i + 1])) > 0.5
    c3 = breadth[i] >= 0.6
    c4 = min(idx[i - 4:i + 1]) > min(idx[i - 9:i - 4])
    return [c1, c2, c3, c4]


def study(syms):
    days, idx, buy, tot, breadth = series(syms)
    rows, first = [], []
    in_ep, fired = False, False
    for i in range(80, len(days) - 10):
        if days[i] < '2021-07-12':
            continue
        pull = any(idx[j] / max(idx[max(0, j - 59):j + 1]) - 1 <= -0.08 for j in range(i - 19, i + 1))
        if not pull:
            in_ep = fired = False
            continue
        if not in_ep:
            in_ep, fired = True, False
        sc = sum(score(i, idx, buy, tot, breadth))
        fwd = idx[i + 10] / idx[i] - 1; worst = min(idx[i + 1:i + 11]) / idx[i] - 1
        rows.append((sc, fwd, worst))
        if sc == 4 and not fired:
            fired = True; first.append((days[i], fwd, worst))

    def agg(x):
        if not x:
            return None
        f = [a for a, _ in x]
        return {'n': len(x), 'mean10': st.mean(f) * 100, 'median10': st.median(f) * 100, 'pct_up': 100 * sum(a > 0 for a in f) / len(f),
                'pct_further_5': 100 * sum(w <= -0.05 for _, w in x) / len(x)}
    return {'all_pullback_days': agg([(f, w) for _, f, w in rows]), 'score_0_1': agg([(f, w) for s, f, w in rows if s <= 1]),
            'score_2_3': agg([(f, w) for s, f, w in rows if s in (2, 3)]), 'score_4': agg([(f, w) for s, f, w in rows if s == 4]),
            'first_score_4_per_episode': agg([(f, w) for _, f, w in first]), 'first_dates': [d for d, _, _ in first]}


out = {g: study(s) for g, s in GROUPS.items()}
json.dump(out, open(os.path.join(ROOT, 'data', 'research', 'reversal_check_study.json'), 'w'), indent=1)
for g, o in out.items():
    print(f'\n{g}:                 n   mean10  median10  %up  %fell a further 5%+')
    for k in ('all_pullback_days', 'score_0_1', 'score_2_3', 'score_4', 'first_score_4_per_episode'):
        v = o[k]
        print(f"  {k:28} " + (f"{v['n']:4} {v['mean10']:+7.2f} {v['median10']:+8.2f} {v['pct_up']:5.0f} {v['pct_further_5']:6.0f}" if v else 'none'))
