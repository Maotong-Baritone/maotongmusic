import unittest

from tools.brahms_op46_op47_low_voice_batch import BATCH, IDS, OP46_IDS, OP47_IDS, TITLE_CORRECTIONS


class BrahmsOp46Op47LowVoiceScopeTests(unittest.TestCase):
    def test_batch_is_bounded_to_nine_expected_files(self):
        self.assertEqual(IDS, ('43417', '347115', '347116', '43418',
                               '43841', '279897', '43842', '43843', '279898'))
        self.assertEqual(len(IDS), 9)
        self.assertEqual(len(OP46_IDS), 4)
        self.assertEqual(len(OP47_IDS), 5)
        self.assertEqual(BATCH.ids, IDS)
        self.assertEqual(BATCH.work_titles, ('4 Lieder, Op.46', '5 Lieder, Op.47'))

    def test_batch_allows_only_art_song_low_voice_metadata(self):
        self.assertEqual(BATCH.allowed_categories, ('艺术歌曲',))
        self.assertIn('低声部、钢琴', BATCH.allowed_voice_types)

    def test_printed_title_corrections_are_bounded(self):
        self.assertEqual(set(TITLE_CORRECTIONS), {'347115', '279897', '43843'})


if __name__ == '__main__':
    unittest.main()
