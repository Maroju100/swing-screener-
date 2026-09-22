"""Extend the committed backtest datasets through 2026-09-22, without disturbing the anchor.

WHY THIS IS NOT JUST A REFETCH
------------------------------
The 6-month anchor ($124,080.90 realized / +155.10%, 122 trading days, 714
trades) is reproducible only because its inputs are frozen in data/. Refetching
the same window from the vendor is NOT guaranteed to return the same bars.

MEASURED 2026-09-22: refetching hourly bars for 2026-03-06..2026-09-04 returned
6,096 bars overlapping the committed file, of which exactly ONE differed:

    INTC 2026-09-04T15:00:00Z   committed close 94.910000   refetch 94.780000

One revised bar in 6,096 (0.016%). It is a 15:00 bar, and the engine prices off
the ~17:00 bar, so it does not touch the anchor's arithmetic -- but the point is
that vendor history is NOT immutable, and a blind overwrite would have silently
moved a reference result that CLAUDE.md treats as ground truth.

POLICY, therefore:
  * bars inside the anchor window come from the COMMITTED file, always;
  * only bars AFTER the committed file's last date are appended from the refetch;
  * any overlap disagreement is recorded in _provenance rather than resolved
    silently.

This keeps `scripts/margin_style_17h_backtest.py --validate` reproducing
$124,080.90 to the cent while the window still reaches 2026-09-22.

USAGE
    python3 scripts/build_extended_datasets.py \
        --hourly-raw <refetch.json> --daily-raw <refetch.json> --min30-raw <refetch.json>

Writes data/margin_live_{daily,hourly}_ext_<start>_<end>.json and
data/margin_live_30min_<start>_<end>.json.
"""
import argparse
import json
import os
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')

ANCHOR_HOURLY = os.path.join(DATA, 'margin_live_hourly_6mo_2026-03-06_2026-09-04.json')
ANCHOR_DAILY_6MO = os.path.join(DATA, 'margin_live_daily_6mo_2026-03-06_2026-09-04.json')
ANCHOR_DAILY_LONG = os.path.join(DATA, 'margin_style_daily_bars_2025-11-03_2026-09-04.json')

UNIVERSE = ['AMD', 'MU', 'WDC', 'SNDK', 'TSM', 'INTC', 'LRCX', 'STX']
FIELDS = ('open_price', 'high_price', 'low_price', 'close_price', 'volume')


def load_results(path):
    with open(path) as fh:
        return json.load(fh)['data']['results']


def index(results):
    return {r['symbol']: {b['begins_at']: b for b in r['bars']} for r in results}


def slim(b):
    out = {'begins_at': b['begins_at']}
    for f in FIELDS:
        if f in b:
            out[f] = b[f]
    return out


def merge(anchor_path, raw_path, label):
    """Anchor bars win on overlap; raw supplies only the strictly-newer tail."""
    anchor = index(load_results(anchor_path))
    raw_results = load_results(raw_path)
    raw = index(raw_results)

    interpolated = sum(1 for r in raw_results for b in r['bars'] if b.get('interpolated'))
    if interpolated:
        raise SystemExit(
            f'{label}: refetch contains {interpolated} interpolated bars -- refusing to '
            'build a dataset that mixes synthesized bars into a backtest.')

    last_anchor = max(ts for sym in anchor for ts in anchor[sym])

    disagreements = []
    compared = 0
    for sym in anchor:
        for ts, ab in anchor[sym].items():
            rb = raw.get(sym, {}).get(ts)
            if rb is None:
                continue
            compared += 1
            if abs(float(ab['close_price']) - float(rb['close_price'])) > 1e-6:
                disagreements.append({'symbol': sym, 'begins_at': ts,
                                      'committed_close': ab['close_price'],
                                      'refetch_close': rb['close_price']})

    merged, appended = {}, 0
    for sym in UNIVERSE:
        bars = dict(anchor.get(sym, {}))
        for ts, b in raw.get(sym, {}).items():
            if ts > last_anchor:
                bars[ts] = b
                appended += 1
        merged[sym] = [slim(bars[t]) for t in sorted(bars)]

    counts = {s: len(v) for s, v in merged.items()}
    if len(set(counts.values())) != 1:
        raise SystemExit(f'{label}: symbols have unequal bar counts {counts} -- '
                         'an uneven panel would distort cross-symbol logic.')

    prov = {
        'label': label,
        'built': '2026-09-22',
        'policy': 'anchor file authoritative on overlap; only strictly-newer bars appended',
        'anchor_file': os.path.basename(anchor_path),
        'anchor_last_bar': last_anchor,
        'overlap_bars_compared': compared,
        'overlap_close_disagreements': disagreements,
        'bars_appended_from_refetch': appended,
        'interpolated_bars': 0,
        'bars_per_symbol': counts[UNIVERSE[0]],
    }
    return merged, prov


def write(merged, prov, stem):
    days = sorted({b['begins_at'][:10] for b in merged[UNIVERSE[0]]})
    name = f'{stem}_{days[0]}_{days[-1]}.json'
    dest = os.path.join(DATA, name)
    payload = {'_provenance': prov,
               'data': {'results': [{'symbol': s, 'bars': merged[s]} for s in UNIVERSE]}}
    with open(dest, 'w') as fh:
        json.dump(payload, fh, separators=(',', ':'))
    # the 30-minute build has no anchor, so it carries neither of these keys
    extra = ''
    if 'bars_appended_from_refetch' in prov:
        extra = (f'appended {prov["bars_appended_from_refetch"]:>4}  '
                 f'overlap-disagreements {len(prov["overlap_close_disagreements"])}  ')
    print(f'{prov["label"]:<8} {days[0]} -> {days[-1]}  '
          f'{len(days):>3} days  {prov["bars_per_symbol"]:>5} bars/sym  '
          f'{extra}-> data/{name}')
    return dest


def build_min30(raw_path):
    """30-minute bars have no committed anchor -- this is the first commit of them."""
    results = load_results(raw_path)
    interp = sum(1 for r in results for b in r['bars'] if b.get('interpolated'))
    if interp:
        raise SystemExit(f'30min: {interp} interpolated bars -- refusing to commit.')
    merged = {r['symbol']: [slim(b) for b in sorted(r['bars'], key=lambda x: x['begins_at'])]
              for r in results}
    byday = defaultdict(int)
    for b in merged[UNIVERSE[0]]:
        byday[b['begins_at'][:10]] += 1
    counts = {s: len(v) for s, v in merged.items()}
    if len(set(counts.values())) != 1:
        raise SystemExit(f'30min: unequal bar counts {counts}')
    prov = {
        'label': '30min',
        'built': '2026-09-22',
        'source': 'get_equity_historicals interval=30minute bounds=regular adjustment=split',
        'policy': 'first commit; no prior anchor to preserve',
        'interpolated_bars': 0,
        'bars_per_symbol': counts[UNIVERSE[0]],
        'trading_days': len(byday),
        'bars_per_full_day': max(byday.values()),
        'short_days': {d: n for d, n in sorted(byday.items()) if n < max(byday.values())},
        'known_limit': ('Robinhood serves real 30-minute bars for roughly a trailing '
                        'quarter; earlier ranges come back interpolated. Do not extend a '
                        '30-minute study past the first date here using this source.'),
    }
    return merged, prov


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hourly-raw', required=True)
    ap.add_argument('--daily-raw', required=True)
    ap.add_argument('--min30-raw', required=True)
    a = ap.parse_args()

    hm, hp = merge(ANCHOR_HOURLY, a.hourly_raw, 'hourly')
    write(hm, hp, 'margin_live_hourly_ext')

    dm, dp = merge(ANCHOR_DAILY_LONG, a.daily_raw, 'daily')
    write(dm, dp, 'margin_live_daily_ext')

    mm, mp = build_min30(a.min30_raw)
    write(mm, mp, 'margin_live_30min')

    for p in (hp, dp):
        for d in p['overlap_close_disagreements']:
            print(f'  NOTE vendor revised {d["symbol"]} {d["begins_at"]}: '
                  f'committed {d["committed_close"]} vs refetch {d["refetch_close"]} '
                  f'-- committed value kept')


if __name__ == '__main__':
    main()
