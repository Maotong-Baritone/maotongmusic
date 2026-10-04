import unittest

from tools.brahms_op43_op84_low_voice_batch import BATCH, IDS


class BrahmsOp43Op84LowVoiceScopeTests(unittest.TestCase):
    def test_batch_is_bounded_to_nine_expected_files(self):
        self.assertEqual(
            IDS,
            ('244481', '245413', '246293', '246294',
             '38727', '38728', '346942', '38729', '346943'),
        )
        self.assertEqual(BATCH.ids, IDS)
        self.assertEqual(len(set(IDS)), 9)

    def test_categories_and_instrumentation_are_explicitly_bounded(self):
        self.assertEqual(BATCH.allowed_categories, ('艺术歌曲', '器乐分谱'))
        self.assertEqual(
            BATCH.allowed_voice_types,
            ('低声部', '圆号分谱', '低声部、钢琴', '二重唱、钢琴'),
        )


if __name__ == '__main__':
    unittest.main()
