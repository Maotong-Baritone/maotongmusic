import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from tools.restore_score import restore
from validate_library import CANONICAL_LANGUAGES


class Response(io.BytesIO):
    status = 200


class ScoreRestoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.pdf = b'%PDF-1.7\noriginal test score\n%%EOF'
        self.item = {'public_id': 'example', 'filename': 'book/example.pdf'}
        self.save('data.json', [self.item])
        self.save('storage-manifest.json', {'entries': [{'public_id': 'example', 'storage_key': 'scores/ex/example.pdf',
                  'file_size': len(self.pdf), 'sha256': hashlib.sha256(self.pdf).hexdigest()}]})
        self.save('site-config.json', {'scoreStorage': {'baseUrl': 'https://scores.example.test'}})

    def save(self, name, value):
        (self.root / name).write_text(json.dumps(value), encoding='utf-8')

    def test_restores_original_bytes_and_preserves_verified_existing_file(self):
        requests = []
        def fetch(request, timeout):
            requests.append(request.full_url)
            return Response(self.pdf)
        path = restore('example', self.root, fetch)
        self.assertEqual(path.read_bytes(), self.pdf)
        self.assertEqual(requests, ['https://scores.example.test/scores/ex/example.pdf'])
        self.assertEqual(restore('example', self.root, fetch), path)
        self.assertEqual(len(requests), 1)

    def test_bad_hash_leaves_no_score_or_partial_file(self):
        with self.assertRaises(ValueError):
            restore('example', self.root, lambda *a, **k: Response(b'%PDF-' + b'x' * (len(self.pdf)-5)))
        self.assertFalse((self.root / 'scores/book/example.pdf').exists())
        self.assertFalse(list((self.root / 'scores').rglob('*.part')))

    def test_existing_different_file_is_preserved(self):
        path = self.root / 'scores/book/example.pdf'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'user-edited score')
        with self.assertRaises(ValueError):
            restore('example', self.root, lambda *a, **k: self.fail('Must not download'))
        self.assertEqual(path.read_bytes(), b'user-edited score')

    def test_path_cannot_escape_scores(self):
        self.item['filename'] = '../outside.pdf'
        self.save('data.json', [self.item])
        with self.assertRaises(ValueError):
            restore('example', self.root, lambda *a, **k: self.fail('Must not download'))
        self.assertFalse((self.root / 'outside.pdf').exists())

    def test_multilingual_anthologies_have_an_accurate_language_option(self):
        self.assertIn('多语种', CANONICAL_LANGUAGES)


if __name__ == '__main__':
    unittest.main()
