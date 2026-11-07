'use strict';
/* astra web GUI core. No dependencies, nothing loaded from other sites.
   Server text is always inserted with textContent (never innerHTML); icons are constants from ui/icons.js.
   Other files: ui/sections.js (declarative tab sections), ui/console.js, ui/settings.js (loaded when first used),
   ui/files.js, ui/logs.js, ui/processes.js, ui/desktop.js (custom tabs). */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const I = (name, cls) => window.ico(name, cls);
const h = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  let value;
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.slice(2), v);
    else if (k === 'style' && typeof v === 'object') Object.assign(e.style, v);   // CSSOM is allowed by our CSP, style="" attributes are not
    else if (k === 'value') value = v;
    else if (k === 'checked' || k === 'selected' || k === 'indeterminate') e[k] = !!v;
    else if (v === true) e.setAttribute(k, '');
    else e.setAttribute(k, v);
  }
  for (const c of kids.flat(Infinity)) if (c != null && c !== false) e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  if (value !== undefined) e.value = value;   // after the options exist (selects)
  return e;
};
const safeParse = s => { try { return JSON.parse(s) || {}; } catch { return {}; } };

/* ---------- formatting ---------- */
const bytes = n => { n = Number(n) || 0; const u = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']; let i = 0; while (n >= 1024 && i < 5) { n /= 1024; i++; } return (i ? n.toFixed(n >= 100 ? 0 : 1) : n.toFixed(0)) + ' ' + u[i]; };
const dur = s => { s = Math.max(0, Number(s) || 0); const d = Math.floor(s / 86400), hr = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60); return d ? `${d}d ${hr}h` : hr ? `${hr}h ${m}m` : `${m}m ${Math.floor(s % 60)}s`; };
const when = t => t ? new Date(t * 1000).toLocaleString() : '';
const ago = t => { if (!t) return ''; const s = Math.max(0, Date.now() / 1000 - t); if (s < 45) return 'just now'; if (s < 3600) return Math.round(s / 60) + ' min ago'; if (s < 86400) return Math.round(s / 3600) + ' h ago'; if (s < 604800) return Math.round(s / 86400) + ' d ago'; return new Date(t * 1000).toLocaleDateString(); };
const GOOD = new Set(['ok', 'active', 'running', 'up', 'enabled', 'local', 'healthy', 'installed', 'on', 'allow', 'pass', 'done', 'online', 'listening']);
const BAD = new Set(['fail', 'failed', 'inactive', 'dead', 'exited', 'error', 'stopped', 'unknown', 'deny', 'critical', 'off', 'offline', 'blocked']);
const stateLevel = v => { v = String(v ?? '').toLowerCase(); return GOOD.has(v) ? 'ok' : BAD.has(v) ? 'bad' : ['not-installed', 'disabled', '-', 'none', 'paused', 'created'].includes(v) ? '' : 'warn'; };
const badge = (v, level, label) => h('span', { class: 'badge ' + (level ?? stateLevel(v)) }, label ?? v);
const tpl = (v, row) => typeof v === 'string' ? v.replace(/\$(\w+)/g, (_, k) => row[k] ?? '') : v;
const tplObj = (o, row) => Object.fromEntries(Object.entries(o || {}).map(([k, v]) => [k, tpl(v, row)]));

/* ---------- ANSI colours (console, logs, command output) ---------- */
const ANSI_RE = /\x1b\[([0-9;?]*)([A-Za-z])/g;
const XT16 = ['#000', '#c33', '#3a3', '#cc3', '#36c', '#c3c', '#3cc', '#ccc', '#666', '#f55', '#5f5', '#ff5', '#58f', '#f5f', '#5ff', '#fff'];
const xterm = n => { if (!(n >= 0 && n < 256)) return ''; if (n < 16) return XT16[n]; if (n >= 232) { const g = 8 + (n - 232) * 10; return `rgb(${g},${g},${g})`; } n -= 16; const c = v => v ? 55 + v * 40 : 0; return `rgb(${c(Math.floor(n / 36))},${c(Math.floor(n / 6) % 6)},${c(n % 6)})`; };
function ansi(text) {
  const frag = document.createDocumentFragment();
  const fresh = () => ({ fg: '', bg: '', b: 0, d: 0, i: 0, u: 0, fgc: '', bgc: '' });
  let st = fresh();
  const emit = s => {
    if (!s) return;
    const cls = [st.fg && 'a' + st.fg, st.bg && 'b' + st.bg, st.b && 'a1', st.d && 'a2', st.i && 'a3', st.u && 'a4'].filter(Boolean).join(' ');
    if (!cls && !st.fgc && !st.bgc) return frag.append(s);
    const sp = h('span', { class: cls }, s);
    if (st.fgc) sp.style.color = st.fgc;
    if (st.bgc) sp.style.background = st.bgc;
    frag.append(sp);
  };
  const sgr = p => {
    const c = (p === '' ? '0' : p).split(';').map(Number);
    for (let k = 0; k < c.length; k++) {
      const n = c[k];
      if (n === 0) st = fresh(); else if (n === 1) st.b = 1; else if (n === 2) st.d = 1; else if (n === 3) st.i = 1; else if (n === 4) st.u = 1;
      else if (n === 22) st.b = st.d = 0; else if (n === 23) st.i = 0; else if (n === 24) st.u = 0;
      else if ((n >= 30 && n <= 37) || (n >= 90 && n <= 97)) { st.fg = n; st.fgc = ''; }
      else if (n === 39) { st.fg = ''; st.fgc = ''; }
      else if (n >= 40 && n <= 44) { st.bg = n; st.bgc = ''; } else if (n === 49) { st.bg = ''; st.bgc = ''; }
      else if (n === 38 || n === 48) {
        let col = '';
        if (c[k + 1] === 5) { col = xterm(c[k + 2]); k += 2; } else if (c[k + 1] === 2) { col = `rgb(${c[k + 2] | 0},${c[k + 3] | 0},${c[k + 4] | 0})`; k += 4; }
        if (n === 38) { st.fg = ''; st.fgc = col; } else { st.bg = ''; st.bgc = col; }
      }
    }
  };
  const lines = String(text ?? '').split('\n');
  lines.forEach((raw, li) => {
    let line = raw.replace(/\x1b\][^\x07\x1b]*(\x07|\x1b\\)/g, '').replace(/\x1b[()][0-9A-B]/g, '');
    if (line.includes('\r')) line = line.split('\r').reverse().find(p => p) ?? '';   // progress bars redraw one line
    let last = 0, m;
    ANSI_RE.lastIndex = 0;
    while ((m = ANSI_RE.exec(line))) { emit(line.slice(last, m.index)); last = ANSI_RE.lastIndex; if (m[2] === 'm') sgr(m[1]); }
    emit(line.slice(last));
    if (li < lines.length - 1) frag.append('\n');
  });
  return frag;
}

/* ---------- scopes: timers and listeners that die with the page (or tab) that created them ---------- */
const bus = new EventTarget();
class Scope {
  constructor() { this.t = []; this.c = []; this.r = []; }
  interval(fn, ms) { const id = setInterval(() => { if (!document.hidden) fn(); }, ms); this.t.push(id); return id; }
  onLeave(f) { this.c.push(f); }
  reload(f) { this.r.push(f); }
  on(name, fn) { const l = e => fn(e.detail); bus.addEventListener(name, l); this.c.push(() => bus.removeEventListener(name, l)); }
  child() { const s = new Scope(); this.c.push(() => s.dispose()); this.r.push(() => s.refresh()); return s; }
  refresh() { this.r.forEach(f => { try { f(); } catch { /* a section failed to refresh: the others still do */ } }); }
  dispose() { this.t.forEach(clearInterval); this.c.splice(0).forEach(f => { try { f(); } catch { /* cleanup must not throw */ } }); this.t = []; this.r = []; }
}
let page = new Scope();
const emit = (name, detail) => bus.dispatchEvent(new CustomEvent(name, { detail }));

/* ---------- toasts, menus, dialogs ---------- */
function toast(msg, kind) {
  const err = kind === true || kind === 'err', warn = kind === 'warn', box = $('#toasts');
  const t = h('div', { class: 'toast' + (err ? ' err' : warn ? ' warn' : ''), role: err ? 'alert' : null },
    I(err ? 'alert-circle' : warn ? 'alert' : 'check-circle'), h('div', { class: 't' }, String(msg)),
    h('button', { type: 'button', class: 'icon-btn sm ghost', 'aria-label': 'Dismiss', onclick: () => t.remove() }, I('x')));
  box.append(t);
  while (box.children.length > 4) box.firstChild.remove();
  setTimeout(() => t.remove(), err ? 7500 : 3800);
}

let openMenu = null;
function closeMenu() { if (openMenu) { openMenu.off(); openMenu.el.remove(); openMenu = null; } }
function menu(at, items, opts = {}) {
  closeMenu();
  const el = h('div', { class: 'menu', role: 'menu' });
  for (const it of items) {
    if (!it) continue;
    if (it === '-' || it.sep) el.append(h('hr'));
    else if (it.header) el.append(h('div', { class: 'mh' }, it.header));
    else el.append(h('button', { type: 'button', role: 'menuitem', class: it.danger ? 'danger' : '', disabled: it.disabled, onclick: () => { closeMenu(); at.focus && at.focus(); it.onclick && it.onclick(); } }, it.icon ? I(it.icon) : null, it.label));
  }
  const host = $$('dialog[open]').pop() || document.body;   // inside a dialog the menu must live in the top layer too
  host.append(el);
  const r = at.getBoundingClientRect ? at.getBoundingClientRect() : { left: at.x, right: at.x, top: at.y, bottom: at.y };
  const w = el.offsetWidth, ht = el.offsetHeight;
  let x = opts.align === 'right' ? r.right - w : r.left;
  x = Math.max(8, Math.min(x, innerWidth - w - 8));
  let y = r.bottom + 4;
  if (y + ht > innerHeight - 8) y = Math.max(8, r.top - ht - 4);
  el.style.left = x + 'px'; el.style.top = y + 'px';
  const btns = () => $$('button:not(:disabled)', el);
  const key = e => {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); const a = at; closeMenu(); a.focus && a.focus(); }
    else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); const b = btns(), i = b.indexOf(document.activeElement); b[(i + (e.key === 'ArrowDown' ? 1 : -1) + b.length) % b.length]?.focus(); }
    else if (e.key === 'Tab') closeMenu();
  };
  const away = e => { if (!el.contains(e.target)) closeMenu(); };
  el.addEventListener('keydown', key);
  setTimeout(() => document.addEventListener('pointerdown', away, true));
  openMenu = { el, off: () => document.removeEventListener('pointerdown', away, true) };
  btns()[0]?.focus();
  return el;
}
const kebab = (items, label = 'More actions') => { const b = h('button', { type: 'button', class: 'icon-btn sm ghost', 'aria-label': label, 'aria-haspopup': 'menu', onclick: () => menu(b, typeof items === 'function' ? items() : items, { align: 'right' }) }, I('more')); return b; };

function modal({ title, body, actions = [], wide = false, icon, onclose, cls = '', drawer = false } = {}) {
  const dlg = h('dialog', { class: (drawer ? 'drawer' : 'modal') + (wide ? ' wide' : '') + (cls ? ' ' + cls : ''), 'aria-label': title });
  const bodyEl = h('div', { class: 'dlg-b' }, body);
  const api = { el: dlg, body: bodyEl, value: undefined, close(v) { api.value = v; if (dlg.open) dlg.close(); } };
  const foot = actions.length ? h('div', { class: 'dlg-f' }) : null;
  for (const a of actions) {
    const b = h('button', { type: 'button', class: [a.primary && 'primary', a.danger && (a.primary ? 'danger solid' : 'danger')].filter(Boolean).join(' '), onclick: async () => {
      if (!a.onclick) return api.close(a.value);
      b.disabled = true;
      try { const r = await a.onclick(api); if (r !== false && !a.keep) api.close(r); } catch (e) { toast(e.message, true); } finally { b.disabled = false; }
    } }, a.icon ? I(a.icon) : null, a.label);
    foot.append(b); a.el = b;
  }
  dlg.append(h('div', { class: 'dlg-h' }, icon ? I(icon, 'lg') : null, h('h2', {}, title || ''),
    h('button', { type: 'button', class: 'icon-btn sm ghost', 'aria-label': 'Close', onclick: () => api.close() }, I('x'))), bodyEl, foot);
  dlg.addEventListener('click', e => { if (e.target === dlg) api.close(); });
  dlg.addEventListener('close', () => { closeMenu(); onclose && onclose(api.value); dlg.remove(); });
  document.body.append(dlg);
  dlg.showModal();
  return api;
}
const drawer = o => modal({ ...o, drawer: true });
const confirmDlg = ({ title = 'Are you sure?', text, ok = 'Confirm', danger = false, icon } = {}) => new Promise(res => {
  modal({ title, icon: icon || (danger ? 'alert' : 'info'), body: text instanceof Node ? text : h('p', { class: 'muted' }, text || ''),
    actions: [{ label: 'Cancel', value: false }, { label: ok, primary: true, danger, value: true }], onclose: v => res(v === true) });
});
const promptDlg = ({ title = 'Enter a value', label, value = '', placeholder = '', ok = 'OK', type = 'text', help = '' } = {}) => new Promise(res => {
  const input = h('input', { type, value, placeholder, 'aria-label': label || title, autocomplete: 'off', spellcheck: 'false' });
  const m = modal({ title, body: h('div', { class: 'field' }, label ? h('label', {}, label, input) : input, help ? h('span', { class: 'help' }, help) : null),
    actions: [{ label: 'Cancel', value: null }, { label: ok, primary: true, onclick: () => input.value }], onclose: v => res(v == null ? null : String(v)) });
  input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); m.close(input.value); } });
  input.focus(); input.select();
});
function showText(title, text, opts = {}) {
  const pre = h('pre', { class: 'out mono', style: { margin: 0, maxHeight: '55vh', background: 'var(--term)', border: '1px solid var(--line)', borderRadius: '.6rem' } }, ansi(text));
  return modal({ title, icon: opts.icon, wide: true, body: pre, actions: [
    { label: 'Copy', icon: 'copy', keep: true, onclick: async () => { try { await navigator.clipboard.writeText(String(text).replace(/\x1b\[[0-9;?]*[A-Za-z]/g, '')); toast('Copied'); } catch { toast('Copy is not allowed in this browser', 'warn'); } return false; } },
    { label: 'Close', primary: true }] });
}
function showKv(title, pairs, icon) {
  return modal({ title, icon, wide: pairs.some(p => String(p[1]).length > 60), body: kv(pairs), actions: [{ label: 'Close', primary: true }] });
}
function saveBlob(blob, name) { const a = h('a', { href: URL.createObjectURL(blob), download: name }); document.body.append(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000); }

/* ---------- small building blocks ---------- */
const card = (title, ...kids) => h('section', { class: 'card' }, title ? h('div', { class: 'card-h' }, h('h2', {}, title)) : null, ...kids);
const kv = pairs => h('dl', { class: 'kv' }, pairs.flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v instanceof Node ? v : String(v ?? ''))]));
function meter(label, value, max, text) {
  const pct = max ? value / max * 100 : 0;
  return h('div', { class: 'meter' }, h('div', { class: 'row' }, h('span', {}, label), h('span', { class: 'muted' }, text)),
    h('progress', { max: 100, value: pct.toFixed(1), class: pct >= 90 ? 'bad' : pct >= 75 ? 'warn' : '', 'aria-label': label }));
}
const emptyState = (icon, title, text, ...actions) => h('div', { class: 'empty' }, I(icon), h('h3', {}, title), text ? h('p', {}, text) : null, actions.length ? h('div', { class: 'row' }, actions) : null);
const skeleton = (n = 3) => h('div', { class: 'col', 'aria-busy': 'true', 'aria-label': 'Loading' }, Array.from({ length: n }, (_, i) => h('div', { class: 'skel', style: { height: '2.2rem', width: i % 2 ? '85%' : '100%' } })));
const NAV_ICON = { services: 'layers', websites: 'globe', files: 'folder', cron: 'clock', firewall: 'flame', docker: 'box', databases: 'database', logs: 'file-text', processes: 'cpu', security: 'shield-check', backups: 'archive', desktop: 'monitor' };
const iconFor = e => (window.ICONS[e.icon] ? e.icon : NAV_ICON[e.name] || 'box');

/* ---------- API ---------- */
const S = { me: null, EXT: [], current: 'dashboard', sub: '', feed: null, running: 0, started: false };
async function req(url, method = 'GET', params = {}) {
  const opt = { method, headers: {}, credentials: 'same-origin' };
  if (method === 'GET') {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== '').map(([k, v]) => [k, typeof v === 'object' ? JSON.stringify(v) : v])).toString();
    if (q) url += (url.includes('?') ? '&' : '?') + q;
  } else { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(params); }
  let r;
  try { r = await fetch(url, opt); } catch { throw new Error('Cannot reach the panel. Is it still running?'); }
  if (r.status === 401 && !url.startsWith('/api/auth/')) { signedOut('Your session ended. Sign in again.'); throw new Error('Session ended: sign in again'); }
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).error || m; } catch { /* not json */ } throw new Error(m); }
  return (r.headers.get('Content-Type') || '').includes('json') ? r.json() : r.blob();
}
const call = (ext, route, params, method) => req(`/api/ext/${ext}/${route}`, method || 'GET', params);
const post = (ext, route, params) => req(`/api/ext/${ext}/${route}`, 'POST', params);

const scripts = {};
const loadScript = src => scripts[src] || (scripts[src] = new Promise((ok, no) => document.head.append(h('script', { src, onload: ok, onerror: () => { delete scripts[src]; no(new Error('Could not load ' + src)); } }))));
const loadCss = href => { if (!$(`link[href="${href}"]`)) document.head.append(h('link', { rel: 'stylesheet', href })); };
async function loadModule(name) { if (!(window.ASTRA_UI && window.ASTRA_UI[name])) await loadScript(`/ui/${name}.js`); return window.ASTRA_UI[name]; }

/* ---------- jobs, console ---------- */
const doneSeen = new Set();
function jobFinished(j) { if (doneSeen.has(j.id)) return; doneSeen.add(j.id); emit('job:done', j); pollFeed(); }
async function openConsole(opts = {}) {
  try { const m = await loadModule('console'); m.open(opts); } catch (e) { toast(e.message, true); }
}
/** Show a background job (install, update, backup...) in the console drawer. */
const watchJob = (id, title) => openConsole({ job: id, title });
function setRunning(n) {
  S.running = n;
  const b = $('#tb-console .badge-dot');
  if (b) { b.textContent = n; b.hidden = !n; }
}
async function pollJobs() {
  if (document.hidden || !S.started) return;
  try {
    const r = await req('/api/jobs');
    setRunning(r.running);
    S.jobs = r.jobs;
    const live = new Set(r.jobs.filter(j => j.state === 'running').map(j => j.id));
    for (const id of [...(S.liveJobs || [])]) if (!live.has(id)) { const j = r.jobs.find(x => x.id === id); if (j && j.kind !== 'console') jobFinished(j); }
    S.liveJobs = live;
  } catch { /* offline: try again next tick */ }
}

/* ---------- notifications ---------- */
const SEV_ICON = { critical: 'alert-circle', warning: 'alert', info: 'info', ok: 'check-circle' };
const CAT_NAV = { security: 'security', services: 'services', websites: 'websites', backups: 'backups', system: 'dashboard' };
function paintBell() {
  const f = S.feed, b = $('#tb-bell .badge-dot');
  if (!b || !f) return;
  const n = f.attention || f.unread;
  b.textContent = n > 99 ? '99+' : n; b.hidden = !n;
  b.className = 'badge-dot' + (f.critical ? '' : f.attention ? ' warn' : ' ac');
  $('#tb-bell').setAttribute('aria-label', n ? `Notifications: ${f.attention} need attention, ${f.unread} unread` : 'Notifications: nothing new');
  const by = {};
  for (const i of f.items) if (!i.read && (i.sev === 'critical' || i.sev === 'warning')) { const t = CAT_NAV[i.cat]; if (t) by[t] = (by[t] || 0) + 1; }
  $$('#nav .nav-item').forEach(el => {
    el.querySelector('.dot-badge')?.remove();
    const n2 = by[el.dataset.id];
    if (n2) el.append(h('span', { class: 'dot-badge', 'aria-label': n2 + ' need attention' }, n2));
  });
}
async function pollFeed() {
  if (document.hidden || !S.started) return;
  try {
    const f = await req('/api/notifications', 'GET', { limit: 200 });
    const fresh = S.feed ? f.items.filter(i => i.id > (S.maxSeen || 0) && !i.read && (i.sev === 'critical' || i.sev === 'warning')) : [];
    S.maxSeen = Math.max(S.maxSeen || 0, ...f.items.map(i => i.id), 0);
    S.feed = f; paintBell();
    if (fresh[0]) toast(fresh[0].title, fresh[0].sev === 'critical' ? true : 'warn');
    emit('feed', f);
  } catch { /* ignore */ }
}
async function openNotifications() {
  let cat = '';
  const list = h('div', { style: { overflow: 'auto', flex: 1 } }), chips = h('div', { class: 'nf-chips', role: 'toolbar', 'aria-label': 'Filter by category' });
  const m = drawer({ title: 'Notifications', icon: 'bell', body: [], actions: [] });
  Object.assign(m.body.style, { padding: '0', gap: '0', display: 'flex', flexDirection: 'column' });
  m.body.append(chips, list);
  m.el.append(h('div', { class: 'dlg-f' },
    h('button', { type: 'button', onclick: async () => { await req('/api/notifications/read', 'POST', {}); await pollFeed(); paint(); } }, I('check'), 'Mark all read'),
    h('button', { type: 'button', onclick: async () => { await req('/api/notifications/clear', 'POST', {}); await pollFeed(); paint(); } }, I('trash'), 'Clear read'),
    h('button', { type: 'button', class: 'primary', onclick: () => m.close() }, 'Close')));
  const item = i => h('div', { class: `nf ${i.sev}${i.read ? '' : ' unread'}`, tabindex: 0, role: 'button', 'aria-label': `${i.title}. ${i.read ? 'Read' : 'Unread, press to mark as read'}`,
    onclick: async () => { if (!i.read) { await req('/api/notifications/read', 'POST', { ids: [i.id] }); await pollFeed(); paint(); } },
    onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click(); } } },
    I(SEV_ICON[i.sev] || 'info'), h('div', { class: 'b' }, h('div', { class: 'ti' }, i.title), i.detail ? h('div', { class: 'de' }, i.detail) : null,
      h('div', { class: 'tm' }, `${S.feed.cats[i.cat] || i.cat} · ${ago(i.ts)}${i.n > 1 ? ' · happened ' + i.n + ' times' : ''}`)));
  function paint() {
    const f = S.feed; if (!f) return;
    chips.replaceChildren(h('button', { type: 'button', class: 'chip', 'aria-pressed': cat === '', onclick: () => { cat = ''; paint(); } }, 'All', h('span', { class: 'n' }, f.unread || '')),
      ...Object.entries(f.cats).filter(([k]) => f.items.some(i => i.cat === k)).map(([k, v]) => h('button', { type: 'button', class: 'chip', 'aria-pressed': cat === k, onclick: () => { cat = k; paint(); } }, v, f.by_cat[k] ? h('span', { class: 'n' }, f.by_cat[k]) : null)));
    const items = f.items.filter(i => !cat || i.cat === cat);
    const need = items.filter(i => !i.read && (i.sev === 'critical' || i.sev === 'warning')), rest = items.filter(i => !need.includes(i));
    const parts = [];
    if (!cat && f.away && f.away.lines.length) parts.push(h('div', { class: 'away', style: { margin: '0 1.1rem .6rem' } }, h('h3', {}, 'While you were away'), h('span', { class: 'muted' }, 'Since your last visit, ' + ago(f.away.since)),
      h('ul', {}, f.away.lines.map(l => h('li', {}, I(SEV_ICON[l.sev] || 'info'), l.text)))));
    if (need.length) parts.push(h('div', { class: 'nf-sec' }, `Needs attention (${need.length})`), ...need.map(item));
    if (rest.length) parts.push(h('div', { class: 'nf-sec' }, need.length ? `Everything else (${rest.length})` : `Recent (${rest.length})`), ...rest.slice(0, 40).map(item));
    if (!items.length) parts.push(emptyState('check-circle', 'All quiet', 'Sign-ins from new places, failed logins, stopped services and finished installs show up here. Repeats are merged into one line.'));
    list.replaceChildren(...parts);
  }
  list.replaceChildren(skeleton());
  await pollFeed(); paint();
}

/* ---------- command palette ---------- */
function palette() {
  const cmds = [
    ...navItems().map(n => ({ label: n.title, icon: n.icon, hint: 'Go to', run: () => go(n.id) })),
    { label: 'Open console', icon: 'terminal', hint: 'Ctrl+`', run: () => openConsole() },
    { label: 'Notifications', icon: 'bell', run: openNotifications },
    { label: 'Settings', icon: 'settings', hint: 'Go to', run: () => go('settings') },
    { label: 'Settings: account and password', icon: 'user', run: () => go('settings', 'account') },
    { label: 'Settings: two-step sign-in', icon: 'shield-check', run: () => go('settings', 'security') },
    { label: 'Toggle light / dark', icon: 'sun', run: () => { window.ASTRA_THEME.toggle(); paintTheme(); } },
    { label: 'Install software', icon: 'package', hint: 'Services', run: () => go('services', 'library') },
    { label: 'Sign out', icon: 'log-out', run: signOutAsk },
  ];
  let idx = 0, shown = cmds;
  const input = h('input', { placeholder: 'Jump to a page or run a command…', 'aria-label': 'Search commands', autocomplete: 'off' }), list = h('div', { class: 'pal-list', role: 'listbox' });
  const dlg = h('dialog', { class: 'palette', 'aria-label': 'Command palette' }, h('div', { class: 'pal-in' }, I('search'), input, h('kbd', {}, 'Esc')), list);
  const paint = () => list.replaceChildren(...shown.map((c, i) => h('button', { type: 'button', role: 'option', 'aria-selected': i === idx, onclick: () => run(c), onmousemove: () => { if (idx !== i) { idx = i; paint(); } } }, I(c.icon), c.label, c.hint ? h('span', { class: 'hint' }, c.hint) : null)));
  const run = c => { dlg.close(); c.run(); };
  input.addEventListener('input', () => { const q = input.value.toLowerCase(); shown = cmds.filter(c => c.label.toLowerCase().includes(q)); idx = 0; paint(); });
  input.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); idx = Math.min(idx + 1, shown.length - 1); paint(); list.children[idx]?.scrollIntoView({ block: 'nearest' }); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); idx = Math.max(idx - 1, 0); paint(); list.children[idx]?.scrollIntoView({ block: 'nearest' }); }
    else if (e.key === 'Enter' && shown[idx]) { e.preventDefault(); run(shown[idx]); }
  });
  dlg.addEventListener('click', e => { if (e.target === dlg) dlg.close(); });
  dlg.addEventListener('close', () => dlg.remove());
  document.body.append(dlg); paint(); dlg.showModal(); input.focus();
}

/* ---------- navigation ---------- */
const navItems = () => [{ id: 'dashboard', title: 'Dashboard', icon: 'dashboard', group: 'Overview' },
  ...[...S.EXT].sort((a, b) => a.order - b.order || a.title.localeCompare(b.title)).map(e => ({ id: e.name, title: e.title, icon: iconFor(e), group: e.group || 'Server', ext: e }))];
function buildNav() {
  const nav = $('#nav'); nav.replaceChildren();
  let group = null;
  for (const n of navItems()) {
    if (n.group !== group) { group = n.group; nav.append(h('div', { class: 'nav-label' }, group)); }
    nav.append(h('button', { type: 'button', class: 'nav-item' + (n.ext && !n.ext.available ? ' off' : ''), 'data-id': n.id, title: n.title,
      'aria-current': n.id === S.current ? 'page' : null, onclick: () => go(n.id) }, I(n.icon), h('span', { class: 'lbl' }, n.title)));
  }
  paintBell();
}
const parseHash = () => { const [id, sub] = decodeURIComponent(location.hash.slice(1)).split('/'); return { id: id || 'dashboard', sub: sub || '' }; };
function go(id, sub) { const next = sub ? id + '/' + sub : id; if (location.hash.slice(1) === next) route(); else location.hash = next; }
function route() {
  const { id, sub } = parseHash();
  S.current = id === 'settings' || id === 'dashboard' || S.EXT.some(e => e.name === id) ? id : 'dashboard';
  S.sub = sub;
  $('#app').classList.remove('nav-open');
  render();
}
const pageHead = (icon, title, desc, ...actions) => h('header', { class: 'page-head' }, h('span', { class: 'ph-icon' }, I(icon, 'lg')),
  h('div', { class: 'grow' }, h('h1', {}, title), desc ? h('p', {}, desc) : null), actions.length ? h('div', { class: 'row' }, actions) : null);

function render() {
  page.dispose(); page = new Scope();
  const id = S.current, e = S.EXT.find(x => x.name === id);
  const title = id === 'dashboard' ? 'Dashboard' : id === 'settings' ? 'Settings' : e.title;
  $$('#nav .nav-item').forEach(b => b.setAttribute('aria-current', b.dataset.id === id ? 'page' : 'false'));
  $('#crumb').replaceChildren(title, ...(S.sub && id !== 'dashboard' ? [h('span', { class: 'muted' }, ' / ' + S.sub)] : []));
  document.title = title + ' · astra';
  const view = h('div', { class: 'page' });
  $('#main').replaceChildren(view); $('#main').scrollTop = 0;
  if (id === 'dashboard') { view.append(pageHead('dashboard', 'Dashboard', S.me ? `${S.me.os === 'windows' ? 'Windows' : 'Linux'} server overview, updated every few seconds.` : '')); dashboard(view, page); }
  else if (id === 'settings') loadModule('settings').then(m => m(view, ASTRA)).catch(x => view.append(card('Settings', h('p', { class: 'bad', role: 'alert' }, x.message))));
  else { view.append(pageHead(iconFor(e), e.title, e.description, h('button', { type: 'button', class: 'ghost', 'aria-label': 'Refresh this page', onclick: () => page.refresh() }, I('refresh'), 'Refresh'))); extView(view, e, page); }
}

async function extView(view, e, scope = page) {
  if (e.ui) {
    try { const f = await loadModule(e.ui); f(view, e, ASTRA); } catch (x) { view.append(h('p', { class: 'bad', role: 'alert' }, x.message)); }
    return;
  }
  if (!e.available) view.append(h('div', { class: 'notice warn' }, I('alert'), h('div', {}, h('h3', {}, 'Not available on this server'), h('p', {}, 'Missing: ' + e.missing.join(', ') + '. Install it, then reload the page.'))));
  const secs = e.sections || [];
  if (!secs.length) return view.append(emptyState('box', 'Nothing to show yet', 'This extension has no sections.'));
  for (const s of secs) view.append(renderSection(e.name, s, { scope, ext: e }));
}
function renderSection(extName, sec, ctx) {
  const f = ASTRA.sections[sec.type];
  if (!f) return h('div', { class: 'notice warn' }, I('alert'), h('div', {}, h('h3', {}, 'Unknown section type: ' + sec.type)));
  try { return f(extName, sec, ctx); } catch (x) { return h('div', { class: 'notice bad' }, I('alert-circle'), h('div', {}, h('h3', {}, 'This section failed to draw'), h('p', {}, x.message))); }
}

/* ---------- dashboard ---------- */
function chart(canvas, series, max) {
  const dpr = window.devicePixelRatio || 1, w = canvas.clientWidth || 600, ht = canvas.clientHeight || 84;
  if (canvas.width !== Math.round(w * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(ht * dpr); }
  const c = canvas.getContext('2d'), cs = getComputedStyle(document.documentElement);
  c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, w, ht);
  c.strokeStyle = cs.getPropertyValue('--bd'); c.globalAlpha = .25; c.lineWidth = 1;
  for (let i = 1; i < 4; i++) { c.beginPath(); c.moveTo(0, ht * i / 4); c.lineTo(w, ht * i / 4); c.stroke(); }
  c.globalAlpha = 1;
  for (const s of series) {
    const col = cs.getPropertyValue(s.color).trim(), pts = s.data.map((v, i) => [i / Math.max(s.data.length - 1, 1) * w, ht - 3 - Math.min(v, max) / max * (ht - 8)]);
    if (pts.length < 2) continue;
    c.beginPath(); pts.forEach(([x, y], i) => i ? c.lineTo(x, y) : c.moveTo(x, y));
    c.strokeStyle = col; c.lineWidth = 2; c.lineJoin = 'round'; c.stroke();
    c.lineTo(w, ht); c.lineTo(0, ht); c.closePath(); c.fillStyle = col; c.globalAlpha = .12; c.fill(); c.globalAlpha = 1;
  }
}
function dashboard(view, scope = page) {
  const cv = label => h('canvas', { class: 'spark', role: 'img', 'aria-label': label });
  const cCpu = cv('CPU and memory history'), cNet = cv('Network history');
  const awayBox = h('div'), stats = h('div', { class: 'stats' }, skeleton(1)), grid = h('div', { class: 'grid' });
  view.append(awayBox, stats, grid);
  const stat = (k, v, s, level, icon) => h('div', { class: 'stat ' + (level || '') }, h('div', { class: 'k' }, I(icon), k), h('div', { class: 'v' }, v), h('div', { class: 's' }, s || '\u00a0'));
  const lv = p => p >= 90 ? 'bad' : p >= 75 ? 'warn' : '';
  const load = async () => {
    try {
      const [d, hist, al] = await Promise.all([req('/api/dashboard'), req('/api/history'), req('/api/alerts')]);
      const now = d.now || { cpu: 0, mem: 0, rx: 0, tx: 0 }, Sm = hist.samples, disk = d.disks[0], dp = disk ? disk.used / disk.total * 100 : 0;
      stats.replaceChildren(stat('CPU', now.cpu.toFixed(0) + '%', d.cpus + ' cores', lv(now.cpu), 'cpu'),
        stat('Memory', now.mem.toFixed(0) + '%', bytes(d.mem.used) + ' of ' + bytes(d.mem.total), lv(now.mem), 'layers'),
        stat('Disk ' + (disk ? disk.mount : ''), dp.toFixed(0) + '%', disk ? bytes(disk.total - disk.used) + ' free' : '', lv(dp), 'hard-drive'),
        stat('Network', '↓ ' + bytes(now.rx) + '/s', '↑ ' + bytes(now.tx) + '/s', '', 'activity'),
        stat('Uptime', dur(d.uptime), d.load ? 'load ' + d.load.map(x => x.toFixed(2)).join(' ') : d.hostname, '', 'clock'));
      grid.replaceChildren(
        h('section', { class: 'card' }, h('div', { class: 'card-h' }, h('h2', {}, 'CPU and memory'), h('span', { class: 'sub' }, 'last few minutes')), cCpu,
          h('div', { class: 'row muted', style: { fontSize: '.8rem', marginTop: '.4rem' } }, h('span', {}, '● CPU'), h('span', { class: 'ok' }, '● Memory'))),
        h('section', { class: 'card' }, h('div', { class: 'card-h' }, h('h2', {}, 'Network'), h('span', { class: 'sub' }, '↓ in  ↑ out')), cNet),
        card('Storage', ...d.disks.map(k => meter(k.mount, k.used, k.total, bytes(k.used) + ' / ' + bytes(k.total))), d.mem.swap_total ? meter('Swap', d.mem.swap_used, d.mem.swap_total, bytes(d.mem.swap_used) + ' / ' + bytes(d.mem.swap_total)) : null),
        card('System', kv([['Host', d.hostname], ['OS', d.os], [d.platform === 'windows' ? 'Build' : 'Kernel', d.kernel + ' ' + d.arch], ['Panel', S.me ? 'astra ' + S.me.version : ''], ['Signed in as', S.me ? S.me.user : '']])),
        h('section', { class: 'card flush' }, h('div', { class: 'card-h' }, h('h2', {}, 'Top processes'), h('button', { type: 'button', class: 'sm', onclick: () => go('processes') }, 'All processes', I('chevron-right'))),
          h('div', { class: 'tbl-wrap' }, h('table', { class: 'tbl' }, h('thead', {}, h('tr', {}, h('th', {}, 'Process'), h('th', { class: 'num' }, 'PID'), h('th', { class: 'num' }, 'Memory'))),
            h('tbody', {}, d.processes.map(p => h('tr', {}, h('td', { class: 'cell-main' }, p.name), h('td', { class: 'num' }, p.pid), h('td', { class: 'num' }, bytes(p.rss)))))))),
        card('Resource alerts', al.length ? h('div', { class: 'col' }, al.slice(-6).reverse().map(a => h('div', { class: 'row' }, badge(a.metric, a.value >= 97 ? 'bad' : 'warn', a.metric.toUpperCase()), `${a.value}% (limit ${a.limit}%)`, h('span', { class: 'muted' }, ago(a.t))))) : emptyState('check-circle', 'No alerts', 'CPU, memory and disk are within limits. Change limits in Settings → Alerts.')));
      chart(cCpu, [{ data: Sm.map(x => x.cpu), color: '--ac' }, { data: Sm.map(x => x.mem), color: '--ok' }], 100);
      const mx = Math.max(1024, ...Sm.map(x => Math.max(x.rx, x.tx)));
      chart(cNet, [{ data: Sm.map(x => x.rx), color: '--ok' }, { data: Sm.map(x => x.tx), color: '--warn' }], mx);
    } catch (e) { stats.replaceChildren(h('div', { class: 'notice bad' }, I('alert-circle'), h('div', {}, h('h3', {}, 'Could not load the dashboard'), h('p', {}, e.message)))); }
  };
  load(); scope.interval(load, 5000); scope.reload(load);
  const showAway = f => {
    if (!f || !f.away || !f.away.lines.length || sessionStorage.getItem('astra_away_seen')) return awayBox.replaceChildren();
    awayBox.replaceChildren(h('div', { class: 'away' }, h('div', { class: 'row' }, h('h3', { class: 'grow' }, 'While you were away'),
      h('button', { type: 'button', class: 'sm', onclick: () => openNotifications() }, 'Open notifications'),
      h('button', { type: 'button', class: 'icon-btn sm ghost', 'aria-label': 'Dismiss', onclick: () => { sessionStorage.setItem('astra_away_seen', '1'); awayBox.replaceChildren(); } }, I('x'))),
      h('span', { class: 'muted' }, 'Since your last visit ' + ago(f.away.since)), h('ul', {}, f.away.lines.map(l => h('li', {}, I(SEV_ICON[l.sev] || 'info'), l.text)))));
  };
  showAway(S.feed); scope.on('feed', showAway);
}

/* ---------- sign in / out ---------- */
function paintTheme() { const b = $('#tb-theme'); if (!b) return; const light = window.ASTRA_THEME.resolved() === 'daylight'; b.replaceChildren(I(light ? 'moon' : 'sun')); b.title = light ? 'Switch to dark mode' : 'Switch to light mode'; b.setAttribute('aria-label', b.title); }
function buildTopbar() {
  const mk = (id, icon, label, fn, badgeCls) => h('button', { type: 'button', id, class: 'icon-btn', title: label, 'aria-label': label, onclick: fn }, I(icon), badgeCls !== undefined ? h('span', { class: 'badge-dot ' + badgeCls, hidden: true }, '') : null);
  const bar = $('#tb-actions'); bar.replaceChildren(
    S.me && S.me.console ? mk('tb-console', 'terminal', 'Console (Ctrl+`)', () => openConsole(), 'ac') : null,
    mk('tb-bell', 'bell', 'Notifications', openNotifications, ''), h('span', { class: 'sep' }),
    mk('tb-theme', 'sun', 'Toggle light or dark', () => { window.ASTRA_THEME.toggle(); paintTheme(); }),
    mk('tb-settings', 'settings', 'Settings', () => go('settings')),
    mk('tb-logout', 'log-out', 'Sign out', signOutAsk));
  paintTheme();
}
async function signOutAsk() {
  if (await confirmDlg({ title: 'Sign out?', text: 'You will need your username and password to get back in. Running installs keep going in the background.', ok: 'Sign out', icon: 'log-out' })) {
    try { await req('/api/auth/logout', 'POST'); } catch { /* already out */ }
    signedOut();
  }
}
function signedOut(msg) {
  S.started = false; S.feed = null; S.maxSeen = 0; page.dispose(); closeMenu();
  (S.timers || []).forEach(clearInterval); S.timers = [];
  $$('dialog[open]').forEach(d => d.close());
  $('#console').hidden = true; $('#stage').classList.remove('console-open');
  $('#app').hidden = true; $('#login').hidden = false; $('#login-form').hidden = false; $('#mfa-form').hidden = true;
  $('#login-err').textContent = msg || ''; sessionStorage.removeItem('astra_away_seen');
  setTimeout(() => $('#user').focus(), 30);
}
async function start() {
  const [me, ext] = await Promise.all([req('/api/me'), req('/api/extensions')]);
  S.me = me; S.EXT = ext; S.started = true;
  $('#login').hidden = true; $('#app').hidden = false;
  $('#ver').textContent = 'v' + me.version;
  buildTopbar(); buildNav();
  S.paintRail = () => { const rail = window.ASTRA_THEME.prefs.sidebar === 'rail', b = $('#rail'); b.replaceChildren(I(rail ? 'chevrons-right' : 'chevrons-left')); b.title = rail ? 'Expand sidebar' : 'Collapse sidebar'; b.setAttribute('aria-label', b.title); };
  S.paintRail();
  const p = parseHash(); S.current = p.id; S.sub = p.sub; route();
  pollFeed(); pollJobs();
  (S.timers || []).forEach(clearInterval);
  S.timers = [setInterval(pollFeed, 30000), setInterval(pollJobs, 5000)];
}
async function boot() {
  for (const id of ['art-logo', 'form-logo', 'mfa-logo', 'side-logo']) $('#' + id).replaceChildren(I('logo'));
  $('#art-points').replaceChildren(...[['activity', 'Live CPU, memory, disk and network'], ['package', 'Install web servers, databases and tools in a click'], ['bell', 'A short list of what actually needs you'], ['terminal', 'A console that follows you around']].map(([i, t]) => h('li', {}, I(i), t)));
  $('#pw-eye').replaceChildren(I('eye'));
  $('#search').replaceChildren(I('search'), h('span', {}, 'Search or jump to…'), h('kbd', {}, 'Ctrl K'));
  $('#burger').replaceChildren(I('menu'));
  $('.skip').addEventListener('click', e => { e.preventDefault(); $('#main').focus(); });
  $('#burger').addEventListener('click', () => $('#app').classList.toggle('nav-open'));
  $('#scrim').addEventListener('click', () => $('#app').classList.remove('nav-open'));
  $('#search').addEventListener('click', palette);
  $('#rail').addEventListener('click', () => { window.ASTRA_THEME.set('sidebar', window.ASTRA_THEME.prefs.sidebar === 'rail' ? 'full' : 'rail'); S.paintRail && S.paintRail(); });
  $('#pw-eye').addEventListener('click', () => { const p = $('#pass'), show = p.type === 'password'; p.type = show ? 'text' : 'password'; $('#pw-eye').replaceChildren(I(show ? 'eye-off' : 'eye')); $('#pw-eye').setAttribute('aria-label', show ? 'Hide password' : 'Show password'); });
  window.addEventListener('hashchange', () => { if (S.started) route(); });
  document.addEventListener('keydown', e => {
    if (!S.started) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); if (!$('dialog.palette')) palette(); }
    else if (e.ctrlKey && e.key === '`' && S.me && S.me.console) { e.preventDefault(); openConsole({ toggle: true }); }
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden && S.started) { pollFeed(); pollJobs(); } });
  let challenge = '';
  const mfaUi = () => { const em = $('#mfa-method').value === 'email'; $('#mfa-send').hidden = !em; $('#mfa-help').textContent = em ? 'Press the button, then enter the code from your inbox.' : 'Enter the current code from your authenticator app.'; };
  $('#login-form').addEventListener('submit', async ev => {
    ev.preventDefault(); $('#login-err').textContent = ''; const btn = $('#login-go'); btn.disabled = true;
    try {
      const r = await req('/api/auth/login', 'POST', { username: $('#user').value.trim(), password: $('#pass').value });
      $('#pass').value = '';
      if (r.session) return await start();
      challenge = r.challenge;
      $('#mfa-method').replaceChildren(...r.mfa.map(m => h('option', { value: m }, m === 'totp' ? 'Authenticator app' : 'E-mail code')));
      mfaUi(); $('#login-form').hidden = true; $('#mfa-form').hidden = false; $('#mfa-code').focus();
    } catch (e) { $('#login-err').textContent = e.message; } finally { btn.disabled = false; }
  });
  $('#mfa-method').addEventListener('change', mfaUi);
  $('#mfa-send').addEventListener('click', async () => { try { await req('/api/auth/send', 'POST', { challenge }); toast('Code sent'); $('#mfa-code').focus(); } catch (e) { $('#mfa-err').textContent = e.message; } });
  $('#mfa-back').addEventListener('click', () => signedOut());
  $('#mfa-form').addEventListener('submit', async ev => {
    ev.preventDefault(); $('#mfa-err').textContent = '';
    try { await req('/api/auth/verify', 'POST', { challenge, method: $('#mfa-method').value, code: $('#mfa-code').value }); $('#mfa-code').value = ''; await start(); }
    catch (e) { $('#mfa-err').textContent = e.message; }
  });
  try {   // already signed in (cookie still valid)?  /api/auth/status never counts as a failed attempt
    const st = await req('/api/auth/status');
    if (st.signed_in) return await start();
  } catch { /* fall through to the sign-in form */ }
  $('#login').hidden = false; $('#user').focus();
}

/* ---------- public API (used by ui/*.js modules, extensions and the desktop) ---------- */
const ASTRA = {
  h, $, $$, I, req, call, post, card, kv, meter, badge, toast, showText, showKv, saveBlob, bytes, dur, when, ago, ansi, menu, kebab, modal, drawer,
  confirm: confirmDlg, prompt: promptDlg, emptyState, skeleton, pageHead, stateLevel, tpl, tplObj, renderSection, extView, dashboard, chart, safeParse,
  go, loadModule, loadScript, loadCss, openConsole, watchJob, openNotifications, emit, Scope, boot, bus, closeMenu,
  sections: {}, settingsTabs: [], state: S,
  get timers() { return page.t; }, onLeave: f => page.onLeave(f), get page() { return page; },
  get EXT() { return S.EXT; }, get me() { return S.me; },
  async refreshExtensions() { S.EXT = await req('/api/extensions'); buildNav(); },
  paintTheme,
};
window.ASTRA = ASTRA;
