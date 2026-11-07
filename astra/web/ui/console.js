'use strict';
/* The console: a panel that floats over the page area (never over the sidebar or top bar).
   Tabs: Terminal (run commands on the server), Activity (every install/backup the panel started), and one tab per job you open.
   Output is parsed for colours and progress bars (ANSI), so apt, pip, npm, docker... look the way they do in a real terminal. */
(() => {
  window.ASTRA_UI = window.ASTRA_UI || {};
  const A = window.ASTRA, { h, $, I, req, ansi, toast, ago } = A;
  const root = $('#console'), stage = $('#stage');
  const T = { tabs: [], cur: 'term', cwd: '', hist: [], hi: -1, info: null, built: false, size: 0 };
  const lvl = j => j.state === 'running' ? '' : j.rc === 0 ? 'ok' : 'bad';
  const jobTab = (id, title) => { let t = T.tabs.find(x => x.id === 'job' + id); if (!t) { t = { id: 'job' + id, job: id, title: title || 'Job ' + id, text: '', next: 0, state: 'running', pct: null, closed: false }; T.tabs.push(t); } return t; };

  function tabButton(t) {
    const x = t.id !== 'term' && t.id !== 'act' ? h('span', { class: 'x', role: 'button', tabindex: 0, 'aria-label': 'Close tab', onclick: e => { e.stopPropagation(); closeTab(t); }, onkeydown: e => { if (e.key === 'Enter') { e.stopPropagation(); closeTab(t); } } }, I('x')) : null;
    const dot = t.job ? h('span', { class: 'dot ' + (t.state === 'running' ? '' : t.rc === 0 ? 'ok' : 'bad') }) : I(t.id === 'term' ? 'terminal' : 'list');
    return h('button', { type: 'button', class: 'con-tab', role: 'tab', 'aria-selected': T.cur === t.id, onclick: () => select(t.id) }, dot, h('span', { class: 't' }, t.title), x);
  }
  function build() {
    if (T.built) return; T.built = true;
    T.tabs = [{ id: 'term', title: 'Terminal' }, { id: 'act', title: 'Activity' }];
    T.out = h('pre', { class: 'out con-out mono', tabindex: 0, 'aria-label': 'Console output', 'aria-live': 'off' });
    T.list = h('div', { class: 'con-list', hidden: true });
    T.prog = h('div', { class: 'con-prog', hidden: true });
    T.input = h('input', { class: 'mono', 'aria-label': 'Command', autocomplete: 'off', spellcheck: 'false', placeholder: 'Type a command and press Enter. Ctrl+C stops it.' });
    T.ps = h('span', { class: 'ps' });
    T.inRow = h('div', { class: 'con-in' }, T.ps, T.input);
    T.tabsEl = h('div', { class: 'con-tabs', role: 'tablist' });
    const btn = (icon, label, fn) => h('button', { type: 'button', class: 'icon-btn sm ghost', title: label, 'aria-label': label, onclick: fn }, I(icon));
    T.minBtn = btn('minus', 'Minimise', () => { root.classList.toggle('min'); });
    T.maxBtn = btn('maximize', 'Maximise', () => { root.classList.toggle('max'); root.classList.remove('min'); });
    const grip = h('div', { class: 'con-grip', 'aria-hidden': 'true' });
    grip.addEventListener('pointerdown', e => {
      e.preventDefault(); const y0 = e.clientY, h0 = root.offsetHeight, max = stage.clientHeight - 24; grip.setPointerCapture(e.pointerId);
      const mv = ev => { T.size = Math.max(160, Math.min(max, h0 + y0 - ev.clientY)); root.style.setProperty('--ch', T.size + 'px'); root.classList.remove('min', 'max'); };
      const up = () => { grip.removeEventListener('pointermove', mv); grip.removeEventListener('pointerup', up); };
      grip.addEventListener('pointermove', mv); grip.addEventListener('pointerup', up);
    });
    root.append(grip, h('div', { class: 'con-bar' }, T.tabsEl, T.minBtn, T.maxBtn, btn('x', 'Close console (Ctrl+`)', close)), h('div', { class: 'con-body' }, T.prog, T.out, T.list, T.inRow));
    root.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('dialog[open]')) { e.stopPropagation(); close(); } });
    T.input.addEventListener('keydown', onKey);
    T.out.addEventListener('click', () => { if (!getSelection().toString()) T.input.focus(); });
    A.req('/api/console/info').then(i => { T.info = i; T.cwd = i.cwd; paintPs(); if (!i.enabled) note('The console is turned off. Turn it on in Settings → Console.'); }).catch(() => {});
    note('Commands run on this server as the panel user. Installs started from the panel also show up here with live progress.\nTry:  ls   |   df -h   |   systemctl status nginx\n');
  }
  const paintPs = () => { const cwd = T.cwd || '~'; T.ps.textContent = (T.info ? T.info.user + ' ' : '') + cwd + (T.info && T.info.root ? ' #' : ' $'); };
  let term = { text: '' };
  const note = s => { term.text += '\x1b[2m' + s + '\x1b[0m\n'; if (T.cur === 'term') paintOut(); };

  function paintTabs() { T.tabsEl.replaceChildren(...T.tabs.map(tabButton)); }
  function curTab() { return T.tabs.find(t => t.id === T.cur); }
  function select(id) {
    T.cur = id; paintTabs();
    const t = curTab(), isAct = id === 'act', isTerm = id === 'term';
    T.out.hidden = isAct; T.list.hidden = !isAct; T.inRow.hidden = isAct;
    T.input.placeholder = isTerm ? 'Type a command and press Enter. Ctrl+C stops it.' : 'This job is waiting for input? Type here and press Enter.';
    paintOut(); paintProg(); if (isAct) paintAct(); else T.input.focus();
  }
  function paintOut() {
    const t = curTab(); if (!t || T.cur === 'act') return;
    const text = T.cur === 'term' ? term.text : t.text, atEnd = T.out.scrollTop + T.out.clientHeight >= T.out.scrollHeight - 30;
    T.out.replaceChildren(ansi(text.length > 150000 ? '…\n' + text.slice(-150000) : text));
    if (atEnd || !T.out.dataset.seen) { T.out.scrollTop = T.out.scrollHeight; T.out.dataset.seen = '1'; }
  }
  function paintProg() {
    const t = curTab(); T.prog.hidden = !(t && t.job);
    if (!t || !t.job) return;
    const run = t.state === 'running';
    T.prog.replaceChildren(h('span', { class: 'badge ' + (run ? '' : t.rc === 0 ? 'ok' : 'bad') }, run ? 'Running' : t.rc === 0 ? 'Finished' : t.rc === -15 || t.cancelled ? 'Cancelled' : 'Failed (' + t.rc + ')'),
      t.steps > 1 ? h('span', {}, `step ${Math.min(t.step + 1, t.steps)} of ${t.steps}`) : null,
      run ? h('progress', { max: 100, value: t.pct == null ? undefined : t.pct, 'aria-label': 'Progress' }) : null, run && t.pct != null ? h('span', {}, t.pct + '%') : null, h('span', { class: 'grow' }),
      run ? h('button', { type: 'button', class: 'sm danger', onclick: async () => { try { await req(`/api/jobs/${t.job}/cancel`, 'POST'); toast('Stopping…'); } catch (e) { toast(e.message, true); } } }, I('stop'), 'Stop') : null);
  }
  function paintAct() {
    const jobs = [...(A.state.jobs || [])].sort((a, b) => b.id - a.id).filter(j => j.kind !== 'console');
    T.list.replaceChildren(...(jobs.length ? jobs.map(j => h('div', { class: 'con-job', tabindex: 0, role: 'button', onclick: () => open({ job: j.id, title: j.title }), onkeydown: e => { if (e.key === 'Enter') open({ job: j.id, title: j.title }); } },
      h('span', { class: 'badge ' + lvl(j) }, j.state === 'running' ? 'Running' : j.rc === 0 ? 'Done' : 'Failed'), h('div', { class: 'b' }, h('div', {}, j.title), h('div', { class: 's' }, ago(j.started))),
      j.state === 'running' ? h('progress', { max: 100, value: j.pct == null ? undefined : j.pct, 'aria-label': 'Progress of ' + j.title }) : null, I('chevron-right'))) :
      [A.emptyState('list', 'No activity yet', 'Installs, removals, backups and other long tasks started from the panel appear here with their full output.')]));
  }
  function closeTab(t) {
    T.tabs = T.tabs.filter(x => x !== t); t.closed = true;
    if (T.cur === t.id) T.cur = 'act'; select(T.cur);
  }

  /* ---- polling of job output ---- */
  const polling = new Set();
  async function follow(t) {
    if (polling.has(t.id)) return; polling.add(t.id);
    try {
      while (!t.closed && root.isConnected) {
        let r;
        try { r = await req(`/api/jobs/${t.job}`, 'GET', { since: t.next }); } catch (e) { t.text += `\n[lost contact: ${e.message}]\n`; break; }
        if (r.truncated) t.text = '[earlier output trimmed]\n';
        t.text += r.text; t.next = r.next; Object.assign(t, { state: r.state, rc: r.rc, pct: r.pct, step: r.step, steps: r.steps });
        if (T.cur === t.id) { paintOut(); paintProg(); }
        if (r.state !== 'running') { paintTabs(); if (r.kind === 'console') term.running = null; break; }
        await new Promise(ok => setTimeout(ok, document.hidden ? 2500 : 600));
      }
    } finally { polling.delete(t.id); if (T.cur === 'term' && t.id === term.running) term.running = null; }
  }

  /* ---- the terminal tab: every command is a job; its output streams into the scrollback ---- */
  async function runCommand(cmd) {
    term.text += `\x1b[36m${T.ps.textContent}\x1b[0m ${cmd}\n`; paintOut();
    try {
      const r = await req('/api/console/run', 'POST', { cmd, cwd: T.cwd });
      if (r.cwd) { T.cwd = r.cwd; paintPs(); return; }
      const t = { id: 'term-job' + r.job, job: r.job, next: 0, text: '', state: 'running' }; term.running = t;
      let seen = 0;
      while (true) {
        const j = await req(`/api/jobs/${r.job}`, 'GET', { since: t.next });
        if (j.truncated) term.text += '\n[output trimmed]\n';
        term.text += j.text; t.next = j.next; seen += j.text.length; paintOut();
        if (j.state !== 'running') { if (j.rc) term.text += `\x1b[2m[exit ${j.rc}]\x1b[0m\n`; break; }
        await new Promise(ok => setTimeout(ok, 350));
      }
    } catch (e) { term.text += `\x1b[31m${e.message}\x1b[0m\n`; }
    term.running = null; paintOut();
  }
  function onKey(e) {
    const t = curTab();
    if (e.key === 'c' && e.ctrlKey && !getSelection().toString()) { e.preventDefault(); const j = T.cur === 'term' ? term.running && term.running.job : t.job; if (j) req(`/api/jobs/${j}/cancel`, 'POST').catch(x => toast(x.message, true)); T.input.value = ''; return; }
    if (e.key === 'l' && e.ctrlKey) { e.preventDefault(); if (T.cur === 'term') { term.text = ''; paintOut(); } return; }
    if (e.key === 'ArrowUp' && T.cur === 'term') { e.preventDefault(); if (T.hist.length) { T.hi = Math.min(T.hi + 1, T.hist.length - 1); T.input.value = T.hist[T.hist.length - 1 - T.hi]; } return; }
    if (e.key === 'ArrowDown' && T.cur === 'term') { e.preventDefault(); T.hi = Math.max(T.hi - 1, -1); T.input.value = T.hi < 0 ? '' : T.hist[T.hist.length - 1 - T.hi]; return; }
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const v = T.input.value; T.input.value = '';
    const target = T.cur === 'term' ? (term.running && term.running.job) : t.job;   // a running program gets the line as its input
    if (target) { req(`/api/jobs/${target}/input`, 'POST', { text: v + '\n' }).catch(x => toast(x.message, true)); return; }
    if (T.cur !== 'term' || !v.trim()) return;
    if (v.trim() === 'clear') { term.text = ''; paintOut(); return; }
    T.hist.push(v); T.hi = -1; runCommand(v);
  }

  function open(opts = {}) {
    build();
    if (opts.toggle && !root.hidden) return close();
    root.hidden = false; stage.classList.add('console-open'); A.state.consoleOpen = true;
    if (opts.job) { const t = jobTab(opts.job, opts.title); select(t.id); follow(t); root.classList.remove('min'); }
    else select(T.cur === 'act' || !T.tabs.some(x => x.id === T.cur) ? 'term' : T.cur);
    if (!opts.job && root.classList.contains('min')) root.classList.remove('min');
  }
  function close() { root.hidden = true; stage.classList.remove('console-open'); A.state.consoleOpen = false; $('#tb-console')?.focus(); }
  window.ASTRA_UI.console = { open, close };
})();
