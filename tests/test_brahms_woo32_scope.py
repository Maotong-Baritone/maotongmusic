import unittest

from tools.brahms_woo32_batch import BATCH, DUPLICATE_ID


class BrahmsWoo32ScopeTests(unittest.TestCase):
    def test_batch_is_bounded_to_the_original_complete_scan(self):
        self.assertEqual(BATCH.ids, ('88084',))
        self.assertEqual(DUPLICATE_ID, '88085')
        self.assertEqual(BATCH.work_titles, ('28 Deutsche Volkslieder, WoO 32',))
        self.assertEqual(BATCH.allowed_categories, ('声乐套曲',))
        self.assertEqual(BATCH.allowed_voice_types, ('声乐、钢琴',))


if __name__ == '__main__':
    unittest.main()
