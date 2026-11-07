'use strict';
/* Web desktop. Loaded only when the Desktop tab is opened. Windows host the other tabs; nothing to install.
   Keyboard: Tab to a title bar, then arrows move the window, Shift+arrows resize it, Esc closes it. */
(() => {
  window.ASTRA_UI = window.ASTRA_UI || {};
  const KEY = 'mp_desktop', STEP = 24;
  window.ASTRA_UI.desktop = (view, ext, ASTRA) => {
    const { h, $, call, card, toast, showText, extView, dashboard, EXT } = ASTRA;
    if (!$('link[href="/ui/desktop.css"]')) document.head.append(h('link', { rel: 'stylesheet', href: '/ui/desktop.css' }));
    const layout = (() => { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch { return {}; } })();
    const save = () => { try { localStorage.setItem(KEY, JSON.stringify(layout)); } catch { /* storage unavailable: layout just isn't remembered */ } };
    const wins = new Map();
    let z = 10, menu = null;
    const area = h('div', { class: 'dsk-area' }), run = h('div', { class: 'run' });
    const clock = h('span', { class: 'muted', 'aria-hidden': 'true' });
    const tick = () => { clock.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); };
    tick(); const clockTimer = setInterval(tick, 30000);

    /* ---- apps: Monitor, every available tab, and the optional Linux GUI ---- */
    const apps = [{ id: 'monitor', title: 'Monitor', icon: '◧', build: b => dashboard(b) },
      ...EXT.filter(e => e.available && !e.ui).map(e => ({ id: e.name, title: e.title, icon: e.icon, build: b => extView(b, e) })),
      { id: 'gui', title: 'Remote GUI (Linux only)', icon: '🖥', build: guiApp }];

    /* ---- windows ---- */
    function focus(w) { wins.forEach(x => { x.el.classList.remove('top'); x.btn.setAttribute('aria-pressed', 'false'); }); w.el.hidden = false; w.el.style.zIndex = ++z; w.el.classList.add('top'); w.btn.setAttribute('aria-pressed', 'true'); }
    function place(w, patch) {
      const s = w.el.style, a = area.getBoundingClientRect();
      if (patch.x !== undefined) s.left = Math.min(Math.max(0, patch.x), Math.max(0, a.width - 80)) + 'px';
      if (patch.y !== undefined) s.top = Math.min(Math.max(0, patch.y), Math.max(0, a.height - 40)) + 'px';
      if (patch.w) s.width = Math.max(288, patch.w) + 'px';
      if (patch.h) s.height = Math.max(144, patch.h) + 'px';
    }
    const remember = w => { const r = w.el, f = layout[w.app.id] = { x: r.offsetLeft, y: r.offsetTop, w: r.offsetWidth, h: r.offsetHeight, max: r.classList.contains('max') }; save(); return f; };
    function close(w) {
      w.timers.forEach(clearInterval); w.el.remove(); w.btn.remove(); wins.delete(w.app.id); area.focus();
    }
    function open(app) {
      closeMenu();
      if (wins.has(app.id)) return focus(wins.get(app.id));
      const tid = 'dsk-t-' + app.id, body = h('div', { class: 'dsk-body' }), w = { app, timers: [] };
      const move = (dx, dy, dw, dh) => { place(w, { x: w.el.offsetLeft + dx, y: w.el.offsetTop + dy, w: dw ? w.el.offsetWidth + dw : 0, h: dh ? w.el.offsetHeight + dh : 0 }); remember(w); };
      const bar = h('div', { class: 'dsk-bar', tabindex: '0', role: 'group', 'aria-label': `${app.title} window. Arrow keys move, Shift plus arrow keys resize, Escape closes`,
        onkeydown: ev => {
          const d = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[ev.key];
          if (d) { ev.preventDefault(); ev.shiftKey ? move(0, 0, d[0] * STEP, d[1] * STEP) : move(d[0] * STEP, d[1] * STEP, 0, 0); }
          else if (ev.key === 'Escape') close(w);
        },
        onpointerdown: ev => {
          if (ev.target.closest('button') || w.el.classList.contains('max')) return;
          const sx = ev.clientX - w.el.offsetLeft, sy = ev.clientY - w.el.offsetTop;
          bar.setPointerCapture(ev.pointerId);
          const mv = e => place(w, { x: e.clientX - sx, y: e.clientY - sy });
          const up = () => { bar.removeEventListener('pointermove', mv); bar.removeEventListener('pointerup', up); remember(w); };
          bar.addEventListener('pointermove', mv); bar.addEventListener('pointerup', up);
        } },
        h('span', { id: tid }, app.icon + ' ' + app.title),
        h('button', { type: 'button', 'aria-label': `Minimize ${app.title}`, onclick: () => { w.el.hidden = true; w.btn.setAttribute('aria-pressed', 'false'); w.btn.focus(); } }, '–'),
        h('button', { type: 'button', 'aria-label': `Maximize or restore ${app.title}`, onclick: () => { w.el.classList.toggle('max'); remember(w); } }, '□'),
        h('button', { type: 'button', class: 'danger', 'aria-label': `Close ${app.title}`, onclick: () => close(w) }, '✕'));
      w.el = h('section', { class: 'dsk-win', tabindex: '-1', 'aria-labelledby': tid, onpointerdown: () => focus(w) }, bar, body);
      w.btn = h('button', { type: 'button', 'aria-pressed': 'false', onclick: () => (w.el.hidden || !w.el.classList.contains('top')) ? focus(w) : (w.el.hidden = true, w.btn.setAttribute('aria-pressed', 'false')) }, app.icon + ' ' + app.title);
      const n = wins.size, f = layout[app.id] || { x: 24 + n * 28, y: 16 + n * 28, w: 620, h: 420 };
      area.append(w.el); run.append(w.btn); wins.set(app.id, w);
      place(w, f); if (f.max) w.el.classList.add('max');
      const t0 = ASTRA.timers.length; app.build(body); w.timers = ASTRA.timers.splice(t0);  // own this window's refresh timers
      focus(w); bar.focus();
    }

    /* ---- start menu ---- */
    function closeMenu() { if (menu) { menu.remove(); menu = null; start.setAttribute('aria-expanded', 'false'); } }
    const start = h('button', { type: 'button', class: 'primary', 'aria-haspopup': 'menu', 'aria-expanded': 'false', onclick: () => {
      if (menu) return closeMenu();
      menu = h('div', { class: 'dsk-menu', role: 'menu', onkeydown: ev => {
        const items = [...menu.querySelectorAll('button')], i = items.indexOf(document.activeElement);
        if (ev.key === 'Escape') { closeMenu(); start.focus(); } else if (ev.key === 'ArrowDown') { ev.preventDefault(); items[(i + 1) % items.length].focus(); } else if (ev.key === 'ArrowUp') { ev.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
      } }, apps.map(a => h('button', { type: 'button', role: 'menuitem', onclick: () => open(a) }, a.icon + ' ' + a.title)));
      start.setAttribute('aria-expanded', 'true'); dsk.append(menu); menu.querySelector('button').focus();
    } }, '▦ Start');

    const dsk = h('div', { class: 'dsk', role: 'region', 'aria-label': 'Desktop' }, area, h('div', { class: 'dsk-task' }, start, run, clock));
    area.tabIndex = -1;
    view.append(dsk);
    ASTRA.onLeave(() => { clearInterval(clockTimer); wins.forEach(w => w.timers.forEach(clearInterval)); });
    if (!Object.keys(layout).length) open(apps[0]);

    /* ---- optional Linux GUI: nothing is installed until you confirm ---- */
    function guiApp(body) {
      const out = h('div');
      body.append(out);
      const draw = async () => {
        let s;
        try { s = await call('desktop', 'status'); } catch (e) { return out.replaceChildren(h('p', { class: 'bad', role: 'alert' }, e.message)); }
        const checks = h('ul', {}, s.checks.map(c => h('li', { class: c.ok ? 'ok' : 'bad' }, (c.ok ? '✓ ' : '✗ ') + c.label + ' (' + c.detail + ')')));
        if (s.supported === false) return out.replaceChildren(card('Remote GUI session is Linux-only',
          h('p', {}, 'The web desktop around this window works on every system. The optional graphical session (TigerVNC + Openbox) is only available on Linux servers. On Windows use Remote Desktop (RDP), ideally through an SSH tunnel or VPN.'), checks));
        if (!s.installed) {
          const log = h('pre', { hidden: true, 'aria-live': 'polite' });
          const go = h('button', { class: 'primary', disabled: !s.can_install, onclick: async () => {
            if (!confirm('Install ' + s.packages.join(', ') + ' with apt?\n\n' + s.size_note + '.\nThis can take several minutes on a slow server and nothing else is changed. Continue?')) return;
            go.disabled = true; log.hidden = false;
            try { await call('desktop', 'install', {}, 'POST'); } catch (e) { toast(e.message, true); go.disabled = false; return; }
            const poll = setInterval(async () => {
              if (!body.isConnected) return clearInterval(poll);  // window closed
              try { const r = await call('desktop', 'install_log'); log.textContent = r.text || 'Working…'; log.scrollTop = log.scrollHeight;
                if (!r.running) { clearInterval(poll); r.installed ? (toast('Installed'), draw()) : (toast('Install failed, see the log', true), go.disabled = false); } } catch { clearInterval(poll); }
            }, 2000);
            ASTRA.timers.push(poll);
          } }, 'Install…');
          return out.replaceChildren(card('Linux desktop is not installed',
            h('p', {}, 'The web desktop around this window works without it. This optional part gives you a real graphical Linux session (Openbox + a terminal) in a browser tab. It needs extra packages, so nothing is installed until you confirm.'),
            checks, h('p', { class: 'muted' }, s.size_note + '. Memory-capped and run as an unprivileged user.'), go, log));
        }
        const act = (label, route, danger) => h('button', { class: danger ? 'danger' : 'primary', onclick: async ev => {
          ev.target.disabled = true;
          try { const r = await call('desktop', route, {}, 'POST');
            if (r.password) showText('Linux desktop started', `1. On your computer run:\n   ${r.tunnel}\n2. Open ${r.url}\n3. Password (shown once): ${r.password}\n\nSession user: ${r.user}`);
            else toast(label + ': done'); } catch (e) { toast(e.message, true); }
          draw(); } }, label);
        out.replaceChildren(card('Linux desktop', h('p', {}, s.running ? '● Running (127.0.0.1:6080, reach it through an SSH tunnel)' : s.partial ? '! Partly running: press Stop, then Start' : '○ Stopped'),
          s.user ? h('p', { class: 'muted' }, 'Session user: ' + s.user) : h('p', { class: 'warn' }, 'Set a user first: astra config set desktop \'{"user":"alice"}\''),
          h('div', { class: 'row' }, s.running ? null : act('Start', 'start'), s.running || s.partial ? act('Stop', 'stop', true) : null), checks));
      };
      draw();
    }
  };
})();
