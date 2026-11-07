'use strict';
/* Settings: a left list of sections (shortcuts) and one pane at a time. To add a section from an extension or another
   module:  ASTRA.settingsTabs.push({ id: 'mine', title: 'Mine', icon: 'cog', group: 'Panel', build: (el, ASTRA) => { el.append(...) } }) */
(() => {
  window.ASTRA_UI = window.ASTRA_UI || {};
  const A = window.ASTRA, { h, I, req, card, kv, toast, badge, saveBlob } = A, TH = window.ASTRA_THEME;
  const row = (label, ...c) => h('div', { class: 'row', style: { justifyContent: 'space-between', flexWrap: 'nowrap', gap: '1rem' } }, h('span', {}, label), ...c);
  const saveBtn = (fn, label = 'Save changes') => { const b = h('button', { type: 'button', class: 'primary', onclick: async () => { b.disabled = true; try { await fn(); } catch (e) { toast(e.message, true); } finally { b.disabled = false; } } }, I('save'), label); return b; };
  const loadSettings = () => req('/api/settings');
  const restartAsk = async () => { if (await A.confirm({ title: 'Restart the panel?', text: 'The page reconnects by itself in a few seconds. Running installs are stopped.', ok: 'Restart', icon: 'restart' })) { try { await req('/api/panel/restart', 'POST'); toast('Restarting…'); setTimeout(() => location.reload(), 4000); } catch (e) { toast(e.message, true); } } };

  const tabs = [
    { id: 'account', title: 'Account', icon: 'user', desc: 'The administrator login for this panel.', async build(el) {
      const me = A.me || {};
      const f = A.fields.grid([{ name: 'current', label: 'Current password', type: 'password', required: true, wide: true }, { name: 'username', label: 'Username', value: me.user, required: true }, { name: 'new_password', label: 'New password', type: 'password', help: 'Leave empty to keep the current one. At least 10 characters.' }, { name: 'again', label: 'Repeat new password', type: 'password' }]);
      el.append(card('Sign-in details', h('p', { class: 'card-d' }, 'There is one administrator account today. Other signed-in browsers are signed out when you change these.'), f.el,
        h('div', { class: 'form-foot' }, saveBtn(async () => {
          const v = f.values(); if (!v.current) return toast('Enter your current password', true);
          if (v.new_password && v.new_password !== v.again) return toast('The two new passwords differ', true);
          const r = await req('/api/account/update', 'POST', { current: v.current, username: v.username, new_password: v.new_password });
          A.me.user = r.user; toast('Account updated'); f.built.forEach(b => { if (b.f.type === 'password') b.input.value = ''; });
        }))));
    } },
    { id: 'security', title: 'Two-step sign-in', icon: 'shield-check', desc: 'Ask for a second code at sign-in.', async build(el) {
      const box = h('div', { class: 'col' }); el.append(box);
      const paint = async () => {
        const st = await req('/api/mfa/status');
        const totp = card('Authenticator app', h('p', { class: 'card-d' }, 'Use Google Authenticator, Microsoft Authenticator, Aegis, 1Password, and similar apps.'), row(st.totp ? 'Enabled' : 'Not set up', badge('', st.totp ? 'ok' : '', st.totp ? 'On' : 'Off')),
          h('div', { class: 'form-foot' }, st.totp ? h('button', { type: 'button', class: 'danger', onclick: async () => { if (await A.confirm({ title: 'Turn off the authenticator app?', text: 'Sign-in will no longer ask for an app code.', ok: 'Turn off', danger: true })) { await req('/api/mfa/disable', 'POST', { method: 'totp' }); toast('Turned off'); paint(); } } }, 'Turn off')
            : h('button', { type: 'button', class: 'primary', onclick: async () => {
              try {
                const b = await req('/api/mfa/totp/begin', 'POST');
                const code = h('input', { inputmode: 'numeric', maxlength: 7, placeholder: '123 456', autocomplete: 'one-time-code', 'aria-label': 'Code from the app' });
                const m = A.modal({ title: 'Set up the authenticator app', icon: 'shield-check', body: [h('p', { class: 'muted' }, 'In your authenticator app choose “enter a setup key” (or “add by link”) and use these details:'), A.kv([['Setup key', h('code', {}, b.secret)], ['Type', 'Time based, 6 digits, 30 s']]),
                  h('a', { href: b.uri, class: 'small' }, 'Open in an app on this device'), h('div', { class: 'field' }, h('label', {}, 'Then enter the 6-digit code it shows', code))],
                  actions: [{ label: 'Cancel', value: false }, { label: 'Verify and turn on', primary: true, onclick: async () => { await req('/api/mfa/totp/confirm', 'POST', { code: code.value }); toast('Authenticator app is on'); paint(); } }] });
                code.focus();
              } catch (e) { toast(e.message, true); }
            } }, I('plus'), 'Set up')));
        const em = h('input', { type: 'email', placeholder: 'you@example.com', 'aria-label': 'E-mail address' });
        const email = card('E-mail code', h('p', { class: 'card-d' }, 'A one-time code is mailed to you at sign-in.'),
          !st.smtp_configured ? h('div', { class: 'notice warn' }, I('alert'), h('div', {}, h('h3', {}, 'No mail server set up'), h('p', {}, 'Add SMTP details to the panel configuration first (see docs/SECURITY.md), then come back.'))) : null,
          row(st.email ? 'Sent to ' + st.email_address : 'Not set up', badge('', st.email ? 'ok' : '', st.email ? 'On' : 'Off')),
          h('div', { class: 'form-foot' }, st.email ? h('button', { type: 'button', class: 'danger', onclick: async () => { await req('/api/mfa/disable', 'POST', { method: 'email' }); toast('Turned off'); paint(); } }, 'Turn off')
            : st.smtp_configured ? [h('div', { class: 'grow' }, em), h('button', { type: 'button', class: 'primary', onclick: async () => {
              try { await req('/api/mfa/email/begin', 'POST', { email: em.value });
                const code = h('input', { inputmode: 'numeric', maxlength: 7, 'aria-label': 'Code from the e-mail' });
                A.modal({ title: 'Check your inbox', icon: 'mail', body: [h('p', { class: 'muted' }, 'We sent a 6-digit code to ' + em.value + '.'), h('div', { class: 'field' }, h('label', {}, 'Code', code))], actions: [{ label: 'Cancel', value: false }, { label: 'Verify', primary: true, onclick: async () => { await req('/api/mfa/email/confirm', 'POST', { code: code.value }); toast('E-mail codes are on'); paint(); } }] });
                code.focus();
              } catch (e) { toast(e.message, true); } } }, I('mail'), 'Send code')] : null));
        box.replaceChildren(totp, email);
      };
      await paint();
    } },
    { id: 'appearance', title: 'Appearance', icon: 'sun', desc: 'Looks of this browser only.', build(el) {
      const P = TH.prefs, mk = (k, v, label, extra) => h('button', { type: 'button', class: extra || '', 'aria-pressed': P[k] === v, onclick: e => { TH.set(k, v); A.paintTheme(); el.querySelectorAll(`[data-k="${k}"]`).forEach(b => b.setAttribute('aria-pressed', b.dataset.v === v)); A.state.paintRail && A.state.paintRail(); } }, label);
      const seg = (k, opts) => h('div', { class: 'seg', role: 'group' }, opts.map(([v, l]) => { const b = mk(k, v, l); b.dataset.k = k; b.dataset.v = v; return b; }));
      const preview = { system: ['#0e1116', '#f5f6fa', '#6d7bff'], daylight: ['#fff', '#f3f4f8', '#4f5bff'], graphite: ['#12151b', '#1d222b', '#6d7bff'], midnight: ['#0b0f29', '#161c47', '#7aa8ff'], forest: ['#101a15', '#1b2b23', '#5fe39c'], contrast: ['#000', '#fff', '#ffe600'] };
      const names = { system: 'Match my device', daylight: 'Light', graphite: 'Graphite', midnight: 'Midnight', forest: 'Forest', contrast: 'High contrast' };
      const themes = h('div', { class: 'themes' }, TH.THEMES.map(t => { const b = mk('theme', t, [h('div', { class: 'pv' }, preview[t].map(c => { const i = h('i'); i.style.background = c; return i; })), names[t]], 'theme-opt'); b.dataset.k = 'theme'; b.dataset.v = t; return b; }));
      const sw = h('div', { class: 'swatches' }, [['indigo', '#6d7bff'], ['blue', '#3b8cff'], ['emerald', '#17b57c'], ['rose', '#ef5a8a'], ['amber', '#f0a020']].map(([v, c]) => { const b = h('button', { type: 'button', class: 'swatch', title: v, 'aria-label': v + ' accent', 'aria-pressed': P.accent === v, onclick: () => { TH.set('accent', v); sw.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', x === b)); } }); b.style.background = c; return b; }));
      el.append(card('Theme', themes), card('Accent colour', sw),
        card('Layout', h('div', { class: 'col' }, row('Text size', seg('size', [['s', 'Small'], ['m', 'Medium'], ['l', 'Large']])), row('Density', seg('density', [['cozy', 'Comfortable'], ['compact', 'Compact']])), row('Sidebar', seg('sidebar', [['full', 'Full'], ['rail', 'Icons only']])), row('Animations', seg('motion', [['on', 'On'], ['off', 'Off']])))),
        h('div', { class: 'row' }, h('button', { type: 'button', onclick: () => { TH.reset(); A.paintTheme(); A.state.paintRail && A.state.paintRail(); A.go('settings', 'appearance'); } }, I('restart'), 'Reset to defaults')));
    } },
    { id: 'panel', title: 'Panel and network', icon: 'server', desc: 'Where the panel listens and who may reach it.', async build(el) {
      const s = await loadSettings();
      const f = A.fields.grid([{ name: 'host', label: 'Listen address', value: s.host, help: '127.0.0.1 = only this machine (recommended behind HTTPS). 0.0.0.0 = every network.' }, { name: 'port', label: 'Port', type: 'number', value: s.port },
        { name: 'allowed_ips', label: 'Allowed IP addresses', value: s.allowed_ips.join(', '), wide: true, placeholder: 'empty = anyone who can sign in', help: 'Comma separated addresses or networks, e.g. 203.0.113.7, 10.0.0.0/24. You are connecting from ' + s.your_ip + '.' },
        { name: 'session_ttl_hours', label: 'Stay signed in for (hours)', type: 'number', value: s.session_ttl_hours }, { name: 'tls_cert', label: 'HTTPS certificate file', value: s.tls_cert, placeholder: '/etc/letsencrypt/live/…/fullchain.pem' }, { name: 'tls_key', label: 'HTTPS key file', value: s.tls_key }]);
      el.append(card('Network', f.el, h('div', { class: 'form-foot' }, saveBtn(async () => { const r = await req('/api/settings', 'POST', f.values()); toast('Saved'); if (r.restart_needed) restartAsk(); }), h('button', { type: 'button', onclick: restartAsk }, I('restart'), 'Restart panel'))),
        card('Addresses', kv([['Open the panel at', h('div', { class: 'col' }, s.urls.map(u => h('a', { href: u }, u)))], ['Encrypted (HTTPS)', s.tls ? 'Yes' : 'No: passwords travel in clear text unless a reverse proxy adds HTTPS']])));
    } },
    { id: 'console', title: 'Console', icon: 'terminal', desc: 'The built-in terminal.', async build(el) {
      const s = await loadSettings(), on = h('input', { type: 'checkbox', checked: s.console_enabled, id: 'con-on' });
      el.append(card('Console access', h('p', { class: 'card-d' }, 'The console runs commands as the user the panel runs as, so anyone who can sign in can do almost anything on this server. Turn it off if you only use the panel for monitoring. Every command is written to the audit log.'),
        h('div', { class: 'field check' }, on, h('label', { for: 'con-on' }, 'Enable the console (Ctrl+` opens it)')), h('div', { class: 'form-foot' }, saveBtn(async () => { await req('/api/settings', 'POST', { console_enabled: on.checked }); A.me.console = on.checked; toast('Saved. Reload the page to see the change.'); }))));
    } },
    { id: 'alerts', title: 'Alerts', icon: 'bell', desc: 'When resource usage becomes a notification.', async build(el) {
      const s = await loadSettings();
      const f = A.fields.grid([['cpu', 'CPU'], ['mem', 'Memory'], ['disk', 'Disk']].map(([k, l]) => ({ name: k, label: l + ' alert at (%)', type: 'number', min: 0, max: 100, value: s.alerts[k], help: '0 turns this alert off' })));
      el.append(card('Resource alerts', h('p', { class: 'card-d' }, 'You get one notification when a limit is crossed and one when it recovers, never a stream of repeats.'), f.el, h('div', { class: 'form-foot' }, saveBtn(async () => { await req('/api/settings', 'POST', { alerts: f.values() }); toast('Saved'); }))));
    } },
    { id: 'privacy', title: 'Privacy and data', icon: 'lock', desc: 'What the panel stores and how to take it out.', async build(el) {
      const s = await loadSettings();
      const f = A.fields.grid([{ name: 'name', label: 'Operator name', value: s.operator.name }, { name: 'email', label: 'Operator e-mail', value: s.operator.email }, { name: 'address', label: 'Operator address', value: s.operator.address, wide: true }]);
      el.append(card('Who runs this panel', h('p', { class: 'card-d' }, 'Shown on the privacy page so people who use this server know who to contact.'), f.el, h('div', { class: 'form-foot' }, saveBtn(async () => { await req('/api/settings', 'POST', { operator: f.values() }); toast('Saved'); }))),
        card('Your data', h('p', { class: 'card-d' }, `Stored in ${s.home}: settings, the audit log (kept ${s.audit_retention_days || 'forever'} days) and notifications. Sessions live in memory only.`),
          h('div', { class: 'row' }, h('button', { type: 'button', onclick: async () => { try { const d = await req('/api/privacy/export'); saveBlob(new Blob([JSON.stringify(d, null, 2)], { type: 'application/json' }), 'astra-export.json'); } catch (e) { toast(e.message, true); } } }, I('download'), 'Export my data'),
            h('button', { type: 'button', class: 'danger', onclick: async () => { const v = await A.prompt({ title: 'Delete the audit log?', label: 'Type delete to confirm', ok: 'Delete', help: 'This erases the audit history and two-step settings.' }); if (v === 'delete') { try { await req('/api/privacy/delete', 'POST', { confirm: 'delete' }); toast('Deleted'); } catch (e) { toast(e.message, true); } } } }, I('trash'), 'Delete audit log'),
            h('a', { href: '/legal/privacy' }, 'Privacy notice'))));
    } },
    { id: 'about', title: 'About', icon: 'info', desc: 'Version and where things live.', async build(el) {
      const s = await loadSettings();
      el.append(card('astra', kv([['Version', s.version], ['System', s.os], ['Config folder', h('code', {}, s.home)], ['Terms', h('a', { href: '/legal/terms' }, 'Read the terms')]])));
    } },
  ];
  A.settingsTabs.unshift(...tabs);

  window.ASTRA_UI.settings = (view, A2) => {
    const list = A2.settingsTabs, byId = Object.fromEntries(list.map(t => [t.id, t]));
    let cur = byId[A2.state.sub] ? A2.state.sub : list[0].id;
    const nav = h('nav', { class: 'snav', 'aria-label': 'Settings sections' }), pane = h('div', { class: 'spane' });
    const draw = async () => {
      const t = byId[cur];
      nav.replaceChildren(...list.map(x => h('button', { type: 'button', 'aria-current': x.id === cur ? 'page' : 'false', onclick: () => { cur = x.id; A2.state.sub = cur; history.replaceState(null, '', '#settings/' + cur); draw(); } }, I(x.icon || 'cog'), x.title)));
      pane.replaceChildren(h('div', {}, h('h2', { style: { fontSize: '1.15rem' } }, t.title), t.desc ? h('p', { class: 'muted' }, t.desc) : null), A2.skeleton(2));
      const body = h('div', { class: 'spane' });
      try { await t.build(body, A2); pane.replaceChildren(pane.firstChild, body); } catch (e) { pane.replaceChildren(pane.firstChild, h('div', { class: 'notice bad' }, I('alert-circle'), h('div', {}, h('h3', {}, 'Could not load this section'), h('p', {}, e.message)))); }
    };
    view.append(A2.pageHead('settings', 'Settings', 'Account, security, appearance and the panel itself.'), h('div', { class: 'settings' }, nav, pane));
    draw();
  };
})();
