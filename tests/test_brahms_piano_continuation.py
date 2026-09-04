import json
import tempfile
import unittest
from pathlib import Path

from tools.brahms_piano_continuation import BATCH, REVIEW_REL, apply_recorded_corrections


class RecordedCorrectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.stage = self.root/BATCH.stage_rel
        self.stage.mkdir(parents=True)
        self.sources = [{'imslp_id':key,'tonality':'','proposed_title':'Title '+key,'decision':'pending'}
                        for key in ('16646','16650','16651','unrelated')]
        self.trial = {'files':[{'imslp_id':f['imslp_id'],'tonality':'','title':f['proposed_title']}
                               for f in self.sources]}
        self.review = {'works':[{'files':self.sources}]}
        self.write(self.root/REVIEW_REL, self.review)
        self.write(self.stage/'manifest.json', self.trial)
        self.write(self.stage/'inspection.json', {
            'metadata_changes': {
                '16646':{'before_key':'','after_key':'d小调','before_title':'Title 16646','after_title':'Short title'},
                '16650':{'before_key':'','after_key':'b小调'},
                '16651':{'before_key':'','after_key':'g小调'},
            },
            'files':{key:{'notes':'Verified original'} for key in ('16646','16650','16651')},
        })

    def write(self,path,value):
        path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')

    def test_scoped_corrections_do_not_approve_or_change_unrelated_records(self):
        apply_recorded_corrections(self.root)
        updated = json.loads((self.root/REVIEW_REL).read_text(encoding='utf-8'))['works'][0]['files']
        self.assertEqual(updated[-1],self.sources[-1])
        self.assertEqual([f['tonality'] for f in updated],['d小调','b小调','g小调',''])
        self.assertTrue(all(f['decision']=='pending' for f in updated))
        before = (self.root/REVIEW_REL).read_bytes()
        apply_recorded_corrections(self.root)
        self.assertEqual((self.root/REVIEW_REL).read_bytes(),before)

    def test_concurrent_metadata_edit_stops_without_writing(self):
        self.sources[1]['tonality'] = 'Already edited'
        self.write(self.root/REVIEW_REL,self.review)
        before = (self.root/REVIEW_REL).read_bytes()
        with self.assertRaisesRegex(ValueError,'Metadata changed'):
            apply_recorded_corrections(self.root)
        self.assertEqual((self.root/REVIEW_REL).read_bytes(),before)
        self.assertEqual(json.loads((self.stage/'manifest.json').read_text(encoding='utf-8')),self.trial)


if __name__ == '__main__':
    unittest.main()
