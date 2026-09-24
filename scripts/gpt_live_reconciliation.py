#!/usr/bin/env python3
"""GPT audit: live-scale replay and broker-fill reconciliation.

Research-only. Replays the production B0 engine from the live activation period
at roughly the observed account capital, then compares simulated trade groups
against committed Robinhood broker fills. Manual broker fills are reported
separately and never treated as strategy execution.

This does NOT modify production state or the live engine.
"""
import csv
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import margin_style_research as R

ROOT = R.ROOT
FILLS = os.path.join(ROOT, "data", "broker_fills_912291820_2026-09-08_2026-09-21.csv")
OUT = os.path.join(R.RESULTS, "gpt_live_reconciliation_17_5k.json")
CAPITAL = 17500.0
START = "2026-07-22"
END = "2026-09-21"
MATCH_START = "2026-09-08"
MATCH_END = "2026-09-21"


def replay(capital, cost_bps, price_field, hourly_path, start=START, tag="gpt_live_recon"):
    return R.H.run(
        start, END, capital, R.ENGINE,
        params=None, tag=tag, src_patches=None,
        daily_path=R.DAILY_EXT, hourly_path=hourly_path,
        cost_bps=cost_bps, price_field=price_field, check_hhmm="17:00"
    )


def load_broker():
    rows = []
    with open(FILLS, newline="") as f:
        for line in f:
            if line.startswith("#"):
                continue
            if not line.strip():
                continue
            # first non-comment line is header
            header = [x.strip() for x in line.strip().split(",")]
            break
        reader = csv.DictReader(f, fieldnames=header)
        for r in reader:
            r["quantity"] = float(r["quantity"])
            r["average_price"] = float(r["average_price"])
            r["date"] = r["created_at"][:10]
            rows.append(r)
    return rows


def agg_sim(trades):
    g = defaultdict(lambda: {"shares": 0.0, "notional": 0.0, "count": 0})
    for t in trades:
        d = t.get("date")
        if not d or d < MATCH_START or d > MATCH_END:
            continue
        side = t["side"]
        q = abs(float(t["shares"]))
        px = float(t.get("price", t.get("avg_price", 0.0)))
        k = (d, t["symbol"], side)
        g[k]["shares"] += q
        g[k]["notional"] += q * px
        g[k]["count"] += 1
    return g


def agg_broker(rows, agent):
    g = defaultdict(lambda: {"shares": 0.0, "notional": 0.0, "count": 0})
    for r in rows:
        if r["placed_agent"] != agent:
            continue
        k = (r["date"], r["symbol"], r["side"])
        q = abs(r["quantity"])
        g[k]["shares"] += q
        g[k]["notional"] += q * r["average_price"]
        g[k]["count"] += 1
    return g


def compare(sim, broker):
    keys = sorted(set(sim) | set(broker))
    rows = []
    for k in keys:
        s = sim.get(k, {"shares": 0.0, "notional": 0.0, "count": 0})
        b = broker.get(k, {"shares": 0.0, "notional": 0.0, "count": 0})
        svwap = s["notional"] / s["shares"] if s["shares"] else None
        bvwap = b["notional"] / b["shares"] if b["shares"] else None
        px_bps = None
        if svwap and bvwap:
            px_bps = (bvwap / svwap - 1.0) * 10000.0
            if k[2] == "sell":
                # positive means broker execution better for both sides
                px_bps = -px_bps
        rows.append({
            "date": k[0], "symbol": k[1], "side": k[2],
            "sim_shares": round(s["shares"], 6),
            "broker_shares": round(b["shares"], 6),
            "share_delta": round(b["shares"] - s["shares"], 6),
            "sim_vwap": round(svwap, 4) if svwap is not None else None,
            "broker_vwap": round(bvwap, 4) if bvwap is not None else None,
            "execution_vs_sim_bps_positive_is_better": round(px_bps, 2) if px_bps is not None else None,
            "sim_count": s["count"], "broker_count": b["count"],
        })
    both = [x for x in rows if x["sim_shares"] and x["broker_shares"]]
    exactish = [x for x in both if abs(x["share_delta"]) <= max(0.01, 0.01 * x["sim_shares"])]
    weighted_bps_num = weighted_bps_den = 0.0
    for x in both:
        if x["execution_vs_sim_bps_positive_is_better"] is not None:
            w = min(x["sim_shares"], x["broker_shares"]) * (x["sim_vwap"] or 0.0)
            weighted_bps_num += x["execution_vs_sim_bps_positive_is_better"] * w
            weighted_bps_den += w
    return rows, {
        "sim_groups": len(sim), "broker_agentic_groups": len(broker),
        "overlapping_groups": len(both),
        "quantity_match_within_1pct_or_0_01_shares": len(exactish),
        "notional_weighted_execution_vs_sim_bps_positive_is_better":
            round(weighted_bps_num / weighted_bps_den, 2) if weighted_bps_den else None,
    }


def summarize_run(r, capital):
    s = R.summarize(r)
    return {"starting_capital": capital, **s}


def main():
    broker_rows = load_broker()
    agentic = agg_broker(broker_rows, "agentic")
    manual = agg_broker(broker_rows, "user")

    runs = {}
    # Full live-period approximation using hourly 17:00 open (noon CDT).
    for cost in (0.0, 5.0):
        r = replay(CAPITAL, cost, "open_price", R.HOURLY_EXT,
                   start=START, tag=f"gpt_live17500_hourly_{cost:g}")
        runs[f"hourly_17open_{cost:g}bps"] = summarize_run(r, CAPITAL)
        if cost == 0.0:
            sim = agg_sim(r["trades"])
            comparison, match_stats = compare(sim, agentic)
            sim_trade_count = len(r["trades"])

    # 30-minute vendor cross-check on its available overlap.
    for cost in (0.0, 5.0):
        r30 = replay(CAPITAL, cost, "open_price", R.MIN30,
                     start="2026-06-22", tag=f"gpt_live17500_min30_{cost:g}")
        runs[f"min30_17open_2026-06-22_{cost:g}bps"] = summarize_run(r30, CAPITAL)

    manual_rows = []
    for (d, sym, side), v in sorted(manual.items()):
        manual_rows.append({
            "date": d, "symbol": sym, "side": side,
            "shares": round(v["shares"], 6),
            "vwap": round(v["notional"] / v["shares"], 4) if v["shares"] else None,
            "count": v["count"],
        })

    out = {
        "_meta": {
            "audit": "GPT live-scale replay + broker reconciliation",
            "engine": R.ENGINE,
            "capital": CAPITAL,
            "replay_window": [START, END],
            "broker_match_window": [MATCH_START, MATCH_END],
            "production_modified": False,
            "important_limitations": [
                "Historical engine snapshot is replayed consistently; this is not a time-versioned replay of every code revision used live.",
                "Broker reconciliation uses committed fills with placed_agent labels only for 2026-09-08..2026-09-21.",
                "Price comparison is against replay check-time proxy, not the exact signal quote captured by the live agent.",
                "Manual broker fills are excluded from agentic matching but still can alter real account state/capital."
            ],
        },
        "replays": runs,
        "broker_reconciliation": {
            "sim_trade_count_full_replay": sim_trade_count,
            "match_stats": match_stats,
            "groups": comparison,
            "manual_broker_groups": manual_rows,
        },
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
