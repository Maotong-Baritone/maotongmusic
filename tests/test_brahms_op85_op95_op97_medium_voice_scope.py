import unittest
from pathlib import Path

from tools import brahms_op85_op95_op97_medium_voice_batch as batch


class MediumVoiceBatchScopeTests(unittest.TestCase):
    def test_scope_is_exact_and_bounded(self):
        self.assertEqual(len(batch.IDS), 10)
        self.assertEqual(len(set(batch.IDS)), 10)
        self.assertEqual(batch.BATCH.allowed_categories, ('艺术歌曲',))
        self.assertEqual(batch.BATCH.allowed_voice_types, ('中音声部、钢琴',))
        self.assertEqual(batch.DOWNLOAD_BATCH.ids, batch.BATCH.ids)
        self.assertEqual(batch.DOWNLOAD_BATCH.batch_id, batch.BATCH.batch_id)
        self.assertEqual(batch.DOWNLOAD_BATCH.stage_rel, batch.BATCH.stage_rel)
        self.assertEqual(batch.DOWNLOAD_BATCH.allowed_categories, ('艺术歌曲',))
        self.assertEqual(batch.DOWNLOAD_BATCH.allowed_voice_types, ('声乐、钢琴', '中音声部'))

    def test_visual_title_corrections_are_bounded(self):
        source = Path(batch.__file__).read_text(encoding='utf-8')
        self.assertIn("'243648': ('No. 1 Nachtigall Langsam", source)
        self.assertIn("'243649': ('No. 4 Dort in den Weiden steht ein Haus", source)
        self.assertNotIn("'143193': ('No. 3 Mädchenlied", source)


if __name__ == '__main__':
    unittest.main()
