// Pre-publish harness for semis_momentum (CLAUDE.md: "Dashboard testing before publish").
// Mocks the DOM, evals the real module, and drives the REAL replay/render functions
// with the committed 1-minute bars -- not synthetic data.
import fs from 'fs';

const ROOT = '/home/user/swing-screener-';
const html = fs.readFileSync(process.argv[2], 'utf8');
const body = html.match(/<script type="module">([\s\S]*?)<\/script>/)[1];

// ---- DOM / platform mocks ----
const mkEl = () => {
  const el = {
    innerHTML: '', textContent: '', value: '', checked: false, hidden: false,
    style: {}, dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    addEventListener() {}, removeEventListener() {},
    appendChild() {}, removeChild() {}, setAttribute() {}, getAttribute: () => null,
    querySelector: () => mkEl(), querySelectorAll: () => [],
    getBoundingClientRect: () => ({ width: 900, height: 300, top: 0, left: 0 }),
  };
  return el;
};
const els = new Map();
globalThis.document = {
  getElementById: (id) => { if (!els.has(id)) els.set(id, mkEl()); return els.get(id); },
  querySelector: () => mkEl(), querySelectorAll: () => [],
  createElement: () => mkEl(), createElementNS: () => mkEl(),
  addEventListener() {}, documentElement: mkEl(), body: mkEl(),
};
globalThis.window = { addEventListener() {}, matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }), location: { href: '' } };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '#888' });
const store = {};
globalThis.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: (k) => { delete store[k]; },
};
globalThis.claude = undefined;   // no connector: init() is expected to bail

// ---- eval the real module ----
try { new Function(body)(); } catch (e) {
  if (!globalThis.__test) { console.error('FATAL before hook:', e.message); process.exit(1); }
  console.log('note: init() threw as expected without a connector -> ' + e.message.slice(0, 80));
}
const T = globalThis.__test;
if (!T) { console.error('FATAL: no __test hook'); process.exit(1); }

// ---- load real committed bars ----
const semis = JSON.parse(fs.readFileSync(`${ROOT}/data/semis_1min_2026-08-10_2026-09-21.json`));
const bench = JSON.parse(fs.readFileSync(`${ROOT}/data/bench_1min_2026-08-10_2026-09-21.json`));
const toBars = (src, sym) => {
  const out = [];
  for (const day of Object.keys(src.bars[sym]).sort())
    for (const [hhmm, o, h, l, c, v] of src.bars[sym][day])
      out.push({ t: `${day}T${hhmm}:00Z`, open: o, high: h, low: l, close: c, volume: v });
  return out;
};
for (const sym of ['WDC', 'MU', 'SNDK']) T.state.bars[sym] = toBars(semis, sym);
T.state.bars[T.BENCH_SYM] = toBars(bench, 'SPY');

let fail = 0;
const check = (name, cond, extra = '') => {
  console.log(`${cond ? 'PASS' : 'FAIL'}  ${name}${extra ? '  ' + extra : ''}`);
  if (!cond) fail++;
};

// ---- 1. universe is clean ----
check('universe is the documented 8 semis',
      T.SYMBOLS.length === 8 && !T.SYMBOLS.includes('SPCX') && !T.SYMBOLS.includes('NVIDIA'),
      T.SYMBOLS.join(','));
check('benchmark is not in the basket', !T.SYMBOLS.includes(T.BENCH_SYM));

// ---- 2. benchmark map builds from real bars ----
const br = T.benchReturnByT();
check('benchReturnByT built', br && br.size > 10000, `size=${br ? br.size : 0}`);

// ---- 3. RS filter actually changes behaviour, in the measured direction ----
const run = (sym, rsRequired, costBps) =>
  T.runV3SignalReplay(T.state.bars[sym], null, T.V3_BASELINE,
                      { benchRet: br, rsRequired, costBps });
let offN = 0, onN = 0, offPnl = 0, onPnl = 0;
for (const sym of ['WDC', 'MU', 'SNDK']) {
  const a = run(sym, false, 0), b = run(sym, true, 0);
  offN += a.events.length; onN += b.events.length;
  offPnl += a.realizedPnl + a.unrealizedPnl;
  onPnl += b.realizedPnl + b.unrealizedPnl;
}
check('RS filter reduces trade count', onN < offN, `${offN} -> ${onN}`);
check('RS filter improves P&L at zero cost (matches replay finding)',
      onPnl > offPnl, `${offPnl.toFixed(2)} -> ${onPnl.toFixed(2)}`);

// ---- 4. cost is applied inside the replay and hurts ----
let free = 0, costed = 0;
for (const sym of ['WDC', 'MU', 'SNDK']) {
  free += run(sym, true, 0).realizedPnl;
  costed += run(sym, true, 10).realizedPnl;
}
check('cost reduces realized P&L', costed < free,
      `0bp ${free.toFixed(2)} vs 10bp ${costed.toFixed(2)}`);

// ---- 5. latest carries RS for the UI ----
const lat = run('WDC', true, 2.5).latest;
check('latest.rs present and finite', lat && Number.isFinite(lat.rs),
      lat ? String(lat.rs?.toFixed?.(5)) : 'none');

// ---- 6. render functions run and emit markup ----
try {
  T.V3_SETTINGS.rsRequired = true;
  T.renderV3FilterBar();
  const strip = document.getElementById('v3RsStrip').innerHTML;
  const note = document.getElementById('v3FilterNote').innerHTML;
  check('RS strip rendered for real symbols', strip.includes('WDC') && strip.includes('%'),
        `${strip.length} chars`);
  check('filter note mentions the measured basis', note.includes('MEASURED'));
  T.V3_SETTINGS.rsRequired = false;
  T.renderV3FilterBar();
  check('note changes when filter is off',
        document.getElementById('v3FilterNote').innerHTML.includes('Filter off'));
} catch (e) { check('render functions run without throwing', false, e.message); }

// ---- 7. no-benchmark degradation ----
try {
  const saved = T.state.bars[T.BENCH_SYM];
  delete T.state.bars[T.BENCH_SYM];
  T.renderV3FilterBar();
  const s2 = document.getElementById('v3RsStrip').innerHTML;
  check('degrades gracefully with no SPY bars', s2.includes('Waiting for SPY'));
  const r = T.runV3SignalReplay(T.state.bars.WDC, null, T.V3_BASELINE,
                                { benchRet: null, rsRequired: true, costBps: 0 });
  check('replay with rsRequired but no benchmark blocks entries rather than throwing',
        r.events.filter(e => e.reason === 'ENTRY').length === 0);
  T.state.bars[T.BENCH_SYM] = saved;
} catch (e) { check('no-benchmark path safe', false, e.message); }

console.log(fail ? `\n${fail} CHECK(S) FAILED` : '\nALL CHECKS PASSED');
process.exit(fail ? 1 : 0);
