import unittest

from tools.brahms_op46_op96_medium_voice_batch import BATCH, IDS


class BrahmsOp46Op96MediumVoiceScopeTests(unittest.TestCase):
    def test_batch_is_bounded_to_nine_expected_files(self):
        self.assertEqual(
            IDS,
            ('133951', '133953', '242969', '242970', '242971',
             '243448', '243534', '243535', '243536'),
        )
        self.assertEqual(BATCH.ids, IDS)
        self.assertEqual(len(set(IDS)), 9)

    def test_category_and_instrumentation_are_explicitly_bounded(self):
        self.assertEqual(BATCH.allowed_categories, ('艺术歌曲',))
        self.assertEqual(BATCH.allowed_voice_types, ('中音声部、钢琴',))


if __name__ == '__main__':
    unittest.main()
