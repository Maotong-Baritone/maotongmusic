import unittest

from tools.brahms_op48_op107_batch import BATCH, IDS, source_record


class BrahmsOp48Op107ScopeTests(unittest.TestCase):
    def test_batch_is_exactly_twelve_selected_files(self):
        self.assertEqual(IDS, ('9105', '9106', '9107', '9108', '9109', '9110', '9111',
                               '246589', '246590', '246591', '246592', '246593'))
        self.assertEqual(len(set(IDS)), 12)
        self.assertEqual(BATCH.allowed_categories, ('艺术歌曲',))
        self.assertEqual(BATCH.allowed_voice_types, ('高声部', '声乐、钢琴', '高声部、钢琴'))

    def test_scope_rejects_outside_file(self):
        with self.assertRaises(ValueError):
            source_record('246594')


if __name__ == '__main__':
    unittest.main()
