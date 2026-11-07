'use strict';
/* Pending tasks drawer: installs, updates and other panel jobs that run one after another (Settings > Panel: how many at once). */
(() => {
  window.ASTRA_UI = window.ASTRA_UI || {};
  const A = window.ASTRA, { h, I, req, toast, badge, ago } = A;
  const LABEL = { queued: 'Waiting', running: 'Running', done: 'Done', failed: 'Failed', cancelled: 'Cancelled' };
  const LEVEL = { queued: 'warn', running: '', done: 'ok', failed: 'bad', cancelled: '' };
  let timer = null;

  function open() {
    const list = h('div', { class: 'col', style: { gap: '.5rem' } }), foot = h('div', { class: 'row', style: { justifyContent: 'space-between' } });
    const m = A.drawer({ title: 'Tasks', icon: 'tasks', body: [h('p', { class: 'muted small' }, 'Installs, removals and updates wait here and run one after another so a small server is not overloaded. Console commands run straight away and are not listed.'), list, foot], actions: [{ label: 'Close', primary: true }], onclose: () => clearInterval(timer) });
    const paint = async () => {
      let r; try { r = await req('api/jobs'); } catch { return; }
      A.state.jobs = r.jobs;
      const jobs = r.jobs.filter(j => j.kind !== 'console');
      list.replaceChildren(...(jobs.length ? jobs.map(j => h('div', { class: 'job-row' },
        h('div', { class: 'grow' }, h('div', { class: 'row' }, h('strong', {}, j.title), badge(j.state, LEVEL[j.state], j.state === 'queued' ? `Waiting #${j.queue_pos}` : LABEL[j.state] || j.state)),
          h('div', { class: 'muted small' }, j.state === 'queued' ? 'Starts when the task before it finishes' : (j.state === 'running' ? 'Started ' : 'Finished ') + ago(j.state === 'running' ? j.started : j.ended || j.started) + (j.steps > 1 ? ` · step ${j.step}/${j.steps}` : '')),
          j.state === 'running' ? h('progress', { max: 100, value: j.pct == null ? undefined : j.pct, 'aria-label': 'Progress of ' + j.title }) : null),
        h('button', { type: 'button', class: 'sm', onclick: () => { m.close(); A.watchJob(j.id, j.title); } }, I('terminal'), 'Output'),
        j.state === 'queued' || j.state === 'running' ? h('button', { type: 'button', class: 'sm danger', onclick: async () => { try { await req(`api/jobs/${j.id}/cancel`, 'POST'); paint(); } catch (e) { toast(e.message, true); } } }, I('x'), 'Cancel') : null))
        : [A.emptyState('check-circle', 'Nothing pending', 'Installs, updates and removals you start will show up here.')]));
      const seg = h('div', { class: 'seg', role: 'group', 'aria-label': 'Tasks at once' }, [1, 2, 3, 4].map(n => h('button', { type: 'button', 'aria-pressed': r.limit === n, onclick: async () => { try { await req('api/jobs/limit', 'POST', { n }); toast(`Up to ${n} task${n > 1 ? 's' : ''} at once`); paint(); } catch (e) { toast(e.message, true); } } }, String(n))));
      foot.replaceChildren(h('div', { class: 'row' }, h('span', { class: 'muted small' }, 'Run at once'), seg),
        h('button', { type: 'button', class: 'sm ghost', onclick: async () => { await req('api/jobs/clear', 'POST'); paint(); } }, I('trash'), 'Clear finished'));
    };
    paint(); timer = setInterval(() => { if (!document.hidden) paint(); }, 2000);
  }
  window.ASTRA_UI.tasks = { open };
})();
