from copy import deepcopy
import unittest

import brahms_review as review
from tools.import_brahms_imslp import category_for, subcategory_for, compact_instrumentation


class BrahmsReviewTest(unittest.TestCase):
    def manifest(self):
        item = {'imslp_id': '1', 'title_scope': 'individual_movement', 'movement_number': 1,
                'proposed_title': 'No. 1 Intermezzo, Op. 116', 'proposed_work': '7 Fantasien, Op. 116',
                'category': '器乐独奏', 'sub_category': '间奏曲', 'voice_types': '钢琴独奏',
                'tonality': 'a小调', 'description_en': 'Complete Score', 'section': 'tabScore1',
                'decision': 'pending', 'warnings': [], 'eligible': True}
        return {'works': [{'source_url': 'https://imslp.org/wiki/test', 'display_work_title': '7 Fantasien, Op. 116',
                           'files': [item, dict(item, imslp_id='2', description_en='Complete Score (scan)')]}]}

    def test_art_song_duets_quartets_use_art_song_not_chorus(self):
        for voices, genre, label in [(2, 'Duets', '二重唱、钢琴'), (4, 'Quartets', '四重唱、钢琴')]:
            work = {'genre_categories': f'{genre}; For {voices} voices, piano; German language'}
            self.assertEqual(category_for(work, {}), '艺术歌曲')
            self.assertEqual(subcategory_for(work, '艺术歌曲'), '')
            self.assertEqual(compact_instrumentation(f'{voices} voices, piano'), label)

    def test_actual_chorus_sacred_and_cantatas_keep_categories(self):
        for genres, expected in [
            ('Songs; For mixed chorus', '合唱作品'),
            ('Motets; For 4 voices', '宗教声乐作品'),
            ('Secular cantatas; For 2 voices, orchestra', '音乐会咏叹调/世俗康塔塔'),
            ('Canons; For 3 voices', '合唱作品'),
        ]:
            self.assertEqual(category_for({'genre_categories': genres}, {}), expected)
        self.assertEqual(category_for({'genre_categories': 'Quartets; For 4 voices, piano'},
                                      {'heading_context': {'h5': 'For Male Chorus and Piano (Smith)'}}), '合唱作品')

    def test_scan_versions_fold_into_one_group_without_dropping_files(self):
        works = review.grouped_works(review.rows_for(self.manifest()))
        self.assertEqual(len(works), 1)
        self.assertEqual(len(works[0]['pieces']), 1)
        self.assertEqual(len(works[0]['pieces'][0]['groups']), 1)
        self.assertEqual(len(works[0]['pieces'][0]['groups'][0]['rows']), 2)

    def test_different_movements_tonalities_parts_and_arrangers_stay_separate(self):
        for field, value in [('movement_number', 2), ('tonality', 'C大调'),
                             ('description_en', 'Horn 2'), ('arranger', 'Other arranger'),
                             ('language_cn', '英语')]:
            manifest = self.manifest()
            manifest['works'][0]['files'][1][field] = value
            works = review.grouped_works(review.rows_for(manifest))
            groups = [g for p in works[0]['pieces'] for g in p['groups']]
            self.assertEqual(len(groups), 2, field)

    def test_issue_counts_are_unique_within_group_not_additive_between_groups(self):
        manifest = self.manifest()
        manifest['works'][0]['files'][0]['warnings'] = ['乐章名称待确认', '标题太长', '许可版本需核对']
        groups = review.issue_groups(review.rows_for(manifest))
        self.assertEqual({g['key']: len(g['rows']) for g in groups}, {'title': 1, 'rights': 1})

    def test_samples_are_deterministic_unique_and_do_not_approve_files(self):
        rows = review.rows_for(self.manifest())
        before = deepcopy(rows)
        sample = review.sample_rows(rows)
        self.assertEqual(sample, review.sample_rows(rows))
        self.assertEqual(len({r['score_file']['imslp_id'] for r in sample}), len(sample))
        self.assertEqual(rows, before)

    def test_edit_or_status_change_invalidates_saved_group_signature(self):
        rows = review.rows_for(self.manifest())
        before = review.row_signature(rows)
        rows[0]['score_file']['decision'] = 'deferred'
        self.assertNotEqual(review.row_signature(rows), before)

    def test_deferred_visible_in_active_but_not_pending(self):
        rows = review.rows_for(self.manifest())
        rows[0]['score_file']['decision'] = 'deferred'
        self.assertEqual(len(review.filter_rows(rows, decision='active')), 2)
        self.assertEqual(len(review.filter_rows(rows, decision='pending')), 1)


if __name__ == '__main__':
    unittest.main()
