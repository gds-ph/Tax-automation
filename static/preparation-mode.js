(() => {
  const mode = document.getElementById('id_filing_mode');
  const button = document.getElementById('queue-preparation');
  const auto = document.getElementById('id_auto_approve');
  const update = () => {
    const nonzero = mode.value === 'NONZERO';
    document.getElementById('nonzero-notice').hidden = !nonzero;
    document.getElementById('zero-confirmation').hidden = nonzero;
    button.disabled = nonzero;
    // Say what the button will do: auto-submit skips the human review of the prepared PDF.
    button.textContent = auto && auto.checked ? button.dataset.autoLabel : button.dataset.label;
  };
  mode.addEventListener('change', update);
  if (auto) auto.addEventListener('change', update);
  update();
})();
