"""Every Margin-Style variant explored so far, on ONE basis (asked 2026-11-05).

Each config is replayed by the real engine (origin/main) with the SAME patch it was originally
tested with, $15,000, 5 bps/side, data through 2026-11-04, on four windows (each a fresh start):
  RISING  Mar 13 - Jun 19      FALLING Jun 22 - Sep 30
  CRASH   Oct 1 - Nov 4        FULL    Mar 13 - Nov 4 (one continuous run)
Nov 2-4 are priced at the 17:00 UTC bar = 11:00 CST (DST). Leverage rows use the margin
harness (margin interest 6%/yr ESTIMATED). Buy & hold = equal $ in the 8 stocks at the 17:00 bar.
Day-trading setups live in a separate committed file (5-minute data, Apr 21 - Oct 21 only);
their window figures are sliced from one continuous run and printed by --daytrade.
Reproduce: python3 scripts/consolidated_windows.py   (writes data/research/consolidated_windows.json)
"""
import json, os, sys
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_protect_rules as P1
import margin_style_protect_rules2 as P2
import margin_style_sizing_rules as SZ
import margin_style_rule_ideas as RI
import margin_style_user_derived as UD
import margin_style_instant_settlement as IS
import margin_style_after_october as AO
import margin_style_reentry_rules as RE

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY = os.path.join(ROOT, 'data', 'margin_live_daily_ext_2025-11-03_2026-11-04.json')
HOURLY = os.path.join(ROOT, 'data', 'margin_live_hourly_ext_2026-03-06_2026-11-04.json')
CAP, COST = 15000.0, 5.0
W = {'rising': ('2026-03-13', '2026-06-19'), 'falling': ('2026-06-22', '2026-09-30'),
     'crash': ('2026-10-01', '2026-11-04'), 'full': ('2026-03-13', '2026-11-04')}
EPS = [R.patch_sell_epsilon]
HALF = [0.50, 0.30, 0.20, 0.10, 0.05]
CAND = {'KILL_SWITCH_DD': -0.08, 'KILL_SWITCH_RESUME_DAYS': 10, 'NO_TREND_GATE': True}
VOL = {'VOL_SIZE': True, 'VOL_TARGET': 0.03}
CONFIGS = [  # (group, label, params, patches)
    ('Live', 'PRODUCTION (current rules)', {}, None),
    ('Stops & caps', 'Intraday stop -2.5% (looser)', {'INTRADAY_STOP': -0.025}, None),
    ('Stops & caps', 'Intraday stop -1.0% (tighter)', {'INTRADAY_STOP': -0.010}, None),
    ('Stops & caps', 'No intraday stop', {'INTRADAY_STOP': -9.99}, None),
    ('Stops & caps', 'Trade cap 10% (was 25%)', {'MAX_TRADE_NOTIONAL_PCT': 0.10}, None),
    ('Stops & caps', 'Symbol cap 25% (was 50%)', {'MAX_SYMBOL_ALLOCATION_PCT': 0.25}, None),
    ('Stops & caps', 'Max 1 tranche per symbol', {'MAX_TRANCHES': 1}, None),
    ('Entry filters', 'Quality filter 3+ down days', {'QUALITY_MIN_DOWN_DAYS': 3}, [R.patch_quality_filter]),
    ('Entry filters', 'Buy only once bounce started', {'BOUNCE_CONFIRM': True}, RI.PATCH),
    ('Entry filters', 'Skip buys under $500', {'MIN_NOTIONAL': 500.0}, RI.PATCH),
    ('Entry filters', 'Your style A: dip 10%+ below 20-day high', {'DD20_MIN': 0.10}, [UD.patch_user]),
    ('Sizing', 'Equal split across qualifiers', {'EQUAL_SPLIT': True}, RI.PATCH),
    ('Sizing', "Rank by yesterday's drop", {'RANK_BY_DAY_DROP': True}, RI.PATCH),
    ('Sizing', 'Volatility sizing 3%', dict(VOL), P2.PATCHES),
    ('Sizing', 'Smaller tranches 50/30/20/10/5', {'TRANCHE_SCHEDULE': HALF}, EPS),
    ('Exits', 'Full exit on a new high (100% trim)', {'PEAK_SELL_PCT': 1.0}, EPS),
    ('Exits', 'PDF candidate (smaller tranches + 100% trim)', {'TRANCHE_SCHEDULE': HALF, 'PEAK_SELL_PCT': 1.0}, EPS),
    ('Exits', 'Regime: trim 30% / hold 10d when market rising', {'REGIME_ADAPTIVE': True, 'REGIME_PEAK_SELL_PCT': 0.30, 'REGIME_MAX_HOLD_DAYS': 10}, RI.PATCH),
    ('Exits', 'Your style B: no profit-taking before day 3', {'MIN_HOLD_PG': 3}, [UD.patch_user]),
    ('Exits', 'Grid-search best (stop off, trim 50%, hold 8d, dip 0.2%)', {'INTRADAY_STOP': -9.99, 'PEAK_SELL_PCT': 0.5, 'MAX_HOLD_DAYS': 8, 'NORMAL_DIP_THRESHOLD': 0.002}, EPS),
    ('Exits', 'Hold through sector-wide drops', {'SECTOR_MOVE_N': 6}, AO.PATCHES),
    ('Settlement', 'Spend same-day sale proceeds (limited margin)', dict(IS.ON), IS.PATCH),
    ('Crash protection', 'C: kill -8%, 10-day cool-off, no SMA lock-out', dict(CAND), P2.PATCHES),
    ('Crash protection', 'K1: kill -8%, 5-day cool-off', {'KILL_SWITCH_DD': -0.08, 'KILL_SWITCH_RESUME_DAYS': 5}, P2.PATCHES),
    ('Crash protection', 'K2: K1 + no SMA lock-out', {'KILL_SWITCH_DD': -0.08, 'KILL_SWITCH_RESUME_DAYS': 5, 'NO_TREND_GATE': True}, P2.PATCHES),
    ('Crash protection', 'C1: K2 + volatility sizing', dict(KILL_SWITCH_DD=-0.08, KILL_SWITCH_RESUME_DAYS=5, NO_TREND_GATE=True, **VOL), P2.PATCHES),
    ('Crash protection', 'Kill -10%, 5d, no SMA, pause after 1 stop', {'KILL_SWITCH_DD': -0.10, 'KILL_SWITCH_RESUME_DAYS': 5, 'NO_TREND_GATE': True, 'CIRCUIT_BREAKER_STOP_COUNT': 1}, P2.PATCHES),
    ('Crash protection', 'Kill-switch cool-off 5 days', {'KILL_SWITCH_RESUME_DAYS': 5}, P2.PATCHES),
    ('Crash protection', 'Stop cool-off 2 days', {'STOP_COOLDOWN': 2}, P2.PATCHES),
    ('Crash protection', 'Stop cool-off 5 days', {'STOP_COOLDOWN': 5}, P2.PATCHES),
    ('Crash protection', 'Equity-curve filter (10 runs)', {'EQ_FILTER_DAYS': 10}, P2.PATCHES),
    ('Crash protection', 'Bank 50% of gains (profit lock)', {'LOCK_PCT': 0.5, 'LOCK_BASE': CAP}, P2.PATCHES),
    ('Re-entry', 'C + early re-entry: chips up 2 days', dict(CAND, REENTRY_MODE='R1'), RE.PATCHES),
    ('Re-entry', 'C + early re-entry: chips above 5-day avg', dict(CAND, REENTRY_MODE='R2'), RE.PATCHES),
    ('Re-entry', 'C + reset high-water mark on re-entry', dict(CAND, RESET_ON_RELEASE=True), RE.PATCHES),
]


def stats(eq):
    pk, dd = 0, 0
    for v in eq:
        pk = max(pk, v); dd = min(dd, v / pk - 1)
    return {'ret': (eq[-1] / CAP - 1) * 100, 'dd': dd * 100}


def one(i):
    g, lbl, p, pats = CONFIGS[i]
    out = {}
    for w, (a, b) in W.items():
        r = R.replay(start=a, end=b, params=dict(p), tag=f'cw{i}_{w}', cost_bps=COST, capital=CAP,
                     src_patches=pats, daily=DAILY, hourly=HOURLY)
        out[w] = {**stats([v for _, v in sorted(r['day_equity'].items())]), 'trades': r['trade_count']}
    return i, out


def lev(L):
    import margin_style_leverage as M
    M.DAILY, M.HOURLY = DAILY, HOURLY
    M.MONTH_ENDS = ['2026-06-19', '2026-09-30', '2026-11-04']
    out = {}
    for w, (a, b) in W.items():
        s = M.run(L, start=a, end=b, cap=CAP, tag=f'cwl{L}_{w}')
        out[w] = {'ret': (s['end'] / CAP - 1) * 100, 'dd': s['dd'], 'trades': s['trades']}
    return out


def hold():
    h = json.load(open(HOURLY))['data']['results']
    chk = {x['symbol']: {b['begins_at'][:10]: float(b['close_price']) for b in x['bars'] if b['begins_at'][11:16] == '17:00'} for x in h}
    out = {}
    for w, (a, b) in W.items():
        days = sorted(d for d in chk['AMD'] if a <= d <= b)
        out[w] = stats([CAP * (1 - 5e-4) * sum(chk[s][d] / chk[s][days[0]] for s in chk) / 8 for d in days])
    return out


def main():
    g = R.replay(start='2026-03-13', end='2026-09-21', params={}, tag='cw_gate', cost_bps=COST)
    if abs(g['realized'] - 124289.71) > 0.005 or g['trade_count'] != 771:
        raise SystemExit(f"GATE FAILED: {g['realized']} / {g['trade_count']}")
    print('gate PASS\n', flush=True)
    with Pool(4) as pool:
        res = dict(pool.map(one, range(len(CONFIGS))))
    rows = [(g, lbl, res[i]) for i, (g, lbl, _, _) in enumerate(CONFIGS)]
    rows += [('Leverage', 'Live rules at 1.4x (margin)', lev(1.4)), ('Leverage', 'Live rules at 1.8x (margin)', lev(1.8)),
             ('Reference', 'Buy & hold the 8 stocks', hold())]
    for g, lbl, r in sorted(rows, key=lambda x: -x[2]['full']['ret']):
        print(f"{g:17}{lbl:58}" + ''.join(f"{r[w]['ret']:>+9.1f}%({r[w]['dd']:+6.1f})" for w in W))
    json.dump({'windows': W, 'capital': CAP, 'cost_bps': COST,
               'rows': [{'group': g, 'label': l, **r} for g, l, r in rows]},
              open(os.path.join(ROOT, 'data', 'research', 'consolidated_windows.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
