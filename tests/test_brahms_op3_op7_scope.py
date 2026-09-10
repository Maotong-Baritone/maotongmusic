import unittest

from tools.brahms_op3_op7_batch import BATCH, IDS, source_record


class BrahmsOp3Op7ScopeTests(unittest.TestCase):
    def test_batch_is_exactly_twelve_selected_files(self):
        self.assertEqual(IDS, ('5333', '5334', '5335', '5336', '5337', '5338',
                               '5346', '5347', '5348', '5349', '5350', '5351'))
        self.assertEqual(len(set(IDS)), 12)
        self.assertEqual(BATCH.allowed_categories, ('艺术歌曲',))
        self.assertEqual(BATCH.allowed_voice_types, ('声乐、钢琴', '高声部、钢琴'))

    def test_scope_rejects_outside_file(self):
        with self.assertRaises(ValueError):
            source_record('22813')


if __name__ == '__main__':
    unittest.main()
