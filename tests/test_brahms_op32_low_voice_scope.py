import unittest

from tools.brahms_op32_low_voice_batch import BATCH, IDS


class BrahmsOp32LowVoiceScopeTests(unittest.TestCase):
    def test_batch_is_bounded_to_nine_expected_files(self):
        self.assertEqual(len(IDS), 9)
        self.assertEqual(BATCH.ids, IDS)
        self.assertEqual(BATCH.work_titles, ('9 Lieder and Songs, Op.32',))

    def test_batch_allows_only_art_song_low_voice_metadata(self):
        self.assertEqual(BATCH.allowed_categories, ('艺术歌曲',))
        self.assertIn('低声部、钢琴', BATCH.allowed_voice_types)


if __name__ == '__main__':
    unittest.main()
