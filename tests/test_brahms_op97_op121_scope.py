import unittest

from tools.brahms_op97_op121_batch import BATCH, IDS, source_record


class BrahmsOp97Op121ScopeTests(unittest.TestCase):
    def test_batch_is_exactly_ten_selected_files(self):
        self.assertEqual(IDS, ('232392', '232393', '232394', '232395', '232396',
                               '232397', '64768', '64769', '64770', '64771'))
        self.assertEqual(len(set(IDS)), 10)
        self.assertEqual(BATCH.allowed_categories, ('艺术歌曲',))
        self.assertEqual(BATCH.allowed_voice_types, ('声乐、钢琴', '高声部', '高声部、钢琴'))

    def test_scope_rejects_outside_file(self):
        with self.assertRaises(ValueError):
            source_record('65445')


if __name__ == '__main__':
    unittest.main()
