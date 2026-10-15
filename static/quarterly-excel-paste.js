/* Excel clipboard text is TSV; quoted cells may contain tabs and newlines. */
(function(root) {
  function parse(text) {
    if (text.length > 1000000) throw new Error('Paste up to 500 transaction rows at a time.');
    const rows = []; let row = [], cell = '', quoted = false;
    text = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    for (let i = 0; i < text.length; i++) {
      const char = text[i];
      if (char === '"') {
        if (quoted && text[i + 1] === '"') { cell += '"'; i++; }
        else if (quoted || cell === '') quoted = !quoted;
        else cell += char;
      } else if (!quoted && (char === '\t' || char === '\n')) {
        row.push(cell); cell = '';
        if (char === '\n') { rows.push(row); row = []; }
      } else cell += char;
    }
    if (quoted) throw new Error('The copied cells contain an unfinished quote. Copy the cells again.');
    row.push(cell); rows.push(row);
    while (rows.length && rows[rows.length - 1].every(value => value.trim() === '')) rows.pop();
    if (!rows.length || rows.length > 500) throw new Error('Paste between 1 and 500 transaction rows.');
    if (rows.some(row => row.length !== rows[0].length)) throw new Error('Copy a rectangular range of Excel cells.');
    return rows;
  }
  if (typeof module !== 'undefined') module.exports = {parse};
  else root.eqExcelPaste = {parse};
})(typeof window !== 'undefined' ? window : globalThis);
