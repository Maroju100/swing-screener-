"""Builds today's synthetic "live" daily bar from real 30-min intraday data, using the
SAME method the 36-strategy compounding-ledger backtest uses (scripts/master_table_noon_twice.py's
build_noon_daily_json / scripts/margin_style_timing_comparison.py's quote_at): pick the 30-min
bar whose start time is closest to 12:00pm ET, then use THAT bar's real open/high/low/close as
today's bar - not a flat single quote (open=high=low=close=one point).

Replaces the Swing and Margin-Style Paper Trackers' prior live-quote-proxy (a single
get_equity_quotes() point collapsed to a flat OHLC), which measurably differs from the
ledger's fidelity: a 2026-08-11 comparison backtest (flat vs this method, same strategies,
same window) found Swing's 12 strategies aggregate +$522.62 higher (Mar-Jul 2026, independent
$5k/mo basis) and Margin-Style -$324.67 lower (+202.01% -> +195.51%, Feb-Jul 2026 true-compounding)
under this more realistic method - Margin-Style's STOP check sees the bar's real low, which
catches intraday dips a flat point-quote would miss, so this fix is not free money, it is
closing a fidelity gap in both directions.

Usage: python3 scripts/noon_bar_proxy.py <intraday_today_json> <daily_hist_json> <output_json>
  intraday_today_json - raw get_equity_historicals response, interval=30minute, for TODAY only
                         (any symbols; only symbols also present in daily_hist_json are used)
  daily_hist_json      - raw get_equity_historicals response, interval=day, through yesterday
  output_json          - combined output: daily_hist_json's real bars + one synthetic bar for
                          today per symbol, in the same {"data":{"results":[...]}} shape both
                          swing_paper_engine.py and margin_style_paper_engine.py expect
"""
import sys, json
from datetime import datetime, timedelta

TARGET_MIN = 12 * 60  # noon ET


def et_minutes(dt_iso):
    dt = datetime.strptime(dt_iso[:16], '%Y-%m-%dT%H:%M') - timedelta(hours=4)  # EDT approx
    return dt.hour * 60 + dt.minute


def build_synthetic_bar(intraday_bars_today):
    noon_bar = min(intraday_bars_today, key=lambda b: abs(et_minutes(b['begins_at']) - TARGET_MIN))
    date = noon_bar['begins_at'][:10]
    return {'begins_at': date + 'T00:00:00Z', 'open_price': noon_bar['open_price'],
            'close_price': noon_bar['close_price'], 'high_price': noon_bar['high_price'],
            'low_price': noon_bar['low_price'], 'volume': noon_bar.get('volume', 0)}


def main():
    intraday_path, daily_path, out_path = sys.argv[1:4]
    intraday = json.load(open(intraday_path))
    daily = json.load(open(daily_path))

    intraday_by_sym = {r['symbol']: r['bars'] for r in intraday['data']['results']}
    out_results = []
    for r in daily['data']['results']:
        sym = r['symbol']
        bars = list(r['bars'])
        today_bars = intraday_by_sym.get(sym) or []
        if today_bars:
            bars.append(build_synthetic_bar(today_bars))
        out_results.append({'symbol': sym, 'bars': bars})

    json.dump({'data': {'results': out_results}}, open(out_path, 'w'))
    n_synth = sum(1 for r in out_results if intraday_by_sym.get(r['symbol']))
    print(f"Wrote {out_path}: {len(out_results)} symbols, {n_synth} with a synthetic noon bar appended")


if __name__ == '__main__':
    main()
