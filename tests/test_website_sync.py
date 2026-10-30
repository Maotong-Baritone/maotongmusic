import copy
import io
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from botocore.exceptions import ClientError

import website_sync as sync


class MemoryS3:
    def __init__(self):
        self.objects = {}; self.head_calls = []; self.put_calls = []; self.before_put = None

    def get_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
        value = self.objects[Key]
        return dict(Body=io.BytesIO(value['Body']), ETag='"' + sync.digest(value['Body']) + '"')

    def put_object(self, **kwargs):
        if self.before_put:
            self.before_put(kwargs)
        key = kwargs['Key']; self.put_calls.append(key)
        existing = self.objects.get(key)
        etag = '"' + sync.digest(existing['Body']) + '"' if existing else None
        if (kwargs.get('IfNoneMatch') == '*' and existing) or ('IfMatch' in kwargs and kwargs['IfMatch'] != etag):
            raise ClientError({'Error': {'Code': 'PreconditionFailed'}}, 'PutObject')
        self.objects[key] = dict(kwargs)

    def head_object(self, *, Bucket, Key):
        self.head_calls.append(Key)
        value = self.objects[Key]
        return dict(ContentLength=len(value['Body']), Metadata=value.get('Metadata', {}))


class WebsiteSyncTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); (self.root / 'scores/艺术歌曲').mkdir(parents=True)
        (self.root / 'lyrics').mkdir(); self.client = MemoryS3()
        self.target = SimpleNamespace(client=self.client, bucket='test')
        self.rows = []; entries = []
        for n in range(2):
            identifier = str(uuid.uuid4()); body = b'%PDF-1.4\n' + str(n).encode() + b'\n%%EOF'
            filename = f'艺术歌曲/{identifier}.pdf'; path = self.root / 'scores' / filename; path.write_bytes(body)
            key = f'scores/{identifier[:2]}/{identifier}.pdf'; sha = sync.digest(body)
            self.rows.append(dict(id=n+1, public_id=identifier, title=f'歌曲{n}', composer='测试作曲家',
                                  category='艺术歌曲', language='汉语', filename=filename, has_lyrics=n == 0))
            entries.append(dict(public_id=identifier, storage_key=key, file_size=len(body), sha256=sha))
            self.client.objects[key] = dict(Body=body, Metadata={'sha256': sha})
        self.write('data.json', self.rows)
        self.write('logs.json', [dict(msg='历史更新', date='2026-01-01')])
        self.write('literature.json', dict(schema_version=1, subjects=[], document_types=[], documents=[]))
        self.write('storage-manifest.json', dict(entries=entries))
        self.write('site-config.json', dict(scoreStorage=dict(baseUrl='https://scores.test')))
        self.write('lyrics/1.json', dict(original='原文', translation='译文'))
        (self.root / '.env').write_text('PRIVATE_SENTINEL=never-publish', encoding='utf-8')

    def write(self, name, value):
        (self.root / name).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

    def verify(self, url, content):
        from urllib.parse import urlsplit
        key = urlsplit(url).path.lstrip('/')
        self.assertEqual(self.client.objects[key]['Body'], content)

    def publish(self, **kwargs):
        return sync.publish(self.root, target=self.target, verifier=kwargs.pop('verifier', self.verify), **kwargs)

    def pointer(self):
        return json.loads(self.client.objects[sync.POINTER_KEY]['Body'])

    def test_delete_switches_one_complete_version_without_removing_pdfs(self):
        first = self.publish(); first_key = self.pointer()['key']
        self.assertEqual(first['status'], 'verified_live'); self.assertTrue(sync.local_status(self.root)['synced'])
        self.assertEqual(len(self.client.head_calls), 2)
        self.write('data.json', self.rows[:1]); self.write('logs.json', [dict(msg='删除重复曲目')])
        self.assertFalse(sync.local_status(self.root)['synced'])
        second = self.publish(); current = self.pointer()
        self.assertNotEqual(first['revision'], second['revision']); self.assertEqual(second['score_count'], 1)
        bundle = json.loads(self.client.objects[current['key']]['Body'])
        self.assertEqual(bundle['scores'], self.rows[:1]); self.assertEqual(bundle['logs'], [dict(msg='删除重复曲目')])
        self.assertEqual(bundle['lyrics']['1']['translation'], '译文')
        self.assertNotIn('PRIVATE_SENTINEL', self.client.objects[current['key']]['Body'].decode())
        self.assertIn(first_key, self.client.objects)
        self.assertEqual(len(self.client.head_calls), 2, 'unchanged PDFs should use verified receipt')
        self.assertEqual(sum(k.endswith('.pdf') for k in self.client.objects), 2)

    def test_failed_snapshot_upload_or_public_verification_preserves_live_pointer(self):
        self.publish(); original = copy.deepcopy(self.client.objects[sync.POINTER_KEY])
        self.rows[0]['title'] = '已修改'; self.write('data.json', self.rows)
        def fail_upload(kwargs):
            if '/releases/' in kwargs['Key']:raise OSError('simulated upload failure')
        self.client.before_put = fail_upload
        with self.assertRaises(OSError):self.publish()
        self.assertEqual(self.client.objects[sync.POINTER_KEY], original)
        self.client.before_put = None
        with self.assertRaises(sync.WebsiteSyncError):
            self.publish(verifier=lambda *args: (_ for _ in ()).throw(sync.WebsiteSyncError('public verification failed')))
        self.assertEqual(self.client.objects[sync.POINTER_KEY], original)
        self.assertFalse(sync.local_status(self.root)['synced'])

    def test_local_edit_during_upload_does_not_publish_a_stale_snapshot(self):
        self.publish(); original = copy.deepcopy(self.client.objects[sync.POINTER_KEY])
        self.rows[0]['title'] = '修改甲'; self.write('data.json', self.rows)
        def edit(url, content):
            self.verify(url, content)
            self.rows[0]['title'] = '修改乙'; self.write('data.json', self.rows)
        with self.assertRaisesRegex(sync.WebsiteSyncError, '发生变化'):self.publish(verifier=edit)
        self.assertEqual(self.client.objects[sync.POINTER_KEY], original)

    def test_modified_pdf_and_unverified_remote_pdf_are_blocked(self):
        self.client.objects[next(k for k in self.client.objects if k.endswith('.pdf'))]['Metadata']['sha256'] = '0'*64
        with self.assertRaises(sync.WebsiteSyncError):self.publish()
        self.assertNotIn(sync.POINTER_KEY, self.client.objects)
        (self.root/'scores'/self.rows[0]['filename']).write_bytes(b'changed PDF')
        with self.assertRaises(sync.WebsiteSyncError):self.publish()

    def test_existing_wordless_etude_can_keep_its_optional_blank_language(self):
        self.rows[0].update(title='Vocalise-Etude', language='')
        self.write('data.json', self.rows)
        self.assertEqual(self.publish()['score_count'], 2)
        self.rows[0]['language'] = 'invalid-language'
        self.write('data.json', self.rows)
        with self.assertRaisesRegex(sync.WebsiteSyncError, '语言'):self.publish()

    def test_concurrent_publish_cannot_overwrite_another_live_version(self):
        self.publish(); self.rows[0]['title'] = '本地新版本'; self.write('data.json', self.rows)
        other = dict(schema_version=1, revision='a'*64, key='website/releases/'+'a'*64+'.json')
        def race(kwargs):
            if kwargs['Key'] == sync.POINTER_KEY:self.client.objects[sync.POINTER_KEY] = dict(Body=sync.encoded(other))
        self.client.before_put = race
        with self.assertRaises(ClientError):self.publish()
        self.assertEqual(self.pointer(), other)
        self.client.before_put = None
        with self.assertRaisesRegex(sync.WebsiteSyncError, '其他发布者'):self.publish()

    def test_retry_after_pointer_committed_but_verification_failed(self):
        def fail_pointer(url, content):
            if 'current.json' in url:raise sync.WebsiteSyncError('temporary public failure')
            self.verify(url, content)
        with self.assertRaises(sync.WebsiteSyncError):self.publish(verifier=fail_pointer)
        self.assertFalse(sync.local_status(self.root)['synced'])
        receipt = self.publish()
        self.assertTrue(receipt['unchanged']); self.assertTrue(sync.local_status(self.root)['synced'])
        puts = len(self.client.put_calls); self.publish(); self.assertEqual(len(self.client.put_calls), puts)

    def test_second_publisher_is_rejected_while_lock_is_held(self):
        with sync.publication_lock(self.root):
            with self.assertRaisesRegex(sync.WebsiteSyncError, '正在进行'):self.publish()


if __name__ == '__main__':unittest.main()
