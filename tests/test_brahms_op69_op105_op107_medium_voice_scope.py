import unittest
from pathlib import Path

from tools import brahms_op69_op105_op107_medium_voice_batch as batch


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
        self.assertEqual(batch.DOWNLOAD_BATCH.allowed_voice_types, ('中音声部',))

    def test_visual_title_corrections_are_bounded(self):
        source = Path(batch.__file__).read_text(encoding='utf-8')
        self.assertIn("'55045': ('No. 1 Wie Melodien zeiht es mir.", source)
        self.assertIn("'55017': ('No. 4 Auf dem Kirchhofe. Mässig", source)
        self.assertIn("'243828': ('No. 2 Salamander. Mit Launeor", source)
        self.assertNotIn("'243829': ('No. 3 Das Mädchen spricht", source)


if __name__ == '__main__':
    unittest.main()
