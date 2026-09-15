(async function () {
  const csrf = document.querySelector('#cor-auto-csrf input')?.value;
  const seen = new Set();
  for (const section of document.querySelectorAll('.cor-auto-source')) {
    async function scan() {
      section.replaceChildren();
      const status = document.createElement('p');
      status.className = 'notice';
      status.setAttribute('role', 'status');
      status.textContent = 'Reading certificate and identifying filings…';
      section.append(status);
      try {
        const response = await fetch(section.dataset.endpoint, {
          method: 'POST', headers: {'X-CSRFToken': csrf},
          body: new URLSearchParams({token: section.dataset.token, cards: '1'})
        });
        if (!response.ok || response.redirected) throw new Error('Scan unavailable');
        const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
        const content = doc.querySelector('[data-cor-digest]');
        if (!content) throw new Error('No card response');
        if (seen.has(content.dataset.corDigest)) { section.remove(); return; }
        seen.add(content.dataset.corDigest);
        section.replaceChildren(document.importNode(content, true));
      } catch (_) {
        status.textContent = 'This certificate could not be read. Other certificates will continue.';
        const retry = document.createElement('button');
        retry.type = 'button'; retry.className = 'button secondary'; retry.textContent = 'Retry';
        retry.addEventListener('click', scan, {once: true}); section.append(retry);
      }
    }
    await scan();
  }
})();
