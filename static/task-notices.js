(() => {
  const badge = document.querySelector('[data-task-count]');
  if (!badge) return;
  let busy = false;
  async function refresh() {
    if (busy || document.hidden) return;
    const panel = document.querySelector('[data-task-notices]');
    if (panel && panel.contains(document.activeElement)) return;
    busy = true;
    try {
      const workerPanel = document.querySelector('[data-worker-status]');
      const response = await fetch(badge.dataset.url + (workerPanel ? '?workers=1' : ''), {
        credentials: 'same-origin', redirect: 'error', signal: AbortSignal.timeout(10000)
      });
      if (!response.ok) return;
      const data = await response.json();
      badge.textContent = data.count;
      badge.hidden = data.count === 0;
      badge.setAttribute('aria-label', `${data.count} unread notifications`);
      if (panel) {
        // Replacing the markup would collapse an expanded list mid-read.
        const expanded = panel.querySelector('details.notice-more[open]') !== null;
        panel.innerHTML = data.html;
        const more = panel.querySelector('details.notice-more');
        if (expanded && more) more.open = true;
      }
      if (workerPanel && !workerPanel.contains(document.activeElement) && data.workers_html) workerPanel.innerHTML = data.workers_html;
    } catch (_) {
      // Keep the last displayed state and retry on the next interval.
    } finally { busy = false; }
  }
  refresh();
  setInterval(refresh, 15000);
  document.addEventListener('visibilitychange', refresh);
})();
