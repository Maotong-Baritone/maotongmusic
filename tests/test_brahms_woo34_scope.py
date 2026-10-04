import unittest

from tools.brahms_woo34_batch import BATCH, DUPLICATE_IDS, STARTS, TITLES


class BrahmsWoo34ScopeTests(unittest.TestCase):
    def test_batch_is_bounded_to_the_rieter_biedermann_first_edition(self):
        self.assertEqual(BATCH.ids, ('23201',))
        self.assertEqual(DUPLICATE_IDS, ('102709', '102710'))
        self.assertEqual(BATCH.work_titles, ('14 Deutsche Volkslieder, WoO 34',))
        self.assertEqual(BATCH.allowed_categories, ('合唱作品',))
        self.assertEqual(BATCH.allowed_voice_types, ('混声合唱（无伴奏）',))
        self.assertEqual(len(STARTS), 14)
        self.assertEqual(len(TITLES), 14)


if __name__ == '__main__':
    unittest.main()
