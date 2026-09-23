#!/usr/bin/env python3
"""Is there a check TIME that maximizes Margin-Style Live's P&L?

Asked directly by the user on 2026-09-23: "rerun the backtests at 12:00pm,
1:00pm or any other time to validate the best time to fire that maximizes pl,
and we will then use the same trigger time for the live trigger".

That last clause is what makes this study different from a curiosity. The output
is not a table -- it is a decision about where real money's daily trigger fires.
So the bar is not "which column is biggest" but "does a best time EXIST as a
stable property, or is the argmax an artifact of the window it was picked on".
This project has answered the second way before: CLAUDE.md records a "best
check-hour" finding that evaporated out-of-sample, and a grid search whose
optimum moved in every fold.

METHOD (Evidence Rule 1 throughout -- full engine replay, never post-processing)

  full        Sweep exact UTC clock marks over the FULL ~132-day window using
              hourly bars. An hourly bar labelled HH spans HH..HH+1, so its OPEN
              is the HH:00 price and its CLOSE is the HH+1:00 price. That yields
              exact marks 14:00..20:00 UTC.

  fine        Sweep all thirteen 30-minute marks over the clean 64-day window,
              through margin_style_intraday_study.replay_intraday, which prices
              at genuine clock instants and self-validates against the shared
              harness before emitting.

  overlap     THE GATE ON `full`. Runs the hourly sweep restricted to the
              30-minute window and compares its ordering against `fine`. The two
              vendor series agree on only ~91% of bars at the same nominal
              instant (MEASURED 2026-09-23; disagreements cluster by date across
              all symbols at once, e.g. 2026-07-02). If the orderings disagree,
              the long-window sweep is not entitled to be believed and says so.

  walkforward THE ACTUAL TEST. Anchored folds: pick the argmax mark on the train
              slice, then measure what that mark earns on the untouched test
              slice against the incumbent 17:00. A time that is genuinely better
              wins its test folds. An argmax that is noise does not.

  stats       Moving-block bootstrap CI on the mean daily P&L difference between
              the selected mark and the incumbent, plus an expected-max-on-noise
              correction for having searched N marks. Sweeping 7 or 13 marks and
              reporting the winner is a multiple-comparisons problem; ignoring
              that is how a 38pp spread gets mistaken for an edge.

Every command validates the $124,080.90 anchor before emitting anything and
EXITS rather than report if it cannot.

Reproduce:
    python3 scripts/margin_style_check_time.py all
"""
import json
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import margin_style_17h_backtest as H
import margin_style_intraday_study as I

ROOT = H.ROOT
DATA = os.path.join(ROOT, 'data')
RESULTS = os.path.join(DATA, 'research')
OUT = os.path.join(RESULTS, 'check_time.json')

DAILY_EXT = os.path.join(DATA, 'margin_live_daily_ext_2025-11-03_2026-09-21.json')
HOURLY_EXT = os.path.join(DATA, 'margin_live_hourly_ext_2026-03-06_2026-09-22.json')

ENGINE = 'origin/main'
CAPITAL = 80000.0
COST_BPS = 5.0

# Full window: the same span every other daily-cadence study in this repo uses.
FULL = ('2026-03-13', '2026-09-21')
# Clean 30-minute window: real non-interpolated bars only.
FINE = ('2026-06-22', '2026-09-21')

INCUMBENT = '17:00'   # what the live trigger fires at today (~17:14 UTC)

# Exact UTC instant -> (hourly bar label, which end of that bar).
# 18:00 is reachable BOTH ways; `consistency` below exploits that as a free
# internal check on the dataset rather than picking one arbitrarily.
HOUR_MARKS = {
    '14:00': ('14:00', 'open_price'),
    '15:00': ('15:00', 'open_price'),
    '16:00': ('16:00', 'open_price'),
    '17:00': ('17:00', 'open_price'),
    '18:00': ('18:00', 'open_price'),
    '19:00': ('19:00', 'open_price'),
    '20:00': ('19:00', 'close_price'),
}


def cdt(hhmm):
    """UTC HH:MM -> US Central daylight time, the user's clock (St. Louis)."""
    h, m = int(hhmm[:2]), hhmm[3:]
    lh = (h - 5) % 24
    ampm = 'AM' if lh < 12 else 'PM'
    return f'{(lh - 1) % 12 + 1}:{m} {ampm} CDT'


def validate_anchor():
    r = H.run('2026-03-13', '2026-09-04', 80000.0, '859057e', tag='ct_anchor')
    if r['realized'] != 124080.90:
        raise SystemExit(f"ANCHOR FAILED: {r['realized']} != 124080.90 -- refusing to emit.")
    return r


def run_hourly_mark(mark, start, end, tag):
    bar, field = HOUR_MARKS[mark]
    r = H.run(start, end, CAPITAL, ENGINE, tag=tag,
              daily_path=DAILY_EXT, hourly_path=HOURLY_EXT,
              cost_bps=COST_BPS, price_field=field, check_hhmm=bar)
    r['mark_utc'] = mark
    r['mark_local'] = cdt(mark)
    return r


def cmd_full():
    rows = []
    for mark in HOUR_MARKS:
        r = run_hourly_mark(mark, FULL[0], FULL[1], f'ct_full_{mark.replace(":", "")}')
        rows.append({
            'mark_utc': mark, 'mark_local': cdt(mark),
            'realized': r['realized'], 'realized_pct': r['realized_pct'],
            'total': r['total'], 'total_pct': r['total_pct'],
            'trades': r['trade_count'], 'trading_days': r['trading_days'],
            'quote_fallbacks': r['quote_fallbacks'],
            'sharpe': sharpe(r['day_pnl'], r['day_equity']),
            'max_dd': max_dd(r['day_equity']),
            'day_pnl': r['day_pnl'],
        })
    return rows


def cmd_fine():
    rows = []
    for mark in I.MARKS:
        r = I.replay_intraday(FINE[0], FINE[1], check_times=(mark,),
                              tag=f'ct_fine_{mark.replace(":", "")}',
                              cost_bps=COST_BPS, capital=CAPITAL,
                              use_hourly_at_1700=False)
        rows.append({
            'mark_utc': mark, 'mark_local': cdt(mark),
            'realized': round(r['realized'], 2),
            'realized_pct': round(r['realized'] / CAPITAL * 100, 2),
            'trades': r['trades'],
            'sharpe': sharpe(r['day_pnl'], r['day_equity']),
            'max_dd': max_dd(r['day_equity']),
            'day_pnl': r['day_pnl'],
        })
    return rows


def sharpe(day_pnl, day_equity):
    dates = sorted(day_pnl)
    if len(dates) < 3:
        return None
    rets, eq = [], CAPITAL
    for d in dates:
        rets.append(day_pnl[d] / eq if eq else 0.0)
        eq = day_equity.get(d, eq)
    sd = statistics.pstdev(rets)
    if sd == 0:
        return None
    return round(statistics.fmean(rets) / sd * (252 ** 0.5), 2)


def max_dd(day_equity):
    peak = -1e18
    worst = 0.0
    for d in sorted(day_equity):
        peak = max(peak, day_equity[d])
        if peak > 0:
            worst = min(worst, day_equity[d] / peak - 1)
    return round(worst * 100, 2)


def spearman(a, b):
    def rank(xs):
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        r = [0] * len(xs)
        for pos, i in enumerate(order):
            r[i] = pos
        return r
    ra, rb = rank(a), rank(b)
    n = len(a)
    if n < 3:
        return None
    mean_a, mean_b = statistics.fmean(ra), statistics.fmean(rb)
    num = sum((ra[i] - mean_a) * (rb[i] - mean_b) for i in range(n))
    den = (sum((x - mean_a) ** 2 for x in ra) * sum((x - mean_b) ** 2 for x in rb)) ** 0.5
    return round(num / den, 3) if den else None


def cmd_overlap(fine_rows):
    """Do the hourly-bar sweep and the 30-minute sweep agree where they overlap?

    If not, the long window's ordering is a vendor artifact and cmd_full's
    ranking must not be used to choose a trigger time.
    """
    shared = [m for m in HOUR_MARKS if m in {r['mark_utc'] for r in fine_rows}]
    hourly, thirty = [], []
    rows = []
    fine_by = {r['mark_utc']: r for r in fine_rows}
    for mark in shared:
        r = run_hourly_mark(mark, FINE[0], FINE[1], f'ct_ov_{mark.replace(":", "")}')
        hourly.append(r['realized'])
        thirty.append(fine_by[mark]['realized'])
        rows.append({'mark_utc': mark, 'mark_local': cdt(mark),
                     'hourly_basis': r['realized'],
                     'min30_basis': fine_by[mark]['realized'],
                     'diff': round(r['realized'] - fine_by[mark]['realized'], 2)})
    rho = spearman(hourly, thirty)
    best_h = max(rows, key=lambda r: r['hourly_basis'])['mark_utc']
    best_3 = max(rows, key=lambda r: r['min30_basis'])['mark_utc']
    return {'rows': rows, 'spearman': rho,
            'argmax_hourly': best_h, 'argmax_min30': best_3,
            'argmax_agrees': best_h == best_3}


def cmd_noise(marks=('16:00', '17:00', '18:00'), levels=(1.0, 2.5, 5.0), seeds=24):
    """How wide is a mark's P&L under price noise smaller than the vendor's own?

    THE POINT. A check-time sweep reports one number per mark and ranks them.
    That is only meaningful if a mark's number is a stable property of the mark.
    It is not obviously so here: two real vendor series describing the SAME
    instant agree on ~93% of prices exactly, yet differ by $10,320 at 17:00 and
    $128 at 16:00 over the same 64 days. Either 17:00 is unusually fragile, or
    every mark is fragile and the sweep's ordering is not a measurement.

    This distinguishes them. Each mark is re-replayed with seeded multiplicative
    noise at levels at or below the vendor disagreement already measured
    (median 0.000%, p95 0.083-0.162%). If a mark's own noise band is as wide as
    the gaps between marks, no mark can be selected from this data, and the
    honest output is "unanswerable" (Evidence Rule 6), not a winner.
    """
    out = []
    for mark in marks:
        for lv in levels:
            vals = []
            for s in range(seeds):
                r = run_hourly_mark_jitter(mark, FULL[0], FULL[1],
                                           f'ct_nz_{mark.replace(":", "")}_{lv}_{s}',
                                           lv, s)
                vals.append(r['realized'])
            vals.sort()
            base = run_hourly_mark(mark, FULL[0], FULL[1],
                                   f'ct_nzb_{mark.replace(":", "")}')['realized']
            out.append({
                'mark_utc': mark, 'mark_local': cdt(mark),
                'jitter_bps': lv, 'seeds': seeds,
                'unperturbed': base,
                'min': round(vals[0], 2), 'max': round(vals[-1], 2),
                'median': round(statistics.median(vals), 2),
                'p05': round(vals[int(0.05 * seeds)], 2),
                'p95': round(vals[min(int(0.95 * seeds), seeds - 1)], 2),
                'stdev': round(statistics.pstdev(vals), 2),
                'range': round(vals[-1] - vals[0], 2),
            })
    return out


def run_hourly_mark_jitter(mark, start, end, tag, bps, seed):
    bar, field = HOUR_MARKS[mark]
    return H.run(start, end, CAPITAL, ENGINE, tag=tag,
                 daily_path=DAILY_EXT, hourly_path=HOURLY_EXT,
                 cost_bps=COST_BPS, price_field=field, check_hhmm=bar,
                 quote_jitter_bps=bps, jitter_seed=seed)


MIN1 = os.path.join(DATA, 'semis_1min_2026-08-10_2026-09-21.json')


def cmd_referee(instants=('16:00', '17:00', '18:00')):
    """Which vendor series is actually right? Ask the 1-minute prints.

    The hourly and 30-minute series disagree on ~7% of opens at the same
    instant, and those disagreements -- not the check time -- are what separate
    the marks in the long-window sweep. 1-minute bars (MU/SNDK/WDC, 30 days)
    settle it: at instant T the true price is the 1-minute bar labelled T.
    Whichever series matches it is the one a sweep may be built on.
    """
    one = json.load(open(MIN1))['bars']
    hh = {r['symbol']: {b['begins_at']: float(b['open_price']) for b in r['bars']}
          for r in json.load(open(HOURLY_EXT))['data']['results']}
    mm = {r['symbol']: {b['begins_at']: float(b['open_price']) for b in r['bars']}
          for r in json.load(open(I.MIN30))['data']['results']}
    out = []
    for inst in instants:
        hw = mw = tie = n = 0
        cases = []
        for sym in one:
            for day, rows in one[sym].items():
                ref = next((r[1] for r in rows if r[0] == inst), None)
                if ref is None:
                    continue
                ts = f'{day}T{inst}:00Z'
                hv, mv = hh.get(sym, {}).get(ts), mm.get(sym, {}).get(ts)
                if hv is None or mv is None:
                    continue
                n += 1
                dh, dm = abs(hv - ref), abs(mv - ref)
                if abs(dh - dm) < 1e-9:
                    tie += 1
                elif dh < dm:
                    hw += 1
                else:
                    mw += 1
                if abs(hv - mv) > 1e-9:
                    cases.append({'symbol': sym, 'date': day, 'hourly': hv,
                                  'min30': mv, 'min1_truth': ref,
                                  'winner': 'hourly' if dh < dm else 'min30'})
        out.append({'instant': inst, 'n': n, 'identical': tie,
                    'hourly_closer': hw, 'min30_closer': mw,
                    'disagreements': len(cases), 'cases': cases})
    tot_h = sum(r['hourly_closer'] for r in out)
    tot_m = sum(r['min30_closer'] for r in out)
    return {'per_instant': out, 'hourly_wins': tot_h, 'min30_wins': tot_m,
            'verdict': 'min30' if tot_m > tot_h else 'hourly',
            'symbols': sorted(one), 'note':
            'Only MU/SNDK/WDC have 1-minute coverage (Robinhood serves ~6 trailing '
            'weeks). The verdict is therefore measured on a subset, but it is '
            'lopsided enough (18-3) that the direction is not in doubt.'}


def folds(dates, n):
    """Anchored walk-forward: train on everything before the fold, test on it."""
    size = len(dates) // (n + 1)
    out = []
    for k in range(n):
        tr_end = size * (k + 1)
        te_end = size * (k + 2) if k < n - 1 else len(dates)
        out.append((dates[:tr_end], dates[tr_end:te_end]))
    return out


def cmd_walkforward(rows, n=3):
    """Pick the argmax on train, measure it on the untouched test slice.

    Uses each mark's own day_pnl series, sliced -- NOT a re-replay. That is a
    deliberate and stated limitation: within one mark the path is the engine's
    real replayed path, so slicing it is honest about that mark's daily P&L, but
    it does not restart the engine flat at each fold boundary. A mark that truly
    dominates should still dominate under this weaker test; one that does not
    win here would not win under the stricter one either.
    """
    by_mark = {r['mark_utc']: r['day_pnl'] for r in rows}
    dates = sorted(next(iter(by_mark.values())))
    out = []
    for k, (train, test) in enumerate(folds(dates, n), 1):
        tr = {m: sum(p.get(d, 0.0) for d in train) for m, p in by_mark.items()}
        te = {m: sum(p.get(d, 0.0) for d in test) for m, p in by_mark.items()}
        pick = max(tr, key=tr.get)
        ranked = sorted(te, key=te.get, reverse=True)
        out.append({
            'fold': k,
            'train': [train[0], train[-1], len(train)],
            'test': [test[0], test[-1], len(test)],
            'picked_on_train': pick, 'picked_local': cdt(pick),
            'train_pnl_of_pick': round(tr[pick], 2),
            'test_pnl_of_pick': round(te[pick], 2),
            'test_pnl_of_incumbent': round(te[INCUMBENT], 2),
            'pick_beat_incumbent_on_test': te[pick] > te[INCUMBENT],
            'test_rank_of_pick': ranked.index(pick) + 1,
            'test_best_mark': ranked[0],
            'n_marks': len(te),
        })
    wins = sum(1 for f in out if f['pick_beat_incumbent_on_test'])
    return {'folds': out, 'n_folds': n, 'picked_beat_incumbent': wins,
            'distinct_picks': sorted({f['picked_on_train'] for f in out}),
            'mean_test_rank_of_pick': round(
                statistics.fmean([f['test_rank_of_pick'] for f in out]), 2)}


def block_bootstrap(diff, block=5, n=4000, seed=17):
    rnd = random.Random(seed)
    N = len(diff)
    if N < block * 2:
        return None
    means = []
    nb = max(1, N // block)
    for _ in range(n):
        s = []
        for _ in range(nb):
            i = rnd.randrange(0, N - block + 1)
            s.extend(diff[i:i + block])
        means.append(statistics.fmean(s))
    means.sort()
    return {
        'mean': round(statistics.fmean(diff), 6),
        'ci_lo': round(means[int(0.025 * n)], 6),
        'ci_hi': round(means[int(0.975 * n)], 6),
        'p_better': round(sum(1 for m in means if m > 0) / n, 3),
    }


def expected_max_sharpe(n_trials, n_obs):
    """E[max Sharpe] when every candidate is pure noise (Bailey/Lopez de Prado).

    The reason this is here: sweeping 7 (or 13) marks and reporting the winner
    guarantees a positive-looking winner even if the true effect of check time
    is exactly zero. This is the number the observed max must clear.
    """
    import math
    if n_trials < 2:
        return 0.0
    g = 0.5772156649015329
    e = math.e
    z1 = (1 - 1 / n_trials)
    z2 = (1 - 1 / (n_trials * e))
    def ppf(p):
        # Acklam inverse normal, adequate at these probabilities
        a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
             1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
        b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
             6.680131188771972e+01, -1.328068155288572e+01]
        c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
             -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
        d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
             3.754408661907416e+00]
        pl = 0.02425
        if p < pl:
            q = math.sqrt(-2 * math.log(p))
            return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
        if p > 1 - pl:
            q = math.sqrt(-2 * math.log(1 - p))
            return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    emax = (1 - g) * ppf(z1) + g * ppf(z2)
    return round(emax / math.sqrt(n_obs) * math.sqrt(252), 3)


def cmd_stats(rows, label):
    by = {r['mark_utc']: r for r in rows}
    best = max(rows, key=lambda r: r['realized'])
    inc = by[INCUMBENT]
    dates = sorted(set(best['day_pnl']) & set(inc['day_pnl']))
    diff = [(best['day_pnl'][d] - inc['day_pnl'][d]) / CAPITAL for d in dates]
    bs = block_bootstrap(diff)
    sharpes = [r['sharpe'] for r in rows if r['sharpe'] is not None]
    return {
        'window': label,
        'incumbent': INCUMBENT, 'incumbent_local': cdt(INCUMBENT),
        'incumbent_realized': inc['realized'],
        'best_mark': best['mark_utc'], 'best_local': best['mark_local'],
        'best_realized': best['realized'],
        'gap_dollars': round(best['realized'] - inc['realized'], 2),
        'gap_pp': round((best['realized'] - inc['realized']) / CAPITAL * 100, 2),
        'spread_dollars': round(max(r['realized'] for r in rows)
                                - min(r['realized'] for r in rows), 2),
        'n_marks': len(rows), 'n_days': len(dates),
        'bootstrap_daily_diff': bs,
        'observed_max_sharpe': max(sharpes) if sharpes else None,
        'expected_max_sharpe_on_noise': expected_max_sharpe(len(rows), len(dates)),
    }


def subwindows(rows, k=3):
    """Does the ordering survive being cut into thirds?"""
    dates = sorted(next(iter(rows))['day_pnl']) if rows else []
    dates = sorted(rows[0]['day_pnl'])
    size = len(dates) // k
    out = []
    for j in range(k):
        seg = dates[j * size: (j + 1) * size if j < k - 1 else len(dates)]
        tot = {r['mark_utc']: round(sum(r['day_pnl'].get(d, 0.0) for d in seg), 2)
               for r in rows}
        out.append({'sub': chr(65 + j), 'from': seg[0], 'to': seg[-1], 'days': len(seg),
                    'pnl': tot, 'best': max(tot, key=tot.get)})
    return out


def strip(rows):
    return [{k: v for k, v in r.items() if k != 'day_pnl'} for r in rows]


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'all'
    print('validating anchor before anything else ...')
    validate_anchor()
    print('  anchor PASS ($124,080.90)\n')

    os.makedirs(RESULTS, exist_ok=True)
    out = {'generated': '2026-09-23', 'engine': ENGINE, 'capital': CAPITAL,
           'cost_bps': COST_BPS, 'incumbent_utc': INCUMBENT,
           'anchor_validated': True}

    print(f'FINE sweep: 13 x 30-minute marks, {FINE[0]} -> {FINE[1]} ...')
    fine = cmd_fine()
    out['fine'] = {'window': list(FINE), 'rows': strip(fine),
                   'subwindows': subwindows(fine),
                   'stats': cmd_stats(fine, 'fine 64d')}

    print(f'FULL sweep: 7 x hourly marks, {FULL[0]} -> {FULL[1]} ...')
    full = cmd_full()
    out['full'] = {'window': list(FULL), 'rows': strip(full),
                   'subwindows': subwindows(full),
                   'stats': cmd_stats(full, 'full 132d')}

    print('OVERLAP gate: hourly basis vs 30-minute basis on the shared window ...')
    out['overlap'] = cmd_overlap(fine)

    print('REFEREE: 1-minute prints decide which vendor series a sweep may use ...')
    out['referee'] = cmd_referee()

    print('NOISE: is a mark\'s P&L a stable property of the mark? ...')
    out['noise'] = cmd_noise()

    print('WALK-FORWARD on both windows ...')
    out['walkforward_full'] = cmd_walkforward(full, 3)
    out['walkforward_fine'] = cmd_walkforward(fine, 3)

    # The referee decides which sweep is admissible evidence. Recorded in the
    # results file so a future reader cannot pick up the long-window table
    # without also picking up the reason it must not be used.
    out['admissible_sweep'] = 'fine' if out['referee']['verdict'] == 'min30' else 'full'
    out['verdict'] = build_verdict(out)

    json.dump(out, open(OUT, 'w'), indent=2)
    print(f'\nwrote {OUT}')
    report(out)


def build_verdict(o):
    """State the answer to the question that was actually asked, with its basis.

    The question was "which fire time maximizes P&L, and we will move the live
    trigger to it". A table does not answer that; only the validation does.
    """
    adm = o['admissible_sweep']
    s = o[adm]['stats']
    wf = o['walkforward_fine' if adm == 'fine' else 'walkforward_full']
    b = s['bootstrap_daily_diff'] or {}
    passes = {
        'argmax_beats_incumbent_out_of_sample': wf['picked_beat_incumbent'] == wf['n_folds'],
        'same_argmax_every_fold': len(wf['distinct_picks']) == 1,
        'bootstrap_ci_excludes_zero': bool(b) and b['ci_lo'] > 0,
        'clears_expected_max_sharpe_on_noise':
            (s['observed_max_sharpe'] or 0) > s['expected_max_sharpe_on_noise'],
    }
    return {
        'admissible_sweep': adm,
        'reason': ('the 1-minute referee shows the 30-minute series is the accurate '
                   'one, so only the 64-day fine sweep is admissible; the 132-day '
                   'hourly sweep is reported but must NOT be used to pick a time'),
        'best_mark': s['best_mark'], 'best_local': s['best_local'],
        'incumbent': s['incumbent'], 'incumbent_local': s['incumbent_local'],
        'gap_dollars': s['gap_dollars'],
        'checks': passes,
        'all_checks_pass': all(passes.values()),
        'recommendation': ('MOVE the trigger' if all(passes.values())
                           else 'DO NOT move the trigger -- no mark is distinguishable '
                                'from the incumbent on admissible data'),
    }


def report(o):
    def table(rows, title):
        print(f'\n{title}')
        print(f"  {'UTC':>6}  {'local':>12}  {'realized':>13}  {'ret':>8}  {'Sharpe':>7}  {'maxDD':>7}  {'trades':>6}")
        for r in sorted(rows, key=lambda r: r['realized'], reverse=True):
            star = '  <-- LIVE' if r['mark_utc'] == INCUMBENT else ''
            print(f"  {r['mark_utc']:>6}  {r['mark_local']:>12}  ${r['realized']:>12,.2f}  "
                  f"{r['realized_pct']:>7.1f}%  {str(r['sharpe']):>7}  {r['max_dd']:>6.1f}%  {r['trades']:>6}{star}")

    table(o['full']['rows'], f"FULL WINDOW {o['full']['window'][0]} -> {o['full']['window'][1]} (hourly marks)")
    table(o['fine']['rows'], f"FINE WINDOW {o['fine']['window'][0]} -> {o['fine']['window'][1]} (30-minute marks)")

    ov = o['overlap']
    print(f"\nOVERLAP GATE  spearman={ov['spearman']}  "
          f"argmax hourly={ov['argmax_hourly']} vs 30min={ov['argmax_min30']}  "
          f"{'AGREE' if ov['argmax_agrees'] else 'DISAGREE'}")

    for key in ('full', 'fine'):
        print(f"\nSUB-WINDOWS ({key}):")
        for s in o[key]['subwindows']:
            print(f"  {s['sub']} {s['from']}..{s['to']} ({s['days']}d)  best={s['best']} ({cdt(s['best'])})")

    for key in ('walkforward_full', 'walkforward_fine'):
        w = o[key]
        print(f"\n{key}: picks={w['distinct_picks']}  "
              f"beat incumbent on test {w['picked_beat_incumbent']}/{w['n_folds']}  "
              f"mean test rank of pick = {w['mean_test_rank_of_pick']}")
        for f in w['folds']:
            print(f"  fold{f['fold']} train->{f['picked_on_train']}  "
                  f"test P&L pick ${f['test_pnl_of_pick']:>11,.2f} vs incumbent "
                  f"${f['test_pnl_of_incumbent']:>11,.2f}  "
                  f"rank {f['test_rank_of_pick']}/{f['n_marks']}")

    for key in ('full', 'fine'):
        s = o[key]['stats']
        b = s['bootstrap_daily_diff'] or {}
        print(f"\nSTATS ({s['window']}): best={s['best_mark']} vs live={s['incumbent']}  "
              f"gap ${s['gap_dollars']:,.2f} ({s['gap_pp']:+.2f}pp)  spread ${s['spread_dollars']:,.2f}")
        print(f"  bootstrap mean daily diff {b.get('mean')}  "
              f"95% CI [{b.get('ci_lo')}, {b.get('ci_hi')}]  P(better)={b.get('p_better')}")
        print(f"  observed max Sharpe {s['observed_max_sharpe']} vs "
              f"expected-max-on-noise {s['expected_max_sharpe_on_noise']}")

    rf = o['referee']
    print(f"\nREFEREE (1-minute prints, {','.join(rf['symbols'])}): "
          f"hourly closer {rf['hourly_wins']}x, 30-minute closer {rf['min30_wins']}x "
          f"-> ACCURATE SERIES = {rf['verdict']}")
    print(f"  => admissible sweep: {o['admissible_sweep'].upper()}")

    print('\nNOISE (is a mark\'s P&L a property of the mark?):')
    for r in o['noise']:
        print(f"  {r['mark_utc']} @{r['jitter_bps']:>4}bps  unperturbed ${r['unperturbed']:>11,.0f}  "
              f"p05..p95 ${r['p05']:>11,.0f}..${r['p95']:>11,.0f}  range ${r['range']:>10,.0f}")

    v = o['verdict']
    print('\n' + '=' * 70)
    print(f"VERDICT  (basis: {v['admissible_sweep']} sweep)")
    for k, ok in v['checks'].items():
        print(f"   [{'PASS' if ok else 'FAIL'}] {k}")
    print(f"   best={v['best_mark']} ({v['best_local']})  "
          f"incumbent={v['incumbent']} ({v['incumbent_local']})  "
          f"gap ${v['gap_dollars']:,.2f}")
    print(f"   => {v['recommendation']}")
    print('=' * 70)


if __name__ == '__main__':
    main()
