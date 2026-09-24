#!/usr/bin/env python3
"""Backtest objective proxies extracted from YouTube trading transcripts.

Research-only. Uses fixed semiconductor 1-minute regular-hours dataset.
No production trading code/state is modified.
"""
import json, math, os, statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "semis_1min_2026-08-10_2026-09-21.json"
OUT = ROOT / "data" / "research" / "youtube_strategy_batch1_results.json"

START_CAPITAL = 17500.0
RISK_PCT = 0.005
COST_BPS = 5.0
OPEN = "13:30"    # 09:30 ET during DST
ENTRY_END = "14:30"  # 10:30 ET
CLOSE = "19:59"
RETEST_TOL = 0.001
RETEST_WINDOW_MIN = 20

def parse():
    obj=json.loads(DATA.read_text())
    return obj.get("meta",{}), obj["bars"]

def cost_adjust(px, side, entering):
    b=COST_BPS/10000.0
    if side=="long":
        return px*(1+b if entering else 1-b)
    return px*(1-b if entering else 1+b)

def cum_vwap(day):
    out=[]
    pv=vol=0.0
    for row in day:
        _,o,h,l,c,v=row
        tp=(h+l+c)/3.0
        pv += tp*v
        vol += v
        out.append(pv/vol if vol else c)
    return out

def summarize(trades, capital=START_CAPITAL):
    eq=capital
    peak=capital
    maxdd=0.0
    wins=0
    gross_win=gross_loss=0.0
    daily=defaultdict(float)
    for t in trades:
        eq += t["pnl"]
        peak=max(peak,eq)
        maxdd=min(maxdd,(eq/peak-1.0)*100.0)
        daily[t["date"]] += t["pnl"]
        if t["pnl"]>0:
            wins+=1; gross_win+=t["pnl"]
        elif t["pnl"]<0:
            gross_loss += -t["pnl"]
    rets=[]
    running=capital
    for d in sorted(daily):
        p=daily[d]
        rets.append(p/running if running else 0)
        running += p
    sharpe=None
    if len(rets)>1 and statistics.pstdev(rets)>0:
        sharpe=statistics.mean(rets)/statistics.pstdev(rets)*math.sqrt(252)
    return {
        "starting_capital": capital,
        "ending_capital": round(eq,2),
        "net_pnl": round(eq-capital,2),
        "return_pct": round((eq/capital-1)*100,2),
        "trades": len(trades),
        "win_rate_pct": round(wins/len(trades)*100,2) if trades else None,
        "profit_factor": round(gross_win/gross_loss,3) if gross_loss else None,
        "sharpe_daily": round(sharpe,3) if sharpe is not None else None,
        "max_drawdown_pct": round(maxdd,2),
        "days_with_trades": len(daily),
    }

def execute(day, entry_idx, side, stop, target=None, exit_eod=False):
    if entry_idx>=len(day): return None
    time,o,h,l,c,v=day[entry_idx]
    entry=cost_adjust(o,side,True)
    risk_per_share=(entry-stop) if side=="long" else (stop-entry)
    if risk_per_share<=0: return None
    # risk sizing with equity handled by caller; return path info + R geometry
    exit_px=None; exit_time=None; reason=None
    for j in range(entry_idx, len(day)):
        tm,oo,hh,ll,cc,vv=day[j]
        if side=="long":
            hit_stop=ll<=stop
            hit_target=(target is not None and hh>=target)
            # conservative: if same bar hits both, stop first
            if hit_stop:
                exit_px=cost_adjust(stop,side,False); exit_time=tm; reason="stop"; break
            if hit_target:
                exit_px=cost_adjust(target,side,False); exit_time=tm; reason="target"; break
        else:
            hit_stop=hh>=stop
            hit_target=(target is not None and ll<=target)
            if hit_stop:
                exit_px=cost_adjust(stop,side,False); exit_time=tm; reason="stop"; break
            if hit_target:
                exit_px=cost_adjust(target,side,False); exit_time=tm; reason="target"; break
    if exit_px is None:
        tm,oo,hh,ll,cc,vv=day[-1]
        exit_px=cost_adjust(cc,side,False); exit_time=tm; reason="eod"
    return entry,exit_px,exit_time,reason,risk_per_share

def chartfanatics(bars, exit_mode="2R"):
    trades=[]
    equity=START_CAPITAL
    for sym,days in bars.items():
        for date,day in sorted(days.items()):
            if len(day)<10: continue
            first=day[:5]
            o0=first[0][1]; c5=first[-1][4]
            if not (c5<o0): continue
            orh=max(x[2] for x in first)
            vw=cum_vwap(day)
            trigger=None
            for i in range(5,len(day)-1):
                tm,o,h,l,c,v=day[i]
                if tm>ENTRY_END: break
                if c>orh and c>vw[i]:
                    trigger=i; break
            if trigger is None: continue
            stop=min(x[3] for x in day[:trigger+1])
            next_open=day[trigger+1][1]
            ent_adj=cost_adjust(next_open,"long",True)
            risk=ent_adj-stop
            if risk<=0: continue
            target=ent_adj+2*risk if exit_mode=="2R" else None
            ex=execute(day,trigger+1,"long",stop,target,exit_mode=="eod")
            if not ex: continue
            entry,exit_px,exit_time,reason,rps=ex
            risk_budget=equity*RISK_PCT
            qty=risk_budget/rps
            pnl=(exit_px-entry)*qty
            equity += pnl
            trades.append({"strategy":"chartfanatics_or_reclaim_"+exit_mode,"symbol":sym,"date":date,
                           "entry_time":day[trigger+1][0],"entry":entry,"stop":stop,
                           "exit_time":exit_time,"exit":exit_px,"reason":reason,"qty":qty,"pnl":pnl})
    return trades

def scarface(bars):
    trades=[]
    equity=START_CAPITAL
    for sym,days in bars.items():
        for date,day in sorted(days.items()):
            if len(day)<12: continue
            first=day[:5]
            fo=first[0][1]; fc=first[-1][4]
            if fc==fo: continue
            side="long" if fc>fo else "short"
            boundary=max(x[2] for x in first) if side=="long" else min(x[3] for x in first)
            breakout=None
            for i in range(5,len(day)-2):
                if day[i][0]>ENTRY_END: break
                c=day[i][4]
                if (side=="long" and c>boundary) or (side=="short" and c<boundary):
                    breakout=i; break
            if breakout is None: continue
            retest=None
            last=min(len(day)-2, breakout+RETEST_WINDOW_MIN)
            for i in range(breakout+1,last+1):
                tm,o,h,l,c,v=day[i]
                if tm>ENTRY_END: break
                if side=="long":
                    touched=l <= boundary*(1+RETEST_TOL)
                    confirmed=c>boundary
                else:
                    touched=h >= boundary*(1-RETEST_TOL)
                    confirmed=c<boundary
                if touched and confirmed:
                    retest=i; break
            if retest is None: continue
            stop=day[retest][3] if side=="long" else day[retest][2]
            next_open=day[retest+1][1]
            ent_adj=cost_adjust(next_open,side,True)
            risk=(ent_adj-stop) if side=="long" else (stop-ent_adj)
            if risk<=0: continue
            target=ent_adj+2*risk if side=="long" else ent_adj-2*risk
            ex=execute(day,retest+1,side,stop,target)
            if not ex: continue
            entry,exit_px,exit_time,reason,rps=ex
            risk_budget=equity*RISK_PCT
            qty=risk_budget/rps
            pnl=(exit_px-entry)*qty if side=="long" else (entry-exit_px)*qty
            equity += pnl
            trades.append({"strategy":"scarface_first_candle_break_retest_2R","symbol":sym,"date":date,
                           "side":side,"entry_time":day[retest+1][0],"entry":entry,"stop":stop,
                           "exit_time":exit_time,"exit":exit_px,"reason":reason,"qty":qty,"pnl":pnl})
    return trades

def by_symbol(trades):
    d=defaultdict(lambda:{"pnl":0.0,"trades":0,"wins":0})
    for t in trades:
        x=d[t["symbol"]]; x["pnl"]+=t["pnl"]; x["trades"]+=1; x["wins"]+= t["pnl"]>0
    return {s:{"pnl":round(v["pnl"],2),"trades":v["trades"],
               "win_rate_pct":round(v["wins"]/v["trades"]*100,2)} for s,v in sorted(d.items())}

def main():
    meta,bars=parse()
    cf2=chartfanatics(bars,"2R")
    cfe=chartfanatics(bars,"eod")
    sf=scarface(bars)
    result={
      "_meta":{
        "source_file":str(DATA.relative_to(ROOT)),
        "source_meta":meta,
        "starting_capital":START_CAPITAL,
        "risk_per_trade_pct":RISK_PCT*100,
        "cost_bps_per_side":COST_BPS,
        "purpose":"mechanical proxies extracted from YouTube transcripts; not production recommendations",
        "limitations":[
          "Fixed semiconductor universe only",
          "Regular-hours bars only; no premarket data",
          "30 trading days is a small sample",
          "Creator discretion/Level-2/news/float filters are not represented unless explicitly encoded",
          "Risk sizing is a common comparison harness assumption, not a creator claim"
        ]
      },
      "strategies":{
        "chartfanatics_or_reclaim_2R":{"summary":summarize(cf2),"by_symbol":by_symbol(cf2),"trades":cf2},
        "chartfanatics_or_reclaim_eod":{"summary":summarize(cfe),"by_symbol":by_symbol(cfe),"trades":cfe},
        "scarface_first_candle_break_retest_2R":{"summary":summarize(sf),"by_symbol":by_symbol(sf),"trades":sf},
        "ross_first_pullback_momentum":{"status":"not_run","reason":"requires small-cap scanner universe + relative volume + float + gap/catalyst data; current semiconductor dataset is not faithful"}
      }
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,indent=2))
    print(json.dumps({k:v.get("summary",v) for k,v in result["strategies"].items()},indent=2))

if __name__=="__main__":
    main()
