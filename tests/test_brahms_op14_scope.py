import unittest

from tools.brahms_op14_songs_batch import BATCH, IDS, source_record


class BrahmsOp14ScopeTests(unittest.TestCase):
    def test_batch_is_exactly_nine_reviewed_files(self):
        self.assertEqual(len(IDS), 9)
        self.assertEqual(len(set(IDS)), 9)
        self.assertEqual(BATCH.allowed_categories, ('艺术歌曲',))
        self.assertEqual(BATCH.allowed_voice_types, ('声乐、钢琴', '低声部、钢琴'))

    def test_scope_rejects_outside_file(self):
        with self.assertRaises(ValueError):
            source_record('105096')


if __name__ == '__main__':
    unittest.main()
