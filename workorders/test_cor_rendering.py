import base64
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
from unittest import skipUnless
from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings
from PIL import Image
from pypdf import PdfWriter

from worker.render_cor import render
from .cor_extraction import read_cor


class RendererRoutingTests(SimpleTestCase):
    @override_settings(COR_NODE_MODULES='')
    @patch('workorders.cor_extraction.shutil.which', return_value='/usr/bin/poppler')
    @patch('workorders.cor_extraction.subprocess.run')
    @patch('workorders.gds_reader.read_images')
    def test_poppler_does_not_require_node_and_failure_never_calls_reader(self, reader, run, which):
        run.return_value = Mock(stdout=b'{"images":["fake"]}')
        reader.return_value = {'is_cor': True, 'taxpayer': {}, 'filings': []}
        read_cor(b'%PDF-fake')
        self.assertTrue(run.call_args.args[0][1].endswith('render_cor.py'))
        reader.reset_mock()
        run.side_effect = OSError('renderer unavailable')
        with self.assertRaises(ValidationError):
            read_cor(b'%PDF-fake')
        reader.assert_not_called()

    @override_settings(COR_NODE_MODULES='fake/modules')
    @patch('workorders.cor_extraction.shutil.which', return_value=None)
    @patch('workorders.cor_extraction.subprocess.run')
    @patch('workorders.gds_reader.read_images')
    def test_node_fallback_remains_available(self, reader, run, which):
        run.return_value = Mock(stdout=b'{"images":["fake"]}')
        reader.return_value = {'is_cor': True, 'taxpayer': {}, 'filings': []}
        read_cor(b'%PDF-fake')
        self.assertEqual(run.call_args.args[0][0], 'node')


@skipUnless(shutil.which('pdftoppm') and shutil.which('pdfinfo'), 'Poppler not installed')
class PopplerIntegrationTests(SimpleTestCase):
    def make_pdf(self, path, pages=1, encrypted=False):
        writer = PdfWriter()
        for _ in range(pages):
            writer.add_blank_page(width=300, height=400)
        if encrypted:
            writer.encrypt('password')
        writer.write(path)

    def test_page_contract_and_dimension_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'test.pdf'
            self.make_pdf(path, pages=2)
            images = render(path)['images']
            self.assertEqual(len(images), 2)
            for uri in images:
                self.assertTrue(uri.startswith('data:image/png;base64,'))
                data = base64.b64decode(uri.split(',', 1)[1])
                with Image.open(io.BytesIO(data)) as page:
                    self.assertEqual(max(page.size), 3000)

    def test_rejects_more_than_six_pages_and_encryption(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'test.pdf'
            self.make_pdf(path, pages=7)
            with self.assertRaises(ValueError):
                render(path)
            self.make_pdf(path, encrypted=True)
            with self.assertRaises(subprocess.CalledProcessError):
                render(path)
