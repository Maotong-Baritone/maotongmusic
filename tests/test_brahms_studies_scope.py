import unittest

from tools.brahms_studies_batch import BATCH


class BrahmsStudiesScopeTests(unittest.TestCase):
    def test_batch_is_limited_to_four_reviewed_piano_scores(self):
        self.assertEqual(BATCH.ids, ("57515", "454876", "454879", "64516"))
        self.assertEqual(BATCH.work_titles, ("5 Studies, Anh.1a/1",))
        self.assertEqual(BATCH.allowed_voice_types, ("钢琴独奏", "钢琴左手"))


if __name__ == "__main__":
    unittest.main()
