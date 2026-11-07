'use strict';
/* File manager tab: breadcrumbs, multi-select, drag items onto folders to move, drop files from the desktop to upload,
   copy / cut / paste, rename, edit text files, right-click menu and keyboard shortcuts. Loaded when the Files tab opens. */
(() => {
  window.ASTRA_UI = window.ASTRA_UI || {};
  window.ASTRA_UI.files = (view, ext, A) => {
    const { h, I, call, post, toast, bytes, when, menu, confirm: confirmDlg, prompt: promptDlg, modal, emptyState, skeleton, saveBlob } = A;
    A.loadCss('ui/files.css');
    const X = 'files', MAX_UP = 8 << 20, MAX_EDIT = 2 << 20;
    const st = { path: '', parent: null, sep: '/', entries: [], sel: new Set(), last: null, sort: { key: 'name', dir: 1 }, q: '', clip: null, roots: [] };
    const join = (d, n) => d.endsWith(st.sep) ? d + n : d + st.sep + n;
    const full = n => join(st.path, n);
    const EXT_ICON = [[/\.(png|jpe?g|gif|webp|svg|ico|bmp)$/i, 'image'], [/\.(zip|gz|tgz|tar|7z|rar|bz2|xz)$/i, 'file-zip'], [/\.(js|ts|py|php|html?|css|json|ya?ml|sh|ps1|conf|ini|xml|sql|c|cpp|go|rs|java|rb)$/i, 'file-code'], [/\.(txt|md|log|csv)$/i, 'file-text']];
    const iconOf = e => e.type === 'dir' ? 'folder' : e.type === 'link' ? 'link' : (EXT_ICON.find(([r]) => r.test(e.name)) || [0, 'file'])[1];
    const isText = n => /\.(txt|md|log|csv|json|ya?ml|conf|ini|xml|html?|css|js|ts|py|php|sh|ps1|sql|env|toml|cfg|service|htaccess)$/i.test(n) || !/\./.test(n);

    const list = h('div', { class: 'fm-list' }), over = h('div', { class: 'fm-over' }, 'Drop files to upload here');
    const box = h('div', { class: 'fm-box', tabindex: 0, 'aria-label': 'Files and folders' }, list, over);
    const pathEl = h('div', { class: 'fm-path', role: 'navigation', 'aria-label': 'Current folder' });
    const foot = h('div', { class: 'fm-foot' });
    const search = h('input', { type: 'search', placeholder: 'Filter this folder…', 'aria-label': 'Filter this folder', oninput: e => { st.q = e.target.value.toLowerCase(); paint(); } });
    const tb = {};
    const btn = (id, icon, label, fn, cls = 'sm') => (tb[id] = h('button', { type: 'button', class: cls, title: label, 'aria-label': label, onclick: () => Promise.resolve(fn()).catch(e => toast(e.message, true)) }, I(icon), h('span', { class: 'lbl' }, label)));
    const fileIn = h('input', { type: 'file', multiple: true, hidden: true, onchange: e => { upload([...e.target.files]); e.target.value = ''; } });

    const names = () => [...st.sel];
    const selEntries = () => st.entries.filter(e => st.sel.has(e.name));
    const rootOf = () => st.roots.find(r => st.path.toLowerCase().startsWith(r.path.toLowerCase()));

    /* ---------- load ---------- */
    async function load(path) {
      list.replaceChildren(skeleton(5));
      try {
        const d = await call(X, 'list', { path: path ?? st.path });
        Object.assign(st, { path: d.path, parent: d.parent, sep: d.sep || (d.path.includes('\\') ? '\\' : '/'), entries: d.entries });
        st.sel = new Set([...st.sel].filter(n => d.entries.some(e => e.name === n)));
        try { sessionStorage.setItem('astra_files_path', st.path); } catch { /* ok */ }
        paint();
      } catch (e) {
        list.replaceChildren(emptyState('alert-circle', 'Cannot open this folder', e.message, h('button', { type: 'button', class: 'primary', onclick: () => load(st.roots[0]?.path || '') }, I('home'), 'Go to the main folder')));
        foot.replaceChildren();
      }
    }
    const reload = () => load(st.path);

    /* ---------- paint ---------- */
    function crumbs() {
      const r = rootOf(), parts = [], base = r ? r.path : st.path;
      parts.push([r ? (r.name || r.path) : st.path, base]);
      let cur = base;
      for (const seg of st.path.slice(base.length).split(/[\\/]/).filter(Boolean)) { cur = join(cur, seg); parts.push([seg, cur]); }
      pathEl.replaceChildren(...parts.flatMap(([n, p], i) => [i ? I('chevron-right') : I('hard-drive'), h('button', { type: 'button', onclick: () => load(p), 'aria-current': i === parts.length - 1 ? 'page' : null }, n)]));
    }
    function sorted() {
      const k = st.sort.key, d = st.sort.dir;
      let r = st.entries.filter(e => !st.q || e.name.toLowerCase().includes(st.q));
      return r.sort((a, b) => (a.type === 'dir') !== (b.type === 'dir') ? (a.type === 'dir' ? -1 : 1) : d * (k === 'name' ? a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }) : (a[k] - b[k])));
    }
    function paint() {
      crumbs();
      const rows = sorted(), n = st.sel.size;
      const th = (k, label, cls = '') => h('span', { class: cls, onclick: () => { st.sort = { key: k, dir: st.sort.key === k ? -st.sort.dir : 1 }; paint(); } }, label, st.sort.key === k ? I(st.sort.dir > 0 ? 'sort-asc' : 'sort-desc') : null);
      const all = h('input', { type: 'checkbox', 'aria-label': 'Select all', checked: rows.length > 0 && rows.every(e => st.sel.has(e.name)), onclick: ev => { ev.stopPropagation(); st.sel = ev.target.checked ? new Set(rows.map(e => e.name)) : new Set(); paint(); } });
      const head = h('div', { class: 'fm-row head' }, all, th('name', 'Name'), th('size', 'Size', 'num'), th('mtime', 'Modified', 'dt'));
      list.replaceChildren(head, ...(rows.length ? rows.map(row) : [emptyState('folder-open', st.q ? 'No match' : 'This folder is empty', st.q ? 'Nothing here matches your filter.' : 'Drag files here from your computer, or use Upload.')]));
      tb.up.disabled = !st.parent;
      for (const id of ['rename', 'dl', 'edit']) tb[id].disabled = n !== 1 || (id !== 'rename' && selEntries()[0]?.type === 'dir');
      for (const id of ['cut', 'copy', 'del']) tb[id].disabled = !n;
      tb.paste.disabled = !st.clip;
      const files = st.entries.filter(e => e.type !== 'dir');
      foot.replaceChildren(h('span', {}, `${st.entries.length - files.length} folders, ${files.length} files · ${bytes(files.reduce((a, e) => a + e.size, 0))}`), h('span', {}, n ? `${n} selected${st.clip ? ' · ' + st.clip.paths.length + ' on clipboard (' + st.clip.op + ')' : ''}` : st.clip ? st.clip.paths.length + ' on clipboard (' + st.clip.op + ')' : 'Tip: right-click for more · Ctrl+C / X / V · Del · F2 rename'));
    }
    function row(e) {
      const cut = st.clip?.op === 'cut' && st.clip.paths.includes(full(e.name));
      const r = h('div', { class: 'fm-row ' + e.type + (st.sel.has(e.name) ? ' sel' : '') + (cut ? ' cut' : ''), draggable: 'true', 'data-n': e.name, role: 'row', 'aria-selected': st.sel.has(e.name) },
        h('input', { type: 'checkbox', checked: st.sel.has(e.name), 'aria-label': 'Select ' + e.name, onclick: ev => { ev.stopPropagation(); ev.target.checked ? st.sel.add(e.name) : st.sel.delete(e.name); st.last = e.name; paint(); } }),
        h('span', { class: 'nm' }, I(iconOf(e)), h('b', { title: e.name }, e.name)),
        h('span', { class: 'num' }, e.type === 'dir' ? '' : bytes(e.size)), h('span', { class: 'dt' }, when(e.mtime)));
      r.addEventListener('click', ev => {
        if (ev.shiftKey && st.last) { const rows = sorted().map(x => x.name), a = rows.indexOf(st.last), b = rows.indexOf(e.name); st.sel = new Set(rows.slice(Math.min(a, b), Math.max(a, b) + 1)); }
        else if (ev.ctrlKey || ev.metaKey) { st.sel.has(e.name) ? st.sel.delete(e.name) : st.sel.add(e.name); st.last = e.name; }
        else { st.sel = new Set([e.name]); st.last = e.name; }
        paint();
      });
      r.addEventListener('dblclick', () => open(e));
      r.addEventListener('contextmenu', ev => { ev.preventDefault(); if (!st.sel.has(e.name)) { st.sel = new Set([e.name]); paint(); } ctxMenu(ev); });
      r.addEventListener('dragstart', ev => { if (!st.sel.has(e.name)) { st.sel = new Set([e.name]); paint(); } ev.dataTransfer.setData('application/x-astra-files', JSON.stringify(names().map(full))); ev.dataTransfer.effectAllowed = 'copyMove'; });
      if (e.type === 'dir') {
        r.addEventListener('dragover', ev => { if (ev.dataTransfer.types.includes('application/x-astra-files')) { ev.preventDefault(); ev.stopPropagation(); r.classList.add('drop'); ev.dataTransfer.dropEffect = ev.ctrlKey ? 'copy' : 'move'; } });
        r.addEventListener('dragleave', () => r.classList.remove('drop'));
        r.addEventListener('drop', ev => { r.classList.remove('drop'); const d = ev.dataTransfer.getData('application/x-astra-files'); if (!d) return; ev.preventDefault(); ev.stopPropagation(); transfer(JSON.parse(d), full(e.name), ev.ctrlKey ? 'copy' : 'move'); });
      }
      return r;
    }

    /* ---------- actions ---------- */
    async function open(e) {
      if (e.type === 'dir') { st.sel.clear(); return load(full(e.name)); }
      if (e.type === 'file' && isText(e.name) && e.size <= MAX_EDIT) return edit(e.name);
      return download(e.name);
    }
    async function download(n) { const e = st.entries.find(x => x.name === n); if (!e || e.type === 'dir') return toast('Folders cannot be downloaded yet. Open it and download the files inside.', 'warn'); toast('Preparing ' + n + '…'); saveBlob(await call(X, 'download', { path: full(n) }), n); }
    async function edit(n) {
      const d = await call(X, 'read', { path: full(n) });
      const ta = h('textarea', { class: 'fm-edit', spellcheck: 'false', 'aria-label': 'Contents of ' + n }, d.content);
      const save = async m => { await post(X, 'write', { path: full(n), content: ta.value }); toast('Saved ' + n); reload(); return false; };
      const m = modal({ title: n, icon: 'file-text', wide: true, body: [h('p', { class: 'muted small' }, d.path + '  ·  Ctrl+S saves'), ta], actions: [{ label: 'Close', value: 1 }, { label: 'Save', primary: true, icon: 'save', keep: true, onclick: save }] });
      ta.addEventListener('keydown', ev => { if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 's') { ev.preventDefault(); save().catch(x => toast(x.message, true)); } if (ev.key === 'Tab') { ev.preventDefault(); const s = ta.selectionStart; ta.setRangeText('\t', s, ta.selectionEnd, 'end'); } });
      ta.focus();
    }
    async function newFolder() { const n = await promptDlg({ title: 'New folder', label: 'Folder name', ok: 'Create' }); if (n) { await post(X, 'mkdir', { path: st.path, name: n }); reload(); } }
    async function newFile() { const n = await promptDlg({ title: 'New file', label: 'File name', ok: 'Create', placeholder: 'index.html' }); if (n) { await post(X, 'write', { path: full(n), content: '' }); await reload(); if (isText(n)) edit(n); } }
    async function rename() { const n = names()[0]; const v = await promptDlg({ title: 'Rename', label: 'New name', value: n, ok: 'Rename' }); if (v && v !== n) { await post(X, 'rename', { path: full(n), new_name: v }); st.sel = new Set([v]); reload(); } }
    async function del() {
      const n = names(); if (!n.length) return;
      if (!(await confirmDlg({ title: n.length === 1 ? 'Delete ' + n[0] + '?' : `Delete ${n.length} items?`, danger: true, ok: 'Delete', icon: 'trash', text: 'This cannot be undone. Folders are deleted with everything inside them.' }))) return;
      await post(X, 'delete_many', { paths: n.map(full) }); st.sel.clear(); toast('Deleted'); reload();
    }
    const clip = op => { if (!st.sel.size) return; st.clip = { op, paths: names().map(full) }; toast((op === 'cut' ? 'Cut ' : 'Copied ') + st.clip.paths.length + ' item(s). Open a folder and paste.'); paint(); };
    async function transfer(paths, dest, op) {
      try { await post(X, op === 'copy' ? 'copy' : 'move', { paths, dest }); toast((op === 'copy' ? 'Copied ' : 'Moved ') + paths.length + ' item(s)'); st.sel.clear(); reload(); } catch (e) { toast(e.message, true); }
    }
    async function paste() { if (!st.clip) return; const c = st.clip; await transfer(c.paths, st.path, c.op === 'cut' ? 'move' : 'copy'); if (c.op === 'cut') st.clip = null; }
    function readB64(f) { return new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(',')[1] || ''); r.onerror = () => no(new Error('Could not read ' + f.name)); r.readAsDataURL(f); }); }
    async function upload(files) {
      let ok = 0;
      for (const f of files) {
        if (f.size > MAX_UP) { toast(`${f.name} is larger than 8 MB. Use scp, rsync or SFTP for big files.`, true); continue; }
        try { await post(X, 'upload', { path: st.path, name: f.name, data: await readB64(f) }); ok++; } catch (e) { toast(f.name + ': ' + e.message, true); }
      }
      if (ok) { toast('Uploaded ' + ok + ' file(s)'); reload(); }
    }
    function ctxMenu(ev) {
      const one = st.sel.size === 1 ? selEntries()[0] : null;
      menu({ x: ev.clientX, y: ev.clientY }, [one && { label: one.type === 'dir' ? 'Open' : 'Open / edit', icon: 'folder-open', onclick: () => open(one) }, one && one.type !== 'dir' && { label: 'Download', icon: 'download', onclick: () => download(one.name) }, '-',
        { label: 'Copy', icon: 'copy', onclick: () => clip('copy') }, { label: 'Cut', icon: 'cut', onclick: () => clip('cut') }, { label: 'Paste here', icon: 'clipboard', disabled: !st.clip, onclick: paste },
        one && { label: 'Rename', icon: 'edit', onclick: rename }, '-', { label: 'Delete', icon: 'trash', danger: true, onclick: () => del().catch(e => toast(e.message, true)) }]);
    }

    /* ---------- wiring ---------- */
    const guard = fn => () => fn().catch(e => toast(e.message, true));
    box.addEventListener('keydown', ev => {
      if (ev.target.tagName === 'INPUT' && ev.target.type !== 'checkbox') return;
      const k = ev.key.toLowerCase(), mod = ev.ctrlKey || ev.metaKey;
      if (mod && k === 'a') { ev.preventDefault(); st.sel = new Set(sorted().map(e => e.name)); paint(); }
      else if (mod && k === 'c') { ev.preventDefault(); clip('copy'); } else if (mod && k === 'x') { ev.preventDefault(); clip('cut'); }
      else if (mod && k === 'v') { ev.preventDefault(); guard(paste)(); }
      else if (k === 'delete') guard(del)(); else if (k === 'f2' && st.sel.size === 1) guard(rename)();
      else if (k === 'enter' && st.sel.size === 1) open(selEntries()[0]); else if (k === 'backspace' && st.parent) load(st.parent); else if (k === 'escape') { st.sel.clear(); paint(); }
    });
    // dropping files from the desktop onto the list uploads them; dropping panel items onto empty space moves them here
    let depth = 0;
    box.addEventListener('dragenter', ev => { if (ev.dataTransfer.types.includes('Files')) { depth++; box.classList.add('over'); } });
    box.addEventListener('dragleave', () => { depth = Math.max(0, depth - 1); if (!depth) box.classList.remove('over'); });
    box.addEventListener('dragover', ev => { if (ev.dataTransfer.types.includes('Files') || ev.dataTransfer.types.includes('application/x-astra-files')) { ev.preventDefault(); ev.dataTransfer.dropEffect = ev.dataTransfer.types.includes('Files') ? 'copy' : 'move'; } });
    box.addEventListener('drop', ev => {
      ev.preventDefault(); depth = 0; box.classList.remove('over');
      if (ev.dataTransfer.files.length) return upload([...ev.dataTransfer.files]);
      const d = ev.dataTransfer.getData('application/x-astra-files'); if (d) transfer(JSON.parse(d), st.path, ev.ctrlKey ? 'copy' : 'move');
    });
    box.addEventListener('click', ev => { if (ev.target === list || ev.target === box) { st.sel.clear(); paint(); } });

    const rootSel = h('select', { 'aria-label': 'Location', onchange: e => load(e.target.value) });
    const bar = h('div', { class: 'fm-bar' }, rootSel, btn('up', 'arrow-up', 'Up', () => load(st.parent)), btn('refresh', 'refresh', 'Refresh', reload), h('span', { class: 'sep' }), pathEl);
    const bar2 = h('div', { class: 'fm-bar' }, btn('nf', 'folder-plus', 'New folder', newFolder), btn('nfile', 'file-plus', 'New file', newFile), btn('up2', 'upload', 'Upload', () => fileIn.click(), 'sm primary'), h('span', { class: 'sep' }),
      btn('edit', 'edit', 'Edit', () => edit(names()[0])), btn('dl', 'download', 'Download', () => download(names()[0])), btn('rename', 'swap', 'Rename', rename), h('span', { class: 'sep' }),
      btn('copy', 'copy', 'Copy', () => clip('copy')), btn('cut', 'cut', 'Cut', () => clip('cut')), btn('paste', 'clipboard', 'Paste', paste), btn('del', 'trash', 'Delete', del, 'sm danger'),
      h('span', { class: 'grow', style: { flex: 1 } }), h('div', { class: 'find tbar', style: { position: 'relative', padding: 0 } }, search), fileIn);
    view.append(h('div', { class: 'fm' }, bar, bar2, box, foot));

    (async () => {
      try {
        st.roots = await call(X, 'roots');
        if (!st.roots.length) return list.replaceChildren(emptyState('folder', 'No folders are shared yet', 'Add a folder to file_roots in Settings > Panel (or run: astra config set file_roots ...) so the file manager has somewhere to start.'));
        rootSel.replaceChildren(...st.roots.map(r => h('option', { value: r.path }, r.path)));
        let start = ''; try { start = sessionStorage.getItem('astra_files_path') || ''; } catch { /* ok */ }
        await load(start && st.roots.some(r => start.toLowerCase().startsWith(r.path.toLowerCase())) ? start : st.roots[0].path);
        rootSel.value = rootOf()?.path || st.roots[0].path;
      } catch (e) { list.replaceChildren(emptyState('alert-circle', 'Could not open the file manager', e.message)); }
    })();
  };
})();
