import unittest
import io
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tools import stage_brahms_op116 as stage
from tools.stage_brahms_op116 import ALLOWED_IDS, local_name, validate_url


class Op116StagingTests(unittest.TestCase):
    def test_trial_is_exactly_four_complete_and_seven_individual_files(self):
        self.assertEqual(len(ALLOWED_IDS), 11)
        self.assertTrue({str(i) for i in range(1524, 1531)} <= ALLOWED_IDS)

    def test_observed_url_must_match_host_and_file_id(self):
        self.assertEqual(validate_url("1524", "https://vmirror.imslp.org/files/IMSLP01524-Bp27.pdf"), "IMSLP01524-Bp27.pdf")
        for file_id, url in [
            ("1030499", "https://imslp.org/IMSLP1030499-test.pdf"),
            ("1524", "https://imslp.org.evil.test/IMSLP01524-test.pdf"),
            ("1524", "https://s9.imslp.org/IMSLP01525-test.pdf"),
            ("1524", "https://s9.imslp.org/IMSLP01524-preview.jpg"),
            ("1524", "https://user:pass@s9.imslp.org/IMSLP01524-test.pdf"),
            ("1524", "http://s9.imslp.org/IMSLP01524-test.pdf"),
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_url(file_id, url)

    def test_local_names_preserve_movement_and_opus(self):
        name = local_name({"imslp_id": "1527", "proposed_title": "No. 4 Intermezzo. Adagio, Op. 116"})
        self.assertEqual(name, "No. 4 Intermezzo. Adagio, Op.116 - IMSLP1527.pdf")
        self.assertIn("Simrock-1892-first-edition", local_name({"imslp_id": "23160"}))


class StagingIsolationTests(unittest.TestCase):
    URL = 'https://vmirror.imslp.org/files/IMSLP01524-Bp27.pdf'
    PAYLOAD = b'%PDF-1.4\nunit-test placeholder\n%%EOF'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.destination = self.root / 'staging/op116'
        self.source = self.root / 'source.json'
        self.source.write_text('original metadata', encoding='utf-8')
        self.file = {
            'imslp_id':'1524', 'proposed_title':'No. 1 Capriccio, Op. 116',
            'proposed_work':'7 Fantasien, Op. 116', 'movement_number':1,
            'category':'器乐独奏','sub_category':'随想曲','voice_types':'钢琴独奏',
            'tonality':'d小调','language_cn':'','publisher':'source publisher','editor':'source editor',
            'copyright':'Public Domain','description':'1. Capriccio',
            'handler_url':'https://imslp.org/wiki/Special:ImagefromIndex/01524','decision':'pending',
        }
        self.work = {'files':[self.file], 'display_work_title':'7 Fantasien, Op.116','source_url':'https://imslp.org/wiki/7_Fantasien'}
        reader = SimpleNamespace(is_encrypted=False, pages=[SimpleNamespace(mediabox=[], get_contents=lambda: None)], close=lambda: None)
        for patch in (
            mock.patch.object(stage, 'STAGE', self.destination),
            mock.patch.object(stage, 'SOURCE', self.source),
            mock.patch.object(stage, 'scoped_work', return_value=self.work),
            mock.patch.dict('sys.modules', {'pypdf':SimpleNamespace(PdfReader=lambda _path:reader)}),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def response(self, length=None):
        response = io.BytesIO(self.PAYLOAD)
        response.headers = {'Content-Length':str(length if length is not None else len(self.PAYLOAD))}
        response.geturl = lambda: self.URL
        return response

    def run_download(self, **kwargs):
        stage.download('1524', self.URL, '2026-01-01T00:00:00+00:00', **kwargs)

    def test_download_writes_only_stage_and_keeps_pending(self):
        for name in ('data.json', 'logs.json'):
            (self.root/name).write_text('untouched', encoding='utf-8')
        with mock.patch.object(stage.urllib.request, 'urlopen', return_value=self.response()):
            self.run_download()
        manifest = json.loads((self.destination/'manifest.json').read_text(encoding='utf-8'))
        saved = manifest['files'][0]
        self.assertFalse(saved['publication_approved'])
        self.assertEqual(saved['visual_check'], 'pending')
        self.assertEqual((self.destination/saved['local_path']).read_bytes(), self.PAYLOAD)
        self.assertEqual(self.file['decision'], 'pending')
        self.assertEqual(self.source.read_text(), 'original metadata')
        self.assertFalse((self.root/'scores').exists())
        for name in ('data.json', 'logs.json'):
            self.assertEqual((self.root/name).read_text(), 'untouched')
        with mock.patch.object(stage.urllib.request, 'urlopen', side_effect=AssertionError('must not refetch')):
            self.run_download()

    def test_truncated_response_is_retained_and_not_accepted(self):
        with mock.patch.object(stage.urllib.request, 'urlopen', return_value=self.response(length=9999)):
            with self.assertRaisesRegex(ValueError, 'Truncated'):
                self.run_download()
        self.assertFalse((self.destination/'manifest.json').exists())
        self.assertEqual(len(list(self.destination.rglob('*.part'))), 1)
        self.assertFalse(list(self.destination.rglob('*.pdf')))

    def test_changed_review_rights_prevent_network_access(self):
        self.file['copyright'] = 'Creative Commons Attribution-ShareAlike 4.0'
        with mock.patch.object(stage.urllib.request, 'urlopen', side_effect=AssertionError('must not request')):
            with self.assertRaisesRegex(ValueError, 'rights'):
                self.run_download()
        self.assertFalse(self.destination.exists())

    def test_existing_untracked_pdf_is_never_overwritten(self):
        target = self.destination/'pdfs'/stage.local_name(self.file)
        target.parent.mkdir(parents=True)
        target.write_bytes(b'user file')
        with self.assertRaisesRegex(ValueError, 'refusing to overwrite'):
            self.run_download()
        self.assertEqual(target.read_bytes(), b'user file')

    def test_old_null_encryption_is_checked_without_rewriting_pdf(self):
        failed_reader = mock.Mock(side_effect=AttributeError("'NullObject' object has no attribute 'get'"))
        with mock.patch.dict('sys.modules', {'pypdf':SimpleNamespace(PdfReader=failed_reader)}), \
             mock.patch.object(stage.subprocess, 'run', return_value=SimpleNamespace(stdout='Pages: 1\nEncrypted: no\n')), \
             mock.patch.object(stage.urllib.request, 'urlopen', return_value=self.response()):
            self.run_download()
        saved = json.loads((self.destination/'manifest.json').read_text(encoding='utf-8'))['files'][0]
        self.assertIn('pypdf', saved['compatibility_note'])
        self.assertEqual((self.destination/saved['local_path']).read_bytes(), self.PAYLOAD)

    def test_encryption_warning_cannot_be_downgraded(self):
        failed_reader = mock.Mock(side_effect=AttributeError("'NullObject' object has no attribute 'get'"))
        with mock.patch.dict('sys.modules', {'pypdf':SimpleNamespace(PdfReader=failed_reader)}), \
             mock.patch.object(stage.subprocess, 'run', return_value=SimpleNamespace(stdout='Pages: 1\nEncrypted: yes\n')), \
             mock.patch.object(stage.urllib.request, 'urlopen', return_value=self.response()):
            with self.assertRaisesRegex(ValueError, 'unencrypted'):
                self.run_download()
        self.assertFalse((self.destination/'manifest.json').exists())


if __name__ == "__main__":
    unittest.main()
