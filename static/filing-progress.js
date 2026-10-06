(() => {
  const notice = document.getElementById('progress-update');
  if (!notice) return;
  const selectors = ['.status-bar', '.stage-rail', 'nav[aria-label="Work order sections"]', '#submission-review', '.document-list'];
  const dirty = new WeakSet();
  document.addEventListener('input', e => {
    const section = e.target.closest('#submission-review');
    if (section) dirty.add(section);
  });
  document.addEventListener('change', e => {
    const section = e.target.closest('#submission-review');
    if (section) dirty.add(section);
  });
  let submitting = false;
  document.addEventListener('submit', () => { submitting = true; });
  async function update() {
    try {
      if (document.hidden || submitting) return;
      const response = await fetch(notice.dataset.progressUrl, {
        credentials: 'same-origin', cache: 'no-store', redirect: 'error',
        signal: AbortSignal.timeout(8000)
      });
      if (!response.ok) throw new Error('Unavailable');
      const page = new DOMParser().parseFromString(await response.text(), 'text/html');
      if (!page.getElementById('progress-update')) throw new Error('Invalid page');
      if (submitting) return;
      const x = window.scrollX, y = window.scrollY;
      for (const selector of selectors) {
        const current = document.querySelector(selector), next = page.querySelector(selector);
        if (!current || !next || dirty.has(current) || current.contains(document.activeElement)) continue;
        // Rotating CSRF tokens alone must not replace an unchanged form.
        const before = current.cloneNode(true), after = next.cloneNode(true);
        for (const node of [before, after]) {
          node.querySelectorAll('[name="csrfmiddlewaretoken"]').forEach(el => el.remove());
        }
        if (before.outerHTML !== after.outerHTML) current.replaceWith(next);
      }
      window.scrollTo({left: x, top: y, behavior: 'instant'});
      notice.textContent = 'Progress updates in the background every 10 seconds. Keep the VM worker running.';
    } catch (_) {
      notice.textContent = 'Progress updates unavailable. Retrying automatically; refresh if your session has expired.';
    } finally {
      window.setTimeout(update, 10000);
    }
  }
  window.setTimeout(update, 10000);
})();
