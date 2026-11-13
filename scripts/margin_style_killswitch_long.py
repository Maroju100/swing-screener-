#!/usr/bin/env python3
"""Kill-switch test on more history and more stocks (asked 2026-11-13).

WHY: on the usual data (Mar-Nov 2026) the kill-switch fired 2-3 times, so no kill-switch rule can be judged.
DATA: daily bars 2021-01-04 -> 2026-11-11 from the broker for 29 symbols (data/long_daily_*.json).
  The broker has NO intraday bars before ~March 2026 (hourly requests return interpolated filler), so this test
  CANNOT use the live 12:30 CST check price.  PRICE BASIS HERE = THE DAILY CLOSE: the engine's "today" price is
  that day's official close, i.e. a once-a-day check at the closing bell.  This is a real engine replay but a
  DIFFERENT check time from live; CLAUDE.md shows results are sensitive to the check time, so read this as
  evidence about the kill-switch rule's behaviour, not as a forecast of live P&L.
UNIVERSES (symbols with full history; SNDK/ARM/ROKU left out for missing history):
  SEMIS 7        AMD MU WDC TSM INTC LRCX STX            (the live universe without SNDK)
  OTHER CHIPS 7  AVGO AMAT KLAC MRVL QCOM ASML SMH
  HIGH BETA 7    TSLA COIN PLTR MSTR SMCI SHOP NFLX
  LARGE CAPS 8   AAPL MSFT AMZN META GOOGL JPM XOM CAT
SETUPS (engine origin/main, only the kill-switch differs), one continuous run each, 2021-07-12 -> 2026-11-11,
$15,000, 5 bps/side, every fire/release date logged:
  LIVE -8%/10d reset | NORESET -8%/10d no reset | K12/20 reset | K15/20 reset | NOKILL

QUESTIONS and pass marks, FIXED BEFORE ANY RUN:
 Q1 reset on or off?  "OFF is better" needs all of: NORESET ends above LIVE in >= 3 of 4 universes; bootstrap 95% CI
    of the daily difference above zero in >= 2 universes and never wholly below zero; and, pooled over every LIVE
    release in all universes, LIVE's return over the next 10 trading days (the stretch a re-fired no-reset system
    sits out) is negative on average with fewer than half positive.  "ON is better" needs the mirror image.
    Anything else = INCONCLUSIVE.
 Q2 does the kill-switch earn its place?  LIVE vs NOKILL: ends higher in >= 3 of 4 universes AND shallower worst
    drawdown in >= 3 of 4.
 Q3 is -8%/10d better than slower switches?  LIVE vs K12/20 and K15/20: same two counts.
Gate: the logging patch must not change results (LIVE and NORESET over Jun 1 -> Nov 11 2026 on the usual 17:00
data = 22,989.73 and 24,878.83).
MEASURED. Reproduce: python3 scripts/margin_style_killswitch_long.py  (resumes from data/research/killswitch_long_raw.json)
"""
import json, os, statistics as st, sys
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_17h_backtest as H
import margin_style_winner_validation as WV

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LD = os.path.join(ROOT, 'data', 'long_daily_2021-01-04_2026-11-12.json')
LH = os.path.join(ROOT, 'data', 'long_eod_as_17h_2021-01-04_2026-11-12.json')
D17 = os.path.join(ROOT, 'data', 'margin_live_daily_to_2026-11-11.json')
H17 = os.path.join(ROOT, 'data', 'margin_live_hourly_to_2026-11-11.json')
RAW = os.path.join(ROOT, 'data', 'research', 'killswitch_long_raw.json')
LOGS = os.path.join(ROOT, 'data', 'research', 'killswitch_long_logs'); os.makedirs(LOGS, exist_ok=True)
START, END, CAP, COST = '2021-07-12', '2026-11-11', 15000.0, 5.0
UNIV = {'SEMIS 7': ['AMD', 'MU', 'WDC', 'TSM', 'INTC', 'LRCX', 'STX'], 'OTHER CHIPS 7': ['AVGO', 'AMAT', 'KLAC', 'MRVL', 'QCOM', 'ASML', 'SMH'],
        'HIGH BETA 7': ['TSLA', 'COIN', 'PLTR', 'MSTR', 'SMCI', 'SHOP', 'NFLX'], 'LARGE CAPS 8': ['AAPL', 'MSFT', 'AMZN', 'META', 'GOOGL', 'JPM', 'XOM', 'CAT']}
SEMIS8 = ['AMD', 'MU', 'WDC', 'SNDK', 'TSM', 'INTC', 'LRCX', 'STX']
CFG = {'LIVE': {}, 'NORESET': {'KILL_SWITCH_RESET_PEAK_ON_RELEASE': False},
       'K12/20': {'KILL_SWITCH_DD': -0.12, 'KILL_SWITCH_RESUME_DAYS': 20}, 'K15/20': {'KILL_SWITCH_DD': -0.15, 'KILL_SWITCH_RESUME_DAYS': 20},
       'NOKILL': {'KILL_SWITCH_DD': -1.0}}


def one(job):
    key, cfg, univ, a, b, daily, hourly = job
    H.UNIVERSE = list(univ)
    log = os.path.join(LOGS, ''.join(ch if ch.isalnum() else '_' for ch in key) + '.txt')
    if os.path.exists(log):
        os.remove(log)
    try:
        r = R.replay(start=a, end=b, params={**CFG[cfg], 'KS_LOG': log}, tag='ksl_' + ''.join(ch if ch.isalnum() else '_' for ch in key),
                     engine='origin/main', cost_bps=COST, capital=CAP, src_patches=[WV.patch_log], daily=daily, hourly=hourly)
    except BaseException as e:
        return key, {'error': repr(e)[:300]}
    eq = r['day_equity']; ds = sorted(eq)
    ev = [x for x in open(log).read().split('\n') if x] if os.path.exists(log) else []
    seen, events = set(), []
    for x in ev:
        if x not in seen:
            seen.add(x); events.append(x)
    return key, {'end': eq[ds[-1]], 'days': ds, 'eq': [round(eq[d], 2) for d in ds], 'events': events, 'trades': r['trade_count']}


def main():
    if not os.path.exists(LH):   # derived file: each day's close presented to the harness as that day's check price
        d = json.load(open(LD))['data']['results']
        json.dump({'data': {'results': [{'symbol': r['symbol'], 'bars': [{'begins_at': b['begins_at'][:10] + 'T17:00:00Z', 'open_price': b['close_price'],
                   'close_price': b['close_price']} for b in r['bars']]} for r in d]}}, open(LH, 'w'))
    res = json.load(open(RAW)) if os.path.exists(RAW) else {}
    jobs = [('gate|LIVE', 'LIVE', SEMIS8, '2026-06-01', END, D17, H17), ('gate|NORESET', 'NORESET', SEMIS8, '2026-06-01', END, D17, H17)]
    jobs += [(f'basis|{c}', c, SEMIS8, '2026-03-13', END, LD, LH) for c in ('LIVE', 'NORESET')]
    jobs += [(f'{u}|{c}', c, UNIV[u], START, END, LD, LH) for u in UNIV for c in CFG]
    todo = [j for j in jobs if j[0] not in res or 'error' in res[j[0]]]
    print(f'{len(jobs)} runs, {len(todo)} to do', flush=True)
    if todo:
        with Pool(4) as pool:
            for i, (k, v) in enumerate(pool.imap_unordered(one, todo)):
                res[k] = v; json.dump(res, open(RAW, 'w'))
                print('done', k, v.get('error') or round(v['end'], 2), flush=True)
    assert abs(res['gate|LIVE']['end'] - 22989.73) < 0.01 and abs(res['gate|NORESET']['end'] - 24878.83) < 0.01, 'GATE FAILED'
    print('gates PASS')
    print(f"price-basis check, semis 8, Mar 13 -> Nov 11 2026 at the CLOSE: LIVE {(res['basis|LIVE']['end']/CAP-1)*100:+.1f}%  NORESET {(res['basis|NORESET']['end']/CAP-1)*100:+.1f}%   (at 17:00 UTC: +153.8% / +174.6%)")

    def stats(x):
        eq = x['eq']; pk = dd = 0.0
        for v in eq:
            pk = max(pk, v); dd = min(dd, v / pk - 1)
        yrs = len(eq) / 252
        return {'end': x['end'], 'ret': (x['end'] / CAP - 1) * 100, 'cagr': ((x['end'] / CAP) ** (1 / yrs) - 1) * 100, 'dd': dd * 100,
                'fires': sum(e.startswith('fire') for e in x['events']), 'trades': x['trades']}

    def rets(x):
        e = [CAP] + x['eq']; return [e[i] / e[i - 1] - 1 for i in range(1, len(e))]

    def yearly(x):
        out, prev = {}, CAP
        for y in sorted({d[:4] for d in x['days']}):
            e = [v for d, v in zip(x['days'], x['eq']) if d.startswith(y)][-1]; out[y] = (e / prev - 1) * 100; prev = e
        return out
    out = {'window': [START, END], 'capital': CAP, 'cost_bps': COST, 'price_basis': 'daily close', 'universes': UNIV, 'table': {}, 'yearly': {}, 'boot': {}}
    post = []
    for u in UNIV:
        out['table'][u] = {c: stats(res[f'{u}|{c}']) for c in CFG}; out['yearly'][u] = {c: yearly(res[f'{u}|{c}']) for c in CFG}
        lv = res[f'{u}|LIVE']
        out['boot'][u] = {c: list(R.block_bootstrap_diff(rets(res[f'{u}|{c}']), rets(lv))) for c in CFG if c != 'LIVE'}
        idx = {d: i for i, d in enumerate(lv['days'])}
        for e in lv['events']:
            if e.startswith('release'):
                i = idx.get(e.split()[1])
                if i is not None and i + 10 < len(lv['eq']):
                    post.append({'universe': u, 'date': e.split()[1], 'ret10': (lv['eq'][i + 10] / lv['eq'][i] - 1) * 100})
        print(f'\n{u}:   total%   CAGR%  maxDD%  fires trades | yearly %')
        for c in CFG:
            t = out['table'][u][c]
            print(f"  {c:8} {t['ret']:+9.1f} {t['cagr']:+7.1f} {t['dd']:+7.1f} {t['fires']:5} {t['trades']:6} | " + ' '.join(f"{y[2:]}:{v:+6.1f}" for y, v in out['yearly'][u][c].items()))
        for c, (lo, hi, p) in out['boot'][u].items():
            print(f"    {c:8} vs LIVE daily diff CI [{lo*100:+.4f}%, {hi*100:+.4f}%] P(better) {p:.3f}")
    r10 = [p['ret10'] for p in post]
    out['post_release'] = {'n': len(r10), 'mean': st.mean(r10) if r10 else None, 'median': st.median(r10) if r10 else None,
                           'positive': sum(x > 0 for x in r10), 'by_universe': {u: [round(p['ret10'], 2) for p in post if p['universe'] == u] for u in UNIV}, 'events': post}
    T = out['table']
    nr_wins = sum(T[u]['NORESET']['end'] > T[u]['LIVE']['end'] for u in UNIV)
    ci_pos = sum(out['boot'][u]['NORESET'][0] > 0 for u in UNIV); ci_neg = sum(out['boot'][u]['NORESET'][1] < 0 for u in UNIV)
    pr = out['post_release']
    off = nr_wins >= 3 and ci_pos >= 2 and ci_neg == 0 and r10 and pr['mean'] < 0 and pr['positive'] < len(r10) / 2
    on = nr_wins <= 1 and ci_neg >= 2 and ci_pos == 0 and r10 and pr['mean'] > 0 and pr['positive'] > len(r10) / 2
    out['Q1'] = {'noreset_wins_of_4': nr_wins, 'ci_above_zero': ci_pos, 'ci_below_zero': ci_neg, 'verdict': 'RESET OFF is better' if off else 'RESET ON is better' if on else 'INCONCLUSIVE'}

    def vs(c):
        return {'live_ends_higher': sum(T[u]['LIVE']['end'] > T[u][c]['end'] for u in UNIV), 'live_shallower_dd': sum(T[u]['LIVE']['dd'] > T[u][c]['dd'] for u in UNIV)}
    out['Q2'] = vs('NOKILL'); out['Q2']['pass'] = out['Q2']['live_ends_higher'] >= 3 and out['Q2']['live_shallower_dd'] >= 3
    out['Q3'] = {c: vs(c) for c in ('K12/20', 'K15/20')}
    json.dump(out, open(os.path.join(ROOT, 'data', 'research', 'killswitch_long.json'), 'w'), indent=1, default=str)
    print(f"\nPost-release (pooled LIVE releases): n={pr['n']} mean 10-day return {pr['mean']:+.2f}% median {pr['median']:+.2f}% positive {pr['positive']}/{pr['n']}")
    for u, v in pr['by_universe'].items():
        print(f'  {u}: {v}')
    print(f"\nQ1 reset: NORESET ends higher in {nr_wins}/4; CI above zero in {ci_pos}, below zero in {ci_neg} -> {out['Q1']['verdict']}")
    print(f"Q2 kill-switch vs none: LIVE ends higher in {out['Q2']['live_ends_higher']}/4, shallower drawdown in {out['Q2']['live_shallower_dd']}/4 -> {'PASS' if out['Q2']['pass'] else 'FAIL'}")
    for c, v in out['Q3'].items():
        print(f"Q3 LIVE vs {c}: ends higher in {v['live_ends_higher']}/4, shallower drawdown in {v['live_shallower_dd']}/4")


if __name__ == '__main__':
    main()
