import io
import json
from unittest.mock import patch, Mock
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings
from .gds_reader import read_images
from .cor_extraction import read_cor


@override_settings(GDS_BASE_URL='https://gateway.example/v1', GDS_API_KEY='fake-key', GDS_MODEL='fake-vision')
class GatewayReaderTests(SimpleTestCase):
    @patch('workorders.gds_reader.build_opener')
    def test_stream_is_assembled_and_tools_disabled(self, opener):
        stream = b'data: ' + json.dumps({'choices': [{'delta': {'content': '{"ok":true}'}}]}).encode() + b'\n\ndata: [DONE]\n\n'
        opener.return_value.open.return_value = io.BytesIO(stream)
        self.assertEqual(read_images(['data:image/png;base64,FAKE'], 'Read this'), {'ok': True})
        request = opener.return_value.open.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload['tool_choice'], 'none')
        self.assertNotIn('response_format', payload)  # GDS injects tools incompatible with JSON mode.

    @patch('workorders.gds_reader.build_opener')
    def test_incomplete_and_provider_errors_are_not_accepted(self, opener):
        for stream in [b'data: {"error":"secret provider detail"}\n',
                       b'data: {"choices":[]}\n', b'data: [DONE]\n',
                       b'data: {"choices":[{"finish_reason":"length"}]}\n']:
            opener.return_value.open.return_value = io.BytesIO(stream)
            with self.assertRaises(ValidationError) as error:
                read_images([], 'Read this')
            self.assertNotIn('secret provider detail', str(error.exception))

    @override_settings(GDS_BASE_URL='http://gateway.example/v1')
    def test_insecure_url_rejected_before_network(self):
        with self.assertRaises(ValidationError):
            read_images([], 'Read this')


@override_settings(COR_NODE_MODULES='fake/modules', GDS_MODEL='fake')
class CORInterpretationTests(SimpleTestCase):
    @patch('workorders.gds_reader.read_images')
    @patch('workorders.cor_extraction.subprocess.run')
    def test_accounting_period_autoselection_requires_evidence(self, run, reader):
        run.return_value = Mock(stdout=b'{"images":["fake"]}')
        cases = [
            ('CALENDAR', '', 'Accounting period: Calendar', 'CALENDAR', '12'),
            ('FISCAL', '6', 'Fiscal year ending June', 'FISCAL', '06'),
            ('CALENDAR', '12', '', '', ''),
            ('CALENDAR', '06', 'Conflicting period entries', '', ''),
            ('FISCAL', '13', 'Fiscal period unclear', 'FISCAL', ''),
        ]
        for basis, month, evidence, expected_basis, expected_month in cases:
            with self.subTest(basis=basis, month=month, evidence=evidence):
                reader.return_value = {'is_cor': True, 'filings': [], 'taxpayer': {
                    'calendar_or_fiscal': basis, 'year_end_month': month,
                    'accounting_period_evidence': evidence}}
                initial = read_cor(b'%PDF-fake')['initial']
                self.assertEqual(initial['calendar_or_fiscal'], expected_basis)
                self.assertEqual(initial['year_end_month'], expected_month)

    @patch('workorders.gds_reader.read_images')
    @patch('workorders.cor_extraction.subprocess.run')
    def test_sole_proprietor_evidence_corrects_client_type(self, run, reader):
        run.return_value = Mock(stdout=b'{"images":["fake"]}')
        for evidence in ('SINGLE PROPRIETORSHIP ONLY (RESIDENT CITIZEN)', 'Sole proprietorship'):
            reader.return_value = {'is_cor': True, 'taxpayer': {
                'client_type': 'NON_INDIVIDUAL', 'taxpayer_type_evidence': evidence}, 'filings': []}
            self.assertEqual(read_cor(b'%PDF-fake')['initial']['client_type'], 'INDIVIDUAL')
        reader.return_value['taxpayer']['taxpayer_type_evidence'] = 'SINGLE PROPRIETORSHIP / CORPORATION'
        self.assertEqual(read_cor(b'%PDF-fake')['initial']['client_type'], '')

    @patch('workorders.gds_reader.read_images')
    @patch('workorders.cor_extraction.subprocess.run')
    def test_uncertainty_and_historical_forms_never_select_automation(self, run, reader):
        run.return_value = Mock(stdout=b'{"images":["fake"]}')
        reader.return_value = {'is_cor': True, 'taxpayer': {'tin4': '001'},
            'filings': [{'form_code': '2551Q', 'uncertain': True},
                        {'form_code': '2550M', 'uncertain': False},
                        {'form_code': '0605', 'uncertain': False},
                        {'form_code': '1701Q', 'uncertain': False}],
            'transcript': '2551Q elsewhere on page'}
        result = read_cor(b'%PDF-fake')
        self.assertEqual(result['initial']['filings'], ['1701Q'])
        self.assertEqual(result['initial']['tin4'], '001')
        self.assertGreaterEqual(len(result['warnings']), 4)

    @patch('workorders.gds_reader.read_images')
    @patch('workorders.cor_extraction.subprocess.run')
    def test_non_cor_rejected(self, run, reader):
        run.return_value = Mock(stdout=b'{"images":[]}')
        reader.return_value = {'is_cor': False}
        with self.assertRaises(ValidationError):
            read_cor(b'%PDF-fake')
