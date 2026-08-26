import unittest

from tools.import_hahn_imslp import (
    category_for,
    concise_file_label,
    concise_instrumentation,
    language_for,
    subcategory_for,
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

    def test_orchestral_part_in_arrangement_tab_uses_parts_category(self):
        work = {
            "work_title": "La fête chez Thérèse",
            "genre_categories": "Ballets; For orchestra",
            "instrumentation": "Orchestra",
        }
        score_file = {"section": "tabArrTrans", "description_en": "Oboe"}
        self.assertEqual(category_for(work, score_file), "器乐分谱")

    def test_orchestral_complete_score_in_arrangement_tab_stays_orchestral(self):
        work = {
            "work_title": "La fête chez Thérèse",
            "genre_categories": "Ballets; For orchestra",
            "instrumentation": "Orchestra",
        }
        score_file = {
            "section": "tabArrTrans",
            "description_en": "Complete Score",
        }
        self.assertEqual(category_for(work, score_file), "管弦乐/交响曲")

    def test_french_english_hahn_work_uses_french_only(self):
        self.assertEqual(language_for({"language": "French and English"}), "法语")

    def test_french_latin_hahn_work_keeps_supported_bilingual_label(self):
        work = {"genre_categories": "French language; Latin language"}
        self.assertEqual(language_for(work), "法语/拉丁语")

    def test_latin_only_hahn_work_keeps_latin_label(self):
        self.assertEqual(language_for({"language": "Latin"}), "拉丁语")

    def test_art_song_does_not_repeat_its_category_as_subcategory(self):
        self.assertEqual(
            subcategory_for({"genre_categories": "Songs"}, "艺术歌曲"),
            "",
        )

    def test_chanson_label_is_hidden_only_when_art_song_is_already_shown(self):
        work = {"genre_categories": "Chansons"}
        self.assertEqual(subcategory_for(work, "艺术歌曲"), "")
        self.assertEqual(subcategory_for(work, "声乐套曲"), "香颂")


if __name__ == "__main__":
    unittest.main()
