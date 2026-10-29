"""Setups derived from the owner's own Margin-account trades (asked 2026-10-29).

Source: 1,388 filled orders in account 410961445, 2026-06-30 -> 2026-10-29, committed as
data/broker_fills_410961445_2026-06-29_2026-10-29.csv. On the 8 universe names (FIFO-matched,
window inventory only):
  - buys sat a median -13% below the stock's 20-day high (97% of buys were below it);
  - round trips held 3-7 days made +$3,926 (63% win); same-day ones ~$0; 1-3 days -$4,522;
    7+ days lost.
Two rules follow from that, tested on the real engine (origin/main), each behind a switch:
  A  DD20: a NORMAL_DIP buy also needs yesterday's close >= 10% below its own 20-day high
  B  MIN3: no PEAK/GAIN profit-taking until a position is 3 trading days old
     (STOP and MAX_HOLD unchanged - the stop is not touched)
Variants fixed before running: A, B, A+B. PASS needs ALL of: beat production over the full
window, the rising half, the falling half and October, AND a block-bootstrap CI on the
daily-return difference that excludes zero. $15,000, 5 bps/side, data through 2026-10-21.
Reproduce: python3 scripts/margin_style_user_derived.py
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY = os.path.join(ROOT, 'data', 'margin_live_daily_ext_2025-11-03_2026-10-21.json')
HOURLY = os.path.join(ROOT, 'data', 'margin_live_hourly_ext_2026-03-06_2026-10-21.json')
CAP, COST = 15000.0, 5.0
WINDOWS = {'full (Mar 13-Oct 21)': ('2026-03-13', '2026-10-21'),
           'rising (Mar 13-Jun 19)': ('2026-03-13', '2026-06-19'),
           'falling (Jun 22-Sep 21)': ('2026-06-22', '2026-09-21'),
           'October (Sep 22-Oct 21)': ('2026-09-22', '2026-10-21')}


def _sub(src, old, new):
    n = src.count(old)
    if n != 1:
        raise SystemExit(f'patch anchor matched {n}x, expected 1:\n{old[:120]}')
    return src.replace(old, new)


def patch_user(src):
    src = _sub(src, "MAX_HOLD_DAYS = 6\n", "MAX_HOLD_DAYS = 6\nDD20_MIN = 0.0\nMIN_HOLD_PG = 0\n")
    src = _sub(src,
               "        if live_price > pos['peak']:\n",
               "        if MIN_HOLD_PG and 'opened' in pos and business_days_elapsed(pos['opened'], today) < MIN_HOLD_PG:\n"
               "            continue\n"
               "        if live_price > pos['peak']:\n")
    src = _sub(src,
               "            elif day_return <= -NORMAL_DIP_THRESHOLD and (not pos or pos.get('tranches', 0) < MAX_TRANCHES):\n",
               "            elif day_return <= -NORMAL_DIP_THRESHOLD and (not pos or pos.get('tranches', 0) < MAX_TRANCHES) \\\n"
               "                    and (not DD20_MIN or yesterday_close <= (1 - DD20_MIN) * max(b['close'] for b in bars[-20:])):\n")
    return src


VARIANTS = [('A  dip must be 10%+ below 20-day high', {'DD20_MIN': 0.10}),
            ('B  no profit-taking before day 3', {'MIN_HOLD_PG': 3}),
            ('A+B', {'DD20_MIN': 0.10, 'MIN_HOLD_PG': 3})]


def run(params, a, b, tag):
    r = R.replay(start=a, end=b, params=params, tag=tag, cost_bps=COST, capital=CAP,
                 src_patches=[patch_user], daily=DAILY, hourly=HOURLY)
    eq = sorted(r['day_equity'].items())
    peak, dd = 0.0, 0.0
    for _, v in eq:
        peak = max(peak, v); dd = min(dd, v / peak - 1)
    return r, {'ret': (eq[-1][1] / CAP - 1) * 100, 'dd': dd * 100, 'trades': r['trade_count']}


def main():
    g = R.replay(start='2026-03-13', end='2026-09-21', params={}, tag='ud_gate', cost_bps=COST,
                 src_patches=[patch_user])
    if abs(g['realized'] - 124289.71) > 0.005 or g['trade_count'] != 771:
        raise SystemExit(f"GATE FAILED: {g['realized']} / {g['trade_count']}")
    print('gate PASS: switches off reproduce production ($124,289.71, 771 trades)\n')
    out = {}
    base = {w: run({}, a, b, f'ud_base_{i}') for i, (w, (a, b)) in enumerate(WINDOWS.items())}
    out['PRODUCTION'] = {w: s for w, (_, s) in base.items()}
    for name, p in VARIANTS:
        res = {w: run(p, a, b, f'ud_{name[:3].strip()}_{i}') for i, (w, (a, b)) in enumerate(WINDOWS.items())}
        lo, hi, pb = R.block_bootstrap_diff(R.daily_returns(res[list(WINDOWS)[0]][0]),
                                            R.daily_returns(base[list(WINDOWS)[0]][0]))
        checks = {w: res[w][1]['ret'] > base[w][1]['ret'] for w in WINDOWS}
        checks['bootstrap CI > 0'] = lo > 0
        out[name] = {**{w: s for w, (_, s) in res.items()}, 'checks': checks,
                     'bootstrap': {'ci': [lo, hi], 'p_better': pb}}
    for name, v in out.items():
        print(f"{name:40}" + ''.join(f"  {w.split()[0]} {v[w]['ret']:+6.1f}% (dd {v[w]['dd']:+5.1f}%)" for w in WINDOWS))
        if 'checks' in v:
            c = v['checks']; print(f"{'':40}  passes {sum(c.values())}/5  {c}  P(better)={v['bootstrap']['p_better']:.2f}")
    R.save('user_derived.json', out)


if __name__ == '__main__':
    main()
