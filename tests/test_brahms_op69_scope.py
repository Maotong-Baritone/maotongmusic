import unittest

from tools.brahms_op69_high_voice_batch import BATCH, IDS, source_record


class BrahmsOp69ScopeTests(unittest.TestCase):
    def test_batch_is_exactly_nine_high_voice_files(self):
        self.assertEqual(len(IDS), 9)
        self.assertEqual(len(set(IDS)), 9)
        self.assertEqual(BATCH.allowed_categories, ('艺术歌曲',))
        self.assertEqual(BATCH.allowed_voice_types, ('高声部', '高声部、钢琴'))

    def test_scope_rejects_outside_file(self):
        with self.assertRaises(ValueError):
            source_record('23099')


if __name__ == '__main__':
    unittest.main()
