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
check('MS_STATE carries the 2026-10-02 open positions (INTC, MU, AMD only)',
      Object.keys(T.MS_STATE.open_positions).sort().join(',') === 'AMD,INTC,MU',
      Object.keys(T.MS_STATE.open_positions).join(','));
check('WDC and STX stopped out (gone from state)', !T.MS_STATE.open_positions.WDC && !T.MS_STATE.open_positions.STX);
check('pending_settlement = 2,180.91 settling 2026-10-05',
      Math.abs(T.MS_STATE.pending_settlement.reduce((a,p)=>a+p.amount,0) - 2180.91) < 0.01
      && T.MS_STATE.pending_settlement.every(p=>p.settle_date==='2026-10-05'));
check('equity_peak unchanged at 18035.23', T.MS_STATE.equity_peak === 18035.23);
check('SNAPSHOT_TIME advanced', T.SNAPSHOT_TIME === '2026-10-02 17:40 UTC', T.SNAPSHOT_TIME);

// --- 2. trade log gained the 7 real fills from 10-02 ---
const t0 = T.MS_DATA.trades[0];
check('newest trade is the 10-02 AMD PEAK sell',
      t0.t==='2026-10-02T17:40:08Z' && t0.sym==='AMD' && t0.side==='SELL' && t0.shares===0.046613);
check('trade count 240 -> 247', T.MS_DATA.trades.length === 247, String(T.MS_DATA.trades.length));
check('10-02: 3 STOP, 2 MAX_HOLD, 2 PEAK',
      ['STOP',3,'MAX_HOLD',2,'PEAK',2].every((v,i,a)=> i%2 ? true : T.MS_DATA.trades.filter(t=>t.t.startsWith('2026-10-02') && t.reason===v).length===a[i+1]));
check('WDC 10-02 STOP carries broker realized -98.74',
      T.MS_DATA.trades.some(t=>t.t.startsWith('2026-10-02') && t.sym==='WDC' && t.reason==='STOP' && t.pnl===-98.74));
check('LRCX 10-01 carries the broker restatement 6.47',
      T.MS_DATA.trades.some(t=>t.t==='2026-10-01T17:40:02Z' && t.sym==='LRCX' && t.pnl===6.47));
check('WDC 09-30 carries the broker restatement 65.43',
      T.MS_DATA.trades.some(t=>t.t==='2026-09-30T17:47:44Z' && t.sym==='WDC' && t.pnl===65.43));
check('INTC 09-30 PEAK carries broker realized 80.77',
      T.MS_DATA.trades.some(t=>t.t.startsWith('2026-09-30') && t.sym==='INTC' && t.reason==='PEAK' && t.pnl===80.77));
check('09-28 SNDK and MU STOPs present',
      ['SNDK','MU'].every(k=>T.MS_DATA.trades.some(t=>t.t.startsWith('2026-09-28') && t.sym===k && t.reason==='STOP')));

// --- 3. broker-sourced figures reconcile to get_realized_pnl(span=all) 2026-10-02 ---
check('total_realized = broker 2851.05', T.MS_DATA.total_realized === 2851.05);
check('BROKER_PNL_SNAPSHOT = live get_realized_pnl', T.BROKER_PNL_SNAPSHOT.total_returns === '2851.05');
check('daily series sums to total_realized',
      Math.abs(T.MS_DATA.daily.reduce((a,d)=>a+d.pnl,0) - 2851.05) < 0.02);
check('daily series ends 2026-10-02 at -108.04 (no phantom zero bar for 09-24)',
      T.MS_DATA.daily[T.MS_DATA.daily.length-1].date === '2026-10-02' && T.MS_DATA.daily[T.MS_DATA.daily.length-1].pnl === -108.04
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
check('positions table renders the 3 open positions', ['INTC','MU','AMD'].every(k=>pos.includes(k)) && !pos.includes('WDC'), `${pos.length} chars`);
check('positions show a live gain vs entry', /[-+]?\d+\.\d+%/.test(pos));
const log = document.getElementById('tradeLogBody').innerHTML;
check('trade log shows the 10-02 STOP and MAX_HOLD sells', log.includes('STOP') && log.includes('MAX_HOLD') && log.includes('$412.5862'));
const svg = document.getElementById('pnlBarSvg').innerHTML;
check('P&L chart emitted marks', svg.length > 500, `${svg.length} chars`);
const dist = document.getElementById('distBody').innerHTML;
check('distance table covers all 8 symbols',
      ['AMD','MU','WDC','SNDK','TSM','INTC','LRCX','STX'].every(s=>dist.includes(s)));
const stats = document.getElementById('statRow').innerHTML;
check('stat row shows unsettled $0.00 (cash account)', stats.includes('unsettled: $0.00'));
check('stat row shows kill-switch off', stats.includes('off') && stats.includes('never triggered'));
const foot = document.getElementById('footerNote').innerHTML;
check('footer carries the new snapshot time', foot.includes('2026-10-02 17:40 UTC'));

// --- 5. published file must not contain the test hook ---
check('no __test hook in the published source', !html.includes('__test'));

console.log(fail ? `\n${fail} CHECK(S) FAILED` : '\nALL CHECKS PASSED');
process.exit(fail?1:0);
