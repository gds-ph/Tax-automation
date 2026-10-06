(() => {
  const search = document.querySelector('[data-form-search]');
  if (!search) return;
  const cards = [...document.querySelectorAll('[data-form-search-text]')];
  if (!cards.length) return;
  const input = search.querySelector('input');
  const status = search.querySelector('[data-form-search-status]');
  search.hidden = false;
  const update = () => {
    const terms = input.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
    let count = 0;
    for (const card of cards) {
      const text = card.dataset.formSearchText.toLocaleLowerCase();
      const matches = terms.every(term => text.includes(term));
      card.hidden = !matches;
      if (matches) count++;
    }
    status.textContent = count ? `${count} of ${cards.length} forms shown` : 'No forms match your search. Try another form number or name.';
  };
  input.addEventListener('input', update);
  update();
})();
