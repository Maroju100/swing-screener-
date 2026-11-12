#!/usr/bin/env python3
"""Reliability study (asked 2026-11-12: "try hard to get a reliable best model").

Why a different kind of test: every earlier search ranked setups by return on ONE run from ONE start date,
and today's work showed that is the unreliable part -- shifting the start date or one kill-switch setting by a
step moves results by 10-90 points (K8/10 +75% vs K8/5 -5% over the same six months). So this study does not
look for the highest return. It measures how much each setup's result depends on WHEN you start.

Method: 12 setups FIXED BEFORE ANY RUN (below), each replayed from many start dates with a fixed 60-trading-day
horizon, flat start, $15,000, 5 bps/side, full engine replay:
  semis (the live 8)            start every 5 trading days, Mar 13 -> (Nov 11 - 60d)   [selection]
  other chip names (8, unseen)  start every 10 trading days, Mar 13 -> (Nov 5 - 60d)   [selection]
  big tech / non-tech / ETFs    rising, falling, crash windows                         [confirmation only]
Per setup and universe: median, worst and best window return, share of windows with a gain, share of windows
beating LIVE, worst drawdown, and START-DATE JITTER = mean |return(start i) - return(start i+1)| on the semis
(adjacent starts share 55 of 60 days, so a large jitter means the result is decided by timing luck).

Decision rule, FIXED BEFORE ANY RUN.  A setup replaces LIVE as "reliable best" only if, on BOTH semis and
other chips: (a) its worst window is no worse than LIVE's, (b) its median is no lower than LIVE's,
(c) it beats LIVE in at least 60% of windows; AND (d) its semis jitter is no higher than LIVE's; AND
(e) on the three confirmation baskets it is not worse than LIVE in at least 6 of 9 cells.
If several qualify, the one with the best worst-window on the semis wins. If none qualifies, LIVE stays.

Caveats that no test design removes: one eight-month history with two sell-offs; windows overlap, so they are
not independent samples; every setup here was seen before. A pass is "more robust on this history", not proof.
Gates: LIVE Oct1->Nov5 = 13,370.47; each patch list switched off reproduces plain LIVE on a 60-day window.
MEASURED. Reproduce: python3 scripts/margin_style_reliability.py   (resumes from data/research/reliability_raw.json)
"""
import json, os, statistics as st, sys
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_17h_backtest as H
import margin_style_drawdown_rules as DR
import margin_style_sizing_rules as SZ
import margin_style_protect_rules as P1
import margin_style_v1v2_other_stocks as O

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, 'data', 'margin_live_daily_to_2026-11-11.json')
HR = os.path.join(ROOT, 'data', 'margin_live_hourly_to_2026-11-11.json')
WD, WH = O.DAILY, O.HOURLY
RAW = os.path.join(ROOT, 'data', 'research', 'reliability_raw.json')
CAP, COST, HORIZON = 15000.0, 5.0, 60
SEMIS = O.SEMIS
NK = {'KILL_SWITCH_DD': -1.0}
M = 'origin/main'
CFG = {  # name: (engine, params, patches)
    'LIVE v2 (-8%/10d, peak reset)': (M, {}, []),
    'v2 no peak reset': (M, {'KILL_SWITCH_RESET_PEAK_ON_RELEASE': False}, []),
    'v1 (-15%/20d, trend lock, $25 min)': (M, {'MIN_NOTIONAL': 25.0, 'KILL_SWITCH_DD': -0.15, 'KILL_SWITCH_RESUME_DAYS': 20,
                                               'KILL_SWITCH_TREND_LOCK': True, 'KILL_SWITCH_RESET_PEAK_ON_RELEASE': False}, []),
    'kill -12%/20d, peak reset': (M, {'KILL_SWITCH_DD': -0.12, 'KILL_SWITCH_RESUME_DAYS': 20}, []),
    'NO kill-switch': (M, dict(NK), []),
    'NO kill-switch + volatility sizing': (M, {**NK, 'VOL_SIZE': True}, [SZ.patch_size]),
    'NO kill-switch + drawdown throttle': (M, {**NK, 'DD_THROTTLE': True}, [DR.patch_dd]),
    'NO kill-switch + whipsaw pause': (M, {**NK, 'WHIPSAW_PAUSE': True}, [DR.patch_dd]),
    'LIVE + volatility sizing': (M, {'VOL_SIZE': True}, [SZ.patch_size]),
    'LIVE + drawdown throttle': (M, {'DD_THROTTLE': True}, [DR.patch_dd]),
    'LIVE + whipsaw pause': (M, {'WHIPSAW_PAUSE': True}, [DR.patch_dd]),
    'v1 engine: kill -8%/5d no lock + vol sizing (C1)': ('1cb91a2', {'KILL_SWITCH_DD': -0.08, 'KILL_SWITCH_RESUME_DAYS': 5, 'NO_TREND_GATE': True,
                                                                     'VOL_SIZE': True, 'VOL_TARGET': 0.03}, [P1.patch_protect, P1.SZ.patch_size]),
}
LIVE = 'LIVE v2 (-8%/10d, peak reset)'
BASK = {'OTHER CHIPS': O.BASKETS['OTHER CHIP NAMES (ref)'], 'BIG TECH': O.BASKETS['BIG TECH'],
        'NON-TECH 8': O.BASKETS['NON-TECH 8'], 'SECTOR ETFs': O.BASKETS['SECTOR ETFs']}
SUB = {'rising': ('2026-03-13', '2026-06-19'), 'falling': ('2026-06-22', '2026-09-30'), 'crash': ('2026-10-01', '2026-11-05')}


def tdays(path, sym):
    for x in json.load(open(path))['data']['results']:
        if x['symbol'] == sym:
            return sorted({b['begins_at'][:10] for b in x['bars'] if b['begins_at'].endswith('17:00:00Z') and b['begins_at'][:10] >= '2026-03-13'})


def windows(days, step):
    return [(days[i], days[i + HORIZON - 1]) for i in range(0, len(days) - HORIZON + 1, step)]


def one(job):
    key, name, univ, a, b, daily, hourly = job
    eng, params, patches = CFG[name] if name in CFG else (M, {}, GATE[name])
    H.UNIVERSE = list(univ)
    try:
        r = R.replay(start=a, end=b, params=dict(params) or None, tag='rel_' + str(abs(hash(key)) % 10**9), engine=eng,
                     cost_bps=COST, capital=CAP, src_patches=patches or None, daily=daily, hourly=hourly)
    except BaseException as e:
        return key, {'error': repr(e)[:200]}
    eq = r['day_equity']; pk = dd = 0.0
    for d in sorted(eq):
        pk = max(pk, eq[d]); dd = min(dd, eq[d] / pk - 1)
    e = eq[max(eq)]
    return key, {'end': e, 'ret': (e / CAP - 1) * 100, 'dd': dd * 100, 'trades': r['trade_count']}


GATE = {'gate_size': [SZ.patch_size], 'gate_dd': [DR.patch_dd]}


def main():
    sw = windows(tdays(HR, 'AMD'), 5)
    ow = windows([d for d in tdays(WH, 'AVGO') if d <= '2026-11-05'], 10)
    jobs = [('gate|oct', LIVE, SEMIS, '2026-10-01', '2026-11-05', D, HR)]
    jobs += [(f'gate|{g}', g, SEMIS, sw[0][0], sw[0][1], D, HR) for g in GATE]
    for n in CFG:
        jobs += [(f'S|{a}|{n}', n, SEMIS, a, b, D, HR) for a, b in sw]
        jobs += [(f'O|{a}|{n}', n, BASK['OTHER CHIPS'], a, b, WD, WH) for a, b in ow]
        jobs += [(f'C|{bk}|{w}|{n}', n, BASK[bk], a, b, WD, WH) for bk in ('BIG TECH', 'NON-TECH 8', 'SECTOR ETFs') for w, (a, b) in SUB.items()]
    res = json.load(open(RAW)) if os.path.exists(RAW) else {}
    todo = [j for j in jobs if j[0] not in res or 'error' in res[j[0]]]
    print(f'{len(sw)} semis windows, {len(ow)} other-chip windows, {len(jobs)} runs, {len(todo)} to do', flush=True)
    with Pool(4) as pool:
        for i, (k, v) in enumerate(pool.imap_unordered(one, todo)):
            res[k] = v
            if 'error' in v:
                print('RUN ERROR', k, v['error'], flush=True)
            if (i + 1) % 25 == 0 or i + 1 == len(todo):
                json.dump(res, open(RAW, 'w'))
                print(f'progress {i + 1}/{len(todo)}', flush=True)
    assert abs(res['gate|oct']['end'] - 13370.47) < 0.01, 'GATE A FAILED'
    base0 = res[f'S|{sw[0][0]}|{LIVE}']['end']
    for g in GATE:
        assert abs(res[f'gate|{g}']['end'] - base0) < 0.01, f'PATCH GATE FAILED {g}'
    print('gates PASS', flush=True)

    def stats(prefix, wins, n):
        xs = [res[f'{prefix}|{a}|{n}'] for a, _ in wins]
        if any('error' in x for x in xs):
            return None
        r = [x['ret'] for x in xs]; lv = [res[f'{prefix}|{a}|{LIVE}']['ret'] for a, _ in wins]
        return {'median': st.median(r), 'worst': min(r), 'best': max(r), 'mean': st.mean(r),
                'pct_gain': 100 * sum(x > 0 for x in r) / len(r), 'pct_beat_live': 100 * sum(x > y + 1e-9 for x, y in zip(r, lv)) / len(r),
                'worst_dd': min(x['dd'] for x in xs), 'jitter': st.mean(abs(r[i] - r[i + 1]) for i in range(len(r) - 1)), 'rets': r}
    out = {'horizon_days': HORIZON, 'capital': CAP, 'cost_bps': COST, 'semis_windows': sw, 'other_windows': ow, 'setups': {}}
    for n in CFG:
        s, o = stats('S', sw, n), stats('O', ow, n)
        cells = [(res[f'C|{bk}|{w}|{n}'], res[f'C|{bk}|{w}|{LIVE}']) for bk in ('BIG TECH', 'NON-TECH 8', 'SECTOR ETFs') for w in SUB]
        conf = None if any('error' in c for c, _ in cells) else sum(c['end'] >= l['end'] - 0.005 for c, l in cells)
        out['setups'][n] = {'semis': s, 'other_chips': o, 'confirm_not_worse_of_9': conf,
                            'confirm_cells': {f'{bk}|{w}': res[f'C|{bk}|{w}|{n}'].get('ret') for bk in ('BIG TECH', 'NON-TECH 8', 'SECTOR ETFs') for w in SUB}}
    L = out['setups'][LIVE]
    qual = []
    for n, x in out['setups'].items():
        if n == LIVE or not x['semis'] or not x['other_chips'] or x['confirm_not_worse_of_9'] is None:
            x['qualifies'] = False if n != LIVE else None
            continue
        ch = {}
        for u in ('semis', 'other_chips'):
            ch[f'{u} worst >= live'] = x[u]['worst'] >= L[u]['worst']
            ch[f'{u} median >= live'] = x[u]['median'] >= L[u]['median']
            ch[f'{u} beats live >= 60%'] = x[u]['pct_beat_live'] >= 60
        ch['semis jitter <= live'] = x['semis']['jitter'] <= L['semis']['jitter']
        ch['confirm >= 6 of 9'] = x['confirm_not_worse_of_9'] >= 6
        x['checks'] = ch; x['qualifies'] = all(ch.values())
        if x['qualifies']:
            qual.append(n)
    out['qualifying'] = qual
    out['reliable_best'] = max(qual, key=lambda n: out['setups'][n]['semis']['worst']) if qual else LIVE
    json.dump(out, open(os.path.join(ROOT, 'data', 'research', 'reliability.json'), 'w'), indent=1)
    for u in ('semis', 'other_chips'):
        print(f'\n{u}:  median  worst   best  %gain %beatLIVE worstDD jitter')
        for n, x in sorted(out['setups'].items(), key=lambda kv: -(kv[1][u]['worst'] if kv[1][u] else -999)):
            s = x[u]
            print(f"  {s['median']:+7.1f} {s['worst']:+6.1f} {s['best']:+6.1f} {s['pct_gain']:5.0f} {s['pct_beat_live']:8.0f} {s['worst_dd']:+7.1f} {s['jitter']:6.1f}  {n}" if s else f'  ERROR {n}')
    print()
    for n, x in out['setups'].items():
        if n != LIVE:
            fails = [k for k, v in x.get('checks', {}).items() if not v]
            print(f"{'QUALIFIES' if x['qualifies'] else 'no       '} conf {x['confirm_not_worse_of_9']}/9  {n}" + (f"   fails: {'; '.join(fails)}" if fails else ''))
    print('\nRELIABLE BEST:', out['reliable_best'])


if __name__ == '__main__':
    main()
