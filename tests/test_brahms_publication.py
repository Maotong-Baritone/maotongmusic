import hashlib
import json
import os
import sys
import importlib
import io
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from tools import publish_brahms_op116 as pub
from tools.sync_object_storage import ObjectState


class MemoryStorage:
    objects = {}

    def __init__(self, **kwargs):
        self.description = 'test storage'

    def inspect(self, entry):
        actual = self.objects.get(entry.storage_key)
        if actual is None:
            return ObjectState('missing')
        return ObjectState('verified' if actual == entry.sha256 else 'different')

    def upload(self, entry):
        self.objects[entry.storage_key] = entry.sha256


class BrahmsPublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stage = self.root/pub.STAGE_REL
        (self.stage/'pdfs').mkdir(parents=True)
        self.old = {'id':1,'public_id':str(uuid.uuid4()),'title':'Existing','composer':'Other',
                    'category':'器乐独奏','filename':'existing.pdf'}
        (self.root/'scores').mkdir()
        (self.root/'scores/existing.pdf').write_bytes(b'%PDF-old')
        source_files, staged_files = [], []
        for n, file_id in enumerate(pub.IDS):
            payload = b'%PDF-test-'+file_id.encode()
            pdf = self.stage/'pdfs'/f'{file_id}.pdf'
            pdf.write_bytes(payload)
            common = {'title':f'Title {file_id}, Op.116','work':'7 Fantasien, Op.116' if n else '',
                      'category':'器乐独奏','sub_category':'幻想曲','voice_types':'钢琴独奏','tonality':'','language':''}
            staged_files.append({'imslp_id':file_id,**common,'copyright':'Public Domain',
                                 'local_path':f'pdfs/{file_id}.pdf','bytes':len(payload),
                                 'sha256':hashlib.sha256(payload).hexdigest(),'visual_check':'checked_with_notes',
                                 'page_count':1,'rendered_pages':1,'publication_approved':False})
            source_files.append({'imslp_id':file_id,'public_id':str(uuid.uuid4()),
                                 **{v:common[k] for k,v in pub.FIELD_MAP.items()},'copyright':'Public Domain',
                                 'decision':'pending','publisher':'old edition','description':'score'})
        self.review = {'composer':'Johannes Brahms/勃拉姆斯','works':[{'title':'7 Fantasien, Op.116',
                       'source_url':'https://imslp.org/wiki/test','files':source_files}]}
        self.write(pub.REVIEW_REL,self.review)
        self.write(pub.STAGE_REL/'manifest.json',{'files':staged_files})
        self.write(pub.STAGE_REL/'inspection.json',{'proposed_first_publication_ids':list(pub.IDS)})
        self.write(Path('data.json'),[self.old])
        self.write(Path('logs.json'),[{'date':'before','type':'add','msg':'Existing log'}])
        self.write(Path('site-config.json'),{'scoreStorage':{'baseUrl':'https://scores.maotong.me'}})
        self.write(Path('storage-manifest.json'),{'schema_version':1,'key_strategy':'public_id_sharded','entries':[]})
        MemoryStorage.objects = {}
        for patch in (
            mock.patch.object(pub,'S3Target',MemoryStorage),
            mock.patch('score_storage.S3Target',MemoryStorage),
            mock.patch.dict(os.environ,{'SCORE_STORAGE_AUTO_SYNC':'1','SCORE_STORAGE_BUCKET':'test',
                'SCORE_STORAGE_ENDPOINT_URL':'https://storage.invalid','SCORE_STORAGE_R2_ACCOUNT_ID':'',
                'SCORE_STORAGE_REGION':'auto','SCORE_STORAGE_ACCESS_KEY_ID':'test',
                'SCORE_STORAGE_SECRET_ACCESS_KEY':'test','SUBMISSIONS_DB':str(self.root/'submissions.db')}),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        # submission_store captures DB_PATH in function defaults at import time.
        # Keep that module isolated so later admin tests cannot inherit this DB.
        modules = mock.patch.dict(sys.modules)
        modules.start()
        self.addCleanup(modules.stop)
        sys.modules.pop('submission_store', None)
        self.store = importlib.import_module('submission_store')
        self.assertEqual(self.store.DB_PATH, self.root/'submissions.db')

    def write(self,path,data):
        (self.root/path).parent.mkdir(parents=True,exist_ok=True)
        (self.root/path).write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')

    def test_exact_scope_and_metadata_change_guard(self):
        self.assertEqual(len(pub.prepare(self.root)['planned']),8)
        self.review['works'][0]['files'][1]['tonality']='E大调'
        self.write(pub.REVIEW_REL,self.review)
        with self.assertRaisesRegex(ValueError,'Metadata changed'):
            pub.prepare(self.root)

    def test_modified_pdf_cannot_publish(self):
        (self.stage/'pdfs/1524.pdf').write_bytes(b'%PDF-changed')
        with self.assertRaisesRegex(ValueError,'PDF changed'):
            pub.prepare(self.root)

    def test_organ_requires_explicit_instrumentation_scope(self):
        from dataclasses import replace
        self.review['works'][0]['files'][0]['voice_types'] = '管风琴独奏'
        self.write(pub.REVIEW_REL,self.review)
        staged = pub.read_json(self.stage/'manifest.json')
        staged['files'][0]['voice_types'] = '管风琴独奏'
        self.write(pub.STAGE_REL/'manifest.json',staged)
        with self.assertRaisesRegex(ValueError,'Instrumentation outside'):
            pub.prepare(self.root)
        batch = replace(pub.OP116_BATCH,ids=pub.IDS[:1],allowed_voice_types=('管风琴独奏',))
        self.write(pub.STAGE_REL/'inspection.json',{'proposed_first_publication_ids':list(batch.ids)})
        plan = pub.prepare(self.root,batch=batch)
        self.assertEqual(plan['planned'][0]['item']['voice_types'],'管风琴独奏')
        self.assertEqual(plan['planned'][0]['item']['category'],'器乐独奏')
        self.assertTrue(plan['planned'][0]['item']['filename'].startswith('器乐独奏/'))

    def test_publish_preserves_old_records_adds_one_log_and_is_idempotent(self):
        pub.publish(self.root,verify_public=False)
        first = (self.root/'data.json').read_bytes()
        data = json.loads(first)
        self.assertEqual(len(data),9)
        self.assertEqual(data[-1],self.old)
        self.assertEqual(len(MemoryStorage.objects),8)
        logs = pub.read_json(self.root/'logs.json')
        self.assertEqual(len(logs),2)
        self.assertEqual(logs[0]['count'],8)
        self.assertEqual(logs[-1]['msg'],'Existing log')
        pub.publish(self.root,verify_public=False)
        self.assertEqual((self.root/'data.json').read_bytes(),first)
        self.assertEqual(pub.read_json(self.root/'logs.json'),logs)

    def test_remote_conflict_does_not_overwrite_or_publish(self):
        first = pub.prepare(self.root)['planned'][0]
        key = pub.storage.storage_key_for(first['item']['public_id'])
        MemoryStorage.objects[key] = 'unrelated-content'
        with self.assertRaisesRegex(ValueError,'conflicting remote'):
            pub.publish(self.root,verify_public=False)
        self.assertEqual(MemoryStorage.objects[key],'unrelated-content')
        self.assertEqual(pub.read_json(self.root/'data.json'),[self.old])

    def test_public_download_bytes_must_match_the_staged_original(self):
        with mock.patch.object(pub,'urlopen',return_value=io.BytesIO(b'incorrect response')) as request:
            with self.assertRaisesRegex(ValueError,'Public download does not match'):
                pub.publish(self.root)
        self.assertEqual(request.call_args.args[0].get_header('User-agent'),'MaoTongMusic-ReviewedPublication/1.0')
        self.assertEqual(pub.read_json(self.root/'data.json'),[self.old])

    def test_multi_work_batch_uses_its_own_scope_count_and_source_page(self):
        second = self.review['works'][0]['files'].pop(1)
        self.review['works'].append({'title':'Second work','source_url':'https://imslp.org/wiki/second',
                                     'files':[second]})
        self.write(pub.REVIEW_REL,self.review)
        batch = pub.PublicationBatch(pub.IDS[:2],'test-two-works',pub.STAGE_REL,
                                     ('7 Fantasien, Op.116','Second work'),'Two reviewed scores')
        self.write(pub.STAGE_REL/'inspection.json',{'proposed_first_publication_ids':list(batch.ids)})
        pub.publish(self.root,batch=batch,verify_public=False)
        data = pub.read_json(self.root/'data.json')
        self.assertEqual(len(data),3)
        self.assertIn('https://imslp.org/wiki/second',data[1]['description'])
        self.assertEqual(pub.read_json(self.root/'logs.json')[0]['count'],2)
        self.assertEqual(len(MemoryStorage.objects),2)
        review = pub.read_json(self.root/pub.REVIEW_REL)
        approved = {f['imslp_id'] for w in review['works'] for f in w['files'] if f['decision']=='approved'}
        self.assertEqual(approved,set(batch.ids))
        self.assertEqual(pub.read_json(self.root/pub.STAGE_REL/'publication.json')['approved_count'],2)

    def test_database_failure_rolls_back_catalog_and_recovers_only_new_pdfs(self):
        before = (self.root/'data.json').read_bytes()
        with mock.patch('submission_store.sync_catalog',side_effect=RuntimeError('database unavailable')):
            with self.assertRaisesRegex(RuntimeError,'database unavailable'):
                pub.publish(self.root,verify_public=False)
        self.assertEqual((self.root/'data.json').read_bytes(),before)
        self.assertEqual(len(list((self.root/'scores').rglob('*.pdf'))),1)
        self.assertEqual(len(list((self.root/'backup/import_publications').rglob('recovered_scores/*.pdf'))),8)
        self.assertEqual(len(MemoryStorage.objects),8)  # No remote deletion.

    def test_prepend_preserves_existing_bytes(self):
        before = b'[\r\n    {"id":1, "spacing":"kept"}\r\n]\r\n'
        after = pub.prepend_json(before,[{'id':2}])
        self.assertTrue(after.endswith(before[1:]))
        self.assertEqual(json.loads(after),[{'id':2},{'id':1,'spacing':'kept'}])

    def test_source_error_note_is_in_details_not_instrumentation_or_title(self):
        trial = pub.read_json(self.stage/'manifest.json')
        note = '原 PDF 页眉调性误标；网站调性依据完整原始扫描，原文件不修改。'
        trial['files'][1]['publication_note'] = note
        self.write(pub.STAGE_REL/'manifest.json', trial)
        planned = pub.prepare(self.root)['planned'][1]
        self.assertIn(note, planned['item']['description'])
        self.assertEqual(planned['item']['title'], trial['files'][1]['title'])
        self.assertEqual(planned['item']['voice_types'], '钢琴独奏')
        self.assertEqual(planned['source'].read_bytes(), b'%PDF-test-1524')


if __name__ == '__main__':
    unittest.main()
