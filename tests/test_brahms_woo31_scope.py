import unittest

from tools.brahms_woo31_batch import BATCH, DUPLICATE_IDS, ENGLISH_ID, GERMAN_ID


class BrahmsWoo31ScopeTests(unittest.TestCase):
    def test_batch_is_bounded_to_two_distinct_public_domain_editions(self):
        self.assertEqual(BATCH.ids, (GERMAN_ID, ENGLISH_ID))
        self.assertEqual(DUPLICATE_IDS, ('88080', '88081'))
        self.assertEqual(BATCH.work_titles, ('15 Volkskinderlieder, WoO 31',))
        self.assertEqual(BATCH.allowed_categories, ('声乐套曲',))
        self.assertEqual(BATCH.allowed_voice_types, ('声乐、钢琴',))


if __name__ == '__main__':
    unittest.main()
