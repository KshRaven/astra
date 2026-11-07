'use strict';
/* Declarative tab sections: stats, notice, help, table, form, text, kv, catalog, tabs. Extensions describe a page with
   these (see docs/EXTENSIONS.md); anything unusual gets its own ui/<name>.js module instead. */
(() => {
  const A = window.ASTRA, { h, I, call, post, toast, badge, bytes, ago, when, tpl, tplObj, card, kv, emptyState, skeleton, showText, showKv, saveBlob, watchJob, modal, menu, kebab, confirm: confirmDlg } = A;
  const S = A.state;

  /* ---------- shared: fields, result handling, loading ---------- */
  function field(f) {
    const id = 'f' + Math.random().toString(36).slice(2, 8), t = f.type || 'text';
    let input;
    const opts = (f.options || []).map(o => typeof o === 'object' ? o : { value: o, label: o });
    if (t === 'select') input = h('select', { id, name: f.name, value: f.value ?? opts[0]?.value }, opts.map(o => h('option', { value: o.value }, o.label)));
    else if (t === 'textarea') input = h('textarea', { id, name: f.name, rows: f.rows || 5, placeholder: f.placeholder, spellcheck: 'false' }, f.value ?? '');
    else if (t === 'checkbox') input = h('input', { id, name: f.name, type: 'checkbox', checked: !!f.value });
    else input = h('input', { id, name: f.name, type: t, value: f.value ?? '', placeholder: f.placeholder, required: f.required, min: f.min, max: f.max, autocomplete: t === 'password' ? 'new-password' : 'off', spellcheck: 'false' });
    const help = f.help ? h('span', { class: 'help' }, f.help) : null;
    const el = t === 'checkbox' ? h('div', { class: 'field check' + (f.wide ? ' wide' : '') }, input, h('label', { for: id }, f.label, help ? h('span', { class: 'help' }, ' ' + f.help) : null))
      : h('div', { class: 'field' + (f.wide || t === 'textarea' ? ' wide' : '') }, h('label', { for: id }, f.label + (f.required ? ' *' : '')), input, help);
    const get = () => t === 'checkbox' ? input.checked : t === 'number' ? (input.value === '' ? '' : Number(input.value)) : input.value;
    return { el, input, get, f };
  }
  const fieldsGrid = fs => { const built = fs.map(field); return { el: h('div', { class: 'form-grid' }, built.map(b => b.el)), values: () => Object.fromEntries(built.map(b => [b.f.name, b.get()])), built }; };
  function fieldsDialog({ title, fields, ok = 'Save', text, icon, danger }) {
    return new Promise(res => {
      const g = fieldsGrid(fields);
      const m = modal({ title, icon, body: [text ? h('p', { class: 'muted' }, text) : null, g.el], actions: [{ label: 'Cancel', value: null }, { label: ok, primary: true, danger, onclick: () => {
        for (const b of g.built) if (b.f.required && (b.get() === '' || b.get() == null)) { b.input.focus(); throw new Error(b.f.label + ' is required'); }
        return g.values();
      } }], onclose: v => res(v && typeof v === 'object' ? v : null) });
      g.built[0]?.input.focus();
      m.el.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.tagName === 'INPUT') { e.preventDefault(); m.el.querySelector('.dlg-f .primary')?.click(); } });
    });
  }
  A.fields = { build: field, grid: fieldsGrid, dialog: fieldsDialog };

  /** Show whatever a route returned: a background job, text, or just a success note. */
  function handle(res, title, quiet) {
    if (res && res.job) { watchJob(res.job, res.title || title); return res; }
    if (res && Array.isArray(res.kv)) { showKv(res.title || title || 'Details', res.kv); return res; }
    if (res && typeof res.text === 'string' && res.text) { showText(title || 'Result', res.text); return res; }
    if (!quiet) toast((res && res.message) || 'Done');
    return res;
  }
  A.handle = handle;

  async function runAction(ext, act, row, done) {
    const params = tplObj(act.params, row);
    if (act.form) {
      const v = await fieldsDialog({ title: tpl(act.label, row), fields: act.form.map(f => ({ ...f, value: f.value != null ? tpl(f.value, row) : f.value })), ok: act.ok || act.label, danger: act.danger });
      if (!v) return;
      Object.assign(params, v);
    }
    if (act.confirm && !(await confirmDlg({ title: tpl(act.label, row), text: tpl(act.confirm, row), ok: act.label, danger: !!act.danger }))) return;
    const method = act.method || 'POST';
    if (act.download) { const b = await call(ext, act.route, params, 'GET'); saveBlob(b, tpl(act.filename || params.name || 'download', row)); return; }
    const res = await call(ext, act.route, params, method);
    handle(res, tpl(act.label, row), !!act.quiet);
    done && done(res);
  }
  A.runAction = runAction;
  const matches = (act, row) => (!act.if || Object.entries(act.if).every(([k, vs]) => [].concat(vs).map(String).includes(String(row[k])))) && (!act.ifnot || !Object.entries(act.ifnot).some(([k, vs]) => [].concat(vs).map(String).includes(String(row[k]))));

  /** Fetch + paint with a skeleton first, an inline error with Retry, and optional polling. */
  function loader(box, fetcher, paint, scope, every) {
    let first = true, busy = false;
    const run = async () => {
      if (busy) return; busy = true;
      if (first) box.replaceChildren(skeleton(3));
      try { const d = await fetcher(); paint(d, first); first = false; }
      catch (e) { if (first || !box.isConnected) box.replaceChildren(h('div', { class: 'notice bad' }, I('alert-circle'), h('div', {}, h('h3', {}, 'Could not load this'), h('p', {}, e.message), h('div', { class: 'row' }, h('button', { type: 'button', class: 'sm', onclick: () => { first = true; run(); } }, I('refresh'), 'Try again'))))); }
      finally { busy = false; }
    };
    run(); scope.reload(run); if (every) scope.interval(run, every * 1000);
    return run;
  }

  /* ---------- formatting ---------- */
  const FMT = {
    state: v => badge(v), bytes: v => bytes(v), time: v => when(v), ago: v => ago(v), num: v => Number(v).toLocaleString(), pct: v => (Number(v) || 0).toFixed(1) + '%',
    mono: v => h('span', { class: 'mono' }, String(v ?? '')), code: v => h('code', {}, String(v ?? '')), bool: v => badge(v ? 'yes' : 'no', v ? 'ok' : '', v ? 'Yes' : 'No'),
    list: v => Array.isArray(v) ? v.join(', ') : String(v ?? ''), level: v => badge(v, v === 'critical' || v === 'high' ? 'bad' : v === 'warning' || v === 'medium' ? 'warn' : v === 'ok' || v === 'good' ? 'ok' : ''),
    dur: v => A.dur(v),
  };
  const col = c => Array.isArray(c) ? { label: c[0], key: c[1], fmt: c[2] } : c;
  const cell = (c, row) => { const v = row[c.key]; if (v == null || v === '') return c.fmt === 'state' ? badge('-') : h('span', { class: 'muted' }, '–'); const f = FMT[c.fmt]; return f ? f(v, row) : String(v); };
  const numeric = c => ['bytes', 'num', 'pct', 'dur'].includes(c.fmt) || c.num;

  /* ---------- sections ---------- */
  const secs = A.sections;

  secs.stats = (ext, s, ctx) => {
    const box = h('div', { class: 'stats' });
    const paint = items => box.replaceChildren(...items.map(i => h('div', { class: 'stat ' + (i.level || '') }, h('div', { class: 'k' }, i.icon ? I(i.icon) : null, i.k), h('div', { class: 'v' }, String(i.v)), h('div', { class: 's' }, i.s || '\u00a0'))));
    if (s.items) paint(s.items); else loader(box, () => call(ext, s.source, s.params), d => paint(d.items || d), ctx.scope, s.refresh);
    return box;
  };

  secs.notice = (ext, s) => {
    const acts = (s.actions || []).map(a => h('button', { type: 'button', class: a.primary ? 'primary sm' : 'sm', onclick: async () => { try { if (a.go) return A.go(a.go, a.sub); await runAction(ext, a, {}); } catch (e) { toast(e.message, true); } } }, a.icon ? I(a.icon) : null, a.label));
    return h('div', { class: 'notice ' + (s.level || '') }, I(s.icon || (s.level === 'bad' ? 'alert-circle' : s.level === 'warn' ? 'alert' : s.level === 'ok' ? 'check-circle' : 'info')), h('div', {}, s.title ? h('h3', {}, s.title) : null, s.text ? h('p', {}, s.text) : null, acts.length ? h('div', { class: 'row' }, acts) : null));
  };

  secs.help = (ext, s) => {
    const key = 'astra_help_' + ext + '_' + (s.id || s.title);
    let closed = false; try { closed = localStorage.getItem(key) === '0'; } catch { /* no storage */ }
    const body = h('div', {}, s.text ? h('p', { class: 'muted' }, s.text) : null,
      s.steps ? h('ol', { class: 'help-steps' }, s.steps.map(x => h('li', {}, Array.isArray(x) ? [h('b', {}, x[0] + ' '), x[1]] : x))) : null,
      s.example ? h('div', { class: 'example' }, h('b', {}, s.example.title || 'Example'), s.example.text, s.example.code ? h('pre', { class: 'out', style: { marginTop: '.5rem' } }, s.example.code) : null) : null);
    const tg = h('button', { type: 'button', class: 'ghost sm', 'aria-expanded': !closed, onclick: () => { closed = !closed; body.hidden = closed; tg.replaceChildren(I(closed ? 'chevron-down' : 'chevron-up'), closed ? 'Show' : 'Hide'); tg.setAttribute('aria-expanded', !closed); try { localStorage.setItem(key, closed ? '0' : '1'); } catch { /* ok */ } } }, I(closed ? 'chevron-down' : 'chevron-up'), closed ? 'Show' : 'Hide');
    body.hidden = closed;
    return h('section', { class: 'card' }, h('div', { class: 'card-h' }, I(s.icon || 'help-circle'), h('h2', {}, s.title || 'What is this?'), tg), body);
  };

  secs.kv = (ext, s, ctx) => {
    const body = h('div'), box = card(s.title, s.desc ? h('p', { class: 'card-d' }, s.desc) : null, body);
    const paint = d => { const pairs = Array.isArray(d) ? d : d.pairs || d.kv || Object.entries(d); body.replaceChildren(pairs.length ? kv(pairs) : emptyState('info', 'Nothing to show', s.empty || '')); };
    if (s.pairs) paint(s.pairs); else loader(body, () => call(ext, s.source, s.params), paint, ctx.scope, s.refresh);
    return box;
  };

  secs.text = (ext, s, ctx) => {
    const pre = h('pre', { class: 'out mono' }); if (s.height) pre.style.maxHeight = s.height;
    const body = h('div', {}, pre), tools = [];
    let last = '';
    tools.push(h('button', { type: 'button', class: 'ghost sm', onclick: async () => { try { await navigator.clipboard.writeText(last); toast('Copied'); } catch { toast('Copy is not allowed in this browser', 'warn'); } } }, I('copy'), 'Copy'));
    const sec = h('section', { class: 'card' }, h('div', { class: 'card-h' }, h('h2', {}, s.title || ''), tools), s.desc ? h('p', { class: 'card-d' }, s.desc) : null, body);
    loader(body, () => call(ext, s.source, s.params), (d, first) => { last = String(d.text ?? ''); const atEnd = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 8; pre.replaceChildren(last ? A.ansi(last) : h('span', { class: 'muted' }, s.empty || '(nothing to show)')); if (first) body.replaceChildren(pre); if (atEnd) pre.scrollTop = pre.scrollHeight; }, ctx.scope, s.refresh);
    return sec;
  };

  secs.form = (ext, s, ctx) => {
    const g = fieldsGrid(s.fields || []), out = h('div');
    const btn = h('button', { type: 'submit', class: s.danger ? 'danger' : 'primary' }, s.icon ? I(s.icon) : null, s.submit || 'Save');
    const f = h('form', { novalidate: true, onsubmit: async ev => {
      ev.preventDefault();
      for (const b of g.built) if (b.f.required && (b.get() === '' || b.get() == null)) { b.input.focus(); return toast(b.f.label + ' is required', true); }
      if (s.confirm && !(await confirmDlg({ title: s.title || 'Please confirm', text: s.confirm, ok: s.submit || 'Confirm', danger: !!s.danger }))) return;
      btn.disabled = true;
      try {
        const res = await call(ext, s.route, g.values(), s.method || 'POST');
        if (res && res.text && !s.dialog) out.replaceChildren(h('pre', { class: 'out mono', style: { marginTop: '.8rem' } }, A.ansi(res.text))); else handle(res, s.title);
        if (s.reset !== false && !(res && res.keep)) f.reset();
        ctx.scope.refresh();
      } catch (e) { toast(e.message, true); } finally { btn.disabled = false; }
    } }, g.el, h('div', { class: 'form-foot' }, btn, s.note ? h('span', { class: 'help' }, s.note) : null), out);
    return card(s.title, s.desc ? h('p', { class: 'card-d' }, s.desc) : null, f);
  };

  secs.table = (ext, s, ctx) => {
    const cols = (s.columns || []).map(col), acts = s.actions || [];
    let rows = [], q = '', sort = s.sort ? { key: s.sort[0], dir: s.sort[1] || 'asc' } : null, limit = s.limit || 200;
    const body = h('tbody'), head = h('thead'), foot = h('div', { class: 'tfoot', hidden: true }), wrap = h('div', { class: 'tbl-wrap' });
    if (s.maxHeight) wrap.style.maxHeight = s.maxHeight;
    const table = h('table', { class: 'tbl' }, head, body); wrap.append(table);
    const search = h('input', { type: 'search', placeholder: s.searchHint || 'Filter…', 'aria-label': 'Filter ' + (s.title || 'rows'), oninput: e => { q = e.target.value.toLowerCase(); paintRows(); } });
    const bar = h('div', { class: 'tbar' }, h('div', { class: 'find', hidden: s.search === false }, I('search'), search), h('span', { class: 'grow' }),
      ...(s.buttons || []).map(b => h('button', { type: 'button', class: b.primary ? 'primary sm' : 'sm', onclick: async () => { try { await runAction(ext, b, {}, () => ctx.scope.refresh()); } catch (e) { toast(e.message, true); } } }, b.icon ? I(b.icon) : null, b.label)));
    const area = h('div');
    const paintHead = () => head.replaceChildren(h('tr', {}, cols.map(c => {
      const on = sort && sort.key === c.key;
      return h('th', { class: (numeric(c) ? 'num ' : '') + 'sortable', 'aria-sort': on ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none', tabindex: 0, onclick: () => { sort = { key: c.key, dir: on && sort.dir === 'asc' ? 'desc' : 'asc' }; paintHead(); paintRows(); }, onkeydown: e => { if (e.key === 'Enter') e.currentTarget.click(); } }, c.label, on ? I(sort.dir === 'asc' ? 'sort-asc' : 'sort-desc') : null);
    }), acts.length ? h('th', { class: 'act' }, '') : null));
    const actCell = row => {
      const mine = acts.filter(a => matches(a, row));
      if (!mine.length) return h('td', { class: 'act' });
      const go = a => async () => { try { await runAction(ext, a, row, () => ctx.scope.refresh()); } catch (e) { toast(e.message, true); } };
      const main = mine.filter(a => !a.danger && !a.more).slice(0, mine.length > 3 ? 1 : 2), rest = mine.filter(a => !main.includes(a));
      return h('td', { class: 'act' }, h('div', { class: 'row' }, main.map(a => h('button', { type: 'button', class: 'sm', onclick: go(a) }, a.icon ? I(a.icon) : null, tpl(a.label, row))),
        rest.length ? kebab(() => rest.map(a => ({ label: tpl(a.label, row), icon: a.icon, danger: a.danger, onclick: go(a) }))) : null));
    };
    function paintRows() {
      let r = rows;
      if (q) r = r.filter(x => cols.some(c => String(x[c.key] ?? '').toLowerCase().includes(q)) || Object.values(x).some(v => typeof v === 'string' && v.toLowerCase().includes(q)));
      if (sort) r = [...r].sort((a, b) => { const x = a[sort.key], y = b[sort.key]; const d = typeof x === 'number' && typeof y === 'number' ? x - y : String(x ?? '').localeCompare(String(y ?? ''), undefined, { numeric: true }); return sort.dir === 'asc' ? d : -d; });
      const shown = r.slice(0, limit);
      body.replaceChildren(...shown.map(row => h('tr', {}, cols.map((c, i) => h('td', { class: (numeric(c) ? 'num ' : '') + (c.main || i === 0 && s.firstBold !== false ? 'cell-main' : '') }, cell(c, row))), acts.length ? actCell(row) : null)));
      foot.hidden = rows.length <= 8 && r.length === rows.length; foot.replaceChildren(`${r.length} of ${rows.length}`, r.length > limit ? [' · ', h('button', { type: 'button', class: 'sm ghost', onclick: () => { limit += 200; paintRows(); } }, 'Show more')] : '');
      table.hidden = !shown.length; if (rows.length && !shown.length) body.replaceChildren(), area.dataset.none = '1';
    }
    const empty = s.empty || {};
    const sec = h('section', { class: 'card flush' }, h('div', { class: 'card-h' }, h('h2', {}, s.title || ''), s.sub ? h('span', { class: 'sub' }, s.sub) : null), s.desc ? h('p', { class: 'card-d', style: { padding: '0 var(--pad)' } }, s.desc) : null, bar, area, foot);
    paintHead();
    loader(area, () => call(ext, s.source, s.params), d => {
      rows = Array.isArray(d) ? d : d.rows || [];
      bar.querySelector('.find').hidden = s.search === false || rows.length <= 8 && s.search !== true;
      if (!rows.length) { area.replaceChildren(emptyState(empty.icon || 'info', empty.title || 'Nothing here yet', empty.text || '', ...(empty.actions || []).map(a => h('button', { type: 'button', class: a.primary ? 'primary' : '', onclick: async () => { try { if (a.go) A.go(a.go, a.sub); else await runAction(ext, a, {}, () => ctx.scope.refresh()); } catch (e) { toast(e.message, true); } } }, a.icon ? I(a.icon) : null, a.label)))); foot.hidden = true; return; }
      area.replaceChildren(wrap); paintRows();
    }, ctx.scope, s.refresh);
    return sec;
  };

  /* ---------- software catalog (install / remove, with a plain-language description of everything) ---------- */
  secs.catalog = (ext, s, ctx) => {
    const route = s.source || 'catalog';
    let rows = [], cat = '', q = '', only = '';
    const grid = h('div', { class: 'cards' }), chips = h('div', { class: 'chips', role: 'toolbar', 'aria-label': 'Filter by category' }), summary = h('span', { class: 'muted small' });
    const search = h('input', { type: 'search', placeholder: 'Search software…', 'aria-label': 'Search software', oninput: e => { q = e.target.value.toLowerCase(); paint(); } });
    const state = r => !r.installed ? 'Not installed' : r.state === 'active' ? 'Running' : r.state === 'failed' ? 'Failed' : r.state === '-' ? 'Installed' : 'Stopped';
    const lvl = r => !r.installed ? '' : r.state === 'active' ? 'ok' : r.state === 'failed' ? 'bad' : r.state === '-' ? 'ok' : 'warn';
    async function detail(r) {
      let d; try { d = await call(ext, s.detail || 'detail', { id: r.id }); } catch (e) { return toast(e.message, true); }
      const m = modal({ title: r.title, icon: A.I && window.ICONS[r.icon] ? r.icon : 'package', wide: true, body: [h('div', { class: 'row' }, badge(r.id, lvl(r), state(r)), r.category ? h('span', { class: 'muted' }, r.category) : null), kv(d.kv)],
        actions: [{ label: 'Close', value: 1 }, ...(r.installed ? [{ label: 'Uninstall', danger: true, icon: 'trash', onclick: () => { setTimeout(() => uninstall(r)); } }] : r.can_install ? [{ label: 'Install', primary: true, icon: 'download', onclick: () => { setTimeout(() => install(r)); } }] : [])] });
    }
    async function install(r) {
      const bits = [r.size && ('Download: ' + r.size), r.ports.length && ('Opens ports: ' + r.ports.join(', ')), r.conflicts.length && ('Not meant to run together with: ' + r.conflicts.join(', '))].filter(Boolean);
      const ok = await confirmDlg({ title: 'Install ' + r.title + '?', icon: 'download', ok: 'Install', text: h('div', { class: 'col' }, h('p', {}, r.summary), h('p', { class: 'muted' }, 'You need it if: ' + r.need), bits.length ? h('ul', { class: 'help-steps' }, bits.map(b => h('li', {}, b))) : null, h('p', { class: 'muted small' }, 'The install runs in the background. Watch it in the console; you get a notification when it finishes.')) });
      if (!ok) return;
      try { const res = await post(ext, s.install || 'install', { id: r.id }); handle(res, 'Install ' + r.title); } catch (e) { toast(e.message, true); }
    }
    async function uninstall(r) {
      const ok = await confirmDlg({ title: 'Uninstall ' + r.title + '?', icon: 'trash', danger: true, ok: 'Uninstall', text: h('div', { class: 'col' }, h('p', {}, r.data ? 'The software is removed. Its data folders are kept; delete them by hand only if you are sure.' : 'The software is removed from this server.'), r.state === 'active' ? h('p', { class: 'warn' }, 'It is running right now and will be stopped.') : null) });
      if (!ok) return;
      try { const res = await post(ext, s.uninstall || 'uninstall', { id: r.id }); handle(res, 'Uninstall ' + r.title); } catch (e) { toast(e.message, true); }
    }
    const svc = (r, op) => async () => { try { await post(ext, s.action || 'action', { name: r.units[0], op }); toast(r.title + ': ' + op + ' done'); ctx.scope.refresh(); } catch (e) { toast(e.message, true); } };
    function paint() {
      const cats = [...new Set(rows.map(r => r.category))];
      chips.replaceChildren(h('button', { type: 'button', class: 'chip', 'aria-pressed': cat === '' && !only, onclick: () => { cat = ''; only = ''; paint(); } }, 'All'),
        h('button', { type: 'button', class: 'chip', 'aria-pressed': only === 'installed', onclick: () => { only = only === 'installed' ? '' : 'installed'; paint(); } }, 'Installed', h('span', { class: 'n' }, rows.filter(r => r.installed).length || '')),
        ...cats.map(c => h('button', { type: 'button', class: 'chip', 'aria-pressed': cat === c, onclick: () => { cat = cat === c ? '' : c; paint(); } }, c)));
      const list = rows.filter(r => (!cat || r.category === cat) && (only !== 'installed' || r.installed) && (!q || (r.title + ' ' + r.summary + ' ' + r.category).toLowerCase().includes(q)));
      summary.textContent = `${list.length} of ${rows.length} · ${rows.filter(r => r.installed).length} installed`;
      grid.replaceChildren(...(list.length ? list.map(r => h('article', { class: 'app' },
        h('div', { class: 'app-h' }, h('span', { class: 'app-ic' }, I(window.ICONS[r.icon] ? r.icon : 'package', 'lg')), h('div', { class: 'grow' }, h('h3', {}, r.title), h('div', { class: 'cat' }, r.category)), badge(r.id, lvl(r), state(r))),
        h('p', {}, r.summary),
        h('div', { class: 'app-f' }, h('button', { type: 'button', class: 'sm', onclick: () => detail(r) }, I('info'), 'Details'),
          h('span', { class: 'grow' }),
          r.installed && r.units.length ? (r.state === 'active' ? h('button', { type: 'button', class: 'sm', title: 'Restart', 'aria-label': 'Restart ' + r.title, onclick: svc(r, 'restart') }, I('restart')) : h('button', { type: 'button', class: 'sm', title: 'Start', 'aria-label': 'Start ' + r.title, onclick: svc(r, 'start') }, I('play'))) : null,
          r.installed ? h('button', { type: 'button', class: 'sm danger', onclick: () => uninstall(r) }, I('trash'), 'Uninstall')
            : r.can_install ? h('button', { type: 'button', class: 'sm primary', onclick: () => install(r) }, I('download'), 'Install')
            : h('button', { type: 'button', class: 'sm', disabled: true, title: r.note || 'No automatic install on this system' }, 'Manual install')))) : [emptyState('search', 'No match', 'Try another word or clear the filters.')]));
    }
    const box = h('div', { class: 'col' });
    loader(box, () => call(ext, route, s.params), d => { rows = (Array.isArray(d) ? d : d.rows).filter(r => !s.only || s.only.includes(r.id) || s.only.includes(r.category)); box.replaceChildren(h('div', { class: 'cat-bar' }, h('div', { class: 'find' }, I('search'), search), chips, h('span', { class: 'grow' }), summary), grid); paint(); }, ctx.scope, s.refresh);
    ctx.scope.on('job:done', () => ctx.scope.refresh());
    return h('section', {}, s.title ? h('div', { class: 'card-h' }, h('h2', {}, s.title)) : null, s.desc ? h('p', { class: 'card-d' }, s.desc) : null, box);
  };

  /* ---------- gate: show different sections depending on a status route ({ok:true} shows s.sections, else d.sections) ---------- */
  secs.gate = (ext, s, ctx) => {
    const box = h('div', { class: 'col' }); let cur = null, sub = null;
    const paint = d => {
      const list = d.ok ? s.sections : (d.sections || []), key = d.ok ? 'ok' : JSON.stringify(list);
      if (key === cur) return; cur = key; sub && sub.dispose(); sub = ctx.scope.child();
      box.replaceChildren(...list.map(x => A.renderSection(ext, x, { ...ctx, scope: sub })));
    };
    loader(box, () => call(ext, s.source, s.params), paint, ctx.scope, s.refresh);
    return box;
  };

  /* ---------- tabs inside a page ---------- */
  secs.tabs = (ext, s, ctx) => {
    const tabs = s.tabs || [], wrap = h('div', { class: 'col' });
    const bar = h('div', { class: 'tabs', role: 'tablist' }), pane = h('div', { class: 'tabpane', role: 'tabpanel' });
    let cur = tabs.find(t => t.id === S.sub) || tabs[0], sub = null;
    const show = () => {
      sub && sub.dispose(); sub = ctx.scope.child();
      bar.replaceChildren(...tabs.map(t => h('button', { type: 'button', class: 'tab', role: 'tab', 'aria-selected': t === cur, tabindex: t === cur ? 0 : -1, onclick: () => { if (t === cur) return; cur = t; S.sub = t.id; history.replaceState(null, '', '#' + ext + '/' + t.id); A.$('#crumb') && 0; show(); },
        onkeydown: e => { const i = tabs.indexOf(cur), d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0; if (d) { e.preventDefault(); cur = tabs[(i + d + tabs.length) % tabs.length]; S.sub = cur.id; history.replaceState(null, '', '#' + ext + '/' + cur.id); show(); A.$$('.tab', bar)[tabs.indexOf(cur)].focus(); } } }, t.icon ? I(t.icon) : null, t.title)));
      pane.replaceChildren(...(cur.sections || []).map(x => A.renderSection(ext, x, { ...ctx, scope: sub })));
    };
    show();
    wrap.append(bar, pane);
    return wrap;
  };
})();
