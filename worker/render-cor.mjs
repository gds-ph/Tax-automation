// Render original PDF pages locally for the GDS vision reader. No remote resources.
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { join } from 'node:path';
import { readFile } from 'node:fs/promises';
const [modules, filename] = process.argv.slice(2);
const require = createRequire(join(modules, '..', 'package.json'));
const { createCanvas } = require('@napi-rs/canvas');
const { getDocument } = await import(pathToFileURL(require.resolve('pdfjs-dist/legacy/build/pdf.mjs')).href);
const loadingTask = getDocument({data:new Uint8Array(await readFile(filename)),isEvalSupported:false,verbosity:0});
const pdf = await loadingTask.promise;
if (pdf.numPages < 1 || pdf.numPages > 6) throw new Error('Choose 1–6 pages');
const images = [];
try {
  for(let n=1;n<=pdf.numPages;n++) {
    const page = await pdf.getPage(n);
    const base = page.getViewport({scale:1});
    if (!Number.isFinite(base.width+base.height) || Math.min(base.width,base.height)<=0) throw new Error('Invalid dimensions');
    const viewport = page.getViewport({scale:Math.min(3,3000/Math.max(base.width,base.height))});
    const canvas = createCanvas(Math.ceil(viewport.width),Math.ceil(viewport.height));
    await page.render({canvasContext:canvas.getContext('2d'),viewport}).promise;
    // Scanned pages can produce very large PNGs. Keep full resolution but
    // compress photographic scans so six pages fit the reader's 35 MB limit.
    let bytes = canvas.toBuffer('image/png');
    let mime = 'image/png';
    if (bytes.length > 4_000_000) {
      mime = 'image/jpeg';
      bytes = canvas.toBuffer(mime, 92);
      if (bytes.length > 4_000_000) bytes = canvas.toBuffer(mime, 80);
    }
    if (bytes.length > 4_000_000) throw new Error('Rendered page exceeds image size limit');
    images.push('data:'+mime+';base64,'+bytes.toString('base64'));
    page.cleanup();
  }
  process.stdout.write(JSON.stringify({images}));
} finally {await loadingTask.destroy();}
