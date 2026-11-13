#!/usr/bin/env python3
"""Combination search (asked 2026-11-13): build a setup from the strengths of the explored ones that beats the
top setup over Jun 1 -> Nov 11 2026 ($15,000, 5 bps/side) -- and then measure honestly whether the win is real.

SEARCH (in-sample by construction).  Full factorial over the levers that showed strength, INTRADAY_STOP untouched:
  kill-switch      -8%/10d (live) | -12%/20d | none
  peak reset       on (live) | off                (irrelevant without a kill-switch)
  drawdown throttle  off (live) | size->0 at -15% | size->0 at -25%
  volatility sizing  off (live) | 3% target | 5% target
  symbol cap       50% (live) | 25%
  whipsaw pause    off (live) | on
= 180 setups, each ONE continuous full-engine replay of origin/main.

OVERFITTING CONTROL (the statistics):
  * CSCV / Probability of Backtest Overfitting (Bailey, Borwein, Lopez de Prado, Zhu): split the daily return
    matrix into 6 blocks, for every 3-vs-3 split pick the best setup in-sample and record its out-of-sample rank.
    PBO = share of splits where the in-sample winner lands in the bottom half out-of-sample.
  * Deflated Sharpe of the winner against the best Sharpe 180 noise trials would be expected to show.
  * Block bootstrap of the winner's daily return minus live's, and minus the previous top setup's.
VALIDATION on data the search never saw (winner by net P&L, winner by Sharpe, and the CSCV-most-robust setup):
  * TIME HOLDOUT: Mar 13 -> May 29 2026 (before the search window), flat start.
  * OTHER CHIP NAMES (never used to choose anything): 11 rolling 60-day windows.
  * START-DATE reliability on the semis: 22 rolling 60-day windows (overlaps the search window; consistency only).
VERDICT, fixed before any run -- a winner is "validated" only if ALL hold: PBO <= 0.30; bootstrap 95% CI vs live
above zero; beats live on the time holdout; on other chips beats live in >= 60% of windows with a worst window no
worse than live's; semis rolling worst window no worse than live's.  Otherwise: "best in hindsight, not validated".

Gates: combined patch switched off = plain live (22,989.73); throttle-only = 25,039.25 and vol-sizing-only =
20,508.61 (the committed all_setups_from_2026-06-01 results).
MEASURED. Reproduce: python3 scripts/margin_style_combo_search.py   (resumes from data/research/combo_search_raw.json)
"""
import itertools, json, math, os, statistics as st, sys
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R
import margin_style_17h_backtest as H
import margin_style_drawdown_rules as DR
import margin_style_sizing_rules as SZ
import margin_style_reliability as RL

ROOT = RL.ROOT
RAW = os.path.join(ROOT, 'data', 'research', 'combo_search_raw.json')
START, END, CAP, COST = '2026-06-01', '2026-11-11', 15000.0, 5.0
HOLD_A, HOLD_B = '2026-03-13', '2026-05-29'


def patch_combo(src):
    """patch_size, then patch_dd's rules re-anchored on the two sizing lines patch_size has already rewritten."""
    src = SZ.patch_size(src)
    s = DR._sub
    src = s(src, "MAX_HOLD_DAYS = 6\n", "MAX_HOLD_DAYS = 6\nWHIPSAW_PAUSE = False\nDD_THROTTLE = False\nDD_THROTTLE_ZERO_AT = 0.15\n")
    src = s(src, "                  'trend_gate_active': trend_gate_active}\n",
            "                  'trend_gate_active': trend_gate_active,\n                  'cb_prev': circuit_breaker_triggered}\n")
    src = s(src, "        state['trend_gate_active'] = actions['risk_state']['trend_gate_active']\n",
            "        state['trend_gate_active'] = actions['risk_state']['trend_gate_active']\n"
            "        state['cb_prev'] = actions['risk_state'].get('cb_prev', False)\n")
    src = s(src, "    candidates = []\n    if not circuit_breaker_triggered and not kill_switch_active:\n",
            "    _whipsaw_block = WHIPSAW_PAUSE and state.get('cb_prev', False)\n"
            "    candidates = []\n    if not circuit_breaker_triggered and not kill_switch_active and not _whipsaw_block:\n")
    src = s(src, "        uncapped_deploy = safe_cash * pct * _vm\n",
            "        _dd_now = (total_equity / equity_peak - 1) if equity_peak > 0 else 0.0\n"
            "        _thr = max(0.0, 1 + _dd_now / DD_THROTTLE_ZERO_AT) if DD_THROTTLE else 1.0\n"
            "        uncapped_deploy = safe_cash * pct * _vm * min(1.0, _thr)\n")
    src = s(src, "        deploy = min(uncapped_deploy, trade_cap_pct * total_equity * _vm)\n",
            "        deploy = min(uncapped_deploy, trade_cap_pct * total_equity * _vm * min(1.0, _thr))\n")
    return src


KILLS = {'K8/10': (-0.08, 10), 'K12/20': (-0.12, 20), 'noKill': (-1.0, 10)}
GRID = []
for k, reset, thr, vol, cap, wh in itertools.product(KILLS, (True, False), (None, 0.15, 0.25), (None, 0.03, 0.05), (0.5, 0.25), (False, True)):
    if k == 'noKill' and not reset:
        continue
    p = {}
    if k != 'K8/10':
        p['KILL_SWITCH_DD'], p['KILL_SWITCH_RESUME_DAYS'] = KILLS[k]
    if not reset:
        p['KILL_SWITCH_RESET_PEAK_ON_RELEASE'] = False
    if thr:
        p['DD_THROTTLE'], p['DD_THROTTLE_ZERO_AT'] = True, thr
    if vol:
        p['VOL_SIZE'], p['VOL_TARGET'] = True, vol
    if cap != 0.5:
        p['MAX_SYMBOL_ALLOCATION_PCT'] = cap
    if wh:
        p['WHIPSAW_PAUSE'] = True
    name = ' | '.join([k, 'reset' if reset else 'noReset', f'thr{int(thr*100)}' if thr else 'thr-', f'vol{int(vol*100)}' if vol else 'vol-',
                       f'cap{int(cap*100)}', 'whip' if wh else 'whip-'])
    GRID.append((name, p))
PARAMS = dict(GRID)
LIVE = 'K8/10 | reset | thr- | vol- | cap50 | whip-'
PREV_TOP = 'K8/10 | reset | thr15 | vol- | cap50 | whip-'
VOL_ONLY = 'K8/10 | reset | thr- | vol3 | cap50 | whip-'


def one(job):
    key, name, univ, a, b, daily, hourly = job
    H.UNIVERSE = list(univ)
    try:
        r = R.replay(start=a, end=b, params=dict(PARAMS[name]) or None, tag='cs_' + str(abs(hash(key)) % 10**9), engine='origin/main',
                     cost_bps=COST, capital=CAP, src_patches=[patch_combo], daily=daily, hourly=hourly)
    except BaseException as e:
        return key, {'error': repr(e)[:200]}
    eq = r['day_equity']; ds = sorted(eq); pk = dd = 0.0
    for d in ds:
        pk = max(pk, eq[d]); dd = min(dd, eq[d] / pk - 1)
    return key, {'end': eq[ds[-1]], 'ret': (eq[ds[-1]] / CAP - 1) * 100, 'dd': dd * 100, 'trades': r['trade_count'],
                 'days': ds, 'eq': [round(eq[d], 2) for d in ds]}


def run(jobs, res):
    todo = [j for j in jobs if j[0] not in res or 'error' in res[j[0]]]
    print(f'{len(jobs)} runs, {len(todo)} to do', flush=True)
    if not todo:
        return
    with Pool(4) as pool:
        for i, (k, v) in enumerate(pool.imap_unordered(one, todo)):
            res[k] = v
            if 'error' in v:
                print('RUN ERROR', k, v['error'], flush=True)
            if (i + 1) % 20 == 0 or i + 1 == len(todo):
                json.dump(res, open(RAW, 'w'))
                print(f'progress {i + 1}/{len(todo)}', flush=True)


def rets(x):
    e = [CAP] + x['eq']
    return [e[i] / e[i - 1] - 1 for i in range(1, len(e))]


def sharpe(r):
    sd = st.pstdev(r)
    return (st.mean(r) / sd * math.sqrt(252)) if sd > 0 else 0.0


def main():
    res = json.load(open(RAW)) if os.path.exists(RAW) else {}
    gates = ((LIVE, 22989.73), (PREV_TOP, 25039.25), (VOL_ONLY, 20508.61))
    run([(f'G|{n}', n, RL.SEMIS, START, END, RL.D, RL.HR) for n, _ in gates], res)
    for n, want in gates:
        assert abs(res[f'G|{n}']['end'] - want) < 0.01, f'GATE FAILED {n} {res[f"G|{n}"]}'
    print('gates PASS', flush=True)
    run([(f'G|{n}', n, RL.SEMIS, START, END, RL.D, RL.HR) for n, _ in GRID], res)
    G = {n: res[f'G|{n}'] for n, _ in GRID if 'error' not in res[f'G|{n}']}
    names = list(G); RT = {n: rets(G[n]) for n in names}; T = min(len(v) for v in RT.values())
    SH = {n: sharpe(RT[n][:T]) for n in names}
    by_pnl = sorted(names, key=lambda n: -G[n]['end']); by_sh = sorted(names, key=lambda n: -SH[n])
    # CSCV / PBO
    S = 6; edges = [round(i * T / S) for i in range(S + 1)]; blocks = [list(range(edges[i], edges[i + 1])) for i in range(S)]
    lam, oos_rank_sum, pairs = [], {n: 0.0 for n in names}, []
    combos = list(itertools.combinations(range(S), S // 2))
    for c in combos:
        ins = [i for b in c for i in blocks[b]]; oos = [i for b in range(S) if b not in c for i in blocks[b]]
        si = {n: sharpe([RT[n][i] for i in ins]) for n in names}; so = {n: sharpe([RT[n][i] for i in oos]) for n in names}
        best = max(names, key=lambda n: si[n]); order = sorted(names, key=lambda n: so[n])
        w = (order.index(best) + 1) / (len(names) + 1); lam.append(math.log(w / (1 - w))); pairs.append((si[best], so[best]))
        for rk, n in enumerate(order):
            oos_rank_sum[n] += (rk + 1) / len(names)
    pbo = sum(l <= 0 for l in lam) / len(lam)
    robust = max(names, key=lambda n: oos_rank_sum[n])
    W = by_pnl[0]; cands = []
    for n in (W, by_sh[0], robust):
        if n not in cands and n not in (LIVE,):
            cands.append(n)
    emax = R.expected_max_sharpe([SH[n] / math.sqrt(252) for n in names])
    dsr = R.deflated_sharpe(SH[W] / math.sqrt(252), emax, RT[W][:T])
    boot = {n: {'vs_live': R.block_bootstrap_diff(RT[n][:T], RT[LIVE][:T]), 'vs_prev_top': R.block_bootstrap_diff(RT[n][:T], RT[PREV_TOP][:T])} for n in cands}
    # validation on unseen data
    ref = [LIVE, PREV_TOP] + cands
    sw = RL.windows(RL.tdays(RL.HR, 'AMD'), 5); ow = RL.windows([d for d in RL.tdays(RL.WH, 'AVGO') if d <= '2026-11-05'], 10)
    jobs = [(f'H|{n}', n, RL.SEMIS, HOLD_A, HOLD_B, RL.D, RL.HR) for n in ref]
    jobs += [(f'O|{a}|{n}', n, RL.BASK['OTHER CHIPS'], a, b, RL.WD, RL.WH) for n in ref for a, b in ow]
    jobs += [(f'S|{a}|{n}', n, RL.SEMIS, a, b, RL.D, RL.HR) for n in ref for a, b in sw]
    run(jobs, res)

    def roll(prefix, wins, n):
        r = [res[f'{prefix}|{a}|{n}']['ret'] for a, _ in wins]; lv = [res[f'{prefix}|{a}|{LIVE}']['ret'] for a, _ in wins]
        return {'median': st.median(r), 'worst': min(r), 'best': max(r), 'pct_beat_live': 100 * sum(x > y + 1e-9 for x, y in zip(r, lv)) / len(r)}
    val = {n: {'period_end': G[n]['end'], 'period_ret': G[n]['ret'], 'period_dd': G[n]['dd'], 'sharpe': SH[n],
               'holdout_ret': res[f'H|{n}']['ret'], 'other_chips': roll('O', ow, n), 'semis_roll': roll('S', sw, n)} for n in ref}
    L = val[LIVE]; verdict = {}
    for n in cands:
        v = val[n]; lo = boot[n]['vs_live'][0]
        ch = {'PBO <= 0.30': pbo <= 0.30, 'bootstrap CI vs live above zero': lo > 0, 'beats live on time holdout': v['holdout_ret'] > L['holdout_ret'],
              'other chips: beats live >= 60% of windows': v['other_chips']['pct_beat_live'] >= 60,
              'other chips: worst window no worse': v['other_chips']['worst'] >= L['other_chips']['worst'],
              'semis rolling: worst window no worse': v['semis_roll']['worst'] >= L['semis_roll']['worst']}
        verdict[n] = {'checks': ch, 'passed': sum(ch.values()), 'validated': all(ch.values())}
    months = sorted({d[:7] for d in G[LIVE]['days']})

    def monthly(n):
        prev, out = CAP, {}
        for m in months:
            e = [v for d, v in zip(G[n]['days'], G[n]['eq']) if d.startswith(m)][-1]; out[m] = round(e - prev, 2); prev = e
        return out
    out = {'window': [START, END], 'capital': CAP, 'cost_bps': COST, 'n_setups': len(names), 'live': LIVE, 'previous_top': PREV_TOP,
           'top20_by_pnl': [{'setup': n, 'end': G[n]['end'], 'ret': G[n]['ret'], 'dd': G[n]['dd'], 'sharpe': SH[n], 'monthly': monthly(n)} for n in by_pnl[:20]],
           'rank_of_live': by_pnl.index(LIVE) + 1, 'rank_of_previous_top': by_pnl.index(PREV_TOP) + 1,
           'n_beating_previous_top': by_pnl.index(PREV_TOP),
           'cscv': {'blocks': S, 'splits': len(combos), 'pbo': pbo, 'mean_is_sharpe_of_pick': st.mean(p[0] for p in pairs),
                    'mean_oos_sharpe_of_pick': st.mean(p[1] for p in pairs), 'most_robust': robust},
           'deflated_sharpe_winner': dsr, 'expected_max_sharpe_noise_annual': emax * math.sqrt(252),
           'bootstrap': {n: {k: list(v) for k, v in b.items()} for n, b in boot.items()},
           'candidates': {'by_pnl': W, 'by_sharpe': by_sh[0], 'cscv_most_robust': robust},
           'validation': val, 'monthly': {n: monthly(n) for n in ref}, 'verdict': verdict,
           'all': {n: {'end': G[n]['end'], 'dd': G[n]['dd'], 'sharpe': SH[n], 'trades': G[n]['trades']} for n in by_pnl}}
    json.dump(out, open(os.path.join(ROOT, 'data', 'research', 'combo_search.json'), 'w'), indent=1, default=str)
    print(f"\n{len(names)} setups; live rank {out['rank_of_live']}, previous top rank {out['rank_of_previous_top']}; {out['n_beating_previous_top']} beat the previous top")
    for i, x in enumerate(out['top20_by_pnl'][:12]):
        print(f"{i+1:3} {x['end']-CAP:+10.2f} {x['ret']:+7.2f}% dd {x['dd']:+6.1f} sh {x['sharpe']:.2f} | " + ' '.join(f'{v:+7.0f}' for v in x['monthly'].values()) + f" | {x['setup']}")
    print(f"\nCSCV: PBO {pbo:.2f} over {len(combos)} splits; in-sample pick Sharpe {out['cscv']['mean_is_sharpe_of_pick']:.2f} -> out-of-sample {out['cscv']['mean_oos_sharpe_of_pick']:.2f}; most robust: {robust}")
    print(f"deflated Sharpe of winner {dsr:.3f} (noise max Sharpe {out['expected_max_sharpe_noise_annual']:.2f})")
    print('\nsetup: period% dd | holdout% | other chips med/worst/%beat | semis roll med/worst/%beat')
    for n in ref:
        v = val[n]; o, s = v['other_chips'], v['semis_roll']
        print(f"  {v['period_ret']:+7.1f} {v['period_dd']:+6.1f} | {v['holdout_ret']:+6.1f} | {o['median']:+6.1f} {o['worst']:+6.1f} {o['pct_beat_live']:4.0f} | {s['median']:+6.1f} {s['worst']:+6.1f} {s['pct_beat_live']:4.0f} | {n}")
    for n in cands:
        b = boot[n]; print(f"\n{n}\n  bootstrap vs live CI [{b['vs_live'][0]*100:+.3f}%, {b['vs_live'][1]*100:+.3f}%] P {b['vs_live'][2]:.3f}; vs previous top CI [{b['vs_prev_top'][0]*100:+.3f}%, {b['vs_prev_top'][1]*100:+.3f}%] P {b['vs_prev_top'][2]:.3f}")
        for k, ok in verdict[n]['checks'].items():
            print(f"  {'PASS' if ok else 'FAIL'}  {k}")
        print('  =>', 'VALIDATED' if verdict[n]['validated'] else f"best in hindsight, NOT validated ({verdict[n]['passed']} of 6)")


if __name__ == '__main__':
    main()
