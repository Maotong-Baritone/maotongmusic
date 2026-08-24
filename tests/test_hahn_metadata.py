import unittest

from tools.import_hahn_imslp import (
    concise_file_label,
    concise_instrumentation,
    voice_types_for,
)


class HahnMetadataLabelTest(unittest.TestCase):
    def test_full_concerto_orchestration_is_reduced_to_soloist(self):
        source = (
            "Solo: violinOrchestra: 2 flutes, 2 oboes, 2 clarinets, "
            "2 bassoons4 horns, 2 trumpets, 3 trombones, timpani, "
            "percussion, harp, strings"
        )
        self.assertEqual(concise_instrumentation(source), "小提琴独奏")

    def test_piano_uses_existing_solo_label_style(self):
        self.assertEqual(concise_instrumentation("piano"), "钢琴独奏")

    def test_piano_score_is_not_duplicated_as_a_part(self):
        self.assertEqual(
            concise_file_label("Piano Score", allow_bare_instrument=True),
            "钢琴谱",
        )

    def test_orchestral_part_uses_short_existing_part_style(self):
        work = {"instrumentation": "Orchestra"}
        score_file = {"section": "tabArrTrans", "description_en": "Oboe"}
        self.assertEqual(voice_types_for(work, score_file), "双簧管分谱")

    def test_concerto_arrangement_is_identified_by_file_content(self):
        work = {
            "instrumentation": (
                "Solo: violinOrchestra: 2 flutes, 2 oboes, 2 clarinets, "
                "2 bassoons4 horns, 2 trumpets, 3 trombones, timpani, "
                "percussion, harp, strings"
            )
        }
        piano_score = {"section": "tabArrTrans", "description_en": "Piano Score"}
        violin_part = {"section": "tabArrTrans", "description_en": "Violin Part"}
        self.assertEqual(voice_types_for(work, piano_score), "钢琴谱")
        self.assertEqual(voice_types_for(work, violin_part), "小提琴分谱")


if __name__ == "__main__":
    unittest.main()
