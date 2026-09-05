import unittest

from tools.brahms_op28_duets_batch import BATCH


class Op28ScopeTests(unittest.TestCase):
    def test_scope_is_only_reviewed_art_song_duet_files(self):
        self.assertEqual(BATCH.ids, ('97827','851926'))
        self.assertEqual(BATCH.work_titles, ('4 Duets, Op.28',))
        self.assertEqual(BATCH.allowed_categories, ('艺术歌曲',))
        self.assertEqual(BATCH.allowed_voice_types, ('二重唱、钢琴',))


if __name__ == '__main__':
    unittest.main()
