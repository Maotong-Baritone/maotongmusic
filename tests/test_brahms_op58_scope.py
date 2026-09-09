import unittest

from tools.brahms_op58_high_voice_batch import BATCH, IDS, source_record


class BrahmsOp58ScopeTests(unittest.TestCase):
    def test_batch_is_exactly_eight_high_voice_files(self):
        self.assertEqual(len(IDS), 8)
        self.assertEqual(len(set(IDS)), 8)
        self.assertEqual(BATCH.allowed_categories, ('艺术歌曲',))
        self.assertEqual(BATCH.allowed_voice_types, ('声乐、钢琴', '高声部、钢琴'))

    def test_scope_rejects_outside_file(self):
        with self.assertRaises(ValueError):
            source_record('110714')


if __name__ == '__main__':
    unittest.main()
