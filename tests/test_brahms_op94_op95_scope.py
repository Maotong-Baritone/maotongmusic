import unittest

from tools.brahms_op94_op95_batch import BATCH, IDS, source_record


class BrahmsOp94Op95ScopeTests(unittest.TestCase):
    def test_batch_is_exactly_twelve_selected_files(self):
        self.assertEqual(IDS, ('244854', '244855', '244856', '244857', '244858',
                               '246557', '246558', '246559', '246560', '246561', '246562', '246563'))
        self.assertEqual(len(set(IDS)), 12)
        self.assertEqual(BATCH.allowed_categories, ('艺术歌曲',))
        self.assertEqual(BATCH.allowed_voice_types, ('高声部', '声乐、钢琴', '高声部、钢琴'))

    def test_scope_rejects_outside_file(self):
        with self.assertRaises(ValueError):
            source_record('347092')


if __name__ == '__main__':
    unittest.main()
