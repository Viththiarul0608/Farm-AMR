/* Farm AMR dashboard — live viewer + control panel.
 * Server mode (default): the farm runs on the server; this page streams it over WebSocket.
 * Preview mode (window.FARM_LOCAL = true): runs the same engine inside the page. */
(() => {
const W = window.WORLD;
const { N, EDGES, BEDS, TYPES, PRANK, PICKS, FINISHES, LOAD_T, name, bedOfWork, workDuration } = W;
const $ = s => document.querySelector(s);
const NS = 'http://www.w3.org/2000/svg';
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const pad = n => String(n).padStart(2, '0');
const clock = t => { const d = new Date(t); return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`; };
const dur = ms => { const s = Math.max(0, Math.round(ms / 1000)); return `${Math.floor(s / 60)}:${pad(s % 60)}`; };
const ago = t => { if (!t) return 'never'; const s = Math.max(0, (Date.now() - t) / 1000); return s < 60 ? 'just now' : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`; };
const bedLabel = node => { const b = bedOfWork(node); return b ? `${b.id} ${b.crop}` : name(node); };
const LOCAL = !!window.FARM_LOCAL;

/* ================= state from engine ================= */
let S = { tasks: [], history: [], store: { kg: 0, byCrop: {} }, auto: { water: false, threshold: 25, liters: 20 }, feed: [] };
let AMRS = [], BSTATE = {}, booted = false, connected = false;
const amrById = id => AMRS.find(a => a.id === id);
const taskOf = a => S.tasks.find(t => t.id === a.taskId);

function applyLive(live) {
  if ($('#speedSel').value !== String(live.speed)) $('#speedSel').value = String(live.speed);
  live.amrs.forEach(s => {
    let a = amrById(s.id);
    if (!a) { AMRS.push({ ...s, dx: s.x, dy: s.y, dh: s.heading }); return; }
    const jump = Math.hypot(a.dx - s.x, a.dy - s.y) > 120;
    Object.assign(a, s); if (jump) { a.dx = s.x; a.dy = s.y; a.dh = s.heading; }
  });
  BSTATE = live.beds;
}
function smooth(dt) {
  const k = 1 - Math.exp(-dt * 12);
  AMRS.forEach(a => { a.dx += (a.x - a.dx) * k; a.dy += (a.y - a.dy) * k; let df = a.heading - a.dh; df = Math.atan2(Math.sin(df), Math.cos(df)); a.dh += df * k; });
}

/* ================= transport ================= */
let cmd;
const pending = new Map();
function setConn(on, txt) { connected = on; $('#conn').classList.toggle('off', !on); $('#connTxt').textContent = txt; }
if (LOCAL) {
  const E = window.FarmEngine, KEY = 'farm-amr-preview-v1';
  let saved = null; try { saved = JSON.parse(localStorage.getItem(KEY)); } catch (e) {}
  E.on('log', e => { S.feed.unshift(e); S.feed.length = Math.min(S.feed.length, 150); if (booted) renderFeed(); });
  let dirty = true; E.on('changed', () => { dirty = true; });
  E.init(saved);
  S = { ...E.dataState(), feed: E.feed() }; applyLive(E.snapshot());
  cmd = (op, args = {}) => { const r = E.cmd({ op, ...args }); if (r && r.msg) toast(r.msg); return Promise.resolve(r || {}); };
  let last = Date.now();
  setInterval(() => { const now = Date.now(); E.step(Math.min(0.5, (now - last) / 1000)); last = now; }, 50);
  setInterval(() => { applyLive(E.snapshot()); if (dirty) { dirty = false; Object.assign(S, E.dataState()); changedUI(); } }, 100);
  setInterval(() => { try { localStorage.setItem(KEY, JSON.stringify(E.exportState())); } catch (e) {} }, 3000);
  $('#modeTxt').textContent = 'preview (runs while this page is open)';
} else {
  let ws, reqSeq = 0, retry = 0;
  const connect = () => {
    ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws');
    ws.onopen = () => { retry = 0; setConn(true, 'LIVE · server'); };
    ws.onclose = () => { setConn(false, 'OFFLINE · reconnecting'); setTimeout(connect, Math.min(10000, 500 * 2 ** retry++)); };
    ws.onerror = () => ws.close();
    ws.onmessage = ev => {
      const m = JSON.parse(ev.data);
      if (m.type === 'hello') { AMRS = []; S = { ...m.data, feed: m.feed || [] }; applyLive(m.live); if (!booted) boot(); else { changedUI(); renderFeed(); } }
      else if (m.type === 'live') applyLive(m.live);
      else if (m.type === 'data') { Object.assign(S, m.data); if (booted) changedUI(); }
      else if (m.type === 'log') { S.feed.unshift(m.entry); S.feed.length = Math.min(S.feed.length, 150); if (booted) renderFeed(); }
      else if (m.type === 'result') { const p = pending.get(m.reqId); if (p) { pending.delete(m.reqId); p(m); } }
    };
  };
  cmd = (op, args = {}) => new Promise(res => {
    if (!connected) { toast('Not connected to the farm server'); res({ ok: false }); return; }
    const reqId = ++reqSeq; pending.set(reqId, r => { if (r.msg) toast(r.msg); res(r); });
    ws.send(JSON.stringify({ type: 'cmd', reqId, cmd: { ...args, op } }));
  });
  connect();
}

/* ================= status helpers ================= */
const ST = { idle: ['Idle', 'var(--st-idle)', 'var(--st-idle-ink)'], parked: ['Parked', 'var(--st-idle)', 'var(--st-idle-ink)'], charging: ['Charging', 'var(--st-chg)', '#fff'],
  nav: ['Navigating', 'var(--st-nav)', '#fff'], collect: ['Collecting tool', 'var(--st-load)', 'var(--st-load-ink)'], return: ['Returning tool', 'var(--st-load)', 'var(--st-load-ink)'],
  unload: ['Unloading harvest', 'var(--st-load)', 'var(--st-load-ink)'], work: ['Working', 'var(--st-work)', '#fff'], paused: ['Paused', 'var(--st-pause)', '#fff'],
  yield: ['Giving Way', 'var(--st-wait)', '#fff'], hold: ['Holding', 'var(--st-bad)', '#fff'] };
function statusKey(a) {
  if (a.paused) return ['paused'];
  const t = taskOf(a);
  if (a.loadKind === 'collect') return ['collect'];
  if (a.loadKind === 'return') return [t && t.type === 'harvest' ? 'unload' : 'return'];
  if (a.phase === 'work') return ['work', t ? TYPES[t.type].verb : 'Working'];
  if (a.phase === 'none') return [a.rest || 'idle'];
  if (a.yielding) return ['yield'];
  if (a.hold && a.v === 0) return ['hold'];
  return ['nav'];
}
const pillHTML = ([k, label]) => `<span class="pill" style="--pc:${ST[k][1]};--pi:${ST[k][2]}">${label || ST[k][0]}</span>`;
const TSTAT = t => ({ queued: 'Queued', to_pickup: 'To pickup', collecting: 'Collecting tool', to_work: 'To bed', working: TYPES[t.type].verb, to_finish: t.type === 'harvest' ? 'To store' : 'Returning tool',
  returning: t.type === 'harvest' ? 'Unloading' : 'Returning tool', completed: 'Completed', cancelled: 'Cancelled' }[t.status]);
const TCOL = { queued: 'var(--st-pause)', to_pickup: 'var(--st-nav)', collecting: 'var(--st-load)', to_work: 'var(--st-nav)', working: 'var(--st-work)', to_finish: 'var(--st-nav)', returning: 'var(--st-load)', completed: 'var(--ok)', cancelled: 'var(--bad)' };
const tpill = t => `<span class="pill" style="--pc:${TCOL[t.status]};--pi:${['collecting', 'returning'].includes(t.status) ? 'var(--st-load-ink)' : '#fff'}">${TSTAT(t)}</span>`;
const TOOLCOL = { water: '#42A5F5', seed: '#D7B377', fertilize: '#9E9E9E', harvest: '#B9824A' };
const SPRAYCOL = { water: '#1565C0', seed: '#6D4C41', fertilize: '#616161', harvest: '#2E7D32' };

/* ================= icons ================= */
const svgI = (b, w = 20) => `<svg width="${w}" height="${w}" viewBox="0 0 24 24" aria-hidden="true">${b}</svg>`;
const IC = {
  locate: svgI('<circle cx="12" cy="12" r="6.5" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="12" r="2.5" fill="currentColor"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4" stroke="currentColor" stroke-width="2"/>', 22),
  pause: svgI('<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><path d="M10 8.5v7M14 8.5v7" stroke="currentColor" stroke-width="2.4"/>'),
  play: svgI('<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><path d="M10 8.5l6 3.5-6 3.5z" fill="currentColor"/>'),
  cancel: svgI('<circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="2.2"/><path d="M6.5 17.5l11-11" stroke="currentColor" stroke-width="2.2"/>'),
  caret: svgI('<path d="M6 9l6 6 6-6z" fill="currentColor"/>', 14)
};

/* ================= map ================= */
const map = $('#map');
const el = (tag, attrs = {}, parent) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; };
const V = { vb: { x: 0, y: 0, w: 960, h: 600 }, follow: null, goalFor: null, drag: null };
let gStatic, gBeds, gRoute, gBot, gHi, bedEls = {}, routeEls = {}, botEls = {}, ndEls = {};
function buildMap() {
  gStatic = el('g', {}, map); gBeds = el('g', {}, map);
  const g = gStatic;
  el('rect', { class: 'f-grass', x: 0, y: 0, width: 960, height: 600 }, g);
  for (let i = 0; i < 16; i++) el('rect', { class: 'f-grass2', x: (i * 157) % 940, y: (i * 89) % 580, width: 18, height: 6, rx: 3, opacity: .6 }, g);
  el('rect', { class: 'f-fence', x: 4, y: 4, width: 952, height: 592, rx: 8 }, g);
  // buildings
  el('rect', { class: 'f-bld', x: 50, y: 28, width: 245, height: 104, rx: 4 }, g);
  el('text', { class: 'f-lbl', x: 172, y: 58 }, g).textContent = 'TOOL SHED';
  el('text', { class: 'f-sub', x: 172, y: 74 }, g).textContent = 'water tank · seeds · fertilizer';
  el('rect', { class: 'f-tank', x: 66, y: 86, width: 38, height: 36, rx: 6 }, g);
  el('text', { class: 'f-sub', x: 85, y: 108, style: 'fill:#0D47A1;font-weight:700' }, g).textContent = 'H₂O';
  el('rect', { class: 'f-glass', x: 335, y: 28, width: 300, height: 104, rx: 4 }, g);
  for (let x = 365; x < 635; x += 30) el('line', { class: 'f-glassrib', x1: x, y1: 28, x2: x, y2: 132 }, g);
  el('text', { class: 'f-lbl', x: 485, y: 84 }, g).textContent = 'GREENHOUSE';
  el('rect', { class: 'f-bld', x: 675, y: 28, width: 265, height: 104, rx: 4 }, g);
  el('text', { class: 'f-lbl', x: 807, y: 58 }, g).textContent = 'BARN';
  el('text', { class: 'f-sub', x: 807, y: 74 }, g).textContent = 'crates · harvest store';
  el('rect', { class: 'f-pad', x: 150, y: 355, width: 58, height: 140, rx: 6 }, g);
  el('text', { class: 'f-sub', x: 179, y: 350 }, g).textContent = 'CHARGING';
  el('rect', { class: 'f-pad', x: 10, y: 280, width: 42, height: 210, rx: 6 }, g);
  el('text', { class: 'f-sub', x: 31, y: 506 }, g).textContent = 'PARK';
  // tracks
  const pts = ([a, b]) => ({ x1: N[a].x, y1: N[a].y, x2: N[b].x, y2: N[b].y });
  EDGES.forEach(e => el('line', { class: 'f-path-e', 'stroke-width': 40, ...pts(e) }, g));
  EDGES.forEach(e => el('line', { class: 'f-path', 'stroke-width': 34, ...pts(e) }, g));
  EDGES.forEach(([a, b]) => {
    el('line', { class: 'f-edge', ...pts([a, b]) }, g);
    const mx = (N[a].x + N[b].x) / 2, my = (N[a].y + N[b].y) / 2, ang = Math.atan2(N[b].y - N[a].y, N[b].x - N[a].x) * 180 / Math.PI;
    el('path', { class: 'f-arrow', d: 'M1 0 L7 -4 L7 4 Z M-1 0 L-7 -4 L-7 4 Z', transform: `translate(${mx} ${my}) rotate(${ang})` }, g);
  });
  // beds
  Object.values(BEDS).forEach(b => {
    const bg = el('g', { class: 'bed', 'data-bed': b.id, tabindex: 0, role: 'button', 'aria-label': `Bed ${b.id} ${b.crop}` }, gBeds);
    const soil = el('rect', { class: 'bed-soil', x: b.x, y: b.y, width: b.w, height: b.h, rx: 6 }, bg);
    el('line', { class: 'bed-furrow', x1: b.x + 8, y1: b.cy, x2: b.x + b.w - 8, y2: b.cy }, bg);
    const plants = [];
    [b.cy - 28, b.cy + 28].forEach(py => { for (let i = 0; i < 7; i++) { const px = b.x + 12 + i * 17; plants.push({ c: el('circle', { class: 'crop', cx: px, cy: py, r: 4 }, bg), f: el('circle', { class: 'fruit', cx: px + 3, cy: py - 2, r: 2 }, bg) }); } });
    el('text', { class: 'bed-lbl', x: b.x + 4, y: b.y - 5 }, bg).textContent = `${b.id} · ${b.crop}`;
    const pct = el('text', { class: 'bed-pct', x: b.x + b.w - 2, y: b.y - 5 }, bg);
    bedEls[b.id] = { soil, plants, pct, g: bg };
  });
  // waypoints
  const GLYPH = { pick: 'P', work: 'W', store: 'S', park: 'K', chg: '⚡' };
  Object.entries(N).forEach(([id, n]) => {
    if (n.t === 'lane') return;
    const gg = el('g', { class: 'nd ' + n.t, 'data-node': id, tabindex: 0, role: 'button', 'aria-label': n.n }, gStatic);
    el('circle', { class: 'c t-' + n.t, cx: n.x, cy: n.y, r: n.t === 'tr' ? 10 : 15 }, gg);
    if (GLYPH[n.t]) el('text', { class: 'glyph', x: n.x, y: n.y }, gg).textContent = GLYPH[n.t];
    if (n.t !== 'work') el('text', { class: 'l', x: n.x, y: n.t === 'tr' ? n.y - 14 : (n.t === 'pick' || n.t === 'store' ? n.y - 21 : n.y + 28) }, gg).textContent = n.n;
    ndEls[id] = gg;
  });
  gRoute = el('g', {}, map); gBot = el('g', {}, map); gHi = el('g', {}, map);
  AMRS.forEach(a => { routeEls[a.id] = el('polyline', { class: 'route ' + a.cls, points: '' }, gRoute); botEls[a.id] = makeBot(a); });
  $('#wpl').innerHTML = [...Object.values(BEDS).map(b => `${b.id} ${b.crop}`), ...Object.values(N).filter(n => n.t !== 'lane').map(n => n.n)].map(v => `<option value="${v}">`).join('');
  wireMap();
}
function makeBot(a) {
  const g = el('g', { class: a.cls }, gBot);
  const hold = el('circle', { class: 'rb-hold', r: 28 }, g);
  const track = el('circle', { class: 'rb-track', r: 28 }, g);
  const prog = el('circle', { class: 'rb-prog', r: 28, transform: 'rotate(-90)' }, g);
  const rot = el('g', {}, g);
  const spray = el('g', { class: 'spray' }, rot);
  [[-6, -20, -14, -46], [6, -20, 12, -46], [0, -20, 0, -50], [-6, 20, -14, 46], [6, 20, 12, 46], [0, 20, 0, 50]].forEach(([x1, y1, x2, y2]) => el('line', { x1, y1, x2, y2 }, spray));
  [[-13, -19], [7, -19], [-13, 15], [7, 15]].forEach(([x, y]) => el('rect', { class: 'rb-wheel', x, y, width: 8, height: 4, rx: 1 }, rot));
  el('rect', { class: 'rb-body', x: -18, y: -16, width: 36, height: 32, rx: 6 }, rot);
  el('path', { class: 'rb-nose', d: 'M10 -8 L20 0 L10 8 Z' }, rot);
  const tool = el('g', {}, rot);
  const tbox = el('rect', { class: 'rb-tool', x: -12, y: -10, width: 20, height: 20, rx: 3 }, tool);
  const tlvl = el('rect', { class: 'rb-level', x: -11, y: -9, width: 18, height: 18, rx: 2 }, tool);
  const tag = el('g', { class: 'rb-tag' }, g);
  const tr = el('rect', { x: -34, y: -54, width: 68, height: 20, rx: 3 }, tag);
  const tt = el('text', { x: 0, y: -44 }, tag);
  return { g, rot, spray, tool, tbox, tlvl, prog, track, hold, tr, tt };
}
function applyVB() { const v = V.vb; map.setAttribute('viewBox', `${v.x.toFixed(1)} ${v.y.toFixed(1)} ${v.w.toFixed(1)} ${v.h.toFixed(1)}`); }
function zoomTo(cx, cy, w) { w = Math.max(240, Math.min(960, w)); const h = w * 600 / 960; V.vb = { x: Math.max(0, Math.min(960 - w, cx - w / 2)), y: Math.max(0, Math.min(600 - h, cy - h / 2)), w, h }; applyVB(); }
function svgPt(e) { const p = map.createSVGPoint(); p.x = e.clientX; p.y = e.clientY; return p.matrixTransform(map.getScreenCTM().inverse()); }
function followTick(dt) {
  const a = amrById(V.follow); if (!a) return;
  const pts = [[a.dx, a.dy], ...a.path.map(id => [N[id].x, N[id].y])];
  if (a.goal && N[a.goal.node]) pts.push([N[a.goal.node].x, N[a.goal.node].y]);
  const t = taskOf(a);
  if (a.phase === 'work' && t) { const b = bedOfWork(t.work); pts.push([b.x, b.y], [b.x + b.w, b.y + b.h]); }
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]), padd = 80;
  const x0 = Math.min(...xs) - padd, x1 = Math.max(...xs) + padd, y0 = Math.min(...ys) - padd - 30, y1 = Math.max(...ys) + padd;
  const w = Math.min(960, Math.max(420, x1 - x0, (y1 - y0) * 1.6)), h = w / 1.6;
  const tx = Math.max(0, Math.min(960 - w, (x0 + x1) / 2 - w / 2)), ty = Math.max(0, Math.min(600 - h, (y0 + y1) / 2 - h / 2));
  const k = 1 - Math.exp(-dt * 3.5), v = V.vb;
  v.x += (tx - v.x) * k; v.y += (ty - v.y) * k; v.w += (w - v.w) * k; v.h = v.w / 1.6; applyVB();
}
function wireMap() {
  document.querySelectorAll('[data-z]').forEach(b => b.onclick = () => { V.follow = null; const v = V.vb, cx = v.x + v.w / 2, cy = v.y + v.h / 2; if (b.dataset.z === 'in') zoomTo(cx, cy, v.w * 0.75); else if (b.dataset.z === 'out') zoomTo(cx, cy, v.w / 0.75); else zoomTo(480, 300, 960); });
  $('#srch').addEventListener('change', e => {
    const v = e.target.value.trim().toLowerCase(); if (!v) return;
    const bed = Object.values(BEDS).find(b => `${b.id} ${b.crop}`.toLowerCase() === v || b.id.toLowerCase() === v || b.crop.toLowerCase() === v);
    const id = bed ? bed.work : Object.keys(N).find(k => N[k].t !== 'lane' && N[k].n.toLowerCase() === v) || Object.keys(N).find(k => N[k].t !== 'lane' && N[k].n.toLowerCase().includes(v));
    if (!id) { toast(`No waypoint matching "${e.target.value}"`); return; }
    const cx = bed ? bed.x + bed.w / 2 : N[id].x, cy = bed ? bed.cy : N[id].y;
    V.follow = null; gHi.innerHTML = ''; el('circle', { class: 'hi', cx, cy, r: bed ? 50 : 24 }, gHi); zoomTo(cx, cy, 520);
    setTimeout(() => { gHi.innerHTML = ''; }, 6000);
  });
  map.addEventListener('pointerdown', e => { V.drag = { x: e.clientX, y: e.clientY, vx: V.vb.x, vy: V.vb.y, moved: false }; });
  map.addEventListener('pointermove', e => {
    const d = V.drag; if (!d) return;
    const dx = e.clientX - d.x, dy = e.clientY - d.y; if (Math.hypot(dx, dy) > 5) { d.moved = true; if (V.vb.w < 960) V.follow = null; }
    if (d.moved && V.vb.w < 960) { const s = V.vb.w / map.clientWidth; V.vb.x = Math.max(0, Math.min(960 - V.vb.w, d.vx - dx * s)); V.vb.y = Math.max(0, Math.min(600 - V.vb.h, d.vy - dy * s)); applyVB(); }
  });
  map.addEventListener('pointerleave', () => { V.drag = null; });
  map.addEventListener('pointerup', e => {
    const d = V.drag; V.drag = null; if (d && d.moved) return;
    const ndEl = e.target.closest('[data-node]'), bedEl = e.target.closest('[data-bed]');
    let id = ndEl ? ndEl.dataset.node : bedEl ? BEDS[bedEl.dataset.bed].work : null;
    if (V.goalFor) {
      if (!id) { const p = svgPt(e); let best = null, bd = Infinity; Object.keys(N).forEach(k => { if (N[k].t === 'lane') return; const dd = Math.hypot(N[k].x - p.x, N[k].y - p.y); if (dd < bd) { bd = dd; best = k; } }); id = best; }
      cmd('amr.goal', { id: V.goalFor, node: id }); closeGoal(); return;
    }
    if (!id) return;
    const t = N[id].t;
    if (t === 'pick') fillFromMap('pick', id);
    else if (t === 'work') fillFromMap('work', id);
    else if (t === 'store') fillFromMap('fin', id);
    else toast(`${name(id)} · press GOAL on an AMR row to send it here`);
  });
}

/* ================= AMR rows ================= */
function buildRows() {
  $('#amrRows').innerHTML = AMRS.map(a => `
    <div class="arow" data-amr="${a.id}">
      <div class="nm"><button class="caret" type="button" data-act="menu">${a.id}${IC.caret}</button><small data-f="sub"></small>
        <div class="menu" hidden><button type="button" data-act="charge">Send to charging station</button><button type="button" data-act="park">Send to parking</button><button type="button" data-act="locate">Follow on map</button></div></div>
      <button class="icon-btn" type="button" data-act="locate" aria-label="Follow ${a.id}">${IC.locate}</button>
      <div class="stcell"><span data-f="pill"></span><small data-f="hold"></small></div>
      <button class="goal" type="button" data-act="goal">GOAL</button>
      <button class="dark" type="button" data-act="pause" aria-label="Pause ${a.id}">${IC.pause}</button>
      <button class="dark" type="button" data-act="cancel" aria-label="Cancel ${a.id} task">${IC.cancel}</button>
    </div>`).join('');
  $('#amrRows').addEventListener('click', e => {
    const b = e.target.closest('[data-act]'); if (!b) return;
    const a = amrById(b.closest('[data-amr]').dataset.amr), act = b.dataset.act;
    const menu = b.closest('.nm')?.querySelector('.menu');
    document.querySelectorAll('.menu').forEach(m => { if (m !== menu) m.hidden = true; });
    if (act === 'menu') { menu.hidden = !menu.hidden; return; }
    if (menu) menu.hidden = true;
    if (act === 'locate') { if (V.follow === a.id) { V.follow = null; toast(`Stopped following ${a.id}`); } else { V.follow = a.id; $('#mon').scrollIntoView({ behavior: 'smooth', block: 'nearest' }); toast(`Following ${a.id}: the map tracks its whole path`); } }
    if (act === 'goal') { if (a.mission === 'task') { toast(`${a.id} is running ${a.taskId}. Cancel it to send a manual goal.`); return; } openGoal(a); }
    if (act === 'pause') cmd('amr.pause', { id: a.id });
    if (act === 'cancel') cmd('amr.cancel', { id: a.id });
    if (act === 'charge') cmd('amr.charge', { id: a.id });
    if (act === 'park') cmd('amr.park', { id: a.id });
  });
  document.addEventListener('click', e => { if (!e.target.closest('.nm')) document.querySelectorAll('.menu').forEach(m => m.hidden = true); });
}
function openGoal(a) {
  V.goalFor = a.id; $('#goalbar').hidden = false; $('#goalAmr').textContent = a.id;
  const grp = (label, ids) => `<optgroup label="${label}">${ids.map(id => `<option value="${id}">${N[id].t === 'work' ? bedLabel(id) + ' (' + N[id].n + ')' : N[id].n}</option>`).join('')}</optgroup>`;
  const by = t => Object.keys(N).filter(k => N[k].t === t);
  $('#goalSel').innerHTML = '<option value="">Choose waypoint</option>' + grp('Garden beds', by('work')) + grp('Tool points', [...by('pick'), ...by('store')]) + grp('Parking & charging', [...by('park'), ...by('chg')]) + grp('Transit', by('tr'));
  map.classList.add('goalmode');
}
function closeGoal() { V.goalFor = null; $('#goalbar').hidden = true; map.classList.remove('goalmode'); }
$('#goalClose').onclick = closeGoal;
$('#goalGo').onclick = () => { const v = $('#goalSel').value; if (v) { cmd('amr.goal', { id: V.goalFor, node: v }); closeGoal(); } };
function renderRows() {
  AMRS.forEach(a => {
    const r = document.querySelector(`.arow[data-amr="${a.id}"]`); if (!r) return;
    const k = statusKey(a), t = taskOf(a), key = k.join('|');
    const pc = r.querySelector('[data-f="pill"]'); if (pc.dataset.k !== key) { pc.dataset.k = key; pc.innerHTML = pillHTML(k); }
    r.querySelector('[data-f="sub"]').textContent = `${Math.round(a.battery)}% · ${name(a.cell)}`;
    const c = a.carrying;
    const hold = a.paused ? 'Paused by operator' : a.hold ? a.hold : t ? `${t.id} · ${TYPES[t.type].label} ${bedLabel(t.work)}${c ? ` · ${c.item} ${c.left}/${c.amount} ${c.unit}` : ''}` : a.mission === 'manual' && a.goal ? `Goal ${name(a.goal.node)}` : a.rest === 'charging' ? `Docked ${name(a.cell)}` : '';
    r.querySelector('[data-f="hold"]').textContent = hold;
    const pb = r.querySelector('[data-act="pause"]'); const want = a.paused ? 'play' : 'pause'; if (pb.dataset.i !== want) { pb.dataset.i = want; pb.innerHTML = IC[want]; pb.setAttribute('aria-label', (a.paused ? 'Resume ' : 'Pause ') + a.id); }
    r.querySelector('[data-act="cancel"]').disabled = !a.goal && !a.taskId;
    r.querySelector('.icon-btn[data-act="locate"]').setAttribute('aria-pressed', String(V.follow === a.id));
  });
  const working = AMRS.filter(a => a.phase === 'work').map(a => `${a.id} ${TYPES[(taskOf(a) || { type: 'water' }).type].verb.toLowerCase()}`);
  $('#mapwho').textContent = (V.follow ? `Following ${V.follow}` : 'Live farm view') + (working.length ? ' · ' + working.join(', ') : '');
}

/* ================= per-frame map render ================= */
const mix = (a, b, t) => { const p = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16)); const A = p(a), B = p(b); return '#' + A.map((v, i) => Math.round(v + (B[i] - v) * t).toString(16).padStart(2, '0')).join(''); };
function renderMap() {
  Object.entries(BEDS).forEach(([id, b]) => {
    const B = BSTATE[id]; if (!B) return; const E = bedEls[id];
    E.soil.setAttribute('fill', mix('#C9A57A', '#5B3E26', B.moisture / 100));
    const r = B.planted ? 2 + B.growth / 100 * 5.5 : 0;
    E.plants.forEach(p => { p.c.setAttribute('r', r.toFixed(1)); p.f.setAttribute('r', B.planted && B.growth >= 80 ? 2.2 : 0); });
    E.pct.textContent = `💧${Math.round(B.moisture)}%`;
    E.g.classList.toggle('sel', $('#fWork').value === b.work && tab === 'form');
  });
  AMRS.forEach(a => {
    const E = botEls[a.id]; if (!E) return;
    routeEls[a.id].setAttribute('points', a.path.length && a.phase !== 'work' ? [[a.dx, a.dy], ...a.path.map(id => [N[id].x, N[id].y])].map(p => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ') : '');
    E.g.setAttribute('transform', `translate(${a.dx.toFixed(1)} ${a.dy.toFixed(1)})`);
    E.rot.setAttribute('transform', `rotate(${(a.dh * 180 / Math.PI).toFixed(1)})`);
    const t = taskOf(a), c = a.carrying;
    let prog = 0, scale = c ? 1 : 0;
    if (a.loadKind) { prog = Math.min(1, Math.max(0, 1 - a.loadT / LOAD_T)); scale = a.loadKind === 'collect' ? prog : 1 - prog; }
    else if (a.phase === 'work') prog = a.workDone;
    const type = c ? c.type : t ? t.type : 'water';
    E.tool.style.display = scale > 0.03 ? '' : 'none';
    E.tool.setAttribute('transform', `scale(${Math.max(.05, scale).toFixed(2)})`);
    E.tbox.setAttribute('fill', TOOLCOL[type] || '#999');
    const lvl = c && c.type === 'water' ? c.left / c.amount : 0;
    E.tlvl.style.display = lvl > 0 ? '' : 'none';
    E.tlvl.setAttribute('height', (18 * lvl).toFixed(1)); E.tlvl.setAttribute('y', (9 - 18 * lvl).toFixed(1));
    E.spray.style.display = a.phase === 'work' && !a.paused ? '' : 'none';
    E.spray.querySelectorAll('line').forEach(l => l.setAttribute('stroke', SPRAYCOL[type] || '#1565C0'));
    const C = 2 * Math.PI * 28, showRing = !!a.loadKind || a.phase === 'work';
    E.prog.style.display = E.track.style.display = showRing ? '' : 'none';
    E.prog.setAttribute('stroke-dasharray', `${(C * prog).toFixed(1)} ${C.toFixed(1)}`);
    E.hold.style.display = a.hold && a.v === 0 && !a.paused ? '' : 'none';
    const tag = a.phase === 'work' && t ? `${a.id} · ${TYPES[t.type].verb} ${Math.round(prog * 100)}%` : c ? `${a.id} · ${c.item} ${c.left}${c.unit === 'kg' ? '' : '/' + c.amount} ${c.unit}` : a.loadKind ? `${a.id} · ${a.loadKind === 'collect' ? 'Collecting' : 'Returning'} ${Math.round(prog * 100)}%` : a.id;
    if (E.tt.textContent !== tag) { E.tt.textContent = tag; const w = tag.length * 6.6 + 16; E.tr.setAttribute('x', -w / 2); E.tr.setAttribute('width', w); }
  });
}
function markTargets() {
  Object.values(ndEls).forEach(g => g.classList.remove('tgt'));
  S.tasks.filter(t => t.status !== 'queued').forEach(t => {
    const ids = t.status === 'to_pickup' || t.status === 'collecting' ? [t.pickup, t.work] : t.status === 'to_finish' || t.status === 'returning' ? [t.finish] : [t.work];
    ids.forEach(id => ndEls[id]?.classList.add('tgt'));
  });
}

/* ================= tasks ================= */
let tab = 'queue', editingId = null;
function setTab(n) { tab = n; document.querySelectorAll('.tabs button').forEach(b => b.setAttribute('aria-selected', String(b.dataset.tab === n))); ['queue', 'form', 'history'].forEach(x => $('#pane-' + x).hidden = x !== n); if (n === 'history') renderHistory(); }
const routeHTML = t => `<span class="rt"><span class="p">${name(t.pickup)}</span> → <span class="w">${bedLabel(t.work)}</span> → <span class="f">${name(t.finish)}</span></span>`;
const canEdit = t => ['queued', 'to_pickup', 'collecting', 'to_work', 'to_finish'].includes(t.status);
const queued = () => S.tasks.filter(t => t.status === 'queued').sort((x, y) => PRANK[x.priority] - PRANK[y.priority] || x.createdAt - y.createdAt);
const amountTxt = t => `${t.amount} ${TYPES[t.type].unit}`;
function changedUI() { renderQueue(); markTargets(); renderBeds(true); $('#hCount').textContent = S.history.length; if (tab === 'history') renderHistory(); refreshFormLocks(); syncAuto(); }
function renderQueue() {
  const run = S.tasks.filter(t => t.status !== 'queued');
  const stage = { to_pickup: 0, collecting: 1, to_work: 2, working: 3, to_finish: 4, returning: 4 };
  $('#runBox').innerHTML = run.length ? run.map(t => {
    const a = amrById(t.amr) || { cls: '' }, st = stage[t.status], T = TYPES[t.type];
    const steps = ['Go to pickup', 'Collect ' + T.item.toLowerCase(), 'Go to bed', T.verb + (t.status === 'working' ? ` ${Math.round((t.progress || 0) * 100)}%` : ''), t.type === 'harvest' ? 'Unload at store' : 'Return tool'];
    return `<div class="run ${a.cls}"><div class="rowx"><span class="mono" style="font-weight:500">${t.id} · ${t.amr}</span><span class="acts">${t.auto ? '<span class="tag">auto</span>' : ''}${tpill(t)}</span></div>
      <div class="rowx"><strong style="font-weight:500">${T.label} · ${bedLabel(t.work)} · ${amountTxt(t)}</strong></div>
      ${routeHTML(t)}
      <div class="steps">${steps.map((s, i) => `<div class="${i < st ? 'done' : i === st ? 'cur' : ''}">${s}</div>`).join('')}</div>
      <div class="rowx"><span class="prio ${t.priority}">${t.priority}</span><span class="acts">${canEdit(t) ? `<button class="btn sm" data-edit="${t.id}" type="button">Edit</button>` : ''}<button class="btn sm bad" data-cancel="${t.id}" type="button">Cancel</button></span></div></div>`;
  }).join('') : `<div class="empty">No task running. Free AMRs return to their charging stations automatically.</div>`;
  const q = queued();
  $('#queueBox').innerHTML = q.length ? `<ol class="qlist">${q.map(t => `<li><div class="qtop"><span class="mono" style="font-weight:500">${t.id}</span><span>${TYPES[t.type].label} · ${bedLabel(t.work)} · ${amountTxt(t)}</span><span class="prio ${t.priority}">${t.priority}</span>${t.auto ? '<span class="tag">auto</span>' : ''}<small style="color:var(--muted)">${t.assignee === 'auto' ? 'Auto' : t.assignee}${t.edits ? ` · edited ${t.edits}×` : ''}</small></div>${routeHTML(t)}
    <span class="acts"><button class="btn sm" data-edit="${t.id}" type="button">Edit</button><button class="btn sm bad" data-cancel="${t.id}" type="button">Cancel</button></span></li>`).join('')}</ol>` : `<div class="empty">Queue is empty.</div>`;
  $('#qCount').textContent = S.tasks.length;
}
function armOrRun(btn, run, label = 'Confirm cancel') { if (btn.classList.contains('armed')) { run(); return; } btn.classList.add('armed'); const old = btn.textContent; btn.textContent = label; setTimeout(() => { if (btn.isConnected) { btn.classList.remove('armed'); btn.textContent = old; } }, 3000); }
document.addEventListener('click', e => {
  const ed = e.target.closest('[data-edit]'), cn = e.target.closest('[data-cancel]');
  if (ed) startEdit(ed.dataset.edit);
  if (cn) armOrRun(cn, () => { cmd('task.cancel', { taskId: cn.dataset.cancel }); if (editingId === cn.dataset.cancel) resetForm(); });
});

/* form */
const fType = $('#fType'), fAmt = $('#fAmt'), fPick = $('#fPick'), fWork = $('#fWork'), fFin = $('#fFin');
function bedLine(b) {
  const B = BSTATE[b.id] || {};
  const st = !B.planted ? 'empty' : B.moisture < 25 ? 'dry' : B.growth >= 90 ? 'ready to harvest' : 'ok';
  return `${b.id} · ${b.crop} — 💧${Math.round(B.moisture || 0)}% · 🌱${Math.round(B.growth || 0)}% · ${st}`;
}
function fillStatic() {
  fType.innerHTML = Object.entries(TYPES).map(([k, T]) => `<option value="${k}">${T.label}</option>`).join('');
  fPick.innerHTML = PICKS.map(id => `<option value="${id}">${N[id].n} — ${Object.values(TYPES).find(T => T.tool === id).item}</option>`).join('');
  fFin.innerHTML = FINISHES.map(id => `<option value="${id}">${N[id].n} — ${N[id].t === 'store' ? 'unload harvest' : 'return the tool here'}</option>`).join('');
  refreshWorkOptions();
}
function refreshWorkOptions() { const keep = fWork.value; fWork.innerHTML = Object.values(BEDS).map(b => `<option value="${b.work}">${bedLine(b)}</option>`).join(''); if (keep) fWork.value = keep; }
function onTypeChange(keepAmount) {
  const T = TYPES[fType.value];
  if (!keepAmount) fAmt.value = T.def;
  fAmt.min = T.min; fAmt.max = T.max;
  $('#fAmtLbl').textContent = `${T.label === 'Watering' ? 'Water' : T.label === 'Harvesting' ? 'Crates' : T.label === 'Seeding' ? 'Seeds' : 'Fertilizer'} (${T.unit}, ${T.min}–${T.max})`;
  if (!editingId) { fPick.value = T.tool; fFin.value = T.finish; }
  renderPreview();
}
function renderPreview() {
  const T = TYPES[fType.value], amt = parseFloat(fAmt.value), b = bedOfWork(fWork.value);
  if (!b || !(amt > 0)) { $('#fPrev').textContent = ''; return; }
  const B = BSTATE[b.id] || {};
  const warn = fType.value === 'harvest' && (!B.planted || B.growth < 60) ? ` <span style="color:var(--warn)">Crop is only ${Math.round(B.growth || 0)}% grown.</span>` : fType.value === 'seed' && B.planted ? ` <span style="color:var(--warn)">This bed is already planted; seeding replants it.</span>` : '';
  $('#fPrev').innerHTML = `AMR collects <b>${T.item} (${amt} ${T.unit})</b> at <b>${N[fPick.value].n}</b> → ${T.verb.toLowerCase()} <b>${b.id} ${b.crop}</b> along the row (~${Math.round(workDuration(fType.value, amt))} s) → goes to <b>${N[fFin.value].n}</b>.${warn}`;
}
fType.addEventListener('change', () => onTypeChange(false));
[fAmt, fPick, fWork, fFin].forEach(x => x.addEventListener('input', renderPreview));
[fPick, fWork, fFin].forEach(x => x.addEventListener('change', renderPreview));
function resetForm() {
  editingId = null; $('#taskForm').reset(); fType.value = 'water'; $('#fPrio').value = 'normal'; $('#fAmr').value = 'auto'; $('#formErr').textContent = '';
  const dry = Object.values(BEDS).sort((x, y) => (BSTATE[x.id]?.moisture || 0) - (BSTATE[y.id]?.moisture || 0))[0];
  if (dry) fWork.value = dry.work;
  $('#formTitle').textContent = 'New farm task'; $('#submitBtn').textContent = 'Create task'; $('#formStatus').innerHTML = ''; $('#tb-form').firstChild.nodeValue = 'Create';
  onTypeChange(false); refreshFormLocks();
}
function startEdit(id) {
  const t = S.tasks.find(x => x.id === id); if (!t || !canEdit(t)) return;
  editingId = id; fType.value = t.type; onTypeChange(true); fAmt.value = t.amount; fPick.value = t.pickup; fWork.value = t.work; fFin.value = t.finish; $('#fPrio').value = t.priority; $('#fAmr').value = t.assignee; $('#formErr').textContent = '';
  $('#formTitle').textContent = `Edit ${t.id}`; $('#submitBtn').textContent = 'Update task'; $('#tb-form').firstChild.nodeValue = 'Edit';
  refreshFormLocks(); renderPreview(); setTab('form');
}
function refreshFormLocks() {
  const t = editingId && S.tasks.find(x => x.id === editingId); if (editingId && !t) { resetForm(); return; }
  const note = $('#lockNote'); [fType, fAmt, fPick, fWork, fFin, $('#fAmr')].forEach(x => x.disabled = false); $('#submitBtn').disabled = false; note.hidden = true;
  if (!t) { $('#formStatus').innerHTML = ''; return; }
  $('#formStatus').innerHTML = tpill(t);
  if (t.status !== 'queued') { fType.disabled = true; $('#fAmr').disabled = true; note.hidden = false; note.textContent = `Running on ${t.amr}. Changing a point re-routes it right away. Type and assignment are locked.`; }
  if (['to_work', 'to_finish'].includes(t.status)) { [fAmt, fPick].forEach(x => x.disabled = true); note.textContent = 'The tool is already on the robot, so pickup and amount are locked. You can still change the bed and the finish point.'; }
  if (t.status === 'to_finish') { fWork.disabled = true; note.textContent = 'The bed work is done. You can still change where the AMR goes next.'; }
  if (!canEdit(t)) { [fType, fAmt, fPick, fWork, fFin].forEach(x => x.disabled = true); $('#submitBtn').disabled = true; note.hidden = false; note.textContent = 'The AMR is busy with this step; editing unlocks when it moves on.'; }
}
function fillFromMap(which, id) {
  if (tab !== 'form') { if (!editingId) resetForm(); setTab('form'); }
  if (which === 'pick' && !fPick.disabled) {
    fPick.value = id; const T = Object.entries(TYPES).find(([, T]) => T.tool === id);
    if (T && !editingId && fType.value !== T[0]) { fType.value = T[0]; onTypeChange(false); fPick.value = id; }
    toast(`Pickup set to ${name(id)}`);
  } else if (which === 'work' && !fWork.disabled) { fWork.value = id; toast(`Work point set to ${bedLabel(id)}`); }
  else if (which === 'fin' && !fFin.disabled) { fFin.value = id; toast(`Finish point set to ${name(id)}`); }
  renderPreview(); $('#tasks').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
$('#clearBtn').onclick = () => resetForm();
$('#newBtn').onclick = () => { resetForm(); setTab('form'); };
$('#taskForm').addEventListener('submit', async e => {
  e.preventDefault();
  const T = TYPES[fType.value], amt = parseFloat(fAmt.value), err = $('#formErr');
  if (!(amt >= T.min && amt <= T.max)) { err.textContent = `Enter ${T.min}–${T.max} ${T.unit} for ${T.label.toLowerCase()}.`; fAmt.focus(); return; }
  err.textContent = '';
  const body = { type: fType.value, amount: amt, pickup: fPick.value, work: fWork.value, finish: fFin.value, assignee: $('#fAmr').value, priority: $('#fPrio').value };
  const r = editingId ? await cmd('task.update', { taskId: editingId, ...body }) : await cmd('task.create', body);
  if (r.ok) { resetForm(); setTab('queue'); } else if (r.msg) err.textContent = r.msg;
});

/* ================= beds card ================= */
let bedsBuilt = false;
function bar(v, col) { return `<div class="bar"><b><i style="width:${Math.max(0, Math.min(100, v)).toFixed(0)}%;background:${col}"></i></b><span>${Math.round(v)}%</span></div>`; }
function renderBeds(force) {
  if (!bedsBuilt || force) {
    $('#bedBody').innerHTML = Object.values(BEDS).map(b => `<tr data-row="${b.id}"><td class="b">${b.id} · ${b.crop}<small data-f="last"></small></td><td data-f="m"></td><td data-f="n"></td><td data-f="g"></td><td data-f="st"></td>
      <td><span class="acts"><button class="btn xs" type="button" data-quick="water" data-bed="${b.id}">Water</button><button class="btn xs" type="button" data-quick="fertilize" data-bed="${b.id}">Fertilize</button><button class="btn xs" type="button" data-f="hv" data-bed="${b.id}"></button></span></td></tr>`).join('');
    bedsBuilt = true;
    const st = S.store || { kg: 0, byCrop: {} };
    $('#storeLine').innerHTML = `Harvest store: <b>${st.kg} kg</b> ${Object.keys(st.byCrop).length ? '(' + Object.entries(st.byCrop).map(([k, v]) => `${k} ${v} kg`).join(' · ') + ')' : ''}`;
  }
  Object.values(BEDS).forEach(b => {
    const B = BSTATE[b.id]; if (!B) return; const r = document.querySelector(`tr[data-row="${b.id}"]`); if (!r) return;
    r.querySelector('[data-f="m"]').innerHTML = bar(B.moisture, 'var(--bar-water)');
    r.querySelector('[data-f="n"]').innerHTML = bar(B.nutrients, 'var(--bar-nutr)');
    r.querySelector('[data-f="g"]').innerHTML = B.planted ? bar(B.growth, 'var(--bar-grow)') : '<span style="color:var(--muted)">not planted</span>';
    const worker = AMRS.find(a => a.phase === 'work' && taskOf(a) && taskOf(a).work === b.work);
    const [lbl, col] = worker ? [`${worker.id} ${TYPES[taskOf(worker).type].verb.toLowerCase()}`, 'var(--st-work)'] : !B.planted ? ['Empty', 'var(--st-pause)'] : B.moisture < 25 ? ['Dry', 'var(--bad)'] : B.growth >= 90 ? ['Ready to harvest', 'var(--st-wait)'] : ['Growing', 'var(--ok)'];
    const stc = r.querySelector('[data-f="st"]'); if (stc.dataset.v !== lbl) { stc.dataset.v = lbl; stc.innerHTML = `<span class="bpill" style="--bc:${col}">${lbl}</span>`; }
    r.querySelector('[data-f="last"]').textContent = `watered ${ago(B.lastWatered)}`;
    const hv = r.querySelector('[data-f="hv"]'); const q = B.planted ? 'harvest' : 'seed'; if (hv.dataset.quick !== q) { hv.dataset.quick = q; hv.textContent = B.planted ? 'Harvest' : 'Seed'; }
  });
}
$('#bedBody').addEventListener('click', e => { const b = e.target.closest('[data-quick]'); if (b) cmd('bed.quick', { bed: b.dataset.bed, type: b.dataset.quick }); });
let autoTouched = 0;
function syncAuto() { if (Date.now() - autoTouched < 1500) return; const a = S.auto || {}; $('#autoOn').checked = !!a.water; if (document.activeElement !== $('#autoTh')) $('#autoTh').value = a.threshold; if (document.activeElement !== $('#autoL')) $('#autoL').value = a.liters; }
['autoOn', 'autoTh', 'autoL'].forEach(id => $('#' + id).addEventListener('change', () => { autoTouched = Date.now(); cmd('auto.set', { water: $('#autoOn').checked, threshold: +$('#autoTh').value, liters: +$('#autoL').value }); }));

/* ================= history ================= */
let openRow = null;
function renderHistory() {
  const q = $('#hSearch').value.trim().toLowerCase(), f = $('#hFilter').value;
  const rows = S.history.filter(t => (f === 'all' || t.status === f) && (!q || [t.id, t.amr, TYPES[t.type].label, bedLabel(t.work)].join(' ').toLowerCase().includes(q)));
  const done = S.history.filter(t => t.status === 'completed' && t.startedAt); const avg = done.length ? done.reduce((s, t) => s + (t.finishedAt - t.startedAt), 0) / done.length : 0;
  const water = done.filter(t => t.type === 'water').reduce((s, t) => s + t.amount, 0);
  $('#hStats').innerHTML = `<span><b>${done.length}</b> completed</span><span><b>${S.history.length - done.length}</b> cancelled</span><span>avg cycle <b>${dur(avg)}</b></span><span>water used <b>${water} L</b></span><span>distance <b>${done.reduce((s, t) => s + t.distance, 0).toFixed(1)} m</b></span>`;
  $('#hBody').innerHTML = rows.length ? rows.map(t => `<tr class="hrow" data-h="${t.id}" tabindex="0"><td class="mono">${t.id}${t.auto ? ' <span class="tag">auto</span>' : ''}${t.edits ? ` <small style="color:var(--muted)">✎${t.edits}</small>` : ''}</td><td>${t.amr || '–'}</td><td>${TYPES[t.type].label}</td><td>${bedLabel(t.work)}</td><td>${t.type === 'harvest' && t.harvestKg != null ? t.harvestKg + ' kg' : amountTxt(t)}</td><td>${tpill(t)}</td>
    <td class="mono">${t.startedAt ? clock(t.startedAt) : '–'}</td><td class="mono">${clock(t.finishedAt)}</td><td class="mono">${t.startedAt ? dur(t.finishedAt - t.startedAt) : '–'}</td><td class="mono">${t.distance ? t.distance.toFixed(1) + ' m' : '–'}</td></tr>
    ${openRow === t.id ? `<tr class="detail"><td colspan="10"><ol class="tl">${t.events.map(ev => `<li><time>${clock(ev.t)}</time><span>${esc(ev.msg)}</span></li>`).join('')}</ol></td></tr>` : ''}`).join('') : `<tr><td colspan="10" style="color:var(--muted)">No tasks match this filter.</td></tr>`;
}
const toggleRow = r => { openRow = openRow === r.dataset.h ? null : r.dataset.h; renderHistory(); };
$('#hBody').addEventListener('click', e => { const r = e.target.closest('[data-h]'); if (r) toggleRow(r); });
$('#hBody').addEventListener('keydown', e => { const r = e.target.closest('[data-h]'); if (r && e.key === 'Enter') toggleRow(r); });
$('#hSearch').addEventListener('input', renderHistory); $('#hFilter').addEventListener('change', renderHistory);

/* ================= misc ================= */
function renderFeed() { $('#feed').innerHTML = S.feed.map(f => `<li class="k-${f.kind}"><time>${clock(f.t)}</time><span>${esc(f.msg)}</span></li>`).join(''); $('#feedCount').textContent = `${S.feed.length} events`; }
document.querySelectorAll('.tabs button').forEach(b => b.onclick = () => setTab(b.dataset.tab));
document.querySelectorAll('.side a').forEach(a => a.addEventListener('click', () => { document.querySelectorAll('.side a').forEach(x => x.classList.toggle('on', x === a)); }));
$('#speedSel').onchange = e => cmd('sim.speed', { value: +e.target.value });
$('#resetBtn').onclick = e => { const btn = e.currentTarget; armOrRun(btn, () => { cmd('sim.reset'); btn.classList.remove('armed'); btn.textContent = 'RESET DEMO'; resetForm(); }, 'CONFIRM RESET'); };
let toastT; function toast(m) { const t = $('#toast'); t.textContent = m; t.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => t.hidden = true, 2600); }

/* ================= boot ================= */
function boot() {
  booted = true;
  buildMap(); buildRows(); fillStatic(); resetForm(); changedUI(); renderFeed(); renderRows(); renderMap();
  let last = performance.now(), uiAcc = 0, optAcc = 0;
  const frame = now => {
    const dt = Math.min(0.1, (now - last) / 1000); last = now;
    smooth(dt); if (V.follow) followTick(dt);
    renderMap();
    uiAcc += dt; if (uiAcc > 0.25) { uiAcc = 0; renderRows(); renderBeds(false); }
    optAcc += dt; if (optAcc > 3) { optAcc = 0; if (document.activeElement !== fWork) refreshWorkOptions(); }
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}
if (LOCAL) { setConn(true, 'LIVE · preview'); boot(); } else setConn(false, 'CONNECTING…');
})();
