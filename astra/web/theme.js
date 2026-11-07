'use strict';
/* Applies saved appearance before first paint (no flash). Prefs live in this browser only. */
(() => {
  const KEY = 'astra_prefs', root = document.documentElement;
  const DEF = { theme: 'system', accent: 'indigo', size: 'm', density: 'cozy', sidebar: 'full', motion: 'on' };
  const THEMES = ['system', 'daylight', 'graphite', 'midnight', 'forest', 'contrast'];
  let prefs = { ...DEF };
  try {
    const mine = JSON.parse(localStorage.getItem(KEY) || 'null');
    if (mine && typeof mine === 'object') Object.assign(prefs, mine);
    else {   // first run after the redesign: carry over the old choices where they still exist
      const old = JSON.parse(localStorage.getItem('mp_prefs') || '{}');
      if (THEMES.includes(old.theme)) prefs.theme = old.theme;
      if (['s', 'm', 'l'].includes(old.size)) prefs.size = old.size;
      if (['cozy', 'compact'].includes(old.density)) prefs.density = old.density;
    }
  } catch { /* storage blocked: defaults */ }
  const dark = () => matchMedia('(prefers-color-scheme: dark)').matches;
  const resolved = () => prefs.theme === 'system' ? (dark() ? 'graphite' : 'daylight') : prefs.theme;
  const apply = () => {
    root.dataset.theme = resolved(); root.dataset.accent = prefs.accent; root.dataset.size = prefs.size;
    root.dataset.density = prefs.density; root.dataset.sidebar = prefs.sidebar; root.dataset.motion = prefs.motion;
    root.style.colorScheme = resolved() === 'daylight' ? 'light' : 'dark';
  };
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch { /* not remembered */ } };
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { if (prefs.theme === 'system') apply(); });
  window.ASTRA_THEME = {
    prefs, THEMES, DEF, resolved,
    set(k, v) { prefs[k] = v; save(); apply(); },
    toggle() { this.set('theme', resolved() === 'daylight' ? (prefs.theme === 'midnight' ? 'midnight' : 'graphite') : 'daylight'); },
    reset() { Object.assign(prefs, DEF); save(); apply(); },
  };
  apply();
})();
