#!/usr/bin/env python3
"""Transcript-derived setup comparison on common 30-minute semiconductor data.

Research-only proxy test. These are objective approximations of rules extracted
from youtube_transcripts; they are NOT claims to reproduce each creator's exact
strategy, especially where the transcript depends on premarket, float, catalyst,
Level 2, tape reading, or subjective supply/demand zones.

Universe/data: AMD MU WDC SNDK TSM INTC LRCX STX
Bars: 30-minute regular-session data, 2026-06-22..2026-09-21
Capital: $17,500
Sizing: max 25% of starting equity per trade; one position at a time per symbol;
        multiple symbols can trade the same day.
Exit: setup stop, 2R target (except failed-breakout Riley proxy uses 1.5R), or EOD.
Costs: per-side bps on every entry/exit.
"""
import json, math, os, statistics
from collections import defaultdict, deque

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "margin_live_30min_2026-06-22_2026-09-22.json")
OUT = os.path.join(ROOT, "data", "research", "transcript_setup_backtest.json")
CAPITAL = 17500.0
MAX_ALLOC = 0.25
START = "2026-06-22"
END = "2026-09-21"

def load():
    raw=json.load(open(DATA))
    out={}
    for r in raw["data"]["results"]:
        byday=defaultdict(list)
        for b in r["bars"]:
            d=b["begins_at"][:10]
            if START <= d <= END:
                x={k:(float(v) if k!="begins_at" else v) for k,v in b.items()}
                byday[d].append(x)
        for d in byday: byday[d].sort(key=lambda z:z["begins_at"])
        out[r["symbol"]]=dict(byday)
    return out

def ema(vals, n):
    if not vals: return None
    a=2/(n+1)
    e=vals[0]
    for v in vals[1:]: e=a*v+(1-a)*e
    return e

def vwap(bars):
    vol=sum(b["volume"] for b in bars)
    if vol<=0: return bars[-1]["close_price"]
    return sum(((b["high_price"]+b["low_price"]+b["close_price"])/3)*b["volume"] for b in bars)/vol

def prior_close(data,sym,day):
    ds=sorted(data[sym])
    i=ds.index(day)
    if i==0: return None
    return data[sym][ds[i-1]][-1]["close_price"]

def firstbar_relvol(data,sym,day,lookback=20):
    ds=sorted(data[sym]); i=ds.index(day)
    vals=[]
    for d in ds[max(0,i-lookback):i]:
        if data[sym][d]: vals.append(data[sym][d][0]["volume"])
    if len(vals)<5: return None
    med=statistics.median(vals)
    return data[sym][day][0]["volume"]/med if med else None

def avg_day_range(data,sym,day,lookback=14):
    ds=sorted(data[sym]); i=ds.index(day)
    vals=[]
    for d in ds[max(0,i-lookback):i]:
        bs=data[sym][d]
        vals.append(max(x["high_price"] for x in bs)-min(x["low_price"] for x in bs))
    return statistics.mean(vals) if len(vals)>=5 else None

def prev_daily_closes(data,sym,day,n=6):
    ds=sorted(data[sym]); i=ds.index(day)
    return [data[sym][d][-1]["close_price"] for d in ds[max(0,i-n):i]]

def choose_trade(setup,data,sym,day):
    bs=data[sym][day]
    if len(bs)<6: return None
    pc=prior_close(data,sym,day)
    if not pc: return None
    gap=bs[0]["open_price"]/pc-1
    closes=[b["close_price"] for b in bs]
    relv=firstbar_relvol(data,sym,day)

    # 1) Ross Cameron adapted first-pullback momentum proxy.
    if setup=="ross_first_pullback":
        # Transcript: gap higher, high relative volume, first pullback, <=50% retrace,
        # hold VWAP and 9EMA. Relaxed rel-vol for this large-cap universe.
        if gap < 0.02 or relv is None or relv < 1.5: return None
        # initial thrust in first 2 bars
        hi=max(bs[0]["high_price"],bs[1]["high_price"])
        lo0=bs[0]["low_price"]
        if hi/bs[0]["open_price"]-1 < 0.01: return None
        for j in (2,3,4):
            pb=bs[j]
            if pb["close_price"] >= pb["open_price"]: continue
            retr=(hi-pb["low_price"])/max(1e-9,hi-lo0)
            vw=vwap(bs[:j+1]); e9=ema(closes[:j+1],9)
            if retr <= 0.50 and pb["low_price"] >= min(vw,e9):
                if j+1>=len(bs): return None
                ent=bs[j+1]["open_price"]; stop=pb["low_price"]
                if stop>=ent: return None
                return (j+1,ent,stop,2.0,"gap>=2%, relvol>=1.5x, first pullback <=50%, holds VWAP/EMA9")
        return None

    # 2) Humbled Trader adapted gap-reclaim proxy.
    if setup=="humbled_gap_reclaim":
        # Transcript examples: gapper, reclaim premarket/key level, VWAP/EMA confirmation.
        if gap < 0.025: return None
        opening_high=bs[0]["high_price"]
        running_low=bs[0]["low_price"]
        for j in range(1,min(6,len(bs)-1)):
            running_low=min(running_low,bs[j]["low_price"])
            vw=vwap(bs[:j+1]); e8=ema(closes[:j+1],8)
            if bs[j]["close_price"] > opening_high and bs[j]["close_price"] > vw and bs[j]["close_price"] > e8:
                ent=bs[j+1]["open_price"]; stop=running_low
                if stop>=ent: return None
                return (j+1,ent,stop,2.0,"gap>=2.5%, reclaim opening high + VWAP + EMA8")
        return None

    # 3) ChartFanatics / Clement adapted opening-range reclaim continuation.
    if setup=="chart_orh_reclaim":
        # Transcript: uptrend, flush/reclaim VWAP, break 5-min opening range high, stop LOD.
        prev=prev_daily_closes(data,sym,day,6)
        if len(prev)<5 or prev[-1] <= statistics.mean(prev[-5:]): return None
        or_high=bs[0]["high_price"]; lod=bs[0]["low_price"]
        flushed=bs[0]["close_price"] < bs[0]["open_price"]
        if not flushed: return None
        for j in range(1,min(7,len(bs)-1)):
            lod=min(lod,bs[j]["low_price"])
            vw=vwap(bs[:j+1])
            if bs[j]["close_price"] > or_high and bs[j]["close_price"] > vw:
                ent=bs[j+1]["open_price"]; stop=lod
                if stop>=ent: return None
                return (j+1,ent,stop,2.0,"daily uptrend + opening flush + VWAP reclaim + ORH break")
        return None

    # 4) Live Traders adapted relative-strength / ATR-direction breakout.
    if setup=="live_relstrength_breakout":
        atr=avg_day_range(data,sym,day,14)
        if atr is None: return None
        # Market proxy = equal-weight move of the other universe names at same bar.
        first2=bs[:2]
        stockret=first2[-1]["close_price"]/bs[0]["open_price"]-1
        peer=[]
        for other in data:
            if other==sym or day not in data[other] or len(data[other][day])<2: continue
            ob=data[other][day]
            peer.append(ob[1]["close_price"]/ob[0]["open_price"]-1)
        mkt=statistics.mean(peer) if peer else 0
        if stockret < mkt + 0.005: return None
        or_high=max(x["high_price"] for x in first2)
        daylow=min(x["low_price"] for x in first2)
        used=or_high-daylow
        if used > 0.8*atr: return None
        for j in range(2,min(7,len(bs)-1)):
            if bs[j]["close_price"] > or_high:
                ent=bs[j+1]["open_price"]; stop=min(x["low_price"] for x in bs[max(0,j-2):j+1])
                if stop>=ent: return None
                return (j+1,ent,stop,2.0,"relative strength > peers + ATR room + opening breakout")
        return None

    # 5) Riley Coleman adapted pullback continuation proxy.
    if setup=="riley_pullback_trend":
        # Transcript: trend via HH/HL, prefer pullback entries, improve R:R, trail beneath swing low.
        # Require first-hour uptrend then one-bar pullback and break back up.
        if bs[1]["high_price"] <= bs[0]["high_price"] or bs[1]["low_price"] <= bs[0]["low_price"]: return None
        for j in range(2,min(7,len(bs)-1)):
            if bs[j]["close_price"] < bs[j]["open_price"] and bs[j]["low_price"] > bs[0]["low_price"]:
                nxt=bs[j+1]
                if nxt["high_price"] > bs[j]["high_price"]:
                    ent=max(bs[j]["high_price"],nxt["open_price"]); stop=bs[j]["low_price"]
                    if stop>=ent: return None
                    return (j+1,ent,stop,2.0,"HH/HL trend + pullback + break of pullback high")
        return None
    return None

def run(setup,data,cost_bps):
    cash=CAPITAL
    daily=defaultdict(float); trades=[]
    days=sorted(set(d for sym in data for d in data[sym]))
    for day in days:
        for sym in sorted(data):
            if day not in data[sym]: continue
            sig=choose_trade(setup,data,sym,day)
            if not sig: continue
            j,raw_entry,stop,R,rule=sig
            bs=data[sym][day]
            entry=raw_entry*(1+cost_bps/10000)
            risk_per=max(1e-9,entry-stop)
            alloc=min(CAPITAL*MAX_ALLOC,max(0,cash))
            qty=alloc/entry
            if qty<=0: continue
            target=entry+R*risk_per
            raw_exit=bs[-1]["close_price"]; why="eod"
            # Walk bars after entry; conservative same-bar collision: stop before target.
            for b in bs[j:]:
                if b["low_price"] <= stop:
                    raw_exit=stop; why="stop"; break
                if b["high_price"] >= target:
                    raw_exit=target; why="target"; break
            exitp=raw_exit*(1-cost_bps/10000)
            pnl=(exitp-entry)*qty
            cash+=pnl; daily[day]+=pnl
            trades.append({"day":day,"symbol":sym,"pnl":pnl,"entry":entry,"exit":exitp,"why":why,"rule":rule})
    # Metrics
    rets=[]; eq=CAPITAL; peak=CAPITAL; maxdd=0
    for d in days:
        prev=eq; eq+=daily.get(d,0)
        if prev>0: rets.append(eq/prev-1)
        peak=max(peak,eq); maxdd=min(maxdd,eq/peak-1)
    if len(rets)>1 and statistics.stdev(rets)>0:
        sharpe=statistics.mean(rets)/statistics.stdev(rets)*math.sqrt(252)
    else: sharpe=0
    wins=[t["pnl"] for t in trades if t["pnl"]>0]
    losses=[t["pnl"] for t in trades if t["pnl"]<0]
    pf=sum(wins)/abs(sum(losses)) if losses else (float("inf") if wins else 0)
    return {
        "return_pct":round((cash/CAPITAL-1)*100,2),
        "pnl":round(cash-CAPITAL,2),
        "sharpe":round(sharpe,3),
        "max_dd_pct":round(maxdd*100,2),
        "win_rate_pct":round(len(wins)/len(trades)*100,1) if trades else 0,
        "trades":len(trades),
        "profit_factor":round(pf,3) if math.isfinite(pf) else "inf",
        "targets":sum(t["why"]=="target" for t in trades),
        "stops":sum(t["why"]=="stop" for t in trades),
        "eod":sum(t["why"]=="eod" for t in trades),
    }

def main():
    data=load()
    setups=[
      ("ross_first_pullback","Ross Cameron — first pullback momentum proxy"),
      ("humbled_gap_reclaim","Humbled Trader — gap/reclaim proxy"),
      ("chart_orh_reclaim","ChartFanatics/Clement — ORH reclaim continuation"),
      ("live_relstrength_breakout","Live Traders — relative-strength ATR breakout"),
      ("riley_pullback_trend","Riley Coleman — pullback trend continuation"),
    ]
    rows=[]
    for key,label in setups:
        z=run(key,data,0.0); c=run(key,data,5.0)
        rows.append({
          "setup":key,"label":label,
          "zero_bps":z,"five_bps":c,
          "five_bps_return_delta_pp":round(c["return_pct"]-z["return_pct"],2)
        })
        print(f"{label:58s} 0bp={z['return_pct']:7.2f}% 5bp={c['return_pct']:7.2f}% "
              f"Sh={c['sharpe']:5.2f} DD={c['max_dd_pct']:6.2f}% WR={c['win_rate_pct']:5.1f}% "
              f"N={c['trades']:3d} PF={c['profit_factor']}")
    out={
      "_meta":{
        "capital":CAPITAL,"window":[START,END],"bar_size":"30 minutes",
        "universe":sorted(data),"cost_bps_per_side":[0,5],
        "sizing":"25% of starting capital max per trade",
        "warning":"Objective proxies on a semiconductor universe; not exact reproductions of creator strategies. Premarket/float/catalyst/Level2/tape/supply-demand subjectivity unavailable."
      },
      "rows":rows,
      "excluded":[
        {"creator":"The Trading Geek","reason":"Supply/demand/order-block setup depends on subjective zone construction and multi-timeframe context; no unambiguous mechanical rule extracted for this first batch."}
      ]
    }
    os.makedirs(os.path.dirname(OUT),exist_ok=True)
    json.dump(out,open(OUT,"w"),indent=2)
    print("wrote",os.path.relpath(OUT,ROOT))

if __name__=="__main__": main()
