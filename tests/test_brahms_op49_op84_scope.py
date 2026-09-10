import unittest

from tools.brahms_op49_op84_batch import BATCH, IDS, source_record


class BrahmsOp49Op84ScopeTests(unittest.TestCase):
    def test_batch_is_exactly_ten_selected_files(self):
        self.assertEqual(IDS, ('9202', '9203', '9204', '9205', '9206',
                               '44067', '44068', '44069', '44070', '44071'))
        self.assertEqual(len(set(IDS)), 10)
        self.assertEqual(BATCH.allowed_categories, ('艺术歌曲',))
        self.assertIn('二重唱、钢琴', BATCH.allowed_voice_types)

    def test_scope_rejects_outside_file(self):
        with self.assertRaises(ValueError):
            source_record('22813')


if __name__ == '__main__':
    unittest.main()
