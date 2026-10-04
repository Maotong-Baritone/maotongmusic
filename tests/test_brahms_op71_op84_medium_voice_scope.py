import unittest
from pathlib import Path

from tools import brahms_op71_op84_medium_voice_batch as batch


class MediumVoiceBatchScopeTests(unittest.TestCase):
    def test_scope_is_exact_and_bounded(self):
        self.assertEqual(len(batch.IDS), 7)
        self.assertEqual(len(set(batch.IDS)), 7)
        self.assertEqual(batch.BATCH.allowed_categories, ('艺术歌曲',))
        self.assertEqual(batch.BATCH.allowed_voice_types, ('中音声部、钢琴', '二重唱、钢琴'))
        self.assertEqual(batch.OP84_IDS, {'142695', '142696', '142697'})
        self.assertEqual(batch.DOWNLOAD_BATCH.ids, batch.BATCH.ids)
        self.assertEqual(batch.DOWNLOAD_BATCH.batch_id, batch.BATCH.batch_id)
        self.assertEqual(batch.DOWNLOAD_BATCH.stage_rel, batch.BATCH.stage_rel)
        self.assertEqual(batch.DOWNLOAD_BATCH.allowed_categories, ('艺术歌曲',))
        self.assertEqual(batch.DOWNLOAD_BATCH.allowed_voice_types, ('中音声部',))

    def test_visual_title_corrections_are_bounded(self):
        self.assertEqual(set(batch.TITLE_CORRECTIONS), {'138117'})
        source = Path(batch.__file__).read_text(encoding='utf-8')
        self.assertIn('No. 1 Es liebt sich so lieblich im Lenze.', source)


if __name__ == '__main__':
    unittest.main()
