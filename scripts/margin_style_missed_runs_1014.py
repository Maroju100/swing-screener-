"""Counterfactual: what if the 2026-10-14/15/16/19 live runs had executed their plans (asked 2026-10-20).

Real engine (origin/main), starting from the 10-13 state (commit e0c3bbe), cash $0.78.
10-14/10-15 quotes = 1-minute bar closes at 17:34 UTC (those runs did not save quotes);
10-16/10-19/10-20 = the quotes the live runs actually used. Fills ASSUMED at the quote,
no slippage. Reproduce: python3 scripts/margin_style_missed_runs_1014.py
"""
import json, subprocess, io, contextlib, datetime as _dt, os
import tempfile
SC=tempfile.mkdtemp()
D='/home/user/swing-screener-/data/research/missed_runs_2026-10-14'
src=subprocess.check_output(['git','show','origin/main:scripts/margin_style_live_engine.py'],cwd='/home/user/swing-screener-').decode()
state0=json.loads(subprocess.check_output(['git','show','e0c3bbe:docs/margin_style_live_state.json'],cwd='/home/user/swing-screener-'))
class FD(_dt.datetime):
    now_=None
    @classmethod
    def now(cls,tz=None): return cls.now_ if tz else cls.now_.replace(tzinfo=None)
ns={'__file__':'/home/user/swing-screener-/scripts/margin_style_live_engine.py','__name__':'cf'}
exec(compile(src,'engine','exec'),ns)
ns['datetime']=FD; ns['STATE_PATH']=SC+'/state.json'
json.dump(state0,open(SC+'/state.json','w'))
hist=json.load(open(D+'/daily_hist_to_2026-10-19.json'))
m14={'AMD':573.01,'MU':923.5603,'WDC':364.025,'SNDK':1414.85,'TSM':430.415,'INTC':98.785,'LRCX':286.29,'STX':718.12}
m15={'AMD':550.04,'MU':911.655,'WDC':345.80,'SNDK':1344.0,'TSM':419.81,'INTC':94.215,'LRCX':273.62,'STX':673.12}
q16={"AMD":536.0,"MU":894.725,"WDC":340.115,"SNDK":1329.34,"TSM":413.5,"INTC":91.06,"LRCX":268.375,"STX":654.755}
q19={"AMD":541.13,"MU":904.6013,"WDC":347.76,"SNDK":1376.822,"TSM":421.48,"INTC":92.66,"LRCX":275.10,"STX":658.6302}
q20=json.load(open(D+'/quotes_2026-10-20.json'))
# daily closes 10-15/10-16/10-19 needed: hist file has through 10-19
cash=0.78
for day,q in [('2026-10-14',m14),('2026-10-15',m15),('2026-10-16',q16),('2026-10-19',q19),('2026-10-20',q20)]:
    FD.now_=_dt.datetime.fromisoformat(day+'T17:35:00+00:00')
    h={'data':{'results':[{'symbol':r['symbol'],'bars':[b for b in r['bars'] if b['begins_at'][:10]<day]} for r in hist['data']['results']]}}
    json.dump(h,open(SC+'/h.json','w')); json.dump(q,open(SC+'/q.json','w'))
    st=json.load(open(SC+'/state.json'))
    buf=io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        ns['cmd_plan'](SC+'/h.json',SC+'/q.json',cash,[],json.dumps({s:p['shares'] for s,p in st['open_positions'].items()}))
    plan=json.loads(buf.getvalue()[buf.getvalue().index('{'):])
    if day=='2026-10-20':
        eq=cash+sum(p['shares']*q[s] for s,p in st['open_positions'].items())
        print(day,'PLAN (not executed):',[(x['symbol'],x['reason']) for x in plan['sells']],[(x['symbol'],x['reason'],round(x['notional'])) for x in plan['buys']])
        print('VALUE TODAY at 12:44 PM CDT quotes: $%.2f  cash %.2f  positions %s'%(eq,cash,{s:round(p['shares'],6) for s,p in st['open_positions'].items()}))
        break
    acts={'sells':[{'symbol':x['symbol'],'shares':x['shares'],'price':x['price'],'reason':x['reason']} for x in plan['sells']],
          'buys':[{'symbol':x['symbol'],'shares':x['shares'],'price':x['price'],'reason':x['reason']} for x in plan['buys']],
          'peak_updates':plan['peak_updates'],'risk_state':plan['risk_state']}
    json.dump(acts,open(SC+'/a.json','w'))
    with contextlib.redirect_stdout(io.StringIO()): ns['cmd_commit'](SC+'/a.json')
    cash+= sum(x['shares']*x['price'] for x in acts['sells'])-sum(x['shares']*x['price'] for x in acts['buys'])
    st=json.load(open(SC+'/state.json'))
    eq=cash+sum(p['shares']*q[s] for s,p in st['open_positions'].items())
    print(day,'equity %.2f'%eq,'cash %.2f'%cash,'sells',[(x['symbol'],x['reason'],round(x['shares']*x['price'])) for x in acts['sells']],'buys',[(x['symbol'],x['reason'],round(x['shares']*x['price'])) for x in acts['buys']],'ks',plan['risk_state']['kill_switch_active'])
