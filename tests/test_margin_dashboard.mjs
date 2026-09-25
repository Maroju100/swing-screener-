// Usage: node tests/test_margin_dashboard.mjs margin_live_dashboard.html
// Pre-publish harness for margin_live_dashboard (CLAUDE.md: "Dashboard testing before publish").
// Mocks the DOM, evals the REAL module body with a test hook appended, and drives the
// REAL render functions with today's committed state + real broker quotes/bars.
import fs from 'fs';

const html = fs.readFileSync(process.argv[2], 'utf8');
let body = html.match(/<script type="module">([\s\S]*?)<\/script>/)[1];
// append hook (test-only; never published)
body = body.replace(/\ninit\(\);\s*$/, `
globalThis.__test = { MS_STATE, MS_DATA, BROKER_PNL_SNAPSHOT, SNAPSHOT_TIME, state,
  renderAll, renderStatRow, renderPositions, renderDistance, renderDailyPnl,
  renderTradeLog, renderBrokerPnl, renderRegimeGauge, ingestQuotes, ingestDailyBars };
`);

const mk = () => ({ innerHTML:'', textContent:'', value:'', checked:false, hidden:false,
  style:{}, dataset:{}, className:'',
  classList:{ add(){}, remove(){}, toggle(){}, contains:()=>false },
  addEventListener(){}, removeEventListener(){}, appendChild(){}, removeChild(){},
  setAttribute(){}, getAttribute:()=>null, querySelector:()=>mk(), querySelectorAll:()=>[],
  getBoundingClientRect:()=>({width:900,height:260,top:0,left:0}) });
const els = new Map();
globalThis.document = {
  getElementById:(id)=>{ if(!els.has(id)) els.set(id, mk()); return els.get(id); },
  querySelector:()=>mk(), querySelectorAll:()=>[], createElement:()=>mk(),
  addEventListener(){}, documentElement:mk(), body:mk() };
globalThis.window = { addEventListener(){}, matchMedia:()=>({matches:false,addEventListener(){}}) };
globalThis.getComputedStyle = () => ({ getPropertyValue:()=>'#2a78d6' });
globalThis.localStorage = { getItem:()=>null, setItem(){}, removeItem(){} };
globalThis.claude = undefined;

try { new Function(body)(); } catch(e) {
  if(!globalThis.__test){ console.error('FATAL before hook:', e.message); process.exit(1); }
  console.log('note: init() bailed without a connector ->', e.message.slice(0,70));
}
const T = globalThis.__test;
if(!T){ console.error('FATAL: no __test hook'); process.exit(1); }

let fail = 0;
const check = (n, c, x='') => { console.log(`${c?'PASS':'FAIL'}  ${n}${x?'  '+x:''}`); if(!c) fail++; };

// --- 1. snapshot matches the committed production state exactly ---
// NOTE: this check is DESIGNED to fail the day after a live run. The page embeds a
// snapshot of docs/margin_style_live_state.json, so once the daily trigger commits a
// new state the embedded copy is stale and the artifact needs republishing. A failure
// here means 'republish the dashboard', not 'the test is broken'.
const prod = JSON.parse(fs.readFileSync('/home/user/swing-screener-/docs/margin_style_live_state.json','utf8'));
check('MS_STATE === committed state.json',
      JSON.stringify(T.MS_STATE) === JSON.stringify(prod));
check('MS_STATE carries the 2026-09-25 open positions',
      ['LRCX','SNDK','MU','TSM','WDC'].every(k=>T.MS_STATE.open_positions[k]) && !T.MS_STATE.open_positions.INTC,
      Object.keys(T.MS_STATE.open_positions).join(','));
check('WDC dip buy recorded', T.MS_STATE.open_positions.WDC?.shares === 0.176777);
check('pending_settlement = 14,233.57 settling 2026-09-28',
      Math.abs(T.MS_STATE.pending_settlement.reduce((a,p)=>a+p.amount,0) - 14233.57) < 0.01
      && T.MS_STATE.pending_settlement.every(p=>p.settle_date==='2026-09-28'));
check('equity_peak 17739.28', T.MS_STATE.equity_peak === 17739.28);
check('SNAPSHOT_TIME advanced', T.SNAPSHOT_TIME === '2026-09-25 17:45 UTC', T.SNAPSHOT_TIME);

// --- 2. trade log gained the 12 real fills from 09-23 / 09-24 / 09-25 ---
const t0 = T.MS_DATA.trades[0];
check('newest trade is the 09-25 WDC buy',
      t0.t==='2026-09-25T17:45:06Z' && t0.sym==='WDC' && t0.side==='BUY' && t0.shares===0.176777);
check('trade count 206 -> 218', T.MS_DATA.trades.length === 218, String(T.MS_DATA.trades.length));
check('six 2026-09-25 trades', T.MS_DATA.trades.filter(t=>t.t.startsWith('2026-09-25')).length === 6);
check('INTC 09-25 STOP carries broker realized -43.06',
      T.MS_DATA.trades.some(t=>t.t.startsWith('2026-09-25') && t.sym==='INTC' && t.reason==='STOP' && t.pnl===-43.06));

// --- 3. broker-sourced figures reconcile to get_realized_pnl(span=all) 2026-09-25 ---
check('total_realized = broker 2659.84', T.MS_DATA.total_realized === 2659.84);
check('BROKER_PNL_SNAPSHOT = live get_realized_pnl', T.BROKER_PNL_SNAPSHOT.total_returns === '2659.84');
check('daily series sums to total_realized',
      Math.abs(T.MS_DATA.daily.reduce((a,d)=>a+d.pnl,0) - 2659.84) < 0.02);
check('daily series ends 2026-09-25 (no phantom zero bar for 09-24)',
      T.MS_DATA.daily[T.MS_DATA.daily.length-1].date === '2026-09-25'
      && !T.MS_DATA.daily.some(d=>d.date==='2026-09-24'));

// --- 4. drive the REAL ingest + renderAll path with real broker payloads ---
const qPayload = JSON.parse(fs.readFileSync(new URL('./fixtures_margin_quotes_2026-09-22.json', import.meta.url),'utf8'));
const hPayload = JSON.parse(fs.readFileSync(new URL('./fixtures_margin_dailybars_2026-09-22.json', import.meta.url),'utf8'));
T.state.quotes    = T.ingestQuotes(qPayload);
T.state.dailyBars = T.ingestDailyBars(hPayload);
T.state.portfolio = { total_value:'17695.56', cash:'17693.63', buying_power:{buying_power:'17693.6300'} };
T.state.accounts  = { account_number:'912291820', type:'cash', unsettled_funds:'0.0000' };
T.state.ts        = Date.parse('2026-09-22T17:16:41Z');
check('ingestQuotes parsed all 8', Object.keys(T.state.quotes).length === 8);
check('ingestDailyBars parsed all 8', Object.keys(T.state.dailyBars).length === 8);
try { T.renderAll(); check('renderAll ran without throwing', true); }
catch(e) { check('renderAll ran without throwing', false, e.stack.split('\n').slice(0,2).join(' | ')); }

const pos = document.getElementById('posBody').innerHTML;
check('positions table renders all 5 positions', ['LRCX','SNDK','MU','TSM','WDC'].every(k=>pos.includes(k)), `${pos.length} chars`);
check('positions show a live gain vs entry', /[-+]?\d+\.\d+%/.test(pos));
const log = document.getElementById('tradeLogBody').innerHTML;
check('trade log shows the 09-25 STOP and PEAK sells', log.includes('STOP') && log.includes('PEAK') && log.includes('WDC'));
const svg = document.getElementById('pnlBarSvg').innerHTML;
check('P&L chart emitted marks', svg.length > 500, `${svg.length} chars`);
const dist = document.getElementById('distBody').innerHTML;
check('distance table covers all 8 symbols',
      ['AMD','MU','WDC','SNDK','TSM','INTC','LRCX','STX'].every(s=>dist.includes(s)));
const stats = document.getElementById('statRow').innerHTML;
check('stat row shows unsettled $0.00 (cash account)', stats.includes('unsettled: $0.00'));
check('stat row shows kill-switch off', stats.includes('off') && stats.includes('never triggered'));
const foot = document.getElementById('footerNote').innerHTML;
check('footer carries the new snapshot time', foot.includes('2026-09-25 17:45 UTC'));

// --- 5. published file must not contain the test hook ---
check('no __test hook in the published source', !html.includes('__test'));

console.log(fail ? `\n${fail} CHECK(S) FAILED` : '\nALL CHECKS PASSED');
process.exit(fail?1:0);
