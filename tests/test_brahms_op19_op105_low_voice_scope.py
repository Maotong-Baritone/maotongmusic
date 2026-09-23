import unittest

from tools.brahms_op19_op105_low_voice_batch import BATCH, IDS, OP19_IDS, OP105_IDS, source_record


class BrahmsOp19Op105LowVoiceScopeTests(unittest.TestCase):
    def test_batch_is_exactly_ten_selected_files(self):
        self.assertEqual(OP19_IDS, ('54911', '54912', '54913', '39255', '39256'))
        self.assertEqual(OP105_IDS, ('43319', '43320', '347100', '43321', '347101'))
        self.assertEqual(IDS, OP19_IDS + OP105_IDS)
        self.assertEqual(len(set(IDS)), 10)
        self.assertEqual(BATCH.work_titles, ('5 Poems, Op.19', '5 Lieder, Op.105'))

    def test_batch_allows_only_art_song_low_voice_metadata(self):
        self.assertEqual(BATCH.allowed_categories, ('艺术歌曲',))
        self.assertIn('低声部、钢琴', BATCH.allowed_voice_types)

    def test_scope_rejects_outside_file(self):
        with self.assertRaises(ValueError):
            source_record('8654')


if __name__ == '__main__':
    unittest.main()
