"""RESEARCH TRACK (standalone, not a replacement for Margin-Style Live or any
other live/paper system in this repo). This is a pure signal-quality study:
does "relative-volume + price spike" have real historical edge across a BROAD
universe, or does it only look good on the small, hand-picked 5/8-symbol
baskets the live systems trade? It answers that question honestly and reports
the FULL outcome distribution - every qualifying event, both tails - rather
than a curated set of winners.

This script:
  - writes NO state file, feeds NO docs/*.json live log, and is never wired
    into margin_style_live_engine.py, swing_paper_engine.py, or any other
    live/paper engine. Its only output is a stdout report and (optionally) a
    JSON dump of every event for further analysis.
  - is an EVENT STUDY, not a capital-constrained portfolio backtest: every
    qualifying spike is scored independently with its own notional position,
    with no shared-cash competition, no MAXP concurrent-position cap, and no
    GFV/settlement mechanics. Those constraints (present in every live engine
    here) can silently exclude signals just because the book was full or cash
    was tied up - that would recreate exactly the "only show the trades that
    made it through" bias this track exists to avoid. Position-sizing and
    capital-allocation questions are a separate, later step once/if the raw
    signal is shown to have real, broad-universe edge.

Methodology (all choices below are deliberately the SIMPLEST honest option,
not the best-looking one - see rationale on each):

  UNIVERSE: every symbol present in the input daily_hist.json. This script
  does not hardcode a curated basket the way the live engines do - "broad"
  is whatever universe the caller supplies. To make the "broad universe"
  claim real, feed it a large, non-cherry-picked list (e.g. S&P 500 or
  Russell 1000 constituents), not a handful of names already known to have
  worked. A run against 5-8 symbols will produce a report, but its
  BROAD_UNIVERSE_WARNING line will say so - read it before trusting the
  result.

  SPIKE DEFINITION: on day i (using only data known through day i's close -
  no lookahead), relative volume rvol = volume[i] / mean(volume[i-LOOKBACK:i])
  and day_return = (close[i]-close[i-1])/close[i-1]. A spike triggers when
  rvol >= RVOL_THRESHOLD AND abs(day_return) >= PRICE_MOVE_THRESHOLD, split
  into UP (day_return > 0) and DOWN (day_return < 0) - reported SEPARATELY,
  since a volume-driven breakout and a volume-driven selloff are different
  phenomena and pooling them would hide whichever one is actually losing.

  COOLDOWN: after a symbol triggers, it is not eligible to trigger again
  until COOLDOWN_DAYS trading days later (default = the longest hold
  horizon tested). Without this, a stock that gaps for 3-4 straight days
  counts as 3-4 "independent" events that are really one correlated move,
  which would silently inflate apparent sample size and make the edge look
  more robust than it is.

  ENTRY: next trading day's OPEN after the spike day - the earliest price
  actually tradeable once the signal is fully known, never the spike day's
  own close.

  EXIT: a fixed holding period (multiple horizons tested: HOLD_HORIZONS
  trading days), exit at that day's close. No stop-loss, no target, no
  trailing exit - those are extra free parameters that can be tuned after
  the fact to flatter a signal. A clean fixed-horizon return is the least
  tunable honest measure of "did the spike itself predict anything."
  Path info (max favorable/adverse excursion over the longest horizon
  tested) is recorded per event for context, but is not used to pick a
  better exit.

  BASELINE: for every eligible day (enough lookback/forward history) in the
  same universe, whether or not it triggered a spike, the same next-open ->
  fixed-horizon return is computed as an ALL_DAYS control. Spike-day
  statistics are only meaningful relative to this baseline - a signal that
  looks identical to "buy any random day" has no real edge no matter how
  good its raw numbers look in isolation.

  REPORTING: full population stats (n, win rate, mean, median, stdev, and
  5/10/25/50/75/90/95 percentiles) for every (direction, horizon) combo,
  a year-by-year breakdown (regime robustness - matches this repo's
  walk-forward/quarter-robustness convention elsewhere), and the actual
  best 15 AND worst 15 events by symbol/date so the losing tail is visible,
  not just described as a statistic.

Input shape (same Robinhood-historicals convention used by every other
backtest script in this repo):
  {"data": {"results": [{"symbol": .., "bars": [{"begins_at": .., "open_price": ..,
   "close_price": .., "high_price": .., "low_price": .., "volume": ..}, ...]}]}}

Usage:
  python3 scripts/research_volume_price_spike_backtest.py <broad_daily_hist.json> \
      [--rvol-threshold 2.0] [--price-move-threshold 0.03] [--lookback-days 20] \
      [--hold-days 1,3,5,10,20] [--cooldown-days 20] [--min-price 1.0] [--out events.json]
"""
import argparse
import json
import statistics
import sys
from collections import defaultdict

LOOKBACK_DAYS_DEFAULT = 20
RVOL_THRESHOLD_DEFAULT = 2.0
PRICE_MOVE_THRESHOLD_DEFAULT = 0.03
HOLD_HORIZONS_DEFAULT = [1, 3, 5, 10, 20]
MIN_PRICE_DEFAULT = 1.0  # excludes sub-$1 names where a "spike" is often a data/liquidity
                          # artifact rather than a real tradeable move


def load_universe(daily_path):
    d = json.load(open(daily_path))
    bars_by_sym = {}
    for r in d['data']['results']:
        bars = []
        for b in r['bars']:
            try:
                bars.append({
                    'date': b['begins_at'][:10],
                    'open': float(b['open_price']),
                    'close': float(b['close_price']),
                    'high': float(b['high_price']),
                    'low': float(b['low_price']),
                    'volume': float(b.get('volume', 0) or 0),
                })
            except (KeyError, TypeError, ValueError):
                continue
        if bars:
            bars_by_sym[r['symbol']] = bars
    return bars_by_sym


def percentile(sorted_vals, pct):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    f, c = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def describe(returns):
    n = len(returns)
    if n == 0:
        return {'n': 0}
    s = sorted(returns)
    wins = [r for r in returns if r > 0]
    return {
        'n': n,
        'win_rate': round(len(wins) / n, 4),
        'mean': round(statistics.mean(returns), 5),
        'median': round(statistics.median(returns), 5),
        'stdev': round(statistics.pstdev(returns), 5) if n > 1 else 0.0,
        'min': round(s[0], 5),
        'p5': round(percentile(s, 5), 5),
        'p10': round(percentile(s, 10), 5),
        'p25': round(percentile(s, 25), 5),
        'p50': round(percentile(s, 50), 5),
        'p75': round(percentile(s, 75), 5),
        'p90': round(percentile(s, 90), 5),
        'p95': round(percentile(s, 95), 5),
        'max': round(s[-1], 5),
    }


def scan_events(bars_by_sym, lookback_days, rvol_threshold, price_move_threshold,
                 hold_horizons, cooldown_days, min_price):
    max_horizon = max(hold_horizons)
    spike_events = []       # UP and DOWN spikes, tagged
    baseline_events = []    # every eligible day, spike or not

    for sym, bars in bars_by_sym.items():
        n = len(bars)
        next_eligible_i = 0  # cooldown gate, index-based
        for i in range(lookback_days, n - 1):  # need i-lookback history and an i+1 open to enter on
            if bars[i]['close'] < min_price:
                continue
            entry_i = i + 1
            exit_i_max = entry_i + max_horizon - 1
            if exit_i_max >= n:
                continue  # not enough forward history to score every tested horizon

            trailing_vols = [bars[j]['volume'] for j in range(i - lookback_days, i)]
            avg_vol = sum(trailing_vols) / lookback_days
            if avg_vol <= 0:
                continue
            rvol = bars[i]['volume'] / avg_vol
            prev_close = bars[i - 1]['close']
            if prev_close <= 0:
                continue
            day_return = (bars[i]['close'] - prev_close) / prev_close

            entry_price = bars[entry_i]['open']
            if entry_price <= 0:
                continue

            window_highs = [bars[j]['high'] for j in range(entry_i, exit_i_max + 1)]
            window_lows = [bars[j]['low'] for j in range(entry_i, exit_i_max + 1)]
            mfe = (max(window_highs) - entry_price) / entry_price
            mae = (min(window_lows) - entry_price) / entry_price

            horizon_returns = {}
            for h in hold_horizons:
                exit_i = entry_i + h - 1
                exit_price = bars[exit_i]['close']
                horizon_returns[h] = (exit_price - entry_price) / entry_price

            is_spike = rvol >= rvol_threshold and abs(day_return) >= price_move_threshold
            record = {
                'symbol': sym, 'spike_date': bars[i]['date'], 'entry_date': bars[entry_i]['date'],
                'rvol': round(rvol, 3), 'day_return': round(day_return, 5),
                'entry_price': round(entry_price, 4), 'mfe': round(mfe, 5), 'mae': round(mae, 5),
                'year': bars[i]['date'][:4],
                'returns': horizon_returns,
            }
            baseline_events.append(record)

            if is_spike and i >= next_eligible_i:
                direction = 'UP' if day_return > 0 else 'DOWN'
                spike_events.append(dict(record, direction=direction))
                next_eligible_i = i + cooldown_days

    return spike_events, baseline_events


def report_group(label, events, hold_horizons):
    print(f"\n=== {label} (n={len(events)} events) ===")
    if not events:
        print("  no qualifying events")
        return
    for h in hold_horizons:
        stats = describe([e['returns'][h] for e in events])
        print(f"  hold={h:>3}d  n={stats['n']:5}  win_rate={stats['win_rate']*100:5.1f}%  "
              f"mean={stats['mean']*100:+6.2f}%  median={stats['median']*100:+6.2f}%  "
              f"stdev={stats['stdev']*100:5.2f}%  p10={stats['p10']*100:+6.2f}%  "
              f"p90={stats['p90']*100:+6.2f}%  min={stats['min']*100:+7.2f}%  max={stats['max']*100:+7.2f}%")

    by_year = defaultdict(list)
    for e in events:
        by_year[e['year']].append(e)
    primary_h = hold_horizons[len(hold_horizons) // 2]
    print(f"  --- by year (hold={primary_h}d) ---")
    for yr in sorted(by_year):
        stats = describe([e['returns'][primary_h] for e in by_year[yr]])
        print(f"    {yr}: n={stats['n']:4}  win_rate={stats['win_rate']*100:5.1f}%  mean={stats['mean']*100:+6.2f}%")


def report_tails(label, events, hold_horizons):
    primary_h = hold_horizons[len(hold_horizons) // 2]
    ranked = sorted(events, key=lambda e: e['returns'][primary_h])
    print(f"\n  --- {label}: worst 15 by hold={primary_h}d return ---")
    for e in ranked[:15]:
        print(f"    {e['spike_date']}  {e['symbol']:6}  rvol={e['rvol']:5.2f}x  "
              f"day_return={e['day_return']*100:+6.2f}%  {primary_h}d_return={e['returns'][primary_h]*100:+7.2f}%")
    print(f"  --- {label}: best 15 by hold={primary_h}d return ---")
    for e in ranked[-15:][::-1]:
        print(f"    {e['spike_date']}  {e['symbol']:6}  rvol={e['rvol']:5.2f}x  "
              f"day_return={e['day_return']*100:+6.2f}%  {primary_h}d_return={e['returns'][primary_h]*100:+7.2f}%")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('daily_hist_path')
    ap.add_argument('--rvol-threshold', type=float, default=RVOL_THRESHOLD_DEFAULT)
    ap.add_argument('--price-move-threshold', type=float, default=PRICE_MOVE_THRESHOLD_DEFAULT)
    ap.add_argument('--lookback-days', type=int, default=LOOKBACK_DAYS_DEFAULT)
    ap.add_argument('--hold-days', type=str, default=','.join(str(h) for h in HOLD_HORIZONS_DEFAULT))
    ap.add_argument('--cooldown-days', type=int, default=None,
                     help='default = the longest --hold-days horizon')
    ap.add_argument('--min-price', type=float, default=MIN_PRICE_DEFAULT)
    ap.add_argument('--out', type=str, default=None, help='optional path to dump every event as JSON')
    args = ap.parse_args()

    hold_horizons = sorted(int(x) for x in args.hold_days.split(','))
    cooldown_days = args.cooldown_days if args.cooldown_days is not None else max(hold_horizons)

    bars_by_sym = load_universe(args.daily_hist_path)
    n_symbols = len(bars_by_sym)
    print(f"Loaded {n_symbols} symbols from {args.daily_hist_path}")
    if n_symbols < 100:
        print(f"BROAD_UNIVERSE_WARNING: only {n_symbols} symbols in this input - this is NOT a broad-universe "
              f"run. Results below describe this specific small universe, not a general edge; feed a "
              f"large (e.g. S&P 500 / Russell 1000) symbol list to make the broad-universe claim honest.")

    spike_events, baseline_events = scan_events(
        bars_by_sym, args.lookback_days, args.rvol_threshold, args.price_move_threshold,
        hold_horizons, cooldown_days, args.min_price)

    up_events = [e for e in spike_events if e['direction'] == 'UP']
    down_events = [e for e in spike_events if e['direction'] == 'DOWN']

    print(f"\nParams: rvol>={args.rvol_threshold}x, |day_return|>={args.price_move_threshold*100:.1f}%, "
          f"lookback={args.lookback_days}d, cooldown={cooldown_days}d, min_price=${args.min_price}, "
          f"hold_horizons={hold_horizons}")

    report_group('UP SPIKES (volume+price up)', up_events, hold_horizons)
    report_tails('UP SPIKES', up_events, hold_horizons)
    report_group('DOWN SPIKES (volume+price down)', down_events, hold_horizons)
    report_tails('DOWN SPIKES', down_events, hold_horizons)
    report_group('BASELINE: ALL_DAYS control (same universe, no spike filter)', baseline_events, hold_horizons)

    print("\n=== EDGE CHECK: spike mean return minus baseline mean return, by horizon ===")
    for h in hold_horizons:
        base_mean = describe([e['returns'][h] for e in baseline_events])['mean'] if baseline_events else 0.0
        up_mean = describe([e['returns'][h] for e in up_events])['mean'] if up_events else None
        down_mean = describe([e['returns'][h] for e in down_events])['mean'] if down_events else None
        up_edge = f"{(up_mean - base_mean)*100:+.2f}pp" if up_mean is not None else "n/a"
        down_edge = f"{(down_mean - base_mean)*100:+.2f}pp" if down_mean is not None else "n/a"
        print(f"  hold={h:>3}d  baseline_mean={base_mean*100:+6.2f}%  UP_edge={up_edge:>9}  DOWN_edge={down_edge:>9}")

    if args.out:
        with open(args.out, 'w') as f:
            json.dump({
                'params': {'rvol_threshold': args.rvol_threshold, 'price_move_threshold': args.price_move_threshold,
                           'lookback_days': args.lookback_days, 'cooldown_days': cooldown_days,
                           'min_price': args.min_price, 'hold_horizons': hold_horizons,
                           'n_symbols': n_symbols},
                'up_spikes': up_events, 'down_spikes': down_events,
                'baseline_all_days': baseline_events,
            }, f, indent=1)
        print(f"\nWrote {len(spike_events)} spike events + {len(baseline_events)} baseline events to {args.out}")


if __name__ == '__main__':
    main()
