import unittest

from tools.brahms_op61_duets_batch import BATCH


class Op61ScopeTests(unittest.TestCase):
    def test_scope_is_only_reviewed_unfiltered_art_song_duet_scan(self):
        self.assertEqual(BATCH.ids, ('97829',))
        self.assertEqual(BATCH.work_titles, ('4 Duets, Op.61',))
        self.assertEqual(BATCH.allowed_categories, ('艺术歌曲',))
        self.assertEqual(BATCH.allowed_voice_types, ('二重唱、钢琴',))


if __name__ == '__main__':
    unittest.main()
