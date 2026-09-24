#!/usr/bin/env python3
"""Backtest objective trading setups extracted from youtube_transcripts.

IMPORTANT:
- Research-only proxy study on the existing 8-symbol semiconductor universe.
- Uses 30-minute bars because that is the validated intraday history available
  in this repo for 2026-06-22..2026-09-21.
- These are NOT claims that the original creators traded these exact rules.
  Each setup records the transcript-derived rule and the approximation required
  to make it mechanical at 30-minute resolution.
- No production engine/state is modified.
"""
import json, os, math
from collections import defaultdict
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SRC = os.path.join(DATA, "margin_live_30min_2026-06-22_2026-09-22.json")
OUT = os.path.join(DATA, "research", "gpt_transcript_setup_backtests.json")
START, END = "2026-06-22", "2026-09-21"
CAPITAL = 17500.0
COST_BPS = 5.0
RISK_PCT = 0.005  # 0.5% equity risk/trade
MAX_POSITION_PCT = 0.25
UNIVERSE = ("AMD","MU","WDC","SNDK","TSM","INTC","LRCX","STX")

def load():
    d=json.load(open(SRC))
    out=defaultdict(list)
    for r in d["data"]["results"]:
        if r["symbol"] not in UNIVERSE: continue
        for b in r["bars"]:
            day=b["begins_at"][:10]
            if START <= day <= END:
                x={k:float(b[k]) if k!="begins_at" else b[k] for k in
                   ("begins_at","open_price","high_price","low_price","close_price","volume")}
                out[(r["symbol"],day)].append(x)
    for k in out: out[k].sort(key=lambda x:x["begins_at"])
    return out

def ema(vals,n=9):
    a=2/(n+1); out=[]; e=None
    for v in vals:
        e=v if e is None else a*v+(1-a)*e
        out.append(e)
    return out

def vwap(bars):
    vals=[]; pv=vol=0.0
    for b in bars:
        tp=(b["high_price"]+b["low_price"]+b["close_price"])/3
        pv += tp*b["volume"]; vol += b["volume"]
        vals.append(pv/vol if vol else b["close_price"])
    return vals

def prev_close_map(data):
    bysym=defaultdict(list)
    for (s,d),bars in data.items():
        bysym[s].append((d,bars[-1]["close_price"],bars[-1]["high_price"],bars[-1]["low_price"]))
    out={}
    for s,rows in bysym.items():
        rows.sort()
        for i in range(1,len(rows)):
            d=rows[i][0]
            out[(s,d)]={"close":rows[i-1][1],"high":rows[i-1][2],"low":rows[i-1][3]}
    return out

def fill_cost(px, side):
    c=COST_BPS/10000
    return px*(1+c if side=="buy" else 1-c)

def trade_result(entry, stop, target, future_bars, side="long"):
    if side!="long": raise NotImplementedError
    for b in future_bars:
        # Conservative same-bar ordering: stop before target when both touched.
        if b["low_price"] <= stop:
            return fill_cost(stop,"sell"), b["begins_at"], "stop"
        if b["high_price"] >= target:
            return fill_cost(target,"sell"), b["begins_at"], "2R"
    b=future_bars[-1]
    return fill_cost(b["close_price"],"sell"), b["begins_at"], "eod"

def size_trade(equity, entry, stop):
    risk_per=max(entry-stop,1e-9)
    risk_budget=equity*RISK_PCT
    q=risk_budget/risk_per
    q=min(q,(equity*MAX_POSITION_PCT)/entry)
    return max(q,0)

def run_setup(name, detector, data, prevs):
    equity=CAPITAL; peak=equity; maxdd=0; trades=[]; daily_pnl=defaultdict(float)
    keys=sorted(data.keys(), key=lambda x:(x[1],x[0]))
    for s,d in keys:
        bars=data[(s,d)]
        sig=detector(s,d,bars,prevs.get((s,d)))
        if not sig: continue
        entry_i, entry_px, stop_px = sig
        if entry_i >= len(bars)-1 or stop_px >= entry_px: continue
        entry=fill_cost(entry_px,"buy")
        # target uses post-cost entry risk conservatively.
        risk=entry-stop_px
        if risk<=0: continue
        target=entry+2*risk
        q=size_trade(equity,entry,stop_px)
        if q*entry < 50: continue
        exit_px, exit_ts, reason=trade_result(entry,stop_px,target,bars[entry_i+1:])
        pnl=q*(exit_px-entry)
        equity += pnl; daily_pnl[d]+=pnl; peak=max(peak,equity); maxdd=min(maxdd,equity/peak-1)
        trades.append({"date":d,"symbol":s,"entry_ts":bars[entry_i]["begins_at"],"entry":round(entry,4),
                       "stop":round(stop_px,4),"target":round(target,4),"exit_ts":exit_ts,
                       "exit":round(exit_px,4),"exit_reason":reason,"shares":round(q,6),"pnl":round(pnl,2)})
    wins=[t for t in trades if t["pnl"]>0]
    gross_win=sum(t["pnl"] for t in trades if t["pnl"]>0)
    gross_loss=-sum(t["pnl"] for t in trades if t["pnl"]<0)
    # Daily Sharpe
    ds=sorted(daily_pnl)
    rets=[daily_pnl[d]/CAPITAL for d in ds]
    sh=0
    if len(rets)>1:
        m=sum(rets)/len(rets); sd=(sum((x-m)**2 for x in rets)/(len(rets)-1))**0.5
        sh=m/sd*math.sqrt(252) if sd else 0
    return {"setup":name,"trades":len(trades),"wins":len(wins),
            "win_rate_pct":round(100*len(wins)/len(trades),2) if trades else None,
            "realized_pnl":round(equity-CAPITAL,2),"return_pct":round((equity/CAPITAL-1)*100,2),
            "profit_factor":round(gross_win/gross_loss,3) if gross_loss else None,
            "sharpe_daily_active_days":round(sh,3),"max_drawdown_pct":round(maxdd*100,2),
            "ending_equity":round(equity,2),"sample_trades":trades[:20]}

# ----- Mechanical proxy detectors -----

def ross_first_pullback(s,d,bars,prev):
    """Transcript: strong momentum stock, first pullback, <=50% retrace,
    lighter red volume, above VWAP and 9 EMA.
    Proxy: first two 30m bars form impulse, third bar pullback, fourth-bar
    breakout entry. Universe/float/Level2 filters omitted due unavailable data.
    """
    if len(bars)<5: return None
    closes=[b["close_price"] for b in bars]; e=ema(closes,9); vw=vwap(bars)
    b0,b1,b2,b3=bars[:4]
    if not (b0["close_price"]>b0["open_price"] and b1["close_price"]>b1["open_price"]): return None
    impulse_low=min(b0["low_price"],b1["low_price"]); impulse_high=max(b0["high_price"],b1["high_price"])
    if impulse_high<=impulse_low: return None
    # first pullback bar
    if not (b2["close_price"] < b2["open_price"]): return None
    retr=(impulse_high-b2["low_price"])/(impulse_high-impulse_low)
    if retr>0.50: return None
    if b2["volume"] >= (b0["volume"]+b1["volume"])/2: return None
    if b2["close_price"] < vw[2] or b2["close_price"] < e[2]: return None
    # breakout confirmation
    if b3["high_price"] <= b2["high_price"]: return None
    entry=max(b2["high_price"],b3["open_price"])
    return 3,entry,b2["low_price"]

def humbled_gap_reclaim(s,d,bars,prev):
    """Transcript: focus on gappers with catalyst/volume; examples use key-level /
    premarket-high reclaim. Proxy: >=2% opening gap, first bar sells off but closes
    above its midpoint, then next bar breaks opening-range high above VWAP.
    Premarket-high and catalyst filters unavailable.
    """
    if not prev or len(bars)<4: return None
    b0,b1=bars[0],bars[1]; gap=b0["open_price"]/prev["close"]-1
    if gap<0.02: return None
    vw=vwap(bars)
    if not (b0["low_price"]<b0["open_price"] and b0["close_price"]>(b0["high_price"]+b0["low_price"])/2): return None
    if b1["high_price"]<=b0["high_price"] or b1["close_price"]<=vw[1]: return None
    entry=max(b0["high_price"],b1["open_price"])
    stop=min(b0["low_price"],b1["low_price"])
    return 1,entry,stop

def chartfanatics_orh_reclaim(s,d,bars,prev):
    """Transcript: initial flush, reclaim VWAP/short MAs, then break opening-range
    high; stop low of day. Proxy uses 30-minute opening range instead of 5-minute.
    """
    if len(bars)<4: return None
    vw=vwap(bars); closes=[b["close_price"] for b in bars]; e=ema(closes,3) # short MA proxy
    b0=bars[0]
    if b0["close_price"]>=b0["open_price"]: return None
    for i in range(1,min(5,len(bars)-1)):
        b=bars[i]
        if b["close_price"]>b0["high_price"] and b["close_price"]>vw[i] and b["close_price"]>e[i]:
            stop=min(x["low_price"] for x in bars[:i+1])
            return i,b["close_price"],stop
    return None

def scarface_prevday_retest(s,d,bars,prev):
    """Transcript: previous-day high/low break + retest, strong price action,
    stop beyond structure, require at least 2R. Long-side proxy only.
    """
    if not prev or len(bars)<5: return None
    lvl=prev["high"]
    broke=None
    for i in range(0,min(6,len(bars)-2)):
        if bars[i]["close_price"]>lvl:
            broke=i; break
    if broke is None: return None
    # retest within next 2 bars: trades at/under level but closes back above.
    for j in range(broke+1,min(broke+3,len(bars)-1)):
        b=bars[j]
        if b["low_price"]<=lvl*1.002 and b["close_price"]>lvl and b["close_price"]>b["open_price"]:
            stop=min(b["low_price"],lvl*0.998)
            return j,b["close_price"],stop
    return None

def main():
    data=load(); prevs=prev_close_map(data)
    specs=[
      ("Ross Cameron — first pullback pattern proxy",ross_first_pullback),
      ("Humbled Trader — gap/reclaim proxy",humbled_gap_reclaim),
      ("ChartFanatics — OR high/VWAP reclaim proxy",chartfanatics_orh_reclaim),
      ("Scarface Trades — prior-day-high retest proxy",scarface_prevday_retest),
    ]
    rows=[run_setup(n,f,data,prevs) for n,f in specs]
    out={
      "_meta":{"generated":"2026-09-24","window":[START,END],"capital":CAPITAL,
               "cost_bps_per_side":COST_BPS,"risk_pct_per_trade":RISK_PCT*100,
               "max_position_pct":MAX_POSITION_PCT*100,"bar_resolution":"30-minute",
               "universe":list(UNIVERSE),
               "warning":"Proxy tests on the existing semiconductor universe. Not faithful tests of creator-specific small-cap universes, Level 2/tape rules, catalyst filters, premarket levels, or 1m/5m execution."},
      "results":rows
    }
    os.makedirs(os.path.dirname(OUT),exist_ok=True)
    json.dump(out,open(OUT,"w"),indent=1)
    print(json.dumps(out,indent=1))

if __name__=="__main__":
    main()
