import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from tools.brahms_late_piano_batch import source_record
from tools.publish_brahms_op116 import OP116_BATCH, REVIEW_REL

class SourceInstrumentationScopeTests(unittest.TestCase):
    def test_organ_is_opt_in_and_rights_review_guards_remain(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / REVIEW_REL
            path.parent.mkdir(parents=True)
            record = {'imslp_id':'84692','copyright':'Public Domain','decision':'pending',
                      'warnings':[],'category':'器乐独奏','voice_types':'管风琴独奏','eligible':True}
            def write():
                path.write_text(json.dumps({'works':[{'title':'7 Fantasien, Op.116','files':[record]}]}),encoding='utf-8')
            write()
            with self.assertRaisesRegex(ValueError,'instrumentation'):
                source_record('84692',root,batch=OP116_BATCH)
            batch = replace(OP116_BATCH,ids=('84692',),allowed_voice_types=('管风琴独奏',))
            self.assertEqual(source_record('84692',root,batch=batch)[1]['voice_types'],'管风琴独奏')
            for key,bad in [('warnings',['unresolved']),('copyright','Special license'),
                            ('decision','deferred'),('eligible',False),
                            ('category','艺术歌曲'),('voice_types','声乐、钢琴')]:
                old = record[key]
                record[key] = bad
                write()
                with self.subTest(key=key),self.assertRaises(ValueError):
                    source_record('84692',root,batch=batch)
                record[key] = old

if __name__ == '__main__':
    unittest.main()
