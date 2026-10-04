import unittest

from tools.brahms_woo33_batch import BATCH, DUPLICATE_ID, STARTS, TITLES


class BrahmsWoo33ScopeTests(unittest.TestCase):
    def test_batch_is_bounded_to_the_simrock_first_edition(self):
        self.assertEqual(BATCH.ids, ('23200',))
        self.assertEqual(DUPLICATE_ID, '87938')
        self.assertEqual(BATCH.work_titles, ('49 Deutsche Volkslieder, WoO 33',))
        self.assertEqual(BATCH.allowed_categories, ('声乐套曲',))
        self.assertEqual(BATCH.allowed_voice_types, ('声乐、钢琴；第43–49首可加混声合唱',))
        self.assertEqual(len(STARTS), 49)
        self.assertEqual(len(TITLES), 49)


if __name__ == '__main__':
    unittest.main()
