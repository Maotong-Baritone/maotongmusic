import unittest

from tools.brahms_op86_op96_batch import BATCH, IDS, source_record


class BrahmsOp86Op96ScopeTests(unittest.TestCase):
    def test_batch_is_exactly_ten_selected_files(self):
        self.assertEqual(IDS, ('46903', '46904', '46905', '46906', '46907', '46908',
                               '246580', '246581', '246582', '246583'))
        self.assertEqual(len(set(IDS)), 10)
        self.assertEqual(BATCH.allowed_categories, ('艺术歌曲',))
        self.assertEqual(BATCH.allowed_voice_types, ('高声部', '声乐、钢琴', '高声部、钢琴'))

    def test_scope_rejects_outside_file(self):
        with self.assertRaises(ValueError):
            source_record('246584')


if __name__ == '__main__':
    unittest.main()
