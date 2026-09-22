"""Monthly breakdown of THE reference 6-month Margin-Style backtest.

Every number this prints is MEASURED -- it is an aggregation of
scripts/margin_style_original_6month_backtest.py, the preserved original that
reproduces $124,080.90 / +155.10% exactly. Nothing here is estimated, scaled
from an assumption, or post-processed with a multiplier.

WHY THIS EXISTS
An artifact titled "Margin-Style Live: Monthly P&L Breakdown" was published with
monthly rows that were wrong in four separate ways:
  * It was badged REAL MONEY. It is a backtest.
  * It said "scaled 0.30x from a $100k backtest". The backtest ran on $80,000
    ($10,000/symbol x 8 symbols), so the correct scale to $30k is 0.375x and
    every dollar figure on the page was ~20% low.
  * Its headline read "+124.08%". That is $124,080.90 -- the realized P&L in
    DOLLARS -- printed as a percent. The realized return is +155.10%.
  * It gave the window as Mar 6 - Sep 4. The engine's first traded day is
    2026-03-13; START_IDX=5 skips the first five days.

TWO DIFFERENT "MONTHLY RETURN" COLUMNS, BOTH REPORTED
They answer different questions and are easy to conflate:
  * pct_of_start_capital = month realized / 80,000. These SUM to +155.10%.
    It is the month's share of the headline figure, NOT a rate of return.
  * equity_return_pct   = (equity_end - equity_start) / equity_start. This is
    the honest month-on-month return on capital actually deployed, and it
    includes mark-to-market. These COMPOUND; they do not sum.
The published page summed the first kind while calling it "Return %", which is
why its August row read +0.66% against a month that actually moved equity by
a different amount.

REALIZED vs MARK-TO-MARKET
day_pnl is realized-only; day_equity includes open-position mark-to-market.
The two are not interchangeable and the monthly table keeps them in separate
columns. realized_total (+155.10%) and total-including-MTM (+158.42%) are both
correct measures of the same run.

SELF-CHECK
The script refuses to emit anything unless the replay reproduces both anchors
to the cent: realized $124,080.90 and final equity $206,737.04.

Run:  python3 scripts/margin_style_monthly_breakdown.py
Writes data/margin_style_monthly_breakdown.json (committed, per Evidence Rule 2).
"""
import json
import os
import runpy
import subprocess
import sys
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = '/tmp/margin_live_full_backtest_v2_results.json'
OUT = os.path.join(ROOT, 'data', 'margin_style_monthly_breakdown.json')

START_CAPITAL = 80000.0          # 10,000/symbol x 8 symbols -- see the original
ANCHOR_REALIZED = 124080.90
ANCHOR_FINAL_EQUITY = 206737.04

MONTH_NAMES = {
    '2026-03': 'March 2026', '2026-04': 'April 2026', '2026-05': 'May 2026',
    '2026-06': 'June 2026', '2026-07': 'July 2026', '2026-08': 'August 2026',
    '2026-09': 'September 2026',
}


def load_replay(force=False):
    """Return (day_pnl, day_equity), running the reference backtest if needed."""
    if force or not os.path.exists(RESULTS):
        print('Running scripts/margin_style_original_6month_backtest.py ...',
              file=sys.stderr)
        subprocess.check_call(
            [sys.executable, os.path.join(ROOT, 'scripts',
                                          'margin_style_original_6month_backtest.py')],
            cwd=ROOT, stdout=sys.stderr)
    d = json.load(open(RESULTS))
    return d['day_pnl'], d['day_equity']


def self_check(day_pnl, day_equity):
    """Refuse to report unless both documented anchors reproduce to the cent."""
    realized = round(sum(day_pnl.values()), 2)
    final = round(day_equity[max(day_equity)], 2)
    problems = []
    if realized != ANCHOR_REALIZED:
        problems.append(f'realized {realized:,.2f} != {ANCHOR_REALIZED:,.2f}')
    if final != ANCHOR_FINAL_EQUITY:
        problems.append(f'final equity {final:,.2f} != {ANCHOR_FINAL_EQUITY:,.2f}')
    if problems:
        sys.exit('SELF-CHECK FAILED, refusing to report:\n  ' + '\n  '.join(problems))
    return realized, final


def build(day_pnl, day_equity):
    # The traded window is day_equity's key range. day_pnl carries five extra
    # leading zero days (2026-03-06..03-12) that the engine never traded.
    days = sorted(day_equity)
    window_start, window_end = days[0], days[-1]

    months = OrderedDict()
    for d in days:
        months.setdefault(d[:7], []).append(d)

    rows = []
    prev_equity = START_CAPITAL
    for ym, ds in months.items():
        pnls = {d: day_pnl.get(d, 0.0) for d in ds}
        realized = sum(pnls.values())
        equity_end = day_equity[ds[-1]]
        equity_start = prev_equity
        traded = [d for d, v in pnls.items() if abs(v) > 0.005]
        best = max(pnls.items(), key=lambda kv: kv[1])
        worst = min(pnls.items(), key=lambda kv: kv[1])
        rows.append(OrderedDict([
            ('month', ym),
            ('label', MONTH_NAMES.get(ym, ym)),
            ('first_day', ds[0]),
            ('last_day', ds[-1]),
            ('trading_days', len(ds)),
            ('days_with_realized_pnl', len(traded)),
            ('realized_pnl', round(realized, 2)),
            ('pct_of_start_capital', round(100 * realized / START_CAPITAL, 2)),
            ('equity_start', round(equity_start, 2)),
            ('equity_end', round(equity_end, 2)),
            ('equity_change', round(equity_end - equity_start, 2)),
            ('equity_return_pct', round(100 * (equity_end - equity_start) / equity_start, 2)),
            ('best_day', best[0]),
            ('best_day_pnl', round(best[1], 2)),
            ('worst_day', worst[0]),
            ('worst_day_pnl', round(worst[1], 2)),
        ]))
        prev_equity = equity_end

    realized_total = sum(r['realized_pnl'] for r in rows)
    final_equity = rows[-1]['equity_end']
    return OrderedDict([
        ('source', 'scripts/margin_style_original_6month_backtest.py'),
        ('kind', 'BACKTEST -- not a record of real-money trading'),
        ('engine_revision', '859057e (last revision before the daily stop)'),
        ('window_start', window_start),
        ('window_end', window_end),
        ('trading_days', len(days)),
        ('start_capital', START_CAPITAL),
        ('capital_basis', '$10,000/symbol x 8 symbols (AMD MU WDC SNDK TSM INTC LRCX STX)'),
        ('realized_total', round(realized_total, 2)),
        ('realized_return_pct', round(100 * realized_total / START_CAPITAL, 2)),
        ('final_equity_incl_mtm', round(final_equity, 2)),
        ('total_return_incl_mtm_pct',
         round(100 * (final_equity - START_CAPITAL) / START_CAPITAL, 2)),
        ('months', rows),
    ])


def main():
    force = '--rerun' in sys.argv
    day_pnl, day_equity = load_replay(force)
    self_check(day_pnl, day_equity)
    report = build(day_pnl, day_equity)

    print(f"MEASURED -- replay of {report['source']}")
    print(f"Window {report['window_start']} to {report['window_end']} "
          f"({report['trading_days']} trading days), "
          f"start capital ${report['start_capital']:,.0f}\n")
    hdr = (f"{'Month':<16}{'Days':>5}{'Traded':>8}{'Realized':>14}"
           f"{'% of $80k':>11}{'Equity end':>14}{'Mo. return':>12}")
    print(hdr)
    print('-' * len(hdr))
    for r in report['months']:
        print(f"{r['label']:<16}{r['trading_days']:>5}{r['days_with_realized_pnl']:>8}"
              f"{r['realized_pnl']:>14,.2f}{r['pct_of_start_capital']:>10.2f}%"
              f"{r['equity_end']:>14,.2f}{r['equity_return_pct']:>11.2f}%")
    print('-' * len(hdr))
    print(f"{'TOTAL':<16}{report['trading_days']:>5}{'':>8}"
          f"{report['realized_total']:>14,.2f}"
          f"{report['realized_return_pct']:>10.2f}%"
          f"{report['final_equity_incl_mtm']:>14,.2f}"
          f"{report['total_return_incl_mtm_pct']:>11.2f}%")
    print("\n'% of $80k' columns SUM to the headline realized return (+155.10%).")
    print("'Mo. return' is equity change incl. mark-to-market and COMPOUNDS;")
    print('the two columns answer different questions -- do not add them together.')

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(report, open(OUT, 'w'), indent=2)
    print(f'\nWrote {os.path.relpath(OUT, ROOT)}')


if __name__ == '__main__':
    main()
