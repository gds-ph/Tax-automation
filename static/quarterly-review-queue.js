document.addEventListener('DOMContentLoaded', () => {
  const button = document.getElementById('eq-review-queue');
  const dialog = document.getElementById('eq-queue-dialog');
  const editor = document.getElementById('eq-editor');
  if (!button || !dialog || !editor) return;
  const snapshot = () => JSON.stringify(Array.from(new FormData(editor).entries()));
  const saved = snapshot();
  dialog.addEventListener('click', event => {
    if (event.target.closest('[data-eq-close]')) dialog.close();
  });
  button.addEventListener('click', async () => {
    dialog.innerHTML = '<h2 id="eq-queue-title">Review and queue</h2><p role="status">Loading saved totals…</p><button type="button" class="button secondary" data-eq-close>Back to worksheet</button>';
    dialog.showModal();
    if (snapshot() !== saved) {
      dialog.querySelector('p').textContent = 'You have unsaved changes. Use Save draft before queueing.';
      return;
    }
    button.disabled = true;
    try {
      const response = await fetch(button.dataset.url, { credentials: 'same-origin' });
      const html = await response.text();
      if (response.redirected || !html.includes('id="eq-queue-title"')) throw new Error('Unavailable');
      dialog.innerHTML = html;
      dialog.querySelector('[data-eq-close]')?.focus();
    } catch (_) {
      dialog.querySelector('p').textContent = 'Unable to load the review. Close this dialog and try again, or refresh to sign in.';
    } finally {
      button.disabled = false;
    }
  });
});
