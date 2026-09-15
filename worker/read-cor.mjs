// Local PDF text/OCR only. No cloud calls and no invoice-app code is executed.
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { join } from 'node:path';
import { readFile } from 'node:fs/promises';
const [modules, filename] = process.argv.slice(2);
const require = createRequire(join(modules, '..', 'package.json'));
const { createCanvas } = require('@napi-rs/canvas');
const { getDocument } = await import(pathToFileURL(require.resolve('pdfjs-dist/legacy/build/pdf.mjs')).href);
const { createWorker } = require('tesseract.js');
const english = require('@tesseract.js-data/eng');
const loadingTask = getDocument({data:new Uint8Array(await readFile(filename)), isEvalSupported:false, verbosity:0});
const pdf = await loadingTask.promise;
if (pdf.numPages > 6) throw new Error('Page limit');
let worker, usedOcr = false;
const texts = [];
try {
  for (let n=1;n<=pdf.numPages;n++) {
    const page = await pdf.getPage(n);
    const content = await page.getTextContent();
    let text = content.items.map(item => item.str + (item.hasEOL ? '\n' : ' ')).join('');
    if (text.replace(/\s/g,'').length < 100) {
      usedOcr = true;
      worker ||= await createWorker('eng',1,{langPath:english.langPath,cacheMethod:'none',gzip:true});
      const base = page.getViewport({scale:1});
      const scale = Math.min(2.5, 2600 / Math.max(base.width,base.height));
      const viewport = page.getViewport({scale});
      const canvas = createCanvas(Math.ceil(viewport.width),Math.ceil(viewport.height));
      await page.render({canvasContext:canvas.getContext('2d'),viewport}).promise;
      text = (await worker.recognize(canvas.toBuffer('image/png'))).data.text;
    }
    texts.push(`--- Page ${n} ---\n${text}`);
  }
  process.stdout.write(JSON.stringify({text:texts.join('\n').slice(0,100000),method:usedOcr?'Local OCR (verify carefully)':'PDF text'}));
} finally {
  if(worker) await worker.terminate();
  await loadingTask.destroy();
}
