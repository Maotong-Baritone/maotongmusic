from __future__ import annotations

import unittest

from lxml import html

from tools.import_brahms_imslp import (
    catalogue_from_title,
    apply_review_defaults,
    category_for,
    compact_instrumentation,
    chinese_tonality,
    deduplicate_manifest_files,
    default_decision,
    heading_context,
    movement_number_from_file,
    movements_from_document,
    normalize_catalogue_in_title,
    normalize_catalogue_text,
    parse_movements,
    proposed_title_for,
    richer_row_map,
    title_with_catalogue,
    value_for_label_fragment,
    split_trailing_key,
)


MOVEMENTS = (
    "7 pieces: "
    "1. Capriccio. Presto energico (D minor) "
    "2. Intermezzo. Andante (A minor) "
    "3. Capriccio. Allegro passionato (G minor) "
    "4. Intermezzo. Adagio (E major) "
    "5. Intermezzo. Andante con grazia ed intimissimo sentimento (E minor) "
    "6. Intermezzo. Andantino teneramente (E major) "
    "7. Capriccio. Allegro agitato (D minor)"
)


class BrahmsImportMetadataTest(unittest.TestCase):
    def work(self):
        return {
            "display_work_title": "7 Fantasien, Op. 116",
            "catalogue_number": "Op. 116",
            "movements": parse_movements(MOVEMENTS),
        }

    def test_normalizes_opus_and_catalogue_spacing_without_duplicates(self):
        self.assertEqual(title_with_catalogue('11 Chorale Preludes, Op.122', 'Op.122 (posth.)'), '11 Chorale Preludes, Op. 122')
        self.assertEqual(normalize_catalogue_text("Op.116"), "Op. 116")
        self.assertEqual(
            normalize_catalogue_in_title("Clarinet Sonata No.1, Op.120 No.1"),
            "Clarinet Sonata No. 1, Op. 120 No. 1",
        )
        self.assertEqual(
            title_with_catalogue("7 Fantasien, Op.116", "Op.116"),
            "7 Fantasien, Op. 116",
        )
        self.assertEqual(
            title_with_catalogue("Albumblatt für Clara Schumann", "WoO 1"),
            "Albumblatt für Clara Schumann, WoO 1",
        )
        self.assertEqual(catalogue_from_title("7 Fantasien, Op.116"), "Op. 116")
        self.assertEqual(
            catalogue_from_title("Clarinet Sonata No.1, Op.120 No.1"),
            "Op. 120 No. 1",
        )

    def test_finds_concatenated_imslp_table_labels(self):
        rows = {
            "Opus/Catalogue NumberOp./Cat. No.": "Op.116",
            "Movements/SectionsMov'ts/Sec's": "7 pieces: 1. Capriccio",
        }
        self.assertEqual(
            value_for_label_fragment(rows, "Opus/Catalogue Number"), "Op.116"
        )
        self.assertIn(
            "1. Capriccio",
            value_for_label_fragment(rows, "Movements/Sections"),
        )

    def test_recovers_css_numbered_movement_list_from_dom(self):
        document = html.fromstring(
            """
            <table><tr><th>乐章/ 段落</th><td>7 pieces:
            <ol><li>Capriccio. Presto energico (D minor)</li>
            <li>Intermezzo. Andante (A minor)</li></ol></td></tr></table>
            """
        )
        movements_text, movements = movements_from_document(
            document, richer_row_map(document)
        )
        self.assertIn("1. Capriccio. Presto energico", movements_text)
        self.assertEqual(movements[0]["number"], 1)
        self.assertEqual(movements[0]["title"], "Capriccio. Presto energico")
        self.assertEqual(movements[1]["key"], "A minor")

    def test_parses_detailed_movement_names_and_keys(self):
        movements = parse_movements(MOVEMENTS)
        self.assertEqual(len(movements), 7)
        self.assertEqual(movements[0]["title"], "Capriccio. Presto energico")
        self.assertEqual(movements[0]["key"], "D minor")
        self.assertEqual(
            movements[4]["title"],
            "Intermezzo. Andante con grazia ed intimissimo sentimento",
        )

    def test_individual_score_uses_movement_title_and_parent_work(self):
        score_file = {
            "description_en": "1. Capriccio",
            "description": "",
            "heading_context": {},
            "original_filename": "",
        }
        title, parent, scope = proposed_title_for(self.work(), score_file)
        self.assertEqual(title, "No. 1 Capriccio. Presto energico, Op. 116")
        self.assertEqual(parent, "7 Fantasien, Op. 116")
        self.assertEqual(scope, "individual_movement")

    def test_complete_score_keeps_whole_work_title(self):
        score_file = {
            "description_en": "Complete Score",
            "description": "",
            "heading_context": {},
            "original_filename": "Brahms-Op116.pdf",
        }
        title, parent, scope = proposed_title_for(self.work(), score_file)
        self.assertEqual(title, "7 Fantasien, Op. 116")
        self.assertEqual(parent, "")
        self.assertEqual(scope, "whole_work")

    def test_arrangement_heading_can_identify_its_movement(self):
        score_file = {
            "description_en": "Flute Part",
            "description": "",
            "heading_context": {
                "h4": "Intermezzo. Adagio (No.4)",
                "h5": "For Flute and Piano (Brenndorff)",
            },
            "original_filename": "",
        }
        self.assertEqual(movement_number_from_file(self.work(), score_file), 4)
        title, parent, scope = proposed_title_for(self.work(), score_file)
        self.assertEqual(title, "No. 4 Intermezzo. Adagio, Op. 116")
        self.assertEqual(parent, "7 Fantasien, Op. 116")
        self.assertEqual(scope, "individual_movement")

    def test_multiple_number_heading_is_a_selection_not_first_movement(self):
        work = {
            "display_work_title": "21 Hungarian Dances (Orchestra), WoO 1",
            "catalogue_number": "WoO 1",
            "movements": [],
        }
        score_file = {
            "description_en": "Complete Score",
            "description": "",
            "heading_context": {"h4": "Nos.1, 3, 10 (Brahms)"},
            "original_filename": "",
        }
        title, parent, scope = proposed_title_for(work, score_file)
        self.assertEqual(title, "Nos. 1, 3, 10, WoO 1")
        self.assertEqual(parent, "21 Hungarian Dances (Orchestra), WoO 1")
        self.assertEqual(scope, "selection")

        score_file["description_en"] = "No.1 - Horn 1, 2 (F)"
        title, parent, scope = proposed_title_for(work, score_file)
        self.assertEqual(title, "No. 1, WoO 1")
        self.assertEqual(parent, "21 Hungarian Dances (Orchestra), WoO 1")
        self.assertEqual(scope, "individual_movement")

    def test_version_suffix_in_filename_is_not_movement_for_one_part_work(self):
        work = {
            "display_work_title": "Academic Festival Overture, Op. 80",
            "catalogue_number": "Op. 80",
            "movements": [{"number": 1, "title": "Allegro", "key": ""}],
        }
        score_file = {
            "description_en": "Complete Score",
            "description": "",
            "heading_context": {},
            "original_filename": "Brahms-Op80-1.pdf",
        }
        title, parent, scope = proposed_title_for(work, score_file)
        self.assertEqual(title, "Academic Festival Overture, Op. 80")
        self.assertEqual(parent, "")
        self.assertEqual(scope, "whole_work")

    def test_heading_supplies_name_when_page_has_no_movement_list(self):
        work = {
            "display_work_title": "14 Deutsche Volkslieder, WoO 34",
            "catalogue_number": "WoO 34",
            "movements": [],
        }
        score_file = {
            "description_en": "Complete Score",
            "description": "",
            "heading_context": {"h4": "In stiller Nacht (No.8)"},
            "original_filename": "",
        }
        title, parent, scope = proposed_title_for(work, score_file)
        self.assertEqual(title, "No. 8 In stiller Nacht, WoO 34")
        self.assertEqual(parent, "14 Deutsche Volkslieder, WoO 34")
        self.assertEqual(scope, "individual_movement")

    def test_range_does_not_backtrack_into_single_digit_number(self):
        score_file = {"description_en": "No.11-16", "heading_context": {}}
        title, _parent, scope = proposed_title_for(self.work(), score_file)
        self.assertEqual(scope, "selection")
        self.assertEqual(title, "Nos. 11–16, Op. 116")

    def test_new_heading_discards_previous_subsection(self):
        document = html.fromstring('<main><h3>Scores</h3><h4>No.1</h4><h5>For Piano</h5><div>A</div><h4>Complete</h4><div id="file">B</div></main>')
        context = heading_context(document.get_element_by_id('file'))
        self.assertEqual(context['h4'], 'Complete')
        self.assertEqual(context['h5'], '')

    def test_original_piano_work_not_changed_by_orchestral_arrangement_tags(self):
        work = self.work() | {"genre_categories": "Fantasias; For piano; For 1 player; For orchestra (arr)"}
        self.assertEqual(category_for(work, {"description_en": "Complete Score"}), "器乐独奏")
        self.assertEqual(category_for(work, {"heading_context": {"h5": "For Orchestra (Smith)"}}), "管弦乐/交响曲")

    def test_arranger_policy_includes_composer_not_unknown_or_others(self):
        self.assertEqual(default_decision({"section": "tabArrTrans", "arranger": "Johannes Brahms"}, True)[0], 'pending')
        self.assertEqual(default_decision({"section": "tabArrTrans", "arranger": ""}, True)[0], 'excluded')
        self.assertEqual(default_decision({"section": "tabScore1", "arranger": "Antonín Dvořák"}, True)[0], 'excluded')

    def test_compact_chinese_instrumentation(self):
        self.assertEqual(compact_instrumentation('piano'), '钢琴独奏')
        self.assertEqual(compact_instrumentation('voice, piano'), '声乐、钢琴')
        self.assertEqual(compact_instrumentation('2 voices, mixed chorus, orchestra'), '独唱、混声合唱、管弦乐队')

    def test_rebuilding_preserves_manual_metadata(self):
        work = self.work() | {"genre_categories": "Fantasias; For piano"}
        file = {"copyright": "Public Domain", "description_en": "1. Capriccio"}
        previous = {"public_id": "stable-id", "review_edited": True, "decision": "approved", "proposed_title": "人工标题, Op. 116", "language_cn": "", "review_notes": "已确认"}
        apply_review_defaults(work, file, previous)
        self.assertEqual(file['public_id'], 'stable-id')
        self.assertEqual(file['proposed_title'], '人工标题, Op. 116')
        self.assertEqual(file['decision'], 'approved')
        self.assertEqual(file['review_notes'], '已确认')
        self.assertEqual(file['sub_category'], '随想曲')

    def test_filename_work_number_is_never_a_movement(self):
        work = self.work() | {"display_work_title": "Clarinet Sonata No. 1, Op. 120 No. 1", "catalogue_number": "Op. 120 No. 1"}
        score_file = {"description_en": "Complete Score", "original_filename": "Brahms_Op120_1.pdf"}
        self.assertEqual(proposed_title_for(work, score_file), (work['display_work_title'], '', 'whole_work'))

    def test_bracketed_piece_name_is_recognized(self):
        self.assertEqual(movement_number_from_file(self.work(), {"description": "1. [Am Sonntag Morgen"}), 1)

    def test_key_symbols_and_bar_counts_are_not_part_of_title(self):
        name, key = split_trailing_key('Un poco allegretto (A♭ major, 164 bars)')
        self.assertEqual(name, 'Un poco allegretto')
        self.assertEqual(chinese_tonality(key), '降A大调')

    def test_same_source_file_has_one_review_row(self):
        first = {"imslp_id": "001", "decision": "excluded", "warnings": []}
        second = {"imslp_id": "1", "decision": "pending", "warnings": []}
        manifest = {'works': [
            {'display_work_title': 'A', 'source_url': 'https://imslp.org/wiki/A', 'files': [first]},
            {'display_work_title': 'B', 'source_url': 'https://imslp.org/wiki/B', 'files': [second]},
        ]}
        deduplicate_manifest_files(manifest)
        self.assertEqual(len(manifest['works'][0]['files']), 0)
        self.assertEqual(len(manifest['works'][1]['files']), 1)
        self.assertEqual(len(second['source_references']), 2)

    def test_nested_sections_do_not_become_part_of_piece_title(self):
        document = html.fromstring('<table><tr><th>Movements</th><td><ol><li>Motet One<ol><li>Section A</li><li>Section B</li></ol></li><li>Motet Two</li></ol></td></tr></table>')
        raw, movements = movements_from_document(document, richer_row_map(document))
        self.assertEqual(len(movements), 2)
        self.assertEqual(movements[0]['title'], 'Motet One')
        self.assertTrue(movements[0]['has_subsections'])
        self.assertIn('Section A', raw)


if __name__ == "__main__":
    unittest.main()
