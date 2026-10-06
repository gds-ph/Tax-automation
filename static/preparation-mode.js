(() => {
  const mode = document.getElementById('id_filing_mode');
  const update = () => {
    const nonzero = mode.value === 'NONZERO';
    document.getElementById('nonzero-notice').hidden = !nonzero;
    document.getElementById('zero-confirmation').hidden = nonzero;
    document.getElementById('queue-preparation').disabled = nonzero;
  };
  mode.addEventListener('change', update);
  update();
})();
