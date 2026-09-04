import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import report_brahms_op116 as report
from tools.publish_brahms_op116 import IDS


class Op116ReportTests(unittest.TestCase):
    def test_refresh_preserves_publication_decisions_and_displays_actual_counts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage = root/'staging'
            (stage/'pdfs').mkdir(parents=True)
            files, renders = [], []
            notes = {'checked_on':'2026-09-02','method':'Test inspection',
                     'single_files':{},'complete_files':{}}
            for file_id in report.ALLOWED_IDS:
                payload = b'%PDF-test-'+file_id.encode()
                (stage/'pdfs'/f'{file_id}.pdf').write_bytes(payload)
                single = 1524 <= int(file_id) <= 1530
                files.append({'imslp_id':file_id,'local_path':f'pdfs/{file_id}.pdf',
                              'sha256':hashlib.sha256(payload).hexdigest(),
                              'page_count':1,'bytes':len(payload),'title':file_id,
                              'movement_number':int(file_id)-1523 if single else None,
                              'tonality':'d小调' if single else '', 'work':'Op.116',
                              'sub_category':'测试','publication_approved':file_id in IDS})
                if single:
                    notes['single_files'][file_id] = {'pages':1,'number':int(file_id)-1523,'key':'d小调'}
                else:
                    notes['complete_files'][file_id] = {'pages':1,'label':'Test edition','notes':'Checked'}
                image_dir = root/'tmp/pdfs/op116'/file_id
                image_dir.mkdir(parents=True)
                (image_dir/'page-1.png').write_bytes(b'test preview copy')
                renders.append({'id':file_id,'rendered_pages':1})
            manifest = {'files':files,'held_back':[],'source_url':'https://imslp.org/wiki/test'}
            paths = {
                stage/'manifest.json':manifest,
                stage/'inspection.json':notes,
                root/'tmp/pdfs/op116/render-check.json':renders,
                stage/'publication.json':{'storage_verified_count':8,'website_published_count':8},
            }
            for path, value in paths.items():
                path.write_text(json.dumps(value),encoding='utf-8')
            def save(value):
                (stage/'manifest.json').write_text(json.dumps(value),encoding='utf-8')
            with mock.patch.object(report,'ROOT',root), mock.patch.object(report,'STAGE',stage), mock.patch.object(report,'save_manifest',side_effect=save):
                report.main()
            result = json.loads((stage/'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual({f['imslp_id'] for f in result['files'] if f['publication_approved']},set(IDS))
            html = (stage/'review.html').read_text(encoding='utf-8')
            self.assertIn('正式网站已上线 8 份',html)
            self.assertIn('首页更新记录已同步',html)
            self.assertNotIn('没有修改正式曲库',html)


if __name__ == '__main__':
    unittest.main()
