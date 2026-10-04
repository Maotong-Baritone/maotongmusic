import unittest

from tools.brahms_woo20_30_small_vocal_batch import BATCH, IDS, VOICE_CORRECTIONS


class BrahmsWoo20To30SmallVocalScopeTests(unittest.TestCase):
    def test_batch_is_bounded_to_nine_expected_files(self):
        self.assertEqual(
            IDS,
            ('102714', '85498', '85506', '102768', '102763', '102770',
             '102716', '102772', '102718'),
        )
        self.assertEqual(BATCH.ids, IDS)
        self.assertEqual(len(set(IDS)), 9)

    def test_categories_and_instrumentation_are_explicitly_bounded(self):
        self.assertEqual(BATCH.allowed_categories, ('合唱作品', '艺术歌曲'))
        self.assertEqual(BATCH.allowed_voice_types, ('混声合唱', '女声合唱', '声乐、钢琴'))

    def test_metadata_corrections_only_cover_live_page_misclassifications(self):
        self.assertEqual(
            set(VOICE_CORRECTIONS),
            {'102768', '102763', '102770', '102716', '102772', '102718'},
        )


if __name__ == '__main__':
    unittest.main()
