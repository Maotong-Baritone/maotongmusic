import unittest

from tools.brahms_op71_op72_low_voice_batch import BATCH, IDS, OP71_IDS, OP72_IDS, TITLE_CORRECTIONS


class BrahmsOp71Op72LowVoiceScopeTests(unittest.TestCase):
    def test_batch_is_bounded_to_ten_expected_files(self):
        self.assertEqual(len(IDS), 10)
        self.assertEqual(len(OP71_IDS), 5)
        self.assertEqual(len(OP72_IDS), 5)
        self.assertEqual(BATCH.ids, IDS)
        self.assertEqual(BATCH.work_titles, ('5 Songs, Op.71', '5 Songs, Op.72'))

    def test_batch_allows_only_art_song_low_voice_metadata(self):
        self.assertEqual(BATCH.allowed_categories, ('艺术歌曲',))
        self.assertIn('低声部、钢琴', BATCH.allowed_voice_types)

    def test_printed_title_corrections_are_bounded(self):
        self.assertEqual(set(TITLE_CORRECTIONS), {'39109', '39110', '326311', '326314'})


if __name__ == '__main__':
    unittest.main()
