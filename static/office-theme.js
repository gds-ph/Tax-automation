(() => {
  const root = document.documentElement;
  // Theme shade and accent colour, applied before first paint so a page never
  // flashes the wrong look. "system" removes data-theme, which lets the
  // stylesheet's prefers-color-scheme rule decide. Blue is the default accent.
  const THEMES = ['light', 'soft', 'dim', 'dark', 'midnight', 'system'];
  const ACCENTS = ['blue', 'teal', 'green', 'purple', 'orange', 'pink'];
  const applyTheme = mode => {
    if (mode === 'system') delete root.dataset.theme; else root.dataset.theme = mode;
    root.dataset.themeChoice = mode;
  };
  const applyAccent = accent => {
    if (accent === 'blue') delete root.dataset.accent; else root.dataset.accent = accent;
    root.dataset.accentChoice = accent;
  };
  let saved, savedAccent;
  try {
    saved = localStorage.getItem('ebirTheme');
    savedAccent = localStorage.getItem('ebirAccent');
  } catch (_) { /* Storage can be disabled. */ }
  applyTheme(THEMES.includes(saved) ? saved : 'light');
  applyAccent(ACCENTS.includes(savedAccent) ? savedAccent : 'blue');
  let clientView;
  try { clientView = localStorage.getItem('ebirClientView'); } catch (_) { /* Use grid by default. */ }
  root.dataset.clientView = clientView === 'list' ? 'list' : 'grid';
  document.addEventListener('DOMContentLoaded', () => {
    // Keep each tab's client search and position when returning from a client.
    const list = document.getElementById('client-results');
    const returnKey = 'ebirClientListReturn';
    if (list) {
      const url = location.pathname + location.search;
      try {
        const savedList = JSON.parse(sessionStorage.getItem(returnKey) || 'null');
        if (savedList && savedList.url === url && Number.isFinite(savedList.scroll)) {
          requestAnimationFrame(() => window.scrollTo(0, savedList.scroll));
        }
      } catch (_) { /* Navigation works without storage. */ }
      const saveList = () => {
        try { sessionStorage.setItem(returnKey, JSON.stringify({url, scroll: window.scrollY})); }
        catch (_) { /* Navigation works without storage. */ }
      };
      list.addEventListener('click', saveList);
      window.addEventListener('pagehide', saveList);
      saveList();
    }
    document.querySelectorAll('[data-clients-back]').forEach(link => {
      try {
        const savedList = JSON.parse(sessionStorage.getItem(returnKey) || 'null');
        if (!savedList) return;
        const target = new URL(savedList.url, location.origin);
        const fallback = new URL(link.href);
        if (target.origin === location.origin && target.pathname === fallback.pathname) {
          link.href = target.href;
        }
      } catch (_) { /* Retain the ordinary Clients link. */ }
    });
    document.querySelectorAll('.cor-read-form').forEach(form => form.addEventListener('submit', () => {
      form.querySelector('button').disabled = true;
      form.querySelector('.cor-reading').hidden = false;
    }));
    const viewButtons = document.querySelectorAll('button[data-client-view]');
    const updateView = () => viewButtons.forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.clientView === root.dataset.clientView));
    });
    viewButtons.forEach(button => button.addEventListener('click', () => {
      root.dataset.clientView = button.dataset.clientView;
      try { localStorage.setItem('ebirClientView', root.dataset.clientView); } catch (_) { /* Keep this page usable. */ }
      updateView();
    }));
    updateView();
    const themeButtons = document.querySelectorAll('button[data-theme-choice]');
    const updateTheme = () => themeButtons.forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.themeChoice === root.dataset.themeChoice));
    });
    themeButtons.forEach(button => button.addEventListener('click', () => {
      applyTheme(button.dataset.themeChoice);
      try { localStorage.setItem('ebirTheme', button.dataset.themeChoice); } catch (_) { /* Keep this page usable. */ }
      updateTheme();
    }));
    updateTheme();
    const accentButtons = document.querySelectorAll('button[data-accent-choice]');
    const updateAccent = () => accentButtons.forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.accentChoice === root.dataset.accentChoice));
    });
    accentButtons.forEach(button => button.addEventListener('click', () => {
      applyAccent(button.dataset.accentChoice);
      try { localStorage.setItem('ebirAccent', button.dataset.accentChoice); } catch (_) { /* Keep this page usable. */ }
      updateAccent();
    }));
    updateAccent();
    // Record actions: the menu opens a confirmation dialog, then closes itself.
    document.querySelectorAll('[data-open-dialog]').forEach(button => button.addEventListener('click', () => {
      const dialog = document.getElementById(button.dataset.openDialog);
      if (!dialog || typeof dialog.showModal !== 'function') return;
      const menu = button.closest('details');
      if (menu) menu.open = false;
      dialog.showModal();
    }));
    document.querySelectorAll('[data-close-dialog]').forEach(button => button.addEventListener('click', () => {
      button.closest('dialog').close();
    }));
    document.querySelectorAll('dialog.confirm-dialog').forEach(dialog => dialog.addEventListener('click', event => {
      if (event.target === dialog) dialog.close();
    }));
    document.querySelectorAll('[data-action-menu]').forEach(menu => {
      document.addEventListener('click', event => { if (menu.open && !menu.contains(event.target)) menu.open = false; });
      menu.addEventListener('keydown', event => { if (event.key === 'Escape') { menu.open = false; menu.querySelector('summary').focus(); } });
    });
    // The appearance menu stays open while choosing; close it on an outside click or Escape.
    const menu = document.querySelector('[data-appearance]');
    if (menu) {
      document.addEventListener('click', event => { if (menu.open && !menu.contains(event.target)) menu.open = false; });
      document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && menu.open) { menu.open = false; menu.querySelector('summary').focus(); }
      });
    }
  });
})();
