"""Consolidate raw get_equity_historicals minute-bar payloads into one committed file.

WHY THIS EXISTS
Every earlier v3 / day-trading backtest in this project read its 1-minute bars from
/tmp, so when the container recycled the evidence went with it and the results became
unfalsifiable -- exactly what Evidence Rule 2 exists to stop. This script writes the
bars into data/ so a replay can be re-run and checked later.

WHAT THE DATA ACTUALLY COVERS -- READ BEFORE TRUSTING A RESULT
Robinhood serves real 1-minute bars for roughly the trailing six weeks only. Older
ranges still return 390 bars/day, but every one has interpolated=true, volume 0 and a
flat price -- synthesized gap-fill carrying no information. Measured 2026-09-22:

    2026-07-06  390/390 interpolated   (synthetic)
    2026-07-17  interpolated           (synthetic)
    2026-07-31  interpolated           (synthetic)
    2026-08-07  interpolated           (synthetic)
    2026-08-10  0/390 interpolated     (REAL)  <- history effectively starts here
    2026-08-14  0/390 interpolated     (REAL)

So a 1-minute study cannot reach further back than ~2026-08-10, and any claim about
v3 over a longer window cannot be reproduced from this source. This script DROPS any
day whose bars are more than half interpolated rather than letting flat synthetic
bars enter a backtest, where they would read as a zero-volatility day and silently
flatter any "trade only on good days" gate.

USAGE
The raw payloads are fetched by the agent via get_equity_historicals (chunked to a
week at a time, because an explicit interval caps the response at ~2,500 bars per
symbol) and land as tool-result JSON files. Point this script at them:

    python3 scripts/fetch_semis_1min_data.py <raw1.json> <raw2.json> ...

Writes data/semis_1min_<start>_<end>.json in a compact schema:

    {"meta": {...}, "bars": {"<SYMBOL>": {"<YYYY-MM-DD>": [["HH:MM", o, h, l, c, v], ...]}}}

Times are UTC, left-edge labelled, regular session only.
"""
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTERP_DAY_THRESHOLD = 0.5   # drop a day if more than half its bars are synthesized


def load_payload(path):
    with open(path) as fh:
        return json.load(fh)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)

    # symbol -> day -> {HH:MM: bar}   (dict keyed by time so overlapping chunks dedupe)
    acc = defaultdict(lambda: defaultdict(dict))
    interp_seen = defaultdict(lambda: defaultdict(int))

    for path in sys.argv[1:]:
        payload = load_payload(path)
        for result in payload['data']['results']:
            sym = result['symbol']
            if result.get('interval') != 'minute':
                sys.exit(f'{path}: {sym} interval is {result.get("interval")!r}, expected "minute"')
            for b in result['bars']:
                ts = b['begins_at']
                day, hhmm = ts[:10], ts[11:16]
                if b.get('interpolated'):
                    interp_seen[sym][day] += 1
                    continue
                acc[sym][day][hhmm] = [
                    round(float(b['open_price']), 4),
                    round(float(b['high_price']), 4),
                    round(float(b['low_price']), 4),
                    round(float(b['close_price']), 4),
                    int(b['volume']),
                ]

    bars, dropped = {}, []
    for sym in sorted(acc):
        bars[sym] = {}
        for day in sorted(acc[sym]):
            real = len(acc[sym][day])
            interp = interp_seen[sym].get(day, 0)
            total = real + interp
            if total and interp / total > INTERP_DAY_THRESHOLD:
                dropped.append((sym, day, real, interp))
                continue
            bars[sym][day] = [[t] + acc[sym][day][t] for t in sorted(acc[sym][day])]

    # also drop any day not present in full for every symbol -- a partial basket day
    # would distort breadth and the cross-symbol gates that read it
    common = None
    for sym in bars:
        days = set(bars[sym])
        common = days if common is None else (common & days)
    common = sorted(common or [])
    for sym in bars:
        bars[sym] = {d: v for d, v in bars[sym].items() if d in common}

    if not common:
        sys.exit('No usable days after filtering -- refusing to write an empty dataset.')

    total_bars = sum(len(v) for s in bars.values() for v in s.values())
    out = {
        'meta': {
            'source': 'get_equity_historicals, interval=minute, bounds=regular',
            'adjustment': 'split (tool default)',
            'symbols': sorted(bars),
            'window_start': common[0],
            'window_end': common[-1],
            'trading_days': len(common),
            'total_bars': total_bars,
            'interpolated_policy':
                f'days with >{INTERP_DAY_THRESHOLD:.0%} synthesized bars dropped entirely',
            'known_limit':
                'Robinhood serves real minute bars for ~6 trailing weeks; earlier '
                'ranges return fully interpolated placeholders. Do not extend a '
                '1-minute study past window_start using this source.',
        },
        'bars': bars,
    }

    name = f'semis_1min_{common[0]}_{common[-1]}.json'
    dest = os.path.join(ROOT, 'data', name)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, 'w') as fh:
        json.dump(out, fh, separators=(',', ':'))

    print(f'symbols      : {", ".join(sorted(bars))}')
    print(f'window       : {common[0]} -> {common[-1]}  ({len(common)} trading days)')
    print(f'bars         : {total_bars:,}')
    if dropped:
        print(f'dropped days : {len(dropped)} (majority-interpolated)')
        for sym, day, real, interp in dropped[:8]:
            print(f'   {sym} {day}  real={real} interp={interp}')
    per_day = {d: len(bars[sorted(bars)[0]][d]) for d in common}
    short = {d: n for d, n in per_day.items() if n < 390}
    if short:
        print(f'short days   : {len(short)} (half-days or gaps) -> {sorted(short.items())[:6]}')
    print(f'wrote        : {os.path.relpath(dest, ROOT)} '
          f'({os.path.getsize(dest) / 1e6:.2f} MB)')


if __name__ == '__main__':
    main()
