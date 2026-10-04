import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import brahms_op47_op63_op49_medium_voice_batch as batch


class MediumVoiceBatchScopeTests(unittest.TestCase):
    def test_scope_is_exact_and_bounded(self):
        self.assertEqual(len(batch.IDS), 8)
        self.assertEqual(len(set(batch.IDS)), 8)
        self.assertEqual(batch.BATCH.allowed_categories, ('艺术歌曲',))
        self.assertEqual(batch.BATCH.allowed_voice_types, ('中音声部、钢琴',))
        self.assertEqual(batch.DOWNLOAD_BATCH.ids, batch.BATCH.ids)
        self.assertEqual(batch.DOWNLOAD_BATCH.batch_id, batch.BATCH.batch_id)
        self.assertEqual(batch.DOWNLOAD_BATCH.stage_rel, batch.BATCH.stage_rel)
        self.assertEqual(batch.DOWNLOAD_BATCH.allowed_categories, ('艺术歌曲',))
        self.assertEqual(batch.DOWNLOAD_BATCH.allowed_voice_types, ('声乐、钢琴', '中音声部'))

    def test_source_lookup_rejects_missing_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / batch.workflow.publication.REVIEW_REL
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'works': []}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'scope changed'):
                batch._source(root)

    def test_visual_title_corrections_are_bounded(self):
        source = Path(batch.__file__).read_text(encoding='utf-8')
        self.assertIn("'135457': ('No. 5 Junge Liebe I.", source)
        self.assertIn("'135864': ('No. 8 Heimweh II.", source)
        self.assertNotIn("'134615': ('No. 1", source)


if __name__ == '__main__':
    unittest.main()
