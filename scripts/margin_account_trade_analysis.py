"""Owner's Margin-account (410961445) trade behaviour, 2026-06-30 -> 2026-10-29, from the committed broker fills.
FIFO round trips use only inventory bought inside the window. Reproduce: python3 scripts/margin_account_trade_analysis.py
"""
import csv, json, statistics as st
from collections import defaultdict, Counter
U=['AMD','MU','WDC','SNDK','TSM','INTC','LRCX','STX']
d=json.load(open('data/research/missed_runs_2026-10-14/daily_hist_to_2026-10-27.json'))
C={r['symbol']:{b['begins_at'][:10]:float(b['close_price']) for b in r['bars']} for r in d['data']['results']}
days=sorted(C['AMD'])
rows=[r for r in csv.DictReader(open('data/broker_fills_410961445_2026-06-29_2026-10-29.csv')) if r['symbol'] in U]
def prev(day):
    ds=[x for x in days if x<day]; return ds
buys=[];sells=[]
for r in rows:
    day=r['created_at'][:10]; s=r['symbol']; p=float(r['avg_price']); ds=prev(day)
    if len(ds)<20: continue
    pc=C[s][ds[-1]]; hi20=max(C[s][x] for x in ds[-20:]); 
    dn=0
    for k in range(len(ds)-1,0,-1):
        if C[s][ds[k]]<C[s][ds[k-1]]: dn+=1
        else: break
    f=dict(day=day,s=s,p=p,n=float(r['notional']),intra=p/pc-1,y1=C[s][ds[-1]]/C[s][ds[-2]]-1,dd20=pc/hi20-1,dn=dn,hr=r['created_at'][11:13])
    (buys if r['side']=='buy' else sells).append(f)
def summ(L,name):
    print(f"\n{name}: n={len(L)} notional ${sum(x['n'] for x in L):,.0f}")
    for k in ('intra','y1','dd20'):
        v=sorted(x[k] for x in L); print(f"  {k}: median {st.median(v):+.2%}  p25 {v[len(v)//4]:+.2%} p75 {v[3*len(v)//4]:+.2%}  share<0 {sum(1 for x in v if x<0)/len(v):.0%}")
    print('  down-days before:',sorted(Counter(x['dn'] for x in L).items()))
    print('  hour UTC:',sorted(Counter(x['hr'] for x in L).items()))
summ(buys,'BUYS'); summ(sells,'SELLS')
# FIFO round trips per symbol, ignoring pre-window inventory
lots=defaultdict(list); trips=[]
for r in sorted(rows,key=lambda r:r['created_at']):
    s=r['symbol'];q=float(r['quantity']);p=float(r['avg_price']);t=r['created_at']
    if r['side']=='buy': lots[s].append([q,p,t]); continue
    while q>1e-9 and lots[s]:
        l=lots[s][0]; m=min(q,l[0]); 
        from datetime import datetime as D
        hd=(D.fromisoformat(t[:19])-D.fromisoformat(l[2][:19])).total_seconds()/86400
        trips.append((s,m,l[1],p,hd,t[:10])); l[0]-=m; q-=m
        if l[0]<=1e-9: lots[s].pop(0)
pnl=sum(m*(b-a) for s,m,a,b,h,_ in trips)
print(f"\nFIFO matched round trips: {len(trips)} pieces, P&L ${pnl:,.0f}")
for lo,hi,lab in [(0,1,'<1 day (same day)'),(1,3,'1-3 days'),(3,7,'3-7 days'),(7,15,'7-15 days'),(15,999,'15+ days')]:
    T=[x for x in trips if lo<=x[4]<hi]
    if T: print(f"  {lab:18} n={len(T):4} P&L ${sum(m*(b-a) for s,m,a,b,h,_ in T):>9,.0f}  win {sum(1 for x in T if x[3]>x[2])/len(T):.0%}  median ret {st.median(x[3]/x[2]-1 for x in T):+.2%}")
for s in U:
    T=[x for x in trips if x[0]==s]
    if T: print(f"  {s:5} P&L ${sum(m*(b-a) for _,m,a,b,h,_ in T):>9,.0f}")
by_m=defaultdict(float)
for s,m,a,b,h,dd in trips: by_m[dd[:7]]+=m*(b-a)
print(' by month:',{k:round(v) for k,v in sorted(by_m.items())})
