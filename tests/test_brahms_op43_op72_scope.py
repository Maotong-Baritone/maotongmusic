import unittest

from tools.brahms_op43_op72_high_voice_batch import BATCH, IDS, source_record


class BrahmsOp43Op72ScopeTests(unittest.TestCase):
    def test_batch_is_exactly_nine_selected_files(self):
        self.assertEqual(IDS, ('9112', '9113', '9114', '9115', '42188', '42189', '42190', '42191', '42192'))
        self.assertEqual(len(set(IDS)), 9)
        self.assertEqual(BATCH.allowed_categories, ('艺术歌曲', '器乐分谱'))
        self.assertEqual(BATCH.allowed_voice_types, ('高声部', '圆号分谱', '高声部、钢琴'))

    def test_scope_rejects_outside_file(self):
        with self.assertRaises(ValueError):
            source_record('42193')


if __name__ == '__main__':
    unittest.main()
