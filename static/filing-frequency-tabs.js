(() => {
  const groups = [['monthly', 'Monthly'], ['quarterly', 'Quarterly'], ['annual', 'Annual'], ['special', 'Special filing']];
  const category = value => {
    const normalized = (value || '').trim().toLowerCase();
    if (['monthly', 'month'].includes(normalized)) return 'monthly';
    if (['quarterly', 'quarter'].includes(normalized)) return 'quarterly';
    if (['annual', 'annually', 'yearly'].includes(normalized)) return 'annual';
    return 'special';
  };
  document.querySelectorAll('[data-filing-tabs]').forEach((root, index) => {
    if (root.dataset.frequencyReady) return;
    root.dataset.frequencyReady = 'true';
    const cards = [...root.querySelectorAll('[data-filing-frequency]')];
    if (!cards.length) return;
    const nav = root.querySelector('[data-frequency-nav]');
    const empty = root.querySelector('[data-frequency-empty]');
    const grid = root.querySelector('[data-frequency-grid], .client-cards');
    const entries = groups.map(([key, label]) => ({key, label, cards: cards.filter(card => category(card.dataset.filingFrequency) === key)}));
    const buttons = entries.map(({key, label, cards: members}) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'tab';
      button.id = `filing-frequency-${index}-${key}`;
      button.setAttribute('role', 'tab');
      button.setAttribute('aria-controls', `filing-frequency-panel-${index}`);
      button.append(document.createTextNode(label + ' '));
      const count = document.createElement('span');
      count.className = 'tab-count';
      count.textContent = members.length;
      button.append(count);
      nav.append(button);
      return button;
    });
    grid.id = `filing-frequency-panel-${index}`;
    grid.setAttribute('role', 'tabpanel');
    grid.tabIndex = 0;
    const select = selected => {
      buttons.forEach((button, i) => {
        button.setAttribute('aria-selected', String(i === selected));
        button.tabIndex = i === selected ? 0 : -1;
      });
      cards.forEach(card => { card.hidden = !entries[selected].cards.includes(card); });
      grid.setAttribute('aria-labelledby', buttons[selected].id);
      empty.textContent = `No ${entries[selected].label.toLowerCase()} forms for this client.`;
      empty.hidden = entries[selected].cards.length !== 0;
    };
    buttons.forEach((button, i) => {
      button.addEventListener('click', () => select(i));
      button.addEventListener('keydown', event => {
        let next;
        if (event.key === 'ArrowRight') next = (i + 1) % buttons.length;
        if (event.key === 'ArrowLeft') next = (i + buttons.length - 1) % buttons.length;
        if (event.key === 'Home') next = 0;
        if (event.key === 'End') next = buttons.length - 1;
        if (next === undefined) return;
        event.preventDefault();
        select(next);
        buttons[next].focus();
      });
    });
    nav.hidden = false;
    select(Math.max(0, entries.findIndex(entry => entry.cards.length)));
  });
})();
