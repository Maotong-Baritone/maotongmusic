import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tools.brahms_art_song_duets_batch import BATCH, source_record
from tools.brahms_late_piano_batch import source_record as generic_source_record
from tools.publish_brahms_op116 import OP116_BATCH, REVIEW_REL


class ArtSongScopeTests(unittest.TestCase):
    def test_art_song_category_and_voice_are_explicitly_bounded(self):
        self.assertEqual(BATCH.ids, ('97824',))
        self.assertEqual(BATCH.allowed_categories, ('艺术歌曲',))
        self.assertEqual(BATCH.allowed_voice_types, ('二重唱、钢琴',))

    def test_default_batch_rejects_art_song_and_opt_in_keeps_rights_guards(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / REVIEW_REL
            path.parent.mkdir(parents=True)
            record = {
                'imslp_id':'97824', 'copyright':'Public Domain', 'decision':'pending',
                'warnings':[], 'category':'艺术歌曲', 'voice_types':'二重唱、钢琴',
                'eligible':True,
            }

            def write():
                path.write_text(json.dumps({'works':[{'title':'3 Duets, Op.20','files':[record]}]}), encoding='utf-8')

            write()
            default = replace(OP116_BATCH, ids=('97824',), work_titles=('3 Duets, Op.20',),
                              allowed_voice_types=('二重唱、钢琴',))
            with self.assertRaisesRegex(ValueError, 'Review, rights, or instrumentation'):
                generic_source_record('97824', root, batch=default)
            self.assertEqual(source_record('97824', root)[1]['category'], '艺术歌曲')

            for key, bad in [('warnings',['unresolved']), ('copyright','Special license'),
                             ('decision','deferred'), ('eligible',False),
                             ('category','合唱作品'), ('voice_types','四重唱、钢琴')]:
                old = record[key]
                record[key] = bad
                write()
                with self.subTest(key=key), self.assertRaises(ValueError):
                    source_record('97824', root)
                record[key] = old


if __name__ == '__main__':
    unittest.main()
