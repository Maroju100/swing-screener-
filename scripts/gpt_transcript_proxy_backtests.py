#!/usr/bin/env python3
import json, math, os
from collections import defaultdict

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA=os.path.join(ROOT,"data","margin_live_30min_2026-06-22_2026-09-22.json")
OUT=os.path.join(ROOT,"data","research","gpt_transcript_proxy_backtests.json")
START_CAP=17500.0
NOTIONAL_FRAC=0.10

def load():
    d=json.load(open(DATA))
    by=defaultdict(lambda:defaultdict(list))
    for r in d["data"]["results"]:
        sym=r["symbol"]
        for b in r["bars"]:
            day=b["begins_at"][:10]
            by[sym][day].append({
                "ts":b["begins_at"],
                "o":float(b["open_price"]),"h":float(b["high_price"]),
                "l":float(b["low_price"]),"c":float(b["close_price"]),
                "v":float(b.get("volume",0) or 0)
            })
    for sym in by:
        for day in by[sym]:
            by[sym][day].sort(key=lambda x:x["ts"])
    return by

def ema(vals,n):
    a=2/(n+1); out=[]; e=None
    for x in vals:
        e=x if e is None else a*x+(1-a)*e
        out.append(e)
    return out

def vwap(bars):
    out=[]; pv=0.; vv=0.
    for b in bars:
        vol=max(b["v"],1.0); tp=(b["h"]+b["l"]+b["c"])/3
        pv+=tp*vol; vv+=vol; out.append(pv/vv)
    return out

def rr_exit(bars, i, entry, stop, side, rr=2.0):
    risk=abs(entry-stop)
    if risk<=0: return None
    tgt=entry+rr*risk if side=="long" else entry-rr*risk
    for j in range(i+1,len(bars)):
        b=bars[j]
        if side=="long":
            if b["l"]<=stop: return stop,j,"stop"
            if b["h"]>=tgt: return tgt,j,"target"
        else:
            if b["h"]>=stop: return stop,j,"stop"
            if b["l"]<=tgt: return tgt,j,"target"
    return bars[-1]["c"],len(bars)-1,"eod"

def ross(b):
    if len(b)<8:return None
    cs=[x["c"] for x in b]; e9=ema(cs,9); vw=vwap(b)
    # first strong impulse in first 2h, then 1-2 bar pullback <=50%, above VWAP/EMA9, trigger new high
    for i in range(3,min(8,len(b)-2)):
        imp_lo=min(x["l"] for x in b[:i-1]); imp_hi=max(x["h"] for x in b[:i])
        if imp_hi/imp_lo-1 < .02: continue
        pb=b[i]
        retr=(imp_hi-pb["l"])/(imp_hi-imp_lo) if imp_hi>imp_lo else 9
        if 0 < retr <= .50 and pb["c"]>vw[i] and pb["c"]>e9[i]:
            trigger=pb["h"]
            nb=b[i+1]
            if nb["h"]>trigger:
                entry=trigger; stop=pb["l"]
                ex=rr_exit(b,i+1,entry,stop,"long")
                if ex:return ("long",entry,*ex)
    return None

def humbled(b):
    if len(b)<8:return None
    cs=[x["c"] for x in b]; e8=ema(cs,8); vw=vwap(b)
    # opening flush then reclaim of both VWAP and EMA8
    op=b[0]["o"]
    for i in range(2,min(10,len(b)-1)):
        prior_below = b[i-1]["c"] < vw[i-1] or b[i-1]["c"] < e8[i-1]
        reclaim = b[i]["c"]>vw[i] and b[i]["c"]>e8[i] and b[i]["c"]>b[i]["o"]
        flushed = min(x["l"] for x in b[:i+1]) <= op*.985
        if prior_below and reclaim and flushed:
            entry=b[i]["c"]; stop=min(x["l"] for x in b[max(0,i-2):i+1])
            ex=rr_exit(b,i,entry,stop,"long")
            if ex:return ("long",entry,*ex)
    return None

def live_traders(b):
    if len(b)<9:return None
    cs=[x["c"] for x in b]; e20=ema(cs,20)
    # breakout of first 90-min high, then pullback near rising EMA20 that holds and turns up
    base_hi=max(x["h"] for x in b[:3])
    br=None
    for i in range(3,min(9,len(b)-2)):
        if b[i]["c"]>base_hi:
            br=i; break
    if br is None:return None
    for i in range(br+1,min(br+5,len(b)-1)):
        near=abs(b[i]["l"]/e20[i]-1)<=.008
        rising=e20[i]>=e20[max(0,i-2)]
        if near and rising and b[i]["c"]>=e20[i]:
            if b[i+1]["h"]>b[i]["h"]:
                entry=b[i]["h"]; stop=min(b[i]["l"],e20[i]*.997)
                ex=rr_exit(b,i+1,entry,stop,"long")
                if ex:return ("long",entry,*ex)
    return None

def riley(b):
    if len(b)<8:return None
    # failed breakout above first 90-min range: wick above, close back below; short with 2R
    hi=max(x["h"] for x in b[:3]); lo=min(x["l"] for x in b[:3])
    for i in range(3,min(10,len(b)-1)):
        if b[i]["h"]>hi*1.002 and b[i]["c"]<hi and b[i]["c"]<b[i]["o"]:
            entry=b[i]["c"]; stop=b[i]["h"]
            ex=rr_exit(b,i,entry,stop,"short")
            if ex:return ("short",entry,*ex)
        if b[i]["l"]<lo*.998 and b[i]["c"]>lo and b[i]["c"]>b[i]["o"]:
            entry=b[i]["c"]; stop=b[i]["l"]
            ex=rr_exit(b,i,entry,stop,"long")
            if ex:return ("long",entry,*ex)
    return None

STRATS={"Ross first-pullback":ross,"Humbled VWAP reclaim":humbled,
        "Live Traders breakout-pullback":live_traders,"Riley failed-breakout":riley}

def backtest(by, fn, bps):
    equity=START_CAP; peak=equity; maxdd=0; wins=0; losses=0; grossw=0; grossl=0
    daily=defaultdict(float); trades=[]
    all_days=sorted({d for x in by.values() for d in x})
    for day in all_days:
        signals=[]
        for sym in sorted(by):
            bars=by[sym].get(day)
            if not bars: continue
            s=fn(bars)
            if s:
                side,entry,exit_px,exit_i,reason=s
                signals.append((bars[0]["ts"],sym,side,entry,exit_px,reason))
        for _,sym,side,entry,exit_px,reason in signals:
            notion=equity*NOTIONAL_FRAC
            qty=notion/entry
            c=bps/10000.0
            efill=entry*(1+c if side=="long" else 1-c)
            xfill=exit_px*(1-c if side=="long" else 1+c)
            pnl=qty*((xfill-efill) if side=="long" else (efill-xfill))
            equity+=pnl; daily[day]+=pnl
            if pnl>0:wins+=1;grossw+=pnl
            elif pnl<0:losses+=1;grossl+=-pnl
            peak=max(peak,equity); maxdd=min(maxdd,equity/peak-1)
            trades.append(pnl)
    vals=[]; eq=START_CAP
    for d in all_days:
        prev=eq; eq+=daily[d]
        if prev>0: vals.append(eq/prev-1)
    sh=0
    if len(vals)>1:
        m=sum(vals)/len(vals); sd=(sum((x-m)**2 for x in vals)/(len(vals)-1))**.5
        sh=m/sd*math.sqrt(252) if sd else 0
    n=wins+losses
    return {"ending_equity":round(equity,2),"return_pct":round((equity/START_CAP-1)*100,2),
            "sharpe":round(sh,3),"max_dd_pct":round(maxdd*100,2),
            "win_rate_pct":round(wins/n*100,2) if n else 0,"trades":n,
            "profit_factor":round(grossw/grossl,3) if grossl else None,
            "gross_profit":round(grossw,2),"gross_loss":round(grossl,2),"cost_bps":bps}

def main():
    by=load(); out={"meta":{"window":["2026-06-22","2026-09-22"],"capital":START_CAP,
        "notional_per_trade_pct":NOTIONAL_FRAC*100,
        "universe":"existing margin_live 30-minute semiconductor universe",
        "warning":"Proxy logic test only; creator-specific universes, scanners, Level II/tape, catalysts and exact execution rules are not available in this dataset."},
        "strategies":{}}
    for name,fn in STRATS.items():
        out["strategies"][name]={"0bps":backtest(by,fn,0.0),"5bps":backtest(by,fn,5.0)}
    os.makedirs(os.path.dirname(OUT),exist_ok=True)
    json.dump(out,open(OUT,"w"),indent=2)
    print(json.dumps(out,indent=2))
if __name__=="__main__":main()
