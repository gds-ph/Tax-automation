"""Render bounded COR pages locally using Poppler; emits the vision reader's JSON contract."""
import base64
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from PIL import Image


def render(filename):
    source = Path(filename).resolve(strict=True)
    if source.stat().st_size > 20_000_000:
        raise ValueError('PDF exceeds size limit')
    env = dict(os.environ, LC_ALL='C')
    info = subprocess.run(['pdfinfo', str(source)], check=True, capture_output=True,
                          timeout=10, env=env).stdout.decode('utf-8', errors='replace')
    match = re.search(r'^Pages:\s+(\d+)\s*$', info, re.M)
    if not match or not 1 <= int(match[1]) <= 6:
        raise ValueError('Choose 1–6 pages')
    if not re.search(r'^Encrypted:\s+no\s*$', info, re.M):
        raise ValueError('Choose an unencrypted PDF')
    pages = int(match[1])
    with tempfile.TemporaryDirectory(prefix='cor-pages-') as temp:
        prefix = Path(temp) / 'page'
        subprocess.run(['pdftoppm', '-f', '1', '-l', str(pages), '-scale-to', '3000',
                        '-png', str(source), str(prefix)], check=True,
                       capture_output=True, timeout=45, env=env)
        files = sorted(Path(temp).glob('page-*.png'))
        if len(files) != pages:
            raise ValueError('Incomplete rendering')
        images = []
        for file in files:
            data = file.read_bytes()
            mime = 'image/png'
            if len(data) > 4_000_000:
                mime = 'image/jpeg'
                with Image.open(file) as page:
                    for quality in (92, 80):
                        output = io.BytesIO()
                        page.convert('RGB').save(output, format='JPEG', quality=quality)
                        data = output.getvalue()
                        if len(data) <= 4_000_000:
                            break
            if len(data) > 4_000_000:
                raise ValueError('Rendered page exceeds image size limit')
            images.append('data:' + mime + ';base64,' + base64.b64encode(data).decode('ascii'))
        return {'images': images}


if __name__ == '__main__':
    json.dump(render(sys.argv[1]), sys.stdout)
