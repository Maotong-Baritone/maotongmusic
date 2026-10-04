import unittest

from tools.brahms_albumblatt_clara_batch import BATCH


class AlbumblattClaraScopeTests(unittest.TestCase):
    def test_batch_is_bounded_to_one_unaccompanied_art_song(self):
        self.assertEqual(BATCH.ids, ('374716',))
        self.assertEqual(BATCH.work_titles, ('Albumblatt für Clara Schumann',))
        self.assertEqual(BATCH.allowed_categories, ('艺术歌曲',))
        self.assertEqual(BATCH.allowed_voice_types, ('独唱（无伴奏）',))


if __name__ == '__main__':
    unittest.main()
