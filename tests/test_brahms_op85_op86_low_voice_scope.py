import unittest

from tools.brahms_op85_op86_low_voice_batch import BATCH, IDS, OP85_IDS, OP86_IDS, TITLE_CORRECTIONS


class BrahmsOp85Op86LowVoiceScopeTests(unittest.TestCase):
    def test_batch_is_bounded_to_twelve_expected_files(self):
        self.assertEqual(len(IDS), 12)
        self.assertEqual(len(OP85_IDS), 6)
        self.assertEqual(len(OP86_IDS), 6)
        self.assertEqual(BATCH.ids, IDS)
        self.assertEqual(BATCH.work_titles, ('6 Lieder, Op.85', '6 Lieder, Op.86'))

    def test_batch_allows_only_art_song_low_voice_metadata(self):
        self.assertEqual(BATCH.allowed_categories, ('艺术歌曲',))
        self.assertIn('低声部、钢琴', BATCH.allowed_voice_types)

    def test_printed_title_corrections_are_bounded(self):
        self.assertEqual(TITLE_CORRECTIONS, {})


if __name__ == '__main__':
    unittest.main()
