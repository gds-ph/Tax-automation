(() => {
  const root = document.documentElement;
  let saved;
  try { saved = localStorage.getItem('ebirTheme'); } catch (_) { /* Storage can be disabled. */ }
  root.dataset.theme = saved === 'dark' ? 'dark' : 'light';
  let clientView;
  try { clientView = localStorage.getItem('ebirClientView'); } catch (_) { /* Use grid by default. */ }
  root.dataset.clientView = clientView === 'list' ? 'list' : 'grid';
  document.addEventListener('DOMContentLoaded', () => {
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
    const toggle = document.getElementById('theme-toggle');
    if (!toggle) return;
    const update = () => {
      const dark = root.dataset.theme === 'dark';
      toggle.setAttribute('aria-pressed', String(dark));
      toggle.setAttribute('aria-label', `Switch to ${dark ? 'light' : 'dark'} theme`);
      toggle.title = toggle.getAttribute('aria-label');
    };
    toggle.addEventListener('click', () => {
      root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem('ebirTheme', root.dataset.theme); } catch (_) { /* Keep this page usable. */ }
      update();
    });
    update();
  });
})();
