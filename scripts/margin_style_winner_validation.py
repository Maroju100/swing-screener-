#!/usr/bin/env python3
"""Why the combo-search winner fails validation, and a single-hypothesis re-test (asked 2026-11-13).

Winner W = live v2 with peak reset OFF and symbol cap 25%.  It is two changes, so everything is run as a 2x2:
  LIVE (reset on, cap 50) | CAP (reset on, cap 25) | NORESET (reset off, cap 50) | W (reset off, cap 25)
No search here: one pre-named candidate and its two components.  $15,000, 5 bps/side, engine origin/main.

 A  attribution over the search window Jun 1 -> Nov 11, with every kill-switch fire/release date logged
 B  how concentrated the edge is: days on which W and LIVE differ, share of the gap from the 5 biggest days
 C  full history Mar 13 -> Nov 11, continuous: block-bootstrap of daily difference vs LIVE, kill-switch events
 D  time holdout Mar 13 -> May 29 (before the search window)
 E  semis, 22 rolling 60-day start dates: wins / ties / losses vs LIVE, mean and median gap, worst window
 F  other chip names (unseen), 11 rolling start dates: same
 G  big tech / non-tech / sector ETFs x rising, falling, crash: same (9 cells)
Gates: the logging patch switched on must not change results (W over the window = 25,999.42; LIVE = 22,989.73).
MEASURED. Reproduce: python3 scripts/margin_style_winner_validation.py
"""
import json, os, statistics as st, sys, tempfile
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_17h_backtest as H
import margin_style_drawdown_rules as DR
import margin_style_combo_search as C
import margin_style_reliability as RL

CAP = C.CAP
N = {'LIVE': C.LIVE, 'CAP': 'K8/10 | reset | thr- | vol- | cap25 | whip-', 'NORESET': 'K8/10 | noReset | thr- | vol- | cap50 | whip-',
     'W': 'K8/10 | noReset | thr- | vol- | cap25 | whip-'}
SUB = {'rising': ('2026-03-13', '2026-06-19'), 'falling': ('2026-06-22', '2026-09-30'), 'crash': ('2026-10-01', '2026-11-05')}
LOGDIR = tempfile.mkdtemp(prefix='kslog_')


def patch_log(src):
    s = DR._sub
    src = s(src, "        kill_switch_triggered_date = today\n",
            "        kill_switch_triggered_date = today\n"
            "        if KS_LOG:\n            open(KS_LOG, 'a').write('fire ' + today + ' ' + str(round(dd_now * 100, 1)) + '\\n')\n")
    src = s(src, "            kill_switch_active = False\n            if KILL_SWITCH_RESET_PEAK_ON_RELEASE:\n",
            "            kill_switch_active = False\n"
            "            if KS_LOG:\n                open(KS_LOG, 'a').write('release ' + today + '\\n')\n"
            "            if KILL_SWITCH_RESET_PEAK_ON_RELEASE:\n")
    return src.replace('\nSYMBOLS', "\nKS_LOG = ''\nSYMBOLS", 1)


def logged(job):
    key, name, a, b = job
    H.UNIVERSE = list(RL.SEMIS)
    log = os.path.join(LOGDIR, key.replace('|', '_') + '.txt')
    r = R.replay(start=a, end=b, params={**C.PARAMS[N[name]], 'KS_LOG': log}, tag='wv_' + key.replace('|', '_'), engine='origin/main',
                 cost_bps=C.COST, capital=CAP, src_patches=[C.patch_combo, patch_log], daily=RL.D, hourly=RL.HR)
    eq = r['day_equity']; ds = sorted(eq)
    ev = sorted(set(open(log).read().split('\n')) - {''}, key=lambda x: x.split()[1]) if os.path.exists(log) else []
    return key, {'end': eq[ds[-1]], 'days': ds, 'eq': [eq[d] for d in ds], 'events': ev, 'trades': r['trade_count']}


def main():
    res = json.load(open(C.RAW))
    sw = RL.windows(RL.tdays(RL.HR, 'AMD'), 5); ow = RL.windows([d for d in RL.tdays(RL.WH, 'AVGO') if d <= '2026-11-05'], 10)
    jobs = []
    for k, n in N.items():
        jobs += [(f'H|{n}', n, RL.SEMIS, C.HOLD_A, C.HOLD_B, RL.D, RL.HR)]
        jobs += [(f'O|{a}|{n}', n, RL.BASK['OTHER CHIPS'], a, b, RL.WD, RL.WH) for a, b in ow]
        jobs += [(f'S|{a}|{n}', n, RL.SEMIS, a, b, RL.D, RL.HR) for a, b in sw]
        jobs += [(f'B|{bk}|{w}|{n}', n, RL.BASK[bk], a, b, RL.WD, RL.WH) for bk in ('BIG TECH', 'NON-TECH 8', 'SECTOR ETFs') for w, (a, b) in SUB.items()]
    C.run(jobs, res)
    with Pool(4) as pool:
        L = dict(pool.map(logged, [(f'{w}|{k}', k, a, b) for k in N for w, (a, b) in (('win', (C.START, C.END)), ('full', ('2026-03-13', C.END)))]))
    assert abs(L['win|W']['end'] - 25999.42) < 0.01 and abs(L['win|LIVE']['end'] - 22989.73) < 0.01, 'GATE FAILED'
    print('gates PASS')
    out = {'names': N}
    print('\nA attribution, Jun 1 -> Nov 11 (net $):')
    out['A'] = {k: {'net': L[f'win|{k}']['end'] - CAP, 'events': L[f'win|{k}']['events']} for k in N}
    for k in N:
        print(f"  {k:8} {out['A'][k]['net']:+10.2f}  kill-switch: {', '.join(out['A'][k]['events']) or 'never fired'}")

    def rets(x):
        e = [CAP] + x['eq']; return [e[i] / e[i - 1] - 1 for i in range(1, len(e))]
    w, l = L['win|W'], L['win|LIVE']
    dd = [(d, (a - a0) - (b - b0)) for d, a, a0, b, b0 in zip(w['days'], w['eq'], [CAP] + w['eq'], l['eq'], [CAP] + l['eq'])]
    nz = [x for x in dd if abs(x[1]) > 0.005]; tot = sum(x[1] for x in dd); top = sorted(nz, key=lambda x: -abs(x[1]))[:5]
    first = nz[0][0] if nz else None
    pre_oct = sum(x[1] for x in dd if x[0] < '2026-10-01')
    out['B'] = {'gap': tot, 'days_total': len(dd), 'days_differ': len(nz), 'top5': top, 'top5_sum': sum(x[1] for x in top),
                'gap_before_oct': pre_oct, 'gap_oct_nov': tot - pre_oct}
    print(f"\nB concentration: gap W-LIVE ${tot:+,.2f}; differ on {len(nz)} of {len(dd)} days; Jun-Sep ${pre_oct:+,.2f}, Oct-Nov ${tot - pre_oct:+,.2f}")
    print('  5 biggest days: ' + ', '.join(f'{d} {v:+.0f}' for d, v in top) + f"  (sum {sum(x[1] for x in top):+,.0f})")
    print('\nC full history Mar 13 -> Nov 11:')
    out['C'] = {}
    for k in N:
        f = L[f'full|{k}']; lo, hi, p = R.block_bootstrap_diff(rets(f), rets(L['full|LIVE'])) if k != 'LIVE' else (0, 0, 0)
        out['C'][k] = {'net': f['end'] - CAP, 'ret': (f['end'] / CAP - 1) * 100, 'events': f['events'], 'ci': [lo, hi], 'p_better': p}
        print(f"  {k:8} {out['C'][k]['ret']:+7.1f}%  CI vs live [{lo*100:+.3f}%, {hi*100:+.3f}%] P {p:.3f}  events: {', '.join(f['events']) or 'none'}")
    print('\nD holdout Mar 13 -> May 29:')
    out['D'] = {k: res[f'H|{n}']['ret'] for k, n in N.items()}
    print('  ' + '  '.join(f'{k} {v:+.2f}%' for k, v in out['D'].items()))

    def paired(prefix, keys):
        o = {}
        for k, n in N.items():
            r = [res[f'{prefix}|{a}|{n}']['ret'] for a in keys]; lv = [res[f'{prefix}|{a}|{N["LIVE"]}']['ret'] for a in keys]
            d = [x - y for x, y in zip(r, lv)]
            o[k] = {'median': st.median(r), 'worst': min(r), 'wins': sum(x > 0.005 for x in d), 'ties': sum(abs(x) <= 0.005 for x in d),
                    'losses': sum(x < -0.005 for x in d), 'mean_gap': st.mean(d), 'median_gap': st.median(d), 'worst_gap': min(d), 'best_gap': max(d)}
        return o
    for tag, title, prefix, keys in (('E', 'semis, 22 rolling start dates', 'S', [a for a, _ in sw]), ('F', 'other chips, 11 rolling start dates', 'O', [a for a, _ in ow]),
                                     ('G', 'big tech / non-tech / ETFs, 9 cells', 'B', [f'{bk}|{w_}' for bk in ('BIG TECH', 'NON-TECH 8', 'SECTOR ETFs') for w_ in SUB])):
        out[tag] = paired(prefix, keys)
        print(f'\n{tag} {title}:  median  worst | wins ties losses vs LIVE | mean gap  median gap  worst gap  best gap')
        for k, v in out[tag].items():
            print(f"  {k:8} {v['median']:+6.1f} {v['worst']:+6.1f} | {v['wins']:3} {v['ties']:3} {v['losses']:3} | {v['mean_gap']:+6.2f} {v['median_gap']:+6.2f} {v['worst_gap']:+6.2f} {v['best_gap']:+6.2f}")
    json.dump(out, open(os.path.join(C.ROOT, 'data', 'research', 'winner_validation.json'), 'w'), indent=1, default=str)


if __name__ == '__main__':
    main()
