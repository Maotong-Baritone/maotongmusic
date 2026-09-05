import unittest

from tools.brahms_op66_duets_batch import BATCH


class Op66ScopeTests(unittest.TestCase):
    def test_scope_is_only_reviewed_unfiltered_art_song_duet_scan(self):
        self.assertEqual(BATCH.ids, ('97831',))
        self.assertEqual(BATCH.work_titles, ('5 Duets, Op.66',))
        self.assertEqual(BATCH.allowed_categories, ('艺术歌曲',))
        self.assertEqual(BATCH.allowed_voice_types, ('二重唱、钢琴',))


if __name__ == '__main__':
    unittest.main()
