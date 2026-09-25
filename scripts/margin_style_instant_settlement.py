#!/usr/bin/env python3
"""What would LIMITED MARGIN (instant access to sale proceeds) do to Margin-Style Live?

QUESTION (asked 2026-09-25): if 912291820 were a limited-margin account, sale
proceeds would be spendable the moment the sell fills instead of the next
business day. Would P&L improve?

WHAT THE EXISTING "--no-settlement-lockup" TEST DID NOT MEASURE
  CLAUDE.md records that removing `safe_cash = real_cash - pending_total` changes
  nothing to the cent. That is true and still true, but it only tests
  YESTERDAY's proceeds, which a cash account also has by the next once-daily run
  (T+1). The thing limited margin actually adds is TODAY's proceeds funding
  TODAY's buys in the same run. Neither the live procedure nor any harness has
  ever done that: cmd_plan sizes every buy off cash as it stood BEFORE the run's
  own sells (2026-09-25: $14,233.57 sold, WDC buy sized off $85.15).

THE VARIANT (one anchored source patch, asserted, nothing else changes)
  Just before the buy loop, credit safe_cash with the proceeds of every sell this
  run has already decided on (STOP / MAX_HOLD / KILL_SWITCH in `sells`, PEAK /
  GAIN in `pending_peak_gain`). When a PEAK/GAIN sell later NETS against a buy of
  the same symbol, the pre-credited proceeds never materialise as a separate
  sale, so the netting branch charges the FULL buy (shares * price) instead of the
  net difference -- cash after the run is then exactly cash + sold - bought, as a
  real sell-then-buy on limited margin would leave it.
  Operationally this corresponds to: place sells, wait for fills, re-read
  buying_power, then size buys. That is a procedure change, not only an account
  change -- the trigger as written would NOT capture this even on limited margin.

  Gate: with the credit switched off the patch must reproduce production to the
  cent, or the script refuses to report.

BATTERY (same pre-set checks as rule_ideas / candidate_pdf): full 132 days,
each third from a flat start, rising vs falling half, 30-minute bars at 17:30
(the live time) and 17:00, block bootstrap on daily returns.

Reproduce:
    python3 scripts/margin_style_instant_settlement.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import margin_style_intraday_study as I
import margin_style_research as R

OUT = os.path.join(R.RESULTS, 'instant_settlement.json')
CAPITAL = 80000.0
COST = 5.0
FULL = (R.RESEARCH_START, R.RESEARCH_END)
HALVES = {'rising': ('2026-03-13', '2026-06-19'), 'falling': ('2026-06-22', '2026-09-21')}
FINE = ('2026-06-22', '2026-09-21')
MARKS = ('17:30', '17:00')

ANCHOR_LOOP = "    buys = []\n    netted_symbols = set()\n"
ANCHOR_NET = ("            netted_symbols.add(sym)\n")
ANCHOR_NETBUY = ("                safe_cash -= actual_deploy\n"
                 "            elif net_shares < -1e-6:\n")


def patch_instant(src):
    for a in (ANCHOR_LOOP, ANCHOR_NET, ANCHOR_NETBUY):
        assert src.count(a) == 1, f'anchor not unique/absent: {a!r}'
    src = src.replace(ANCHOR_LOOP, ANCHOR_LOOP +
        "    if INSTANT_SETTLEMENT:\n"
        "        safe_cash += sum(s['shares'] * s['price'] for s in sells)\n"
        "        safe_cash += sum(p['shares'] * p['price'] for p in pending_peak_gain.values())\n")
    src = src.replace(ANCHOR_NET, ANCHOR_NET +
        "            if INSTANT_SETTLEMENT:\n"
        "                safe_cash -= shares * live_price\n")
    src = src.replace(ANCHOR_NETBUY,
        "                if not INSTANT_SETTLEMENT:\n"
        "                    safe_cash -= actual_deploy\n"
        "            elif net_shares < -1e-6:\n")
    return src.replace('\nSYMBOLS', '\nINSTANT_SETTLEMENT = False\nSYMBOLS', 1)


PATCH = [R.patch_sell_epsilon, patch_instant]
ON = {'INSTANT_SETTLEMENT': True}


def hourly(s, e, params, tag):
    return R.replay(start=s, end=e, params=params, tag=tag, src_patches=PATCH, cost_bps=COST)


def fine(mark, params, tag):
    return I.replay_intraday(FINE[0], FINE[1], check_times=(mark,), tag=tag, params=params,
                             src_patches=PATCH, cost_bps=COST, capital=CAPITAL,
                             use_hourly_at_1700=False, exact_open=True)


def pct(x):
    return round(x / CAPITAL * 100, 2)


def deployed(r):
    return round(sum(t['shares'] * t['price'] for t in r['trades'] if t['side'] == 'buy'), 2)


def main():
    prod = R.replay(start=FULL[0], end=FULL[1], tag='is_prod',
                    src_patches=[R.patch_sell_epsilon], cost_bps=COST)
    off = hourly(FULL[0], FULL[1], None, 'is_off')
    if abs(off['realized'] - prod['realized']) > 0.005 or off['trade_count'] != prod['trade_count']:
        raise SystemExit(f"GATE FAILED: patch OFF ${off['realized']:,.2f}/{off['trade_count']} "
                         f"!= production ${prod['realized']:,.2f}/{prod['trade_count']}")
    print(f"gate PASS: patch OFF == production (${prod['realized']:,.2f}, {prod['trade_count']} trades)")

    on = hourly(FULL[0], FULL[1], ON, 'is_on')
    days = sorted(prod['day_pnl'])
    k = len(days) // 3
    thirds = [(days[0], days[k - 1]), (days[k], days[2 * k - 1]), (days[2 * k], days[-1])]
    P = {'thirds': [hourly(s, e, None, f'is_pt{i}') for i, (s, e) in enumerate(thirds)],
         'halves': {h: hourly(s, e, None, f'is_ph{h}') for h, (s, e) in HALVES.items()},
         'fine': {m: fine(m, None, f'is_pf{m[:2]}{m[3:]}') for m in MARKS}}
    V = {'thirds': [hourly(s, e, ON, f'is_vt{i}') for i, (s, e) in enumerate(thirds)],
         'halves': {h: hourly(s, e, ON, f'is_vh{h}') for h, (s, e) in HALVES.items()},
         'fine': {m: fine(m, ON, f'is_vf{m[:2]}{m[3:]}') for m in MARKS}}
    lo, hi, p = R.block_bootstrap_diff(R.daily_returns(on), R.daily_returns(prod))
    checks = {
        'full window': on['realized'] > prod['realized'],
        'all 3 thirds': all(v['realized'] > b['realized'] for v, b in zip(V['thirds'], P['thirds'])),
        'both halves': all(V['halves'][h]['realized'] > P['halves'][h]['realized'] for h in HALVES),
        'both 30-min marks': all(V['fine'][m]['realized'] > P['fine'][m]['realized'] for m in MARKS),
        'bootstrap CI excludes 0': lo > 0,
    }
    out = {
        'generated': '2026-09-25', 'engine': R.ENGINE, 'window': list(FULL), 'capital': CAPITAL,
        'cost_bps': COST, 'thirds': thirds,
        'gate_patch_off_equals_production': True,
        'production': {'full_pct': pct(prod['realized']), 'realized': prod['realized'],
                       'trades': prod['trade_count'], 'summary': R.summarize(prod),
                       'thirds_pct': [pct(r['realized']) for r in P['thirds']],
                       'halves_pct': {h: pct(r['realized']) for h, r in P['halves'].items()},
                       'fine_pct': {m: pct(r['realized']) for m, r in P['fine'].items()}},
        'instant_settlement': {'full_pct': pct(on['realized']), 'realized': on['realized'],
                               'trades': on['trade_count'], 'summary': R.summarize(on),
                               'thirds_pct': [pct(r['realized']) for r in V['thirds']],
                               'halves_pct': {h: pct(r['realized']) for h, r in V['halves'].items()},
                               'fine_pct': {m: pct(r['realized']) for m, r in V['fine'].items()}},
        'bootstrap': {'ci_daily': [lo, hi], 'p_better': p},
        'checks': checks, 'checks_passed': sum(checks.values()),
        'verdict': 'PASS' if all(checks.values()) else 'NOT AN IMPROVEMENT',
        'total_bought_notional': {'production': deployed(prod), 'instant_settlement': deployed(on)},
    }
    json.dump(out, open(OUT, 'w'), indent=1)
    print(f'wrote {OUT}\n')
    a, b = out['production'], out['instant_settlement']
    hk = list(HALVES)
    hdr = f"{'':26}{'6mo':>8}{'T1':>7}{'T2':>7}{'T3':>7}{'rise':>7}{'fall':>7}{'30m17:30':>9}{'30m17:00':>9}{'trades':>7}{'Sharpe':>7}{'maxDD':>7}"
    print(hdr)
    for n, x in (('PRODUCTION (cash, T+1)', a), ('INSTANT SETTLEMENT', b)):
        print(f"{n:26}{x['full_pct']:>+8.1f}" + ''.join(f"{v:>+7.1f}" for v in x['thirds_pct'])
              + ''.join(f"{x['halves_pct'][h]:>+7.1f}" for h in hk)
              + ''.join(f"{x['fine_pct'][m]:>+9.1f}" for m in MARKS)
              + f"{x['trades']:>7}{x['summary']['sharpe']:>7.2f}{x['summary']['max_dd_pct']:>7.1f}")
    print(f"\ntotal bought: production ${deployed(prod):,.0f}  instant ${deployed(on):,.0f}")
    print(f"bootstrap CI [{lo*100:+.3f}%, {hi*100:+.3f}%] P(better)={p:.3f}")
    print(f"checks {out['checks_passed']}/5: {checks}\nVERDICT: {out['verdict']}")


if __name__ == '__main__':
    main()
