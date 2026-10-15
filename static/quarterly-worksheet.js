(() => {
  const catalog = new Map(JSON.parse(document.getElementById('eq-catalog').textContent).map(x => [x.code, x]));
  const body = document.getElementById('eq-rows'), total = document.getElementById('id_rows-TOTAL_FORMS');
  const format = input => { const raw = input.value.replaceAll(',', '').trim(); if (/^\d+(\.\d{1,2})?$/.test(raw)) input.value = Number(raw).toLocaleString('en-PH', {minimumFractionDigits: 2, maximumFractionDigits: 2}); };
  function bind(row) {
    const atc = row.querySelector('[name$="-atc"]'), rate = row.querySelector('[data-rate]');
    const update = () => { rate.value = catalog.get(atc.value.trim().toUpperCase())?.rate || ''; };
    atc.addEventListener('input', update); update();
    const base = row.querySelector('[name$="-base"]'); format(base); base.addEventListener('blur', () => format(base));
    const deleted = row.querySelector('[name$="-DELETE"]'); row.hidden = deleted.checked;
    row.querySelector('[data-remove]').addEventListener('click', () => { deleted.checked = true; row.hidden = true; });
  }
  function appendRow(month) {
    const index = Number(total.value);
    body.insertAdjacentHTML('beforeend', document.getElementById('eq-empty').innerHTML.replaceAll('__prefix__', index));
    total.value = index + 1;
    const row = body.lastElementChild; bind(row); row.querySelector('select').value = month;
    return row;
  }
  const pasteStatus = document.getElementById('eq-paste-status');
  body.addEventListener('paste', event => {
    const input = event.target.closest('input');
    if (!input || input.readOnly || !input.name) return;
    const text = event.clipboardData?.getData('text/plain') || '';
    if (!/[\t\r\n]/.test(text)) return;
    event.preventDefault();
    try {
      const cells = window.eqExcelPaste.parse(text);
      const field = input.name.replace(/^rows-\d+-/, '');
      const editable = ['payee', 'tin', 'atc', 'base', 'reference'];
      if (!editable.includes(field)) return;
      let fields;
      if (cells[0].length === 1) fields = [field];
      else if (field === 'payee' && cells[0].length === 7) fields = ['payee', 'tin', 'atc', 'base', null, null, 'reference'];
      else if (field === 'payee' && cells[0].length === 5) fields = editable;
      else throw new Error('Paste one column into its matching field, or paste 5 or 7 columns starting in Supplier / payee.');
      if (cells.some(row => /^(total|registered name|supplier \/ payee)$/i.test(row[0].trim())))
        throw new Error('Copy transaction cells only, without the header or Total row.');
      const visible = [...body.querySelectorAll('[data-eq-row]')].filter(row => !row.hidden);
      const start = visible.indexOf(input.closest('[data-eq-row]'));
      const needed = Math.max(0, cells.length - (visible.length - start));
      if (Number(total.value) + needed > 500) throw new Error('This paste exceeds the 500-row limit. No cells were changed.');
      // Validate all lengths before changing any cell.
      cells.forEach(values => values.forEach((value, index) => {
        const name = fields[index]; if (!name) return;
        const max = {payee:200, tin:17, atc:5, base:24, reference:300}[name];
        if (value.trim().length > max) throw new Error('A pasted ' + name + ' exceeds its field limit. No cells were changed.');
      }));
      const month = input.closest('[data-eq-row]').querySelector('select').value;
      for (let i = 0; i < needed; i++) visible.push(appendRow(month));
      cells.forEach((values, offset) => values.forEach((value, index) => {
        if (!fields[index]) return;
        const target = visible[start + offset].querySelector('[name$="-' + fields[index] + '"]');
        target.value = value.trim();
        target.dispatchEvent(new Event('input', {bubbles:true}));
        if (fields[index] === 'base') format(target);
      }));
      pasteStatus.textContent = cells.length + ' row(s) pasted. New rows use the starting row’s month. Review the entries before saving.' + (fields.length === 7 ? ' Excel rates and withholding were ignored; the app calculates them.' : '');
    } catch (error) { pasteStatus.textContent = error.message; }
    pasteStatus.hidden = false;
  });
  body.querySelectorAll('[data-eq-row]').forEach(bind);
  document.getElementById('eq-add').addEventListener('click', () => {
    const index = Number(total.value); if (index >= 500) return;
    const lastMonth = Number(document.querySelector('#eq-editor [name=quarter]').value) * 3;
    const firstMonth = lastMonth - 2;
    const existingMonths = [...body.querySelectorAll('[data-eq-row]')]
      .filter(row => !row.hidden && [...row.querySelectorAll('input:not([type=checkbox])')].some(input => input.value.trim()))
      .map(row => Number(row.querySelector('select').value))
      .filter(month => month >= firstMonth && month <= lastMonth);
    const nextMonth = existingMonths.length ? Math.min(Math.max(...existingMonths) + 1, lastMonth) : firstMonth;
    body.insertAdjacentHTML('beforeend', document.getElementById('eq-empty').innerHTML.replaceAll('__prefix__', index));
    total.value = index + 1; const row = body.lastElementChild; bind(row); row.querySelector('select').value = nextMonth; row.querySelector('select').focus();
  });
  document.querySelectorAll('[name$="remittance"], [name="surcharge"], [name="interest"], [name="compromise"]').forEach(input => { format(input); input.addEventListener('blur', () => format(input)); });
  const penalties = ['surcharge', 'interest', 'compromise'].map(name => document.querySelector('[name="' + name + '"]'));
  const totalPenalties = document.getElementById('eq-penalties-total');
  function updatePenaltyTotal() {
    let cents = 0n;
    for (const input of penalties) {
      const value = input.value.replaceAll(',', '').trim() || '0';
      if (!/^\d+(\.\d{1,2})?$/.test(value)) { totalPenalties.value = 'Check amounts'; return; }
      const [whole, fraction = ''] = value.split('.');
      cents += BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'));
    }
    totalPenalties.value = (cents / 100n).toLocaleString('en-PH') + '.' + (cents % 100n).toString().padStart(2, '0');
  }
  penalties.forEach(input => {
    if (!input.value.trim()) input.value = '0.00';
    input.addEventListener('input', updatePenaltyTotal);
    input.addEventListener('blur', () => { if (!input.value.trim()) input.value = '0.00'; updatePenaltyTotal(); });
  });
  updatePenaltyTotal();
})();
