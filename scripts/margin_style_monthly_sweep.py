"""Does banking profits monthly help? (asked 2026-10-21)

Real engine replay, $15,000, Apr 21 -> Oct 21 2026, 5 bps/side, data through 10-21.
SWEEP: at each month start, anything above BASE ($15,000) is withdrawn ("banked"); below BASE
nothing is withdrawn and nothing is topped up. Each month is replayed from flat with that
month's starting capital (a sweep is assumed to happen with the account in cash, and the
kill-switch high-water mark is reset to the new balance, as it must be after a withdrawal).
NO SWEEP: one continuous replay. Compared for production and C1.
Reproduce: python3 scripts/margin_style_monthly_sweep.py
"""
import calendar, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_protect_rules as P1
import margin_style_protect_rules2 as P2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P1.DAILY = os.path.join(ROOT, 'data', 'margin_live_daily_ext_2025-11-03_2026-10-21.json')
P1.HOURLY = os.path.join(ROOT, 'data', 'margin_live_hourly_ext_2026-03-06_2026-10-21.json')
BASE, START, END = 15000.0, '2026-04-21', '2026-10-21'
MONTHS = [('2026-04-21', '2026-04-30')] + [(f'2026-{m:02d}-01', f'2026-{m:02d}-{calendar.monthrange(2026, m)[1]:02d}')
                                           for m in range(5, 10)] + [('2026-10-01', END)]

for name, key in [('Current setup', 'PRODUCTION'), ('C1', 'C1 fast switch + vol sizing (round 1)')]:
    params = P2.VARIANTS[key]
    cont = P2.run(START, END, params, BASE, f'sw_c_{key.split()[0]}')
    cap, banked, rows, worst = BASE, 0.0, [], 0.0
    for a, b in MONTHS:
        r = P2.run(a, b, params, cap, f'sw_{key.split()[0]}_{a}')
        end = r['end_equity']
        take = max(0.0, end - BASE)
        rows.append((a[:7], cap, end, take))
        worst = min(worst, r['max_dd_pct'])
        banked += take; cap = end - take
    print(f"\n{name}")
    print(f"{'month':8}{'starts':>10}{'ends':>10}{'banked':>9}")
    for m, c, e, t in rows:
        print(f"{m:8}{c:>10,.0f}{e:>10,.0f}{t:>9,.0f}")
    total = cap + banked
    print(f"SWEEP:    in account ${cap:,.0f} + banked ${banked:,.0f} = ${total:,.0f} ({(total / BASE - 1) * 100:+.1f}%)"
          f"   worst monthly drop {worst:.1f}%")
    print(f"NO SWEEP: ${cont['end_equity']:,.0f} ({cont['ret_pct']:+.1f}%)   peak ${cont['peak_equity']:,.0f}"
          f"   worst drop {cont['max_dd_pct']:.1f}%   given back from peak ${cont['peak_equity'] - cont['end_equity']:,.0f}")
