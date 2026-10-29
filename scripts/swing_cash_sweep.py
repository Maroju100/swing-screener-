"""60% swing / 40% cash with a monthly profit sweep (asked 2026-10-29).

Total $28,700 (the Margin account's size). Swing bucket = Live rules (production engine, real
replay, 5 bps/side) on 60% = $17,220; cash bucket = 40% = $11,480.
ESTIMATED: cash earns 4.0%/yr (T-bill/money-market proxy), accrued monthly.
SWEEP: at each month start, swing equity above $17,220 moves to cash. Two versions:
  - no top-up: a losing month is not refilled (same rule as margin_style_monthly_sweep.py)
  - top-up: if swing starts a month below $17,220 it is refilled from cash
Each month is replayed from flat with that month's starting swing capital.
Compared with 100% swing with and without the sweep. Apr 21 -> Oct 21 2026 (data ends 10-21).
Reproduce: python3 scripts/swing_cash_sweep.py
"""
import calendar, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_protect_rules as P1
import margin_style_protect_rules2 as P2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P1.DAILY = os.path.join(ROOT, 'data', 'margin_live_daily_ext_2025-11-03_2026-10-21.json')
P1.HOURLY = os.path.join(ROOT, 'data', 'margin_live_hourly_ext_2026-03-06_2026-10-21.json')
TOTAL, SWING_W, RATE = 28700.0, 0.60, 0.04
START, END = '2026-04-21', '2026-10-21'
MONTHS = [('2026-04-21', '2026-04-30')] + [(f'2026-{m:02d}-01', f'2026-{m:02d}-{calendar.monthrange(2026, m)[1]:02d}')
                                           for m in range(5, 10)] + [('2026-10-01', END)]
PROD = P2.VARIANTS['PRODUCTION']


def sweep(base, cash0, topup):
    swing, cash, rows, worst_total, peak_total = base, cash0, [], 0.0, base + cash0
    for i, (a, b) in enumerate(MONTHS):
        if topup and swing < base and cash > 0:
            add = min(base - swing, cash); swing += add; cash -= add
        r = P2.run(a, b, PROD, swing, f'scs_{int(base)}_{topup}_{i}')
        # worst total-account drawdown inside the month, cash held flat for the month
        for d, v in sorted(r['day_equity'].items()):
            t = v + cash
            peak_total = max(peak_total, t); worst_total = min(worst_total, t / peak_total - 1)
        end = r['end_equity']
        cash *= 1 + RATE * (12 if i else 1.5) / 12 / 12          # Apr stub ~1/3 month
        take = max(0.0, end - base)
        rows.append((a[:7], swing, end, take, cash + take))
        cash += take; swing = end - take
    return swing, cash, rows, worst_total * 100


def show(name, swing, cash, rows, dd):
    total = swing + cash
    print(f"\n{name}")
    print(f"{'month':8}{'swing starts':>14}{'swing ends':>12}{'to cash':>9}{'cash after':>12}")
    for m, s, e, t, c in rows:
        print(f"{m:8}{s:>14,.0f}{e:>12,.0f}{t:>9,.0f}{c:>12,.0f}")
    print(f"END: swing ${swing:,.0f} + cash ${cash:,.0f} = ${total:,.0f} ({(total / TOTAL - 1) * 100:+.1f}%)  "
          f"worst drop of whole account {dd:.1f}%")


if __name__ == '__main__':
    base = TOTAL * SWING_W
    show('60/40, monthly sweep, no top-up', *sweep(base, TOTAL - base, False))
    show('60/40, monthly sweep, top-up swing from cash', *sweep(base, TOTAL - base, True))
    show('100% swing, monthly sweep (reference)', *sweep(TOTAL, 0.0, False))
    c = P2.run(START, END, PROD, base, 'scs_cont60')
    cash = (TOTAL - base) * (1 + RATE / 2)
    peak, dd = 0, 0
    for _, v in sorted(c['day_equity'].items()):
        peak = max(peak, v + cash); dd = min(dd, (v + cash) / peak - 1)
    print(f"\n60/40, NO sweep: ${c['end_equity'] + cash:,.0f} ({(c['end_equity'] + cash) / TOTAL * 100 - 100:+.1f}%)  "
          f"worst drop {dd * 100:.1f}%")
    f = P2.run(START, END, PROD, TOTAL, 'scs_cont100')
    print(f"100% swing, NO sweep: ${f['end_equity']:,.0f} ({f['ret_pct']:+.1f}%)  worst drop {f['max_dd_pct']:.1f}%")
