"""Top-5 swing setups combined vs current rules, with every kill-switch trigger logged (asked 2026-11-05).

The top 5 (from scripts/consolidated_windows.py): 1 skip buys under $500 (MIN_NOTIONAL 500);
2 spend same-day sale proceeds (INSTANT_SETTLEMENT, limited margin); 3 kill -8%/10d/no SMA;
4 kill -10%/5d/no SMA/pause after 1 stop; 5 tranches 50/30/20/10/5 + 100% trim on a new high.
3 and 4 are alternative kill-switch settings, so they cannot both apply. Combos, fixed before
running:
  ALL-5 (3)   1 + 2 + 3 + 5
  ALL-5 (4)   1 + 2 + 4 + 5
  NO-MARGIN   1 + 3 + 5   (what a cash account can actually run -- 2 needs limited margin)
Real engine (origin/main), $15,000, 5 bps/side, data to 2026-11-04 (Nov 2-4 priced 11:00 CST).
Windows as consolidated_windows.py; FULL is one continuous run. Kill-switch trigger and release
dates are written by an extra log-only patch (switched off it reproduces production exactly).
Reproduce: python3 scripts/margin_style_top5_combined.py
"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_protect_rules2 as P2
import margin_style_instant_settlement as IS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY = os.path.join(ROOT, 'data', 'margin_live_daily_ext_2025-11-03_2026-11-04.json')
HOURLY = os.path.join(ROOT, 'data', 'margin_live_hourly_ext_2026-03-06_2026-11-04.json')
CAP, COST = 15000.0, 5.0
W = {'rising': ('2026-03-13', '2026-06-19'), 'falling': ('2026-06-22', '2026-09-30'),
     'crash': ('2026-10-01', '2026-11-04'), 'full': ('2026-03-13', '2026-11-04')}


def patch_kslog(src):
    a = "        kill_switch_triggered_date = today\n"
    b = "            kill_switch_active = False\n"
    assert src.count(a) == 1 and src.count(b) == 1
    src = src.replace(a, a + "        if KS_LOG:\n            open(KS_LOG, 'a').write('fire ' + today + ' dd=' + str(round(dd_now * 100, 1)) + '\\n')\n")
    src = src.replace(b, b + "            if KS_LOG:\n                open(KS_LOG, 'a').write('release ' + today + '\\n')\n")
    return src.replace('\nSYMBOLS', "\nKS_LOG = ''\nSYMBOLS", 1)


PATCHES = [R.patch_sell_epsilon, IS.patch_instant] + P2.PATCHES + [patch_kslog]
HALF = [0.50, 0.30, 0.20, 0.10, 0.05]
S1 = {'MIN_NOTIONAL': 500.0}
S2 = {'INSTANT_SETTLEMENT': True}
S3 = {'KILL_SWITCH_DD': -0.08, 'KILL_SWITCH_RESUME_DAYS': 10, 'NO_TREND_GATE': True}
S4 = {'KILL_SWITCH_DD': -0.10, 'KILL_SWITCH_RESUME_DAYS': 5, 'NO_TREND_GATE': True, 'CIRCUIT_BREAKER_STOP_COUNT': 1}
S5 = {'TRANCHE_SCHEDULE': HALF, 'PEAK_SELL_PCT': 1.0}
CONFIGS = {'CURRENT RULES': {}, 'ALL-5 with kill #3 (1+2+3+5)': {**S1, **S2, **S3, **S5},
           'ALL-5 with kill #4 (1+2+4+5)': {**S1, **S2, **S4, **S5}, 'NO-MARGIN combo (1+3+5)': {**S1, **S3, **S5}}


def run(p, a, b, tag):
    log = tempfile.mktemp(suffix='.ks')
    r = R.replay(start=a, end=b, params={**p, 'KS_LOG': log}, tag=tag, cost_bps=COST, capital=CAP,
                 src_patches=PATCHES, daily=DAILY, hourly=HOURLY)
    eq = [v for _, v in sorted(r['day_equity'].items())]
    pk, dd = 0, 0
    for v in eq:
        pk = max(pk, v); dd = min(dd, v / pk - 1)
    ev = open(log).read().split('\n')[:-1] if os.path.exists(log) else []
    return {'ret': (eq[-1] / CAP - 1) * 100, 'dd': dd * 100, 'end': eq[-1], 'trades': r['trade_count'], 'ks': ev}


def main():
    g = R.replay(start='2026-03-13', end='2026-09-21', params={}, tag='t5_gate', cost_bps=COST, src_patches=PATCHES)
    if abs(g['realized'] - 124289.71) > 0.005 or g['trade_count'] != 771:
        raise SystemExit(f"GATE FAILED: {g['realized']} / {g['trade_count']}")
    print('gate PASS: all patches off reproduce production\n', flush=True)
    out = {}
    for name, p in CONFIGS.items():
        out[name] = {w: run(p, a, b, f"t5_{name[:6].replace(' ', '')}_{w}") for w, (a, b) in W.items()}
        r = out[name]
        print(f"{name:32}" + ''.join(f"  {w} {r[w]['ret']:+6.1f}% ({r[w]['dd']:+5.1f})" for w in W)
              + f"  | full ${r['full']['end']:,.0f}, {r['full']['trades']} trades", flush=True)
        print(f"{'':32}  kill-switch (full run): {r['full']['ks'] or 'never fired'}", flush=True)
    R.save('top5_combined.json', out)


if __name__ == '__main__':
    main()
