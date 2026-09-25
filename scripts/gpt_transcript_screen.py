#!/usr/bin/env python3
import json, math, os, statistics
from collections import defaultdict

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA=os.path.join(ROOT,"data","margin_live_30min_2026-06-22_2026-09-22.json")
OUT=os.path.join(ROOT,"data","research","gpt_transcript_screen.json")
CAPITAL=17500.0
ALLOC=0.10
START="2026-06-22"; END="2026-09-21"

raw=json.load(open(DATA))
by=defaultdict(lambda: defaultdict(list))
for r in raw["data"]["results"]:
    s=r["symbol"]
    for b in r["bars"]:
        d=b["begins_at"][:10]
        if START<=d<=END:
            by[s][d].append({
                "t":b["begins_at"][11:16],
                "o":float(b["open_price"]),"h":float(b["high_price"]),
                "l":float(b["low_price"]),"c":float(b["close_price"]),
                "v":float(b.get("volume",0) or 0)
            })
for s in by:
    for d in by[s]: by[s][d].sort(key=lambda x:x["t"])

def vwap_so_far(bars,i):
    num=den=0.0
    for j in range(i+1):
        x=bars[j]; tp=(x["h"]+x["l"]+x["c"])/3
        w=max(x["v"],1.0); num+=tp*w; den+=w
    return num/den if den else bars[i]["c"]

def entries(name,bars):
    if len(bars)<5: return []
    res=[]
    # 1) First pullback momentum: strong first hour, then first red/inside pullback, buy next break
    if name=="first_pullback":
        if bars[0]["c"]>bars[0]["o"] and bars[1]["c"]>=bars[0]["c"]:
            for i in range(2,min(7,len(bars)-1)):
                pull = bars[i]["c"]<bars[i]["o"] or bars[i]["h"]<=bars[i-1]["h"]
                if pull and bars[i+1]["h"]>bars[i]["h"]:
                    res.append((i+1,bars[i]["h"],min(bars[i]["l"],bars[i+1]["l"])))
                    break
    # 2) Opening range breakout: break first-hour high after 60m, stop at OR low
    elif name=="orb":
        orh=max(bars[0]["h"],bars[1]["h"]); orl=min(bars[0]["l"],bars[1]["l"])
        for i in range(2,min(8,len(bars))):
            if bars[i]["h"]>orh:
                res.append((i,orh,orl)); break
    # 3) VWAP reclaim: bar closes back above intraday VWAP after prior close below
    elif name=="vwap_reclaim":
        prev_below=False
        for i in range(2,min(9,len(bars))):
            vw=vwap_so_far(bars,i)
            if prev_below and bars[i]["c"]>vw and bars[i]["c"]>bars[i]["o"]:
                res.append((i,bars[i]["c"],bars[i]["l"])); break
            prev_below=bars[i]["c"]<vw
    # 4) High-of-day breakout: later break of prior HOD after at least 3 bars of consolidation
    elif name=="hod_breakout":
        for i in range(4,min(10,len(bars))):
            prior=max(x["h"] for x in bars[:i-1])
            recent=bars[i-3:i]
            compact=(max(x["h"] for x in recent)-min(x["l"] for x in recent))/max(prior,1)<0.035
            if compact and bars[i]["h"]>prior:
                res.append((i,prior,min(x["l"] for x in recent))); break
    return res

def run(name,cost_bps):
    trades=[]; daily=defaultdict(float)
    c=cost_bps/10000.0
    for s in sorted(by):
        for d,bars in sorted(by[s].items()):
            for i,entry,stop in entries(name,bars):
                entry=entry*(1+c)
                risk=max(entry-stop, entry*0.005)
                target=entry+2*risk
                exit_px=bars[-1]["c"]*(1-c); reason="close"
                for j in range(i,len(bars)):
                    b=bars[j]
                    if b["l"]<=stop:
                        exit_px=stop*(1-c); reason="stop"; break
                    if b["h"]>=target:
                        exit_px=target*(1-c); reason="target"; break
                notional=CAPITAL*ALLOC
                qty=notional/entry
                pnl=qty*(exit_px-entry)
                ret=pnl/notional
                trades.append((d,s,pnl,ret,reason))
                daily[d]+=pnl
                break
    pnls=[t[2] for t in trades]; wins=[x for x in pnls if x>0]; losses=[x for x in pnls if x<0]
    dates=sorted(daily)
    eq=CAPITAL; peak=CAPITAL; maxdd=0; rets=[]
    for d in dates:
        eq0=eq; eq+=daily[d]; rets.append((eq-eq0)/eq0 if eq0 else 0)
        peak=max(peak,eq); maxdd=min(maxdd,eq/peak-1)
    sh=0
    if len(rets)>1 and statistics.stdev(rets)>0:
        sh=statistics.mean(rets)/statistics.stdev(rets)*math.sqrt(252)
    pf=(sum(wins)/abs(sum(losses))) if losses else None
    return {
        "trades":len(trades),
        "realized_pnl":round(sum(pnls),2),
        "return_pct":round(sum(pnls)/CAPITAL*100,2),
        "sharpe":round(sh,3),
        "max_dd_pct":round(maxdd*100,2),
        "win_rate_pct":round((len(wins)/len(trades)*100) if trades else 0,2),
        "profit_factor":round(pf,3) if pf is not None else None
    }

strategies=["first_pullback","orb","vwap_reclaim","hod_breakout"]
out={"meta":{"capital":CAPITAL,"allocation_per_trade_pct":ALLOC*100,"window":[START,END],"universe":"existing 8-symbol semiconductor research universe","note":"Fast transcript-theme screen; objective approximations, not creator-faithful replications."},"rows":[]}
for s in strategies:
    a=run(s,0); b=run(s,5)
    out["rows"].append({"strategy":s,"zero_bps":a,"five_bps":b,"sensitivity_return_pp":round(b["return_pct"]-a["return_pct"],2)})
os.makedirs(os.path.dirname(OUT),exist_ok=True)
json.dump(out,open(OUT,"w"),indent=2)
print(json.dumps(out,indent=2))
