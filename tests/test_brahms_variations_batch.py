import json
import tempfile
import unittest
from pathlib import Path

from tools.brahms_variations_batch import (BATCH, OP35_CORRECTIONS,
                                            apply_recorded_corrections)
from tools.publish_brahms_op116 import REVIEW_REL


class VariationsBatchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.root.joinpath(REVIEW_REL).parent.mkdir(parents=True)
        records = []
        for file_id, values in OP35_CORRECTIONS.items():
            title, work, scope = values['before']
            records.append({'imslp_id': file_id, 'proposed_title': title,
                            'proposed_work': work, 'title_scope': scope,
                            'decision': 'pending', 'review_edited': False,
                            'review_notes': ''})
        records.append({'imslp_id': 'unrelated', 'proposed_title': 'Keep me',
                        'proposed_work': '', 'title_scope': 'whole_work',
                        'decision': 'pending'})
        self.review = {'works': [{'files': records}]}
        self.root.joinpath(REVIEW_REL).write_text(
            json.dumps(self.review, ensure_ascii=False), encoding='utf-8')

    def test_batch_is_bounded_to_six_expected_sources(self):
        self.assertEqual(BATCH.ids,
                         ('107618', '107692', '107694', '107697', '107699', '107701'))

    def test_book_corrections_are_scoped_and_idempotent(self):
        apply_recorded_corrections(self.root)
        result = json.loads(self.root.joinpath(REVIEW_REL).read_text(encoding='utf-8'))
        sources = {f['imslp_id']: f for w in result['works'] for f in w['files']}
        self.assertEqual(sources['unrelated']['proposed_title'], 'Keep me')
        for file_id, correction in OP35_CORRECTIONS.items():
            source = sources[file_id]
            self.assertEqual((source['proposed_title'], source['proposed_work'],
                              source['title_scope']), correction['after'])
            self.assertEqual(source['decision'], 'pending')
        before = self.root.joinpath(REVIEW_REL).read_bytes()
        apply_recorded_corrections(self.root)
        self.assertEqual(self.root.joinpath(REVIEW_REL).read_bytes(), before)

    def test_unexpected_existing_metadata_stops_without_writing(self):
        self.review['works'][0]['files'][0]['proposed_title'] = 'Unexpected'
        path = self.root.joinpath(REVIEW_REL)
        path.write_text(json.dumps(self.review, ensure_ascii=False), encoding='utf-8')
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Metadata changed'):
            apply_recorded_corrections(self.root)
        self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
