import unittest

from tools.brahms_woo35_batch import BATCH, DUPLICATE_ID, FILE_IDS, SPECIAL_LICENSE_ID, STARTS, TITLES


class BrahmsWoo35ScopeTests(unittest.TestCase):
    def test_batch_is_bounded_to_two_reviewed_public_domain_files(self):
        self.assertEqual(BATCH.ids, ('102712', '108869'))
        self.assertEqual(FILE_IDS, ('102712', '108869'))
        self.assertEqual(DUPLICATE_ID, '102713')
        self.assertEqual(SPECIAL_LICENSE_ID, '202904')
        self.assertEqual(BATCH.work_titles, ('12 Deutsche Volkslieder, WoO 35',))
        self.assertEqual(BATCH.allowed_categories, ('合唱作品',))
        self.assertEqual(BATCH.allowed_voice_types, ('混声合唱（无伴奏）',))
        self.assertEqual(len(STARTS), 12)
        self.assertEqual(len(TITLES), 12)


if __name__ == '__main__':
    unittest.main()
