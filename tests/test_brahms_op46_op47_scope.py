import unittest

from tools.brahms_op46_op47_batch import BATCH, IDS, source_record


class BrahmsOp46Op47ScopeTests(unittest.TestCase):
    def test_batch_is_exactly_nine_selected_files(self):
        self.assertEqual(IDS, ('9005', '9006', '9007', '9008',
                               '9017', '9018', '9019', '9020', '9021'))
        self.assertEqual(len(set(IDS)), 9)
        self.assertEqual(BATCH.allowed_categories, ('艺术歌曲',))
        self.assertEqual(BATCH.allowed_voice_types, ('声乐、钢琴', '高声部、钢琴'))

    def test_scope_rejects_outside_file(self):
        with self.assertRaises(ValueError):
            source_record('22813')


if __name__ == '__main__':
    unittest.main()
