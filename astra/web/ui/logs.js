'use strict';
/* Logs tab: pick any log (panel, system, web server, database, Event Log / journal), filter, show only warnings or errors,
   follow live, wrap lines, copy or download. Lines are coloured by severity; ANSI colours in the log itself are kept. */
(() => {
  window.ASTRA_UI = window.ASTRA_UI || {};
  window.ASTRA_UI.logs = (view, ext, A) => {
    const { h, I, call, toast, card, emptyState, skeleton, saveBlob, ansi } = A;
    const BAD = /\b(error|err|fatal|critical|crit|emerg|alert|panic|fail(ed|ure)?|denied|refused|exception|traceback|segfault)\b/i, WARN = /\b(warn(ing)?|deprecated|timeout|timed out|retry)\b/i;
    const st = { source: '', lines: 200, q: '', level: 'all', follow: false, wrap: false, text: '' };
    try { Object.assign(st, JSON.parse(localStorage.getItem('astra_logs') || '{}'), { follow: false }); } catch { /* ok */ }
    const keep = () => { try { localStorage.setItem('astra_logs', JSON.stringify({ source: st.source, lines: st.lines, level: st.level, wrap: st.wrap })); } catch { /* ok */ } };
    const out = h('pre', { class: 'out mono', tabindex: 0, 'aria-label': 'Log output', style: { margin: 0, maxHeight: 'calc(100vh - 19rem)', minHeight: '18rem', background: 'var(--term)', border: '1px solid var(--line)', borderRadius: '.7rem', whiteSpace: 'pre' } });
    const info = h('span', { class: 'muted small' });
    let timer = null, busy = false;
    const sel = h('select', { 'aria-label': 'Log', onchange: e => { st.source = e.target.value; keep(); fetch1(true); } });
    const linesSel = h('select', { 'aria-label': 'Lines', onchange: e => { st.lines = +e.target.value; keep(); fetch1(true); } }, [100, 200, 500, 1000, 2000].map(n => h('option', { value: n, selected: n === st.lines }, n + ' lines')));
    const levelSel = h('select', { 'aria-label': 'Severity', onchange: e => { st.level = e.target.value; keep(); draw(); } }, [['all', 'All lines'], ['warn', 'Warnings and errors'], ['bad', 'Errors only']].map(([v, l]) => h('option', { value: v, selected: v === st.level }, l)));
    const find = h('input', { type: 'search', placeholder: 'Search in this log…', 'aria-label': 'Search in this log', oninput: e => { st.q = e.target.value.toLowerCase(); draw(); } });
    const follow = h('input', { type: 'checkbox', 'aria-label': 'Follow', onchange: e => { st.follow = e.target.checked; clearInterval(timer); if (st.follow) { timer = setInterval(() => fetch1(false), 3000); A.onLeave(() => clearInterval(timer)); } } });
    const wrap = h('input', { type: 'checkbox', checked: st.wrap, 'aria-label': 'Wrap lines', onchange: e => { st.wrap = e.target.checked; keep(); out.style.whiteSpace = st.wrap ? 'pre-wrap' : 'pre'; } });
    out.style.whiteSpace = st.wrap ? 'pre-wrap' : 'pre';

    function draw() {
      let lines = st.text.split('\n');
      if (st.level !== 'all') lines = lines.filter(l => BAD.test(l) || (st.level === 'warn' && WARN.test(l)));
      if (st.q) lines = lines.filter(l => l.toLowerCase().includes(st.q));
      const atEnd = out.scrollTop + out.clientHeight >= out.scrollHeight - 12;
      if (!lines.some(l => l.trim())) { out.replaceChildren(h('span', { class: 'muted' }, st.text.trim() ? 'No lines match your filters.' : '(this log is empty)')); info.textContent = ''; return; }
      const frag = document.createDocumentFragment();
      for (const l of lines) {
        const row = h('div', { class: l.includes('\x1b') ? '' : BAD.test(l) ? 'bad' : WARN.test(l) ? 'warn' : '' });
        l.includes('\x1b') ? row.append(ansi(l)) : row.textContent = l || ' ';
        frag.append(row);
      }
      out.replaceChildren(frag);
      info.textContent = `${lines.length} line${lines.length === 1 ? '' : 's'} shown`;
      if (atEnd || st.fresh) out.scrollTop = out.scrollHeight; st.fresh = false;
    }
    async function fetch1(fresh) {
      if (busy || !st.source) return; busy = true;
      if (fresh) { out.replaceChildren(skeleton(4)); st.fresh = true; }
      try { st.text = (await call('logs', 'view', { source: st.source, lines: st.lines })).text || ''; draw(); }
      catch (e) { st.text = ''; out.replaceChildren(h('div', { class: 'bad' }, e.message)); info.textContent = ''; }
      finally { busy = false; }
    }
    const copy = async () => { try { await navigator.clipboard.writeText(st.text.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, '')); toast('Copied'); } catch { toast('Copy is not allowed in this browser', 'warn'); } };
    const dl = async () => { try { saveBlob(await call('logs', 'download', { source: st.source }), st.source.replace(/[^\w.-]+/g, '_') + '.log'); } catch (e) { toast(e.message, true); } };

    const bar = h('div', { class: 'tbar', style: { padding: 0 } }, sel, linesSel, levelSel, h('div', { class: 'find' }, I('search'), find),
      h('label', { class: 'row small', style: { gap: '.4rem' } }, follow, 'Follow'), h('label', { class: 'row small', style: { gap: '.4rem' } }, wrap, 'Wrap'),
      h('span', { class: 'grow' }), info,
      h('button', { type: 'button', class: 'sm', onclick: () => fetch1(true) }, I('refresh'), 'Refresh'), h('button', { type: 'button', class: 'sm', onclick: copy }, I('copy'), 'Copy'), h('button', { type: 'button', class: 'sm', onclick: dl }, I('download'), 'Download'));
    view.append(card('Log viewer', h('p', { class: 'card-d' }, 'Pick a log, then narrow it down with search or severity. Red lines are errors, amber lines are warnings.'), bar, out));

    (async () => {
      try {
        const d = await call('logs', 'sources'), all = d.groups.flatMap(g => g.items);
        if (!all.length) return out.replaceChildren(emptyState('file-text', 'No logs found', 'Add log files in Settings > Panel (log_files) and they will show up here.'));
        sel.replaceChildren(...d.groups.map(g => h('optgroup', { label: g.title }, g.items.map(i => h('option', { value: i.value }, i.label)))));
        if (!all.some(i => i.value === st.source)) st.source = all[0].value;
        sel.value = st.source; fetch1(true);
      } catch (e) { out.replaceChildren(h('div', { class: 'bad' }, e.message)); }
    })();
  };
})();
