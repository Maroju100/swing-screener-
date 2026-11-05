"""Re-entry after the kill-switch: on the calendar, or on recovery? (asked 2026-11-05)

FINDING THAT MOTIVATES THIS (measured, see ks check below): after the cool-off ends the
engine releases the kill-switch but never resets equity_peak. A system sitting in cash cannot
climb back above its threshold, so the switch re-fires on the next run. The candidate
(-8%/10d) sat below its threshold for 32 run-days from 2026-07-15.

VARIANTS, fixed before any run, applied to BOTH bases:
  base P = production (kill -15%, 20-day cool-off, permanent SMA-50 gate)
  base C = candidate  (kill -8%, 10-day cool-off, no SMA-50 gate)
  T   time only (as is)
  RS  time release + reset equity_peak to current equity at release
  R1  release early once the 8-stock basket closed UP two days in a row since the trigger
  R2  release early once the basket index closes above its 5-day average (>= 3 days after)
  R3  release early once the basket is +5% off its lowest close since the trigger
  (R1-R3 also reset equity_peak at release -- otherwise an early release re-fires at once,
   and the time limit stays as a backstop.) All signals use completed daily closes only.
WINDOWS (fresh $15k starts): RISING Mar 13-Jun 19, FALLING Jun 22-Sep 30, CRASH Oct 1-Nov 4,
  FULL Mar 13-Nov 4 (one run), plus JUL22 Jul 22-Nov 4 (one run). Buy & hold shown for each.
PASS, fixed before any run: beat its OWN base (T) in rising, falling, crash AND full, and a
  block-bootstrap CI on the full-window daily-return difference that excludes zero.
5 bps/side. Nov 2-4 are priced at the 17:00 UTC bar = 11:00 CST (DST).
Reproduce: python3 scripts/margin_style_reentry_rules.py
"""
import json, os, sys
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_protect_rules2 as P2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY = os.path.join(ROOT, 'data', 'margin_live_daily_ext_2025-11-03_2026-11-04.json')
HOURLY = os.path.join(ROOT, 'data', 'margin_live_hourly_ext_2026-03-06_2026-11-04.json')
CAP, COST = 15000.0, 5.0
W = {'rising': ('2026-03-13', '2026-06-19'), 'falling': ('2026-06-22', '2026-09-30'),
     'crash': ('2026-10-01', '2026-11-04'), 'full': ('2026-03-13', '2026-11-04'), 'jul22': ('2026-07-22', '2026-11-04')}


def _sub(src, old, new):
    n = src.count(old)
    if n != 1:
        raise SystemExit(f'patch anchor matched {n}x:\n{old[:120]}')
    return src.replace(old, new)


def patch_reentry(src):
    src = _sub(src, "MAX_HOLD_DAYS = 6\n", "MAX_HOLD_DAYS = 6\nREENTRY_MODE = ''\nRESET_ON_RELEASE = False\n")
    src = _sub(src,
               "        if today >= d.date().isoformat():\n            kill_switch_active = False\n",
               "        if today >= d.date().isoformat():\n            kill_switch_active = False\n"
               "            if RESET_ON_RELEASE:\n                equity_peak = total_equity\n"
               "        if kill_switch_active and REENTRY_MODE:\n"
               "            _ss = sorted(bars_by_sym)\n"
               "            _bd = {s: {b['date']: b['close'] for b in bars_by_sym[s]} for s in _ss}\n"
               "            _dates = sorted(set.intersection(*(set(v) for v in _bd.values())))\n"
               "            _post = [x for x in _dates if x >= kill_switch_triggered_date]\n"
               "            _ok = False\n"
               "            if _post:\n"
               "                _b0 = _post[0]\n"
               "                _ix = [sum(_bd[s][x] / _bd[s][_b0] for s in _ss) / len(_ss) for x in _dates]\n"
               "                _np = len(_post)\n"
               "                if REENTRY_MODE == 'R1' and _np >= 3:\n"
               "                    _ok = _ix[-1] > _ix[-2] > _ix[-3]\n"
               "                elif REENTRY_MODE == 'R2' and _np >= 3:\n"
               "                    _ok = _ix[-1] > sum(_ix[-5:]) / 5\n"
               "                elif REENTRY_MODE == 'R3' and _np >= 2:\n"
               "                    _ok = _ix[-1] >= 1.05 * min(_ix[len(_dates) - _np:])\n"
               "            if _ok:\n"
               "                kill_switch_active = False\n"
               "                equity_peak = total_equity\n")
    return src


PATCHES = P2.PATCHES + [patch_reentry]
BASES = {'P': {}, 'C': {'KILL_SWITCH_DD': -0.08, 'KILL_SWITCH_RESUME_DAYS': 10, 'NO_TREND_GATE': True}}
MODS = {'T': {}, 'RS': {'RESET_ON_RELEASE': True}, 'R1': {'REENTRY_MODE': 'R1'}, 'R2': {'REENTRY_MODE': 'R2'},
        'R3': {'REENTRY_MODE': 'R3'}}
NAMES = {'T': 'time only (as is)', 'RS': 'time + reset high-water mark', 'R1': 'early: basket up 2 days',
         'R2': 'early: basket above 5-day avg', 'R3': 'early: basket +5% off low'}


def one(key):
    b, m = key
    out = {}
    for w, (a, e) in W.items():
        r = R.replay(start=a, end=e, params={**BASES[b], **MODS[m]}, tag=f're_{b}{m}_{w}', cost_bps=COST, capital=CAP,
                     src_patches=PATCHES, daily=DAILY, hourly=HOURLY)
        eq = [v for _, v in sorted(r['day_equity'].items())]
        pk, dd = 0, 0
        for v in eq:
            pk = max(pk, v); dd = min(dd, v / pk - 1)
        out[w] = {'ret': (eq[-1] / CAP - 1) * 100, 'dd': dd * 100, 'trades': r['trade_count']}
        if w == 'full':
            out['rets'] = R.daily_returns(r)
    return key, out


def bh(a, e):
    h = json.load(open(HOURLY))['data']['results']
    chk = {x['symbol']: {b['begins_at'][:10]: float(b['close_price']) for b in x['bars'] if b['begins_at'][11:16] == '17:00'} for x in h}
    days = sorted(d for d in chk['AMD'] if a <= d <= e)
    vals = [sum(chk[s][d] / chk[s][days[0]] for s in chk) / 8 * (1 - 5e-4) for d in days]
    pk, dd = 0, 0
    for v in vals:
        pk = max(pk, v); dd = min(dd, v / pk - 1)
    return {'ret': (vals[-1] - 1) * 100, 'dd': dd * 100}


def main():
    g = R.replay(start='2026-03-13', end='2026-09-21', params={}, tag='re_gate', cost_bps=COST, src_patches=PATCHES)
    if abs(g['realized'] - 124289.71) > 0.005 or g['trade_count'] != 771:
        raise SystemExit(f"GATE FAILED: {g['realized']} / {g['trade_count']}")
    print('gate PASS: all patches off reproduce production\n', flush=True)
    keys = [(b, m) for b in BASES for m in MODS]
    with Pool(4) as pool:
        res = dict(pool.map(one, keys))
    hold = {w: bh(*W[w]) for w in W}
    fmt = lambda r: '  '.join(f"{w} {r[w]['ret']:+6.1f}% ({r[w]['dd']:+5.1f})" for w in W)
    out = {'windows': W, 'hold': hold, 'results': {}}
    print(f"{'Buy & hold':42} {fmt(hold)}")
    for b in BASES:
        base = res[(b, 'T')]
        print(f"\nBASE {b} ({'production' if b == 'P' else 'candidate -8%/10d/no SMA'})")
        for m in MODS:
            r = res[(b, m)]
            line = f"  {NAMES[m]:40} {fmt(r)}"
            rec = {w: {k: r[w][k] for k in ('ret', 'dd', 'trades')} for w in W}
            if m != 'T':
                wins = {w: r[w]['ret'] > base[w]['ret'] for w in ('rising', 'falling', 'crash', 'full')}
                lo, hi, pb = R.block_bootstrap_diff(r['rets'], base['rets'])
                ok = all(wins.values()) and lo > 0
                line += f"  wins {sum(wins.values())}/4 P={pb:.2f} {'PASS' if ok else 'fail'}"
                rec.update(wins=wins, bootstrap=[lo, hi, pb], passed=ok)
            print(line)
            out['results'][f'{b}-{m}'] = rec
    R.save('reentry_rules.json', out)


if __name__ == '__main__':
    main()
