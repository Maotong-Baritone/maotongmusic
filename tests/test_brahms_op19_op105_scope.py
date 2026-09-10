import unittest

from tools.brahms_op19_op105_batch import BATCH, IDS, source_record


class BrahmsOp19Op105ScopeTests(unittest.TestCase):
    def test_batch_is_exactly_ten_selected_files(self):
        self.assertEqual(IDS, ('8654', '8655', '8656', '8657', '8658',
                               '246584', '246585', '246586', '246587', '246588'))
        self.assertEqual(len(set(IDS)), 10)
        self.assertEqual(BATCH.allowed_categories, ('艺术歌曲',))
        self.assertEqual(BATCH.allowed_voice_types, ('高声部', '声乐、钢琴', '高声部、钢琴'))

    def test_scope_rejects_outside_file(self):
        with self.assertRaises(ValueError):
            source_record('83196')


if __name__ == '__main__':
    unittest.main()
