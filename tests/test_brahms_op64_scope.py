import unittest

from tools.brahms_op64_quartets_batch import BATCH


class Op64ScopeTests(unittest.TestCase):
    def test_scope_is_only_reviewed_unfiltered_art_song_quartet_scan(self):
        self.assertEqual(BATCH.ids, ('104767',))
        self.assertEqual(BATCH.work_titles, ('3 Quartets, Op.64',))
        self.assertEqual(BATCH.allowed_categories, ('艺术歌曲',))
        self.assertEqual(BATCH.allowed_voice_types, ('四重唱、钢琴',))


if __name__ == '__main__':
    unittest.main()
