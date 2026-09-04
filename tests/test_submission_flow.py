from __future__ import annotations

import importlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class SubmissionFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_context = tempfile.TemporaryDirectory()
        cls.temp_root = Path(cls.temp_context.name)
        (cls.temp_root / "data.json").write_text("[]\n", encoding="utf-8")
        (cls.temp_root / "logs.json").write_text("[]\n", encoding="utf-8")

        os.environ["ADMIN_USER"] = "admin"
        os.environ["ADMIN_PASS"] = "test-password"
        os.environ["FLASK_SECRET_KEY"] = "test-secret-key-for-submission-flow"
        os.environ["SUBMISSIONS_DB"] = str(cls.temp_root / "submissions.db")
        os.environ["PENDING_UPLOAD_DIR"] = str(cls.temp_root / "private_uploads")
        os.environ["SUBMISSION_MAX_MB"] = "2"
        # Unit tests must never use credentials from the developer's real .env.
        os.environ["SCORE_STORAGE_AUTO_SYNC"] = "0"

        cls.original_cwd = Path.cwd()
        os.chdir(cls.temp_root)
        cls.admin = importlib.import_module("admin_tool")
        cls.admin.app.config.update(TESTING=True)

    def setUp(self):
        for folder_name in ("scores", "lyrics", "backup", "private_uploads", "imports"):
            shutil.rmtree(self.temp_root / folder_name, ignore_errors=True)
            (self.temp_root / folder_name).mkdir(parents=True, exist_ok=True)
        (self.temp_root / "data.json").write_text("[]\n", encoding="utf-8")
        (self.temp_root / "logs.json").write_text("[]\n", encoding="utf-8")
        database_path = Path(os.environ["SUBMISSIONS_DB"])
        database_path.unlink(missing_ok=True)
        self.admin.init_database()
        self.admin.sync_catalog([])
        self.client = self.admin.app.test_client()

    def seed_brahms_review_manifest(self):
        manifest_path = self.temp_root / "imports" / "johannes_brahms" / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "composer": "Johannes Brahms/勃拉姆斯",
            "generated_at": "2026-09-01T12:00:00+00:00",
            "works": [{
                "display_work_title": "7 Fantasien, Op. 116",
                "catalogue_number": "Op. 116",
                "movements_text": "7 pieces: 1. Capriccio. Presto energico (D minor)",
                "source_url": "https://imslp.org/wiki/7_Fantasien",
                "files": [{
                    "imslp_id": "1524",
                    "proposed_title": "No. 1 Capriccio. Presto energico, Op. 116",
                    "proposed_work": "7 Fantasien, Op. 116",
                    "title_scope": "individual_movement",
                    "category": "器乐独奏",
                    "sub_category": "幻想曲",
                    "voice_types": "钢琴独奏",
                    "tonality": "d小调",
                    "decision": "pending",
                    "eligible": True,
                    "warnings": [],
                    "review_notes": "",
                    "description_en": "1. Capriccio",
                    "handler_url": "https://imslp.org/wiki/Special:ImagefromIndex/1524",
                    "copyright": "Public Domain",
                    "original_filename": "Brahms-Op116-1.pdf",
                    "publisher": "Test publisher",
                }],
            }],
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return manifest_path

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls.original_cwd)
        cls.temp_context.cleanup()

    def csrf_token(self):
        self.client.get("/submit")
        with self.client.session_transaction() as session:
            return session["_csrf_token"]

    def post_submission(self):
        return self.client.post(
            "/submit",
            data={
                "_csrf_token": self.csrf_token(),
                "submitter_name": "测试投稿人",
                "submitter_email": "submitter@example.com",
                "title": "测试咏叹调",
                "composer": "测试作曲家",
                "work": "测试歌剧",
                "language": "意大利语",
                "category": "歌剧咏叹调",
                "sub_category": "测试体裁",
                "voice_types": "Soprano",
                "voice_count": "独唱",
                "tonality": "C major",
                "description": "用于验证投稿审核闭环。",
                "lyrics_original": "Testo originale",
                "lyrics_translation": "测试译文",
                "copyright_confirmed": "1",
                "file": (io.BytesIO(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"), "score.pdf"),
            },
            content_type="multipart/form-data",
        )

    def post_batch(self, files, *, titles=None, **overrides):
        data = {
            "_csrf_token": self.csrf_token(),
            "composer": "批量测试作曲家",
            "work": "批量测试作品",
            "language": "德语",
            "category": "艺术歌曲",
            "sub_category": "艺术歌曲",
            "voice_count": "独唱",
            "voice_types": "Voice, Piano",
            "tonality": "C major",
            "description": "批量上传测试资料",
            "files": [(io.BytesIO(content), filename) for content, filename in files],
        }
        if titles is not None:
            data["titles"] = titles
        data.update(overrides)
        return self.client.post(
            "/batch-upload",
            data=data,
            content_type="multipart/form-data",
        )

    def post_single(self, content=b"%PDF-1.4\nsingle score\n%%EOF\n"):
        return self.client.post(
            "/",
            data={
                "_csrf_token": self.csrf_token(),
                "title": "单份自动同步测试",
                "composer": "测试作曲家",
                "category": "艺术歌曲",
                "file": (io.BytesIO(content), "single.pdf"),
            },
            content_type="multipart/form-data",
        )

    def login(self):
        response = self.client.post(
            "/login",
            data={
                "_csrf_token": self.csrf_token(),
                "username": "admin",
                "password": "test-password",
            },
        )
        self.assertEqual(response.status_code, 302)

    def successful_storage_publish(self, item_paths, *, force=False):
        entries = []
        for item, path, sha256 in item_paths:
            entry = self.admin.manifest_entry_for(
                path,
                public_id=item["public_id"],
                catalog_filename=item["filename"],
                sha256=sha256,
            )
            self.admin.apply_storage_metadata(item, entry)
            entries.append(entry)
        return self.admin.PublishResult(
            enabled=True,
            entries=tuple(entries),
            detail=f"R2 已校验 0 份，新上传 {len(entries)} 份",
        )

    def sample_item(self, item_id=1, *, has_lyrics=True):
        public_id = str(uuid.uuid4())
        return {
            "id": item_id,
            "public_id": public_id,
            "title": f"测试乐谱 {item_id}",
            "composer": "测试作曲家",
            "work": "测试作品",
            "language": "意大利语",
            "category": "艺术歌曲",
            "sub_category": "",
            "voice_count": "独唱",
            "voice_types": "Soprano",
            "tonality": "C major",
            "description": "测试资料",
            "filename": f"艺术歌曲/{public_id}.pdf",
            "date": "2026-08-23",
            "has_lyrics": has_lyrics,
        }

    def seed_item_files(self, item):
        score_path = self.temp_root / "scores" / Path(item["filename"])
        score_path.parent.mkdir(parents=True, exist_ok=True)
        score_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
        if item["has_lyrics"]:
            lyric_path = self.temp_root / "lyrics" / f"{item['id']}.json"
            lyric_path.write_text(
                json.dumps({"id": item["id"], "original": "old", "translation": "旧译文"}, ensure_ascii=False),
                encoding="utf-8",
            )

    def test_batch_upload_page_requires_login_and_explains_atomic_import(self):
        anonymous = self.client.get("/batch-upload")
        self.assertEqual(anonymous.status_code, 302)
        self.assertIn("/login?next=", anonymous.headers["Location"])

        with self.client.session_transaction() as session:
            session["_csrf_token"] = "anonymous-token"
        anonymous_post = self.client.post(
            "/batch-upload",
            data={
                "_csrf_token": "anonymous-token",
                "composer": "未登录",
                "category": "艺术歌曲",
                "files": (io.BytesIO(b"%PDF-anonymous"), "anonymous.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(anonymous_post.status_code, 302)
        self.assertIn("/login?next=", anonymous_post.headers["Location"])

        self.login()
        response = self.client.get("/batch-upload")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("批量上传乐谱", html)
        self.assertIn('name="files"', html)
        self.assertIn("multiple", html)
        self.assertIn("整批都不会发布", html)
        self.assertIn("逐份确认资料", html)
        self.assertIn("将默认资料应用到全部", html)
        self.assertIn("item_composers", html)
        self.assertIn("item_works", html)
        self.assertIn("item_tonalities", html)
        self.assertIn("item_voice_types", html)

    def test_brahms_review_edits_staging_manifest_only(self):
        manifest_path = self.seed_brahms_review_manifest()
        data_before = (self.temp_root / "data.json").read_bytes()
        logs_before = (self.temp_root / "logs.json").read_bytes()

        anonymous = self.client.get("/import-review/brahms")
        self.assertEqual(anonymous.status_code, 302)
        self.login()
        page = self.client.get("/import-review/brahms")
        html = page.get_data(as_text=True)
        self.assertEqual(page.status_code, 200)
        self.assertIn("勃拉姆斯导入预审", html)
        self.assertIn("No. 1 Capriccio. Presto energico, Op. 116", html)
        self.assertIn("本页不执行下载或发布", html)

        response = self.client.post(
            "/import-review/brahms/1524",
            data={
                "_csrf_token": self.csrf_token(),
                "proposed_title": "No. 1 Capriccio, Op. 116",
                "proposed_work": "7 Fantasien, Op. 116",
                "decision": "approved",
                "category": "器乐独奏",
                "sub_category": "随想曲",
                "voice_types": "钢琴独奏",
                "tonality": "d小调",
                "review_notes": "标题已人工确认",
            },
        )
        self.assertEqual(response.status_code, 302)
        updated = json.loads(manifest_path.read_text(encoding="utf-8"))
        item = updated["works"][0]["files"][0]
        self.assertEqual(item["proposed_title"], "No. 1 Capriccio, Op. 116")
        self.assertEqual(item["decision"], "approved")
        self.assertTrue(item["review_edited"])
        self.assertEqual((self.temp_root / "data.json").read_bytes(), data_before)
        self.assertEqual((self.temp_root / "logs.json").read_bytes(), logs_before)

    def test_brahms_review_rejects_invalid_or_unprotected_updates(self):
        manifest_path = self.seed_brahms_review_manifest()
        self.login()
        before = manifest_path.read_bytes()
        self.assertEqual(self.client.post('/import-review/brahms/1524', data={'decision': 'approved'}).status_code, 400)
        response = self.client.post('/import-review/brahms/1524', data={
            '_csrf_token': self.csrf_token(), 'decision': 'approved', 'category': '器乐独奏', 'proposed_title': '',
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(manifest_path.read_bytes(), before)

    def test_brahms_batch_skips_ineligible_files_and_only_updates_review(self):
        manifest_path = self.seed_brahms_review_manifest()
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        item = manifest['works'][0]['files'][0]
        manifest['works'][0]['files'].append(item | {'imslp_id': '999', 'eligible': False, 'decision': 'excluded'})
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        data_before = (self.temp_root / 'data.json').read_bytes()
        logs_before = (self.temp_root / 'logs.json').read_bytes()
        self.login()
        response = self.client.post('/import-review/brahms/batch', data={
            '_csrf_token': self.csrf_token(), 'decision': 'approved', 'imslp_ids': ['1524', '999'],
        })
        self.assertEqual(response.status_code, 302)
        files = json.loads(manifest_path.read_text(encoding='utf-8'))['works'][0]['files']
        self.assertEqual([f['decision'] for f in files], ['approved', 'excluded'])
        self.assertEqual((self.temp_root / 'data.json').read_bytes(), data_before)
        self.assertEqual((self.temp_root / 'logs.json').read_bytes(), logs_before)

    def test_brahms_review_scope_search_and_source_safety(self):
        manifest_path = self.seed_brahms_review_manifest()
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['works'][0]['files'][0]['warnings'] = ['分类待确认']
        manifest['works'][0]['source_url'] = 'javascript:alert(1)'
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        self.login()
        page = self.client.get('/import-review/brahms?scope=individual_movement&keyword=分类待确认')
        self.assertIn('No. 1 Capriccio', page.get_data(as_text=True))
        self.assertNotIn('javascript:alert', page.get_data(as_text=True))
        empty = self.client.get('/import-review/brahms?scope=selection')
        self.assertIn('没有符合当前筛选条件', empty.get_data(as_text=True))

    def test_brahms_style_confirmation_does_not_approve_any_files(self):
        manifest_path = self.seed_brahms_review_manifest()
        self.login()
        before = json.loads(manifest_path.read_text(encoding='utf-8'))
        samples = self.admin.brahms_views.sample_rows(self.admin.brahms_views.rows_for(before))
        response = self.client.post('/import-review/brahms/style', data={
            '_csrf_token': self.csrf_token(), 'signature': self.admin.brahms_views.style_signature(samples),
        })
        self.assertEqual(response.status_code, 302)
        after = json.loads(manifest_path.read_text(encoding='utf-8'))
        self.assertEqual(before['works'], after['works'])
        self.assertIn('style_confirmation', after['review_workflow'])
        self.assertIn('这组样例风格已确认', self.client.get('/import-review/brahms').get_data(as_text=True))

    def test_brahms_group_edits_are_scoped_and_reject_stale_forms(self):
        manifest_path = self.seed_brahms_review_manifest()
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        item = manifest['works'][0]['files'][0]
        manifest['works'][0]['files'].extend([dict(item, imslp_id='1525'), dict(item, imslp_id='1526', tonality='C大调')])
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        groups = self.admin.brahms_views.grouped_works(self.admin.brahms_views.rows_for(manifest))[0]['pieces'][0]['groups']
        group = next(g for g in groups if len(g['rows']) == 2)
        self.login()
        payload = {field: item.get(field, '') for field in self.admin.brahms_views.EDIT_FIELDS}
        payload.update(_csrf_token=self.csrf_token(), signature=group['signature'], confirm_group='1',
                       imslp_ids=['1524', '1525'], proposed_title='No. 1 Capriccio, Op. 116')
        data_before = (self.temp_root / 'data.json').read_bytes()
        logs_before = (self.temp_root / 'logs.json').read_bytes()
        response = self.client.post('/import-review/brahms/group/' + group['key'], data=payload)
        self.assertEqual(response.status_code, 302)
        items = json.loads(manifest_path.read_text(encoding='utf-8'))['works'][0]['files']
        self.assertEqual(items[0]['proposed_title'], payload['proposed_title'])
        self.assertEqual(items[1]['proposed_title'], payload['proposed_title'])
        self.assertEqual(items[2]['proposed_title'], item['proposed_title'])
        self.assertTrue(all(f['decision'] == 'pending' for f in items))
        self.assertEqual(self.client.post('/import-review/brahms/group/' + group['key'], data=payload).status_code, 409)
        self.assertEqual((self.temp_root / 'data.json').read_bytes(), data_before)
        self.assertEqual((self.temp_root / 'logs.json').read_bytes(), logs_before)

    def test_brahms_defer_issue_is_reversible_and_preserves_other_records(self):
        manifest_path = self.seed_brahms_review_manifest()
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        item = manifest['works'][0]['files'][0]
        item['warnings'] = ['许可版本需核对']
        manifest['works'][0]['files'].append(dict(item, imslp_id='999', decision='approved'))
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        rows = self.admin.brahms_views.filter_rows(self.admin.brahms_views.rows_for(manifest), decision='pending')
        group = self.admin.brahms_views.issue_groups(rows)[0]
        self.login()
        response = self.client.post('/import-review/brahms/issue/rights/defer', data={
            '_csrf_token': self.csrf_token(), 'signature': group['signature'],
        })
        self.assertEqual(response.status_code, 302)
        items = json.loads(manifest_path.read_text(encoding='utf-8'))['works'][0]['files']
        self.assertEqual([f['decision'] for f in items], ['deferred', 'approved'])
        response = self.client.post('/import-review/brahms/batch', data={
            '_csrf_token': self.csrf_token(), 'decision': 'pending', 'imslp_ids': ['1524'],
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(json.loads(manifest_path.read_text(encoding='utf-8'))['works'][0]['files'][0]['decision'], 'pending')

    def test_brahms_overview_views_render_and_exact_file_filter(self):
        manifest_path = self.seed_brahms_review_manifest()
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        self.login()
        work_key = self.admin.brahms_views.work_key(manifest['works'][0])
        for url in ('?view=samples', '?view=works', '?view=works&work=' + work_key, '?view=issues', '?view=files&file=1524'):
            response = self.client.get('/import-review/brahms' + url)
            self.assertEqual(response.status_code, 200, url)
            self.assertIn('本页不执行下载或发布', response.get_data(as_text=True))
        self.assertIn('没有符合当前筛选条件', self.client.get('/import-review/brahms?view=files&file=524').get_data(as_text=True))

    def test_single_admin_upload_keeps_its_original_size_limit(self):
        self.login()
        oversized_pdf = b"%PDF-oversized"
        with (
            mock.patch.object(self.admin, "ADMIN_UPLOAD_MAX_BYTES", 1),
            mock.patch.object(self.admin, "UPLOAD_FORM_OVERHEAD_BYTES", 0),
        ):
            response = self.client.post(
                "/",
                data={
                    "_csrf_token": self.csrf_token(),
                    "title": "超大单份文件",
                    "composer": "测试作曲家",
                    "category": "艺术歌曲",
                    "file": (io.BytesIO(oversized_pdf), "oversized.pdf"),
                },
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 413)
        self.assertIn("单份后台上传不能超过", response.get_data(as_text=True))
        self.assertEqual(list((self.temp_root / "scores").rglob("*.pdf")), [])

    def test_single_upload_records_verified_storage_metadata(self):
        self.login()
        with (
            mock.patch.object(
                self.admin,
                "publish_catalog_items_to_storage",
                side_effect=self.successful_storage_publish,
            ),
            mock.patch.object(self.admin, "update_manifest_after_publish"),
        ):
            response = self.post_single()

        self.assertEqual(response.status_code, 302)
        saved = json.loads((self.temp_root / "data.json").read_text(encoding="utf-8"))
        self.assertEqual(len(saved), 1)
        self.assertTrue(saved[0]["storage_key"].endswith(f'/{saved[0]["public_id"]}.pdf'))
        self.assertEqual(len(saved[0]["storage_sha256"]), 64)
        self.assertGreater(saved[0]["storage_size"], 0)
        self.assertIn("+00:00", saved[0]["storage_synced_at"])

    def test_single_upload_does_not_publish_when_r2_fails(self):
        self.login()
        with mock.patch.object(
            self.admin,
            "publish_catalog_items_to_storage",
            side_effect=self.admin.StoragePublishError("模拟 R2 失败"),
        ):
            response = self.post_single()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(json.loads((self.temp_root / "data.json").read_text(encoding="utf-8")), [])
        self.assertEqual(list((self.temp_root / "scores").rglob("*.pdf")), [])

    def test_login_has_a_small_independent_request_limit(self):
        with mock.patch.object(self.admin, "LOGIN_MAX_BYTES", 1):
            response = self.client.post(
                "/login",
                data={"username": "admin", "password": "test-password", "_csrf_token": "token"},
            )
        self.assertEqual(response.status_code, 413)
        self.assertIn("登录请求内容过大", response.get_data(as_text=True))

    def test_batch_upload_publishes_multiple_pdfs_atomically(self):
        first_pdf = b"%PDF-1.4\nfirst batch score\n%%EOF\n"
        second_pdf = b"%PDF-1.4\nsecond batch score\n%%EOF\n"
        self.login()

        response = self.post_batch(
            [(first_pdf, "first.pdf"), (second_pdf, "second.pdf")],
            titles=["第一首批量乐谱", "第二首批量乐谱"],
            category="乐谱书/曲集",
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/manage")
        saved = json.loads((self.temp_root / "data.json").read_text(encoding="utf-8"))
        self.assertEqual(len(saved), 2)
        by_title = {item["title"]: item for item in saved}
        self.assertEqual(set(by_title), {"第一首批量乐谱", "第二首批量乐谱"})
        self.assertEqual({item["composer"] for item in saved}, {"批量测试作曲家"})
        self.assertEqual({item["category"] for item in saved}, {"乐谱书/曲集"})
        self.assertEqual(len({item["id"] for item in saved}), 2)
        self.assertEqual(len({item["public_id"] for item in saved}), 2)
        self.assertTrue(all(not item["has_lyrics"] for item in saved))
        self.assertEqual(
            (self.temp_root / "scores" / Path(by_title["第一首批量乐谱"]["filename"])).read_bytes(),
            first_pdf,
        )
        self.assertEqual(
            (self.temp_root / "scores" / Path(by_title["第二首批量乐谱"]["filename"])).read_bytes(),
            second_pdf,
        )
        self.assertEqual(list((self.temp_root / "backup").rglob("*.part")), [])

    def test_batch_upload_saves_per_file_composer_work_tonality_and_instrumentation(self):
        self.login()
        response = self.post_batch(
            [
                (b"%PDF-1.4\nfirst metadata score\n", "first.pdf"),
                (b"%PDF-1.4\nsecond metadata score\n", "second.pdf"),
            ],
            titles=["第一首", "第二首"],
            item_composers=["舒伯特", "莫扎特"],
            item_works=["冬之旅", "费加罗的婚礼"],
            item_tonalities=["d minor", "D major"],
            item_voice_types=["Tenor, Piano", "Soprano, Orchestra"],
        )

        self.assertEqual(response.status_code, 302)
        saved = json.loads((self.temp_root / "data.json").read_text(encoding="utf-8"))
        by_title = {item["title"]: item for item in saved}
        self.assertEqual(by_title["第一首"]["composer"], "舒伯特")
        self.assertEqual(by_title["第一首"]["work"], "冬之旅")
        self.assertEqual(by_title["第一首"]["tonality"], "d minor")
        self.assertEqual(by_title["第一首"]["voice_types"], "Tenor, Piano")
        self.assertEqual(by_title["第二首"]["composer"], "莫扎特")
        self.assertEqual(by_title["第二首"]["work"], "费加罗的婚礼")
        self.assertEqual(by_title["第二首"]["tonality"], "D major")
        self.assertEqual(by_title["第二首"]["voice_types"], "Soprano, Orchestra")

    def test_instrumental_parts_category_is_available_and_can_be_published(self):
        self.assertIn("器乐分谱", self.admin.ALLOWED_CATEGORIES)
        self.assertIn("器乐分谱", self.client.get("/submit").get_data(as_text=True))
        self.login()
        for url in ("/", "/batch-upload", "/manage"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertIn("器乐分谱", response.get_data(as_text=True))

        response = self.post_batch(
            [(b"%PDF-1.4\ninstrumental part\n", "violin-part.pdf")],
            titles=["小提琴分谱"],
            category="器乐分谱",
        )
        self.assertEqual(response.status_code, 302)
        saved = json.loads((self.temp_root / "data.json").read_text(encoding="utf-8"))
        self.assertEqual(saved[0]["category"], "器乐分谱")
        self.assertTrue(saved[0]["filename"].startswith("器乐分谱/"))
        self.assertTrue((self.temp_root / "scores" / Path(saved[0]["filename"])).is_file())

    def test_batch_upload_rejects_mismatched_or_missing_per_file_composer(self):
        self.login()
        mismatched = self.post_batch(
            [(b"%PDF-first", "first.pdf"), (b"%PDF-second", "second.pdf")],
            titles=["第一首", "第二首"],
            item_composers=["只有一项"],
        )
        self.assertEqual(mismatched.status_code, 200)
        self.assertIn("文件与作曲家列表不一致", mismatched.get_data(as_text=True))

        missing = self.post_batch(
            [(b"%PDF-first", "first.pdf"), (b"%PDF-second", "second.pdf")],
            titles=["第一首", "第二首"],
            composer="",
            item_composers=["舒伯特", "   "],
        )
        self.assertEqual(missing.status_code, 200)
        self.assertIn("请填写第 2 份乐谱的作曲家", missing.get_data(as_text=True))
        self.assertEqual(json.loads((self.temp_root / "data.json").read_text(encoding="utf-8")), [])
        self.assertEqual(list((self.temp_root / "scores").rglob("*.pdf")), [])

    def test_batch_upload_derives_titles_from_pdf_filenames(self):
        self.login()
        response = self.post_batch([
            (b"%PDF-1.4\nfirst\n", "An_die_Musik.pdf"),
            (b"%PDF-1.4\nsecond\n", "中文曲名.PDF"),
        ])

        self.assertEqual(response.status_code, 302)
        saved = json.loads((self.temp_root / "data.json").read_text(encoding="utf-8"))
        self.assertEqual({item["title"] for item in saved}, {"An die Musik", "中文曲名"})

    def test_batch_upload_rejects_invalid_or_duplicate_pdf_without_partial_changes(self):
        self.login()
        invalid = self.post_batch(
            [(b"%PDF-1.4\nvalid\n", "valid.pdf"), (b"not a pdf", "broken.pdf")],
            titles=["有效文件", "伪装文件"],
        )
        self.assertEqual(invalid.status_code, 200)
        self.assertIn("不是有效 PDF", invalid.get_data(as_text=True))
        self.assertEqual(json.loads((self.temp_root / "data.json").read_text(encoding="utf-8")), [])
        self.assertEqual(list((self.temp_root / "scores").rglob("*.pdf")), [])
        self.assertEqual(list((self.temp_root / "backup").rglob("*.pdf")), [])

        same_pdf = b"%PDF-1.4\nidentical\n"
        duplicate = self.post_batch(
            [(same_pdf, "one.pdf"), (same_pdf, "two.pdf")],
            titles=["第一份", "第二份"],
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertIn("内容完全相同", duplicate.get_data(as_text=True))
        self.assertEqual(list((self.temp_root / "scores").rglob("*.pdf")), [])

    def test_batch_upload_enforces_count_and_total_size_limits(self):
        self.login()
        with mock.patch.object(self.admin, "BATCH_UPLOAD_MAX_FILES", 1):
            too_many = self.post_batch(
                [(b"%PDF-one", "one.pdf"), (b"%PDF-two", "two.pdf")],
                titles=["一", "二"],
            )
        self.assertEqual(too_many.status_code, 200)
        self.assertIn("一次最多上传 1 份", too_many.get_data(as_text=True))

        with mock.patch.object(self.admin, "BATCH_UPLOAD_MAX_BYTES", 10):
            too_large = self.post_batch(
                [(b"%PDF-one", "one.pdf"), (b"%PDF-two", "two.pdf")],
                titles=["一", "二"],
            )
        self.assertEqual(too_large.status_code, 200)
        self.assertIn("总大小不能超过", too_large.get_data(as_text=True))
        self.assertEqual(json.loads((self.temp_root / "data.json").read_text(encoding="utf-8")), [])
        self.assertEqual(list((self.temp_root / "scores").rglob("*.pdf")), [])

    def test_batch_upload_rolls_back_when_r2_fails(self):
        self.login()
        with mock.patch.object(
            self.admin,
            "publish_catalog_items_to_storage",
            side_effect=self.admin.StoragePublishError("模拟批量 R2 失败"),
        ):
            response = self.post_batch(
                [(b"%PDF-one", "one.pdf"), (b"%PDF-two", "two.pdf")],
                titles=["一", "二"],
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("模拟批量 R2 失败", response.get_data(as_text=True))
        self.assertEqual(json.loads((self.temp_root / "data.json").read_text(encoding="utf-8")), [])
        self.assertEqual(list((self.temp_root / "scores").rglob("*.pdf")), [])

    def test_batch_upload_rolls_back_all_files_when_catalog_save_fails(self):
        existing = self.sample_item(900, has_lyrics=False)
        self.seed_item_files(existing)
        original_data = json.dumps([existing], ensure_ascii=False)
        (self.temp_root / "data.json").write_text(original_data, encoding="utf-8")
        self.admin.sync_catalog([existing])
        self.login()

        with mock.patch.object(self.admin, "save_all", side_effect=OSError("模拟批量保存失败")):
            with self.assertRaises(OSError):
                self.post_batch(
                    [(b"%PDF-new-one", "one.pdf"), (b"%PDF-new-two", "two.pdf")],
                    titles=["新增一", "新增二"],
                    category="其他",
                )

        saved = json.loads((self.temp_root / "data.json").read_text(encoding="utf-8"))
        self.assertEqual(saved, [existing])
        score_files = list((self.temp_root / "scores").rglob("*.pdf"))
        self.assertEqual(score_files, [self.temp_root / "scores" / Path(existing["filename"])])
        self.assertEqual(list((self.temp_root / "backup").rglob("*.pdf")), [])

    def test_batch_upload_rolls_back_files_and_json_when_database_sync_fails(self):
        existing = self.sample_item(901, has_lyrics=False)
        self.seed_item_files(existing)
        original_log = [{"date": "2026-08-23 09:00", "type": "add", "msg": "原记录"}]
        (self.temp_root / "data.json").write_text(
            json.dumps([existing], ensure_ascii=False), encoding="utf-8"
        )
        (self.temp_root / "logs.json").write_text(
            json.dumps(original_log, ensure_ascii=False), encoding="utf-8"
        )
        self.admin.sync_catalog([existing])
        self.login()

        with mock.patch.object(
            self.admin,
            "sync_catalog",
            side_effect=[OSError("模拟数据库同步失败"), None],
        ):
            with self.assertRaises(OSError):
                self.post_batch(
                    [(b"%PDF-new-one", "one.pdf"), (b"%PDF-new-two", "two.pdf")],
                    titles=["新增一", "新增二"],
                    category="其他",
                )

        saved_data = json.loads((self.temp_root / "data.json").read_text(encoding="utf-8"))
        saved_log = json.loads((self.temp_root / "logs.json").read_text(encoding="utf-8"))
        self.assertEqual(saved_data, [existing])
        self.assertEqual(saved_log, original_log)
        score_files = list((self.temp_root / "scores").rglob("*.pdf"))
        self.assertEqual(score_files, [self.temp_root / "scores" / Path(existing["filename"])])
        self.assertEqual(list((self.temp_root / "backup").rglob("*.pdf")), [])

    def test_complete_submission_review_flow(self):
        response = self.post_submission()
        self.assertEqual(response.status_code, 302)

        receipt = self.client.get(response.headers["Location"])
        self.assertEqual(receipt.status_code, 200)
        self.assertIn("投稿已安全保存", receipt.get_data(as_text=True))

        submissions = self.admin.list_submissions("pending")
        self.assertEqual(len(submissions), 1)
        submission = submissions[0]
        submission_id = submission["id"]
        private_file = self.admin.pending_file_path(submission["stored_filename"])
        self.assertTrue(private_file.is_file())

        duplicate = self.post_submission()
        self.assertEqual(duplicate.status_code, 200)
        self.assertIn("已经投稿过", duplicate.get_data(as_text=True))
        self.assertEqual(len(self.admin.list_submissions("pending")), 1)

        protected_queue = self.client.get("/submissions")
        self.assertEqual(protected_queue.status_code, 302)
        self.assertIn("/login", protected_queue.headers["Location"])
        protected_file = self.client.get(f"/submissions/{submission_id}/file")
        self.assertEqual(protected_file.status_code, 302)
        protected_file.close()

        self.login()
        queue = self.client.get("/submissions")
        self.assertEqual(queue.status_code, 200)
        self.assertIn("测试咏叹调", queue.get_data(as_text=True))

        preview = self.client.get(f"/submissions/{submission_id}/file")
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.mimetype, "application/pdf")
        preview.close()

        rejected = self.client.post(
            f"/submissions/{submission_id}/reject",
            data={"_csrf_token": self.csrf_token(), "review_note": "资料需要补充"},
        )
        self.assertEqual(rejected.status_code, 302)
        self.assertEqual(self.admin.get_submission(submission_id)["status"], "rejected")
        self.assertTrue(private_file.is_file())

        restored = self.client.post(
            f"/submissions/{submission_id}/restore",
            data={"_csrf_token": self.csrf_token()},
        )
        self.assertEqual(restored.status_code, 302)
        self.assertEqual(self.admin.get_submission(submission_id)["status"], "pending")

        approved = self.client.post(
            f"/submissions/{submission_id}/approve",
            data={"_csrf_token": self.csrf_token(), "review_note": "测试通过"},
        )
        self.assertEqual(approved.status_code, 302)
        approved_record = self.admin.get_submission(submission_id)
        self.assertEqual(approved_record["status"], "approved")
        self.assertFalse(private_file.exists())

        public_data = json.loads((self.temp_root / "data.json").read_text(encoding="utf-8"))
        self.assertEqual(len(public_data), 1)
        self.assertEqual(public_data[0]["title"], "测试咏叹调")
        self.assertTrue((self.temp_root / "scores" / public_data[0]["filename"]).is_file())
        self.assertTrue((self.temp_root / "lyrics" / f"{public_data[0]['id']}.json").is_file())

        approved_preview = self.client.get(f"/submissions/{submission_id}/file")
        self.assertEqual(approved_preview.status_code, 200)
        self.assertEqual(approved_preview.mimetype, "application/pdf")
        approved_preview.close()

    def test_submission_approval_stays_pending_when_r2_fails(self):
        submitted = self.post_submission()
        self.assertEqual(submitted.status_code, 302)
        submission = self.admin.list_submissions("pending")[0]
        private_file = self.admin.pending_file_path(submission["stored_filename"])
        self.login()

        with mock.patch.object(
            self.admin,
            "publish_catalog_items_to_storage",
            side_effect=self.admin.StoragePublishError("模拟投稿 R2 失败"),
        ):
            response = self.client.post(
                f'/submissions/{submission["id"]}/approve',
                data={"_csrf_token": self.csrf_token(), "review_note": "尝试通过"},
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.admin.get_submission(submission["id"])["status"], "pending")
        self.assertTrue(private_file.is_file())
        self.assertEqual(json.loads((self.temp_root / "data.json").read_text(encoding="utf-8")), [])
        self.assertEqual(list((self.temp_root / "scores").rglob("*.pdf")), [])

    def test_manage_can_retry_one_score_storage_sync(self):
        item = self.sample_item(77, has_lyrics=False)
        self.seed_item_files(item)
        (self.temp_root / "data.json").write_text(
            json.dumps([item], ensure_ascii=False), encoding="utf-8"
        )
        self.admin.sync_catalog([item])
        self.login()

        with (
            mock.patch.object(
                self.admin,
                "publish_catalog_items_to_storage",
                side_effect=self.successful_storage_publish,
            ) as publish,
            mock.patch.object(self.admin, "update_manifest_after_publish"),
        ):
            response = self.client.post(
                f'/storage/sync/{item["id"]}',
                data={"_csrf_token": self.csrf_token(), "next": "/manage"},
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/manage")
        self.assertTrue(publish.call_args.kwargs["force"])
        saved = json.loads((self.temp_root / "data.json").read_text(encoding="utf-8"))
        self.assertEqual(len(saved[0]["storage_sha256"]), 64)
        self.assertTrue(saved[0]["storage_key"].startswith("scores/"))

    def test_save_all_restores_json_when_database_sync_fails(self):
        original_item = self.sample_item(10, has_lyrics=False)
        original_log = [{"date": "2026-08-23 10:00", "type": "add", "msg": "old"}]
        (self.temp_root / "data.json").write_text(
            json.dumps([original_item], ensure_ascii=False), encoding="utf-8"
        )
        (self.temp_root / "logs.json").write_text(
            json.dumps(original_log, ensure_ascii=False), encoding="utf-8"
        )

        replacement = self.sample_item(11, has_lyrics=False)
        with mock.patch.object(
            self.admin,
            "sync_catalog",
            side_effect=[OSError("模拟数据库写入失败"), None],
        ):
            with self.assertRaises(OSError):
                self.admin.save_all([replacement], [{"msg": "new"}])

        restored_data = json.loads((self.temp_root / "data.json").read_text(encoding="utf-8"))
        restored_log = json.loads((self.temp_root / "logs.json").read_text(encoding="utf-8"))
        self.assertEqual(restored_data, [original_item])
        self.assertEqual(restored_log, original_log)

    def test_launcher_reuses_healthy_existing_admin_instance(self):
        with (
            mock.patch.object(self.admin, "admin_port_is_open", return_value=True),
            mock.patch.object(self.admin, "existing_admin_is_healthy", return_value=True),
            mock.patch.object(self.admin, "AUTO_OPEN_BROWSER", True),
            mock.patch.object(self.admin, "open_admin_browser") as open_browser,
        ):
            self.admin.run_local_admin()
        open_browser.assert_called_once_with(f"http://127.0.0.1:{self.admin.ADMIN_PORT}/login")

    def test_launcher_rejects_port_used_by_another_service(self):
        with (
            mock.patch.object(self.admin, "admin_port_is_open", return_value=True),
            mock.patch.object(self.admin, "existing_admin_is_healthy", return_value=False),
        ):
            with self.assertRaisesRegex(RuntimeError, "ADMIN_PORT"):
                self.admin.run_local_admin()

    def test_edit_restores_old_lyrics_when_catalog_save_fails(self):
        item = self.sample_item(20)
        self.seed_item_files(item)
        (self.temp_root / "data.json").write_text(
            json.dumps([item], ensure_ascii=False), encoding="utf-8"
        )
        self.admin.sync_catalog([item])
        original_lyrics = (self.temp_root / "lyrics" / "20.json").read_bytes()
        self.login()

        with mock.patch.object(self.admin, "save_all", side_effect=OSError("模拟磁盘写入失败")):
            with self.assertRaises(OSError):
                self.client.post(
                    "/edit/20",
                    data={
                        "_csrf_token": self.csrf_token(),
                        "title": item["title"],
                        "composer": item["composer"],
                        "work": item["work"],
                        "language": item["language"],
                        "category": item["category"],
                        "sub_category": item["sub_category"],
                        "voice_count": item["voice_count"],
                        "voice_types": item["voice_types"],
                        "tonality": item["tonality"],
                        "description": item["description"],
                        "lyrics_og": "new",
                        "lyrics_cn": "新译文",
                    },
                )

        self.assertEqual((self.temp_root / "lyrics" / "20.json").read_bytes(), original_lyrics)

    def test_manage_uses_server_side_pagination(self):
        items = [self.sample_item(item_id, has_lyrics=False) for item_id in range(1, 124)]
        (self.temp_root / "data.json").write_text(
            json.dumps(items, ensure_ascii=False), encoding="utf-8"
        )
        self.login()

        response = self.client.get("/manage?page=2&per_page=50")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(html.count('href="/edit/'), 50)
        self.assertIn("共 123 条 · 第 2 / 3 页", html)

    def test_dashboard_and_duplicate_review_use_normalized_metadata(self):
        first = self.sample_item(201, has_lyrics=False)
        second = self.sample_item(202, has_lyrics=False)
        first["title"] = "Ave Maria"
        first["composer"] = "Charles Gounod"
        second["title"] = "  AVE   MARIA  "
        second["composer"] = "CHARLES GOUNOD"
        for item in (first, second):
            self.seed_item_files(item)
        (self.temp_root / "data.json").write_text(
            json.dumps([first, second], ensure_ascii=False), encoding="utf-8"
        )
        self.admin.sync_catalog([first, second])
        self.login()

        dashboard = self.client.get("/dashboard")
        dashboard_html = dashboard.get_data(as_text=True)
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("资料健康", dashboard_html)
        self.assertIn("疑似重复组", dashboard_html)
        self.assertIn("正常", dashboard_html)

        duplicate_page = self.client.get("/duplicates")
        duplicate_html = duplicate_page.get_data(as_text=True)
        self.assertEqual(duplicate_page.status_code, 200)
        self.assertEqual(duplicate_html.count('class="duplicate-group'), 1)
        self.assertIn("Ave Maria", duplicate_html)
        self.assertIn("AVE   MARIA", duplicate_html)
        self.assertIn('data-src="/scores/201/file"', duplicate_html)
        self.assertIn('href="/scores/202/file"', duplicate_html)
        self.assertIn('action="/delete/201"', duplicate_html)
        self.assertEqual(duplicate_html.count('name="next" value="/duplicates"'), 2)

    def test_catalog_health_requires_login_and_keeps_launcher_health_public(self):
        launcher_health = self.client.get("/health")
        self.assertEqual(launcher_health.status_code, 200)
        self.assertEqual(launcher_health.get_json(), {"status": "ok"})

        anonymous = self.client.get("/catalog-health")
        self.assertEqual(anonymous.status_code, 302)
        self.assertIn("/login?next=", anonymous.headers["Location"])

        self.login()
        page = self.client.get("/catalog-health")
        self.assertEqual(page.status_code, 200)
        self.assertIn("资料健康明细", page.get_data(as_text=True))

    def test_catalog_health_lists_exact_file_problems_and_escapes_output(self):
        normal = self.sample_item(1001, has_lyrics=False)
        missing = self.sample_item(1002, has_lyrics=False)
        invalid = self.sample_item(1003, has_lyrics=False)
        normal["title"] = "正常乐谱"
        missing["title"] = '<script>alert("x")</script>'
        missing["filename"] = "艺术歌曲/missing-score.pdf"
        invalid["title"] = "非法路径乐谱"
        invalid["filename"] = "../outside.pdf"
        self.seed_item_files(normal)
        orphan_path = self.temp_root / "scores" / "其他" / "missing-score.pdf"
        orphan_path.parent.mkdir(parents=True, exist_ok=True)
        orphan_path.write_bytes(b"%PDF-orphan")
        (self.temp_root / "data.json").write_text(
            json.dumps([normal, missing, invalid], ensure_ascii=False), encoding="utf-8"
        )
        self.login()

        pdf_page = self.client.get("/catalog-health?issue=pdf")
        html = pdf_page.get_data(as_text=True)
        self.assertEqual(pdf_page.status_code, 200)
        self.assertIn("记录指向的 PDF 不存在", html)
        self.assertIn("记录的 PDF 路径不合法", html)
        self.assertIn("scores/艺术歌曲/missing-score.pdf", html)
        self.assertIn("scores/其他/missing-score.pdf", html)
        self.assertIn("scores/../outside.pdf", html)
        self.assertIn("&lt;script&gt;alert", html)
        self.assertNotIn('<script>alert("x")</script>', html)
        self.assertNotIn("正常乐谱", html)
        self.assertNotIn(str(self.temp_root), html)

        orphan_page = self.client.get("/catalog-health?issue=orphan")
        orphan_html = orphan_page.get_data(as_text=True)
        self.assertEqual(orphan_page.status_code, 200)
        self.assertIn("scores/其他/missing-score.pdf", orphan_html)
        self.assertNotIn(str(self.temp_root), orphan_html)

    def test_catalog_health_normalizes_windows_case_and_separators(self):
        case_item = self.sample_item(1004, has_lyrics=False)
        slash_item = self.sample_item(1005, has_lyrics=False)
        case_item["filename"] = "艺术歌曲/casename.pdf"
        slash_item["filename"] = "艺术歌曲\\backslash.pdf"
        case_path = self.temp_root / "scores" / "艺术歌曲" / "CaseName.PDF"
        slash_path = self.temp_root / "scores" / "艺术歌曲" / "backslash.pdf"
        case_path.parent.mkdir(parents=True, exist_ok=True)
        case_path.write_bytes(b"%PDF-case")
        slash_path.write_bytes(b"%PDF-slash")

        report = self.admin.catalog_health_report([case_item, slash_item])
        self.assertTrue(report["healthy"])
        self.assertEqual(report["file_issues"], [])
        self.assertEqual(report["orphan_files"], [])

    def test_dashboard_health_counts_link_to_matching_details(self):
        missing = self.sample_item(1101, has_lyrics=False)
        missing["work"] = ""
        missing["description"] = ""
        missing["filename"] = "艺术歌曲/missing-dashboard.pdf"
        orphan = self.temp_root / "scores" / "其他" / "orphan-dashboard.pdf"
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_bytes(b"%PDF-orphan")
        (self.temp_root / "data.json").write_text(
            json.dumps([missing], ensure_ascii=False), encoding="utf-8"
        )
        self.login()

        dashboard = self.client.get("/dashboard")
        html = dashboard.get_data(as_text=True)
        self.assertEqual(dashboard.status_code, 200)
        for issue in ("pdf", "orphan", "missing_work", "missing_description"):
            self.assertIn(f'/catalog-health?issue={issue}', html)
        self.assertIn("需处理", html)

    def test_catalog_health_metadata_filters_whitespace_and_paginates(self):
        both_missing = self.sample_item(1201, has_lyrics=False)
        work_only = self.sample_item(1202, has_lyrics=False)
        description_only = self.sample_item(1203, has_lyrics=False)
        complete = self.sample_item(1204, has_lyrics=False)
        both_missing["title"] = "两项都缺"
        both_missing["work"] = ""
        both_missing["description"] = " "
        work_only["title"] = "只缺作品"
        work_only["work"] = "   "
        description_only["title"] = "只缺简介"
        description_only["description"] = "\t"
        items = [both_missing, work_only, description_only, complete]
        (self.temp_root / "data.json").write_text(
            json.dumps(items, ensure_ascii=False), encoding="utf-8"
        )
        self.login()

        work_page = self.client.get("/catalog-health?issue=missing_work")
        work_html = work_page.get_data(as_text=True)
        self.assertIn("两项都缺", work_html)
        self.assertIn("只缺作品", work_html)
        self.assertNotIn("只缺简介", work_html)
        self.assertNotIn("测试乐谱 1204", work_html)

        description_page = self.client.get("/catalog-health?issue=missing_description")
        description_html = description_page.get_data(as_text=True)
        self.assertIn("两项都缺", description_html)
        self.assertIn("只缺简介", description_html)
        self.assertNotIn("只缺作品", description_html)
        self.assertNotIn("测试乐谱 1204", description_html)

        many_items = [self.sample_item(item_id, has_lyrics=False) for item_id in range(1300, 1423)]
        for item in many_items:
            item["work"] = ""
        (self.temp_root / "data.json").write_text(
            json.dumps(many_items, ensure_ascii=False), encoding="utf-8"
        )
        page_two = self.client.get("/catalog-health?issue=missing_work&page=2&per_page=50")
        page_two_html = page_two.get_data(as_text=True)
        self.assertEqual(page_two_html.count('href="/edit/'), 50)
        self.assertIn("共 123 条 · 第 2 / 3 页", page_two_html)

    def test_edit_same_category_preserves_legacy_nested_filename(self):
        item = self.sample_item(1501, has_lyrics=False)
        item["filename"] = f"声乐作品/艺术歌曲/{item['public_id']}.pdf"
        self.seed_item_files(item)
        original_path = self.temp_root / "scores" / Path(item["filename"])
        direct_path = self.temp_root / "scores" / "艺术歌曲" / original_path.name
        (self.temp_root / "data.json").write_text(
            json.dumps([item], ensure_ascii=False), encoding="utf-8"
        )
        self.admin.sync_catalog([item])
        self.login()

        response = self.client.post(
            "/edit/1501",
            data={
                "_csrf_token": self.csrf_token(),
                "title": item["title"],
                "composer": item["composer"],
                "work": item["work"],
                "language": item["language"],
                "category": item["category"],
                "sub_category": item["sub_category"],
                "voice_count": item["voice_count"],
                "voice_types": item["voice_types"],
                "tonality": item["tonality"],
                "description": item["description"],
                "lyrics_og": "",
                "lyrics_cn": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        saved = json.loads((self.temp_root / "data.json").read_text(encoding="utf-8"))
        self.assertEqual(saved[0]["filename"], item["filename"])
        self.assertTrue(original_path.is_file())
        self.assertFalse(direct_path.exists())

    def test_catalog_pdf_preview_requires_login_and_serves_pdf(self):
        item = self.sample_item(601, has_lyrics=False)
        self.seed_item_files(item)
        (self.temp_root / "data.json").write_text(
            json.dumps([item], ensure_ascii=False), encoding="utf-8"
        )
        self.admin.sync_catalog([item])

        anonymous = self.client.get("/scores/601/file")
        self.assertEqual(anonymous.status_code, 302)
        self.assertIn("/login?next=", anonymous.headers["Location"])

        self.login()
        preview = self.client.get("/scores/601/file")
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.mimetype, "application/pdf")
        self.assertTrue(preview.data.startswith(b"%PDF-"))
        self.assertIn("inline", preview.headers.get("Content-Disposition", ""))
        preview.close()
        self.assertEqual(self.client.get("/scores/999999/file").status_code, 404)

        item["filename"] = "../outside.pdf"
        (self.temp_root / "data.json").write_text(
            json.dumps([item], ensure_ascii=False), encoding="utf-8"
        )
        self.assertEqual(self.client.get("/scores/601/file").status_code, 404)

    def test_duplicate_review_can_delete_to_trash_and_return_to_review(self):
        first = self.sample_item(701)
        second = self.sample_item(702)
        first["title"] = second["title"] = "可删除重复乐谱"
        first["composer"] = second["composer"] = "重复作曲家"
        for item in (first, second):
            self.seed_item_files(item)
        (self.temp_root / "data.json").write_text(
            json.dumps([first, second], ensure_ascii=False), encoding="utf-8"
        )
        self.admin.sync_catalog([first, second])
        self.login()

        deleted = self.client.post(
            "/delete/701",
            data={"_csrf_token": self.csrf_token(), "next": "/duplicates"},
        )
        self.assertEqual(deleted.status_code, 302)
        self.assertEqual(deleted.headers["Location"], "/duplicates")
        saved = json.loads((self.temp_root / "data.json").read_text(encoding="utf-8"))
        self.assertEqual([item["id"] for item in saved], [702])
        self.assertFalse((self.temp_root / "scores" / Path(first["filename"])).exists())
        self.assertTrue((self.temp_root / "scores" / Path(second["filename"])).is_file())
        entries = self.admin.load_deleted_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["item"]["id"], 701)

        refreshed = self.client.get("/duplicates").get_data(as_text=True)
        self.assertIn("未发现同曲名且同作曲家的记录", refreshed)

    def test_duplicate_review_delete_rolls_back_files_when_save_fails(self):
        items = [self.sample_item(item_id) for item_id in (801, 802)]
        for item in items:
            item["title"] = "回滚测试乐谱"
            item["composer"] = "回滚测试作曲家"
            self.seed_item_files(item)
        (self.temp_root / "data.json").write_text(
            json.dumps(items, ensure_ascii=False), encoding="utf-8"
        )
        self.admin.sync_catalog(items)
        self.login()

        with mock.patch.object(self.admin, "save_all", side_effect=OSError("模拟删除保存失败")):
            with self.assertRaises(OSError):
                self.client.post(
                    "/delete/801",
                    data={"_csrf_token": self.csrf_token(), "next": "/duplicates"},
                )

        saved = json.loads((self.temp_root / "data.json").read_text(encoding="utf-8"))
        self.assertEqual([item["id"] for item in saved], [801, 802])
        self.assertTrue((self.temp_root / "scores" / Path(items[0]["filename"])).is_file())
        self.assertTrue((self.temp_root / "lyrics" / "801.json").is_file())
        self.assertEqual(self.admin.load_deleted_entries(), [])

    def test_batch_update_changes_language_without_moving_files(self):
        items = [self.sample_item(item_id, has_lyrics=False) for item_id in (301, 302)]
        for item in items:
            self.seed_item_files(item)
        (self.temp_root / "data.json").write_text(
            json.dumps(items, ensure_ascii=False), encoding="utf-8"
        )
        self.admin.sync_catalog(items)
        original_paths = [self.temp_root / "scores" / Path(item["filename"]) for item in items]
        self.login()

        response = self.client.post(
            "/batch-update",
            data={
                "_csrf_token": self.csrf_token(),
                "item_ids": ["301", "302"],
                "batch_action": "set_language",
                "target_language": "德语",
                "next": "/manage?page=1",
            },
        )
        self.assertEqual(response.status_code, 302)
        saved = json.loads((self.temp_root / "data.json").read_text(encoding="utf-8"))
        self.assertEqual({item["language"] for item in saved}, {"德语"})
        self.assertTrue(all(path.is_file() for path in original_paths))

    def test_deprecated_compound_languages_are_not_admin_options(self):
        self.assertIn("法语/拉丁语", self.admin.CANONICAL_LANGUAGES)
        for language in ("俄语/法语", "俄语/德语", "法语/俄语", "法语/英语"):
            self.assertNotIn(language, self.admin.CANONICAL_LANGUAGES)

    def test_batch_category_move_updates_files_and_catalog(self):
        items = [self.sample_item(item_id, has_lyrics=False) for item_id in (401, 402)]
        for item in items:
            self.seed_item_files(item)
        (self.temp_root / "data.json").write_text(
            json.dumps(items, ensure_ascii=False), encoding="utf-8"
        )
        self.admin.sync_catalog(items)
        original_paths = [self.temp_root / "scores" / Path(item["filename"]) for item in items]
        self.login()

        response = self.client.post(
            "/batch-update",
            data={
                "_csrf_token": self.csrf_token(),
                "item_ids": ["401", "402"],
                "batch_action": "set_category",
                "target_category": "其他",
                "next": "/manage?page=1",
            },
        )
        self.assertEqual(response.status_code, 302)
        saved = json.loads((self.temp_root / "data.json").read_text(encoding="utf-8"))
        self.assertEqual({item["category"] for item in saved}, {"其他"})
        self.assertTrue(all(item["filename"].startswith("其他/") for item in saved))
        self.assertTrue(all(not path.exists() for path in original_paths))
        self.assertTrue(all((self.temp_root / "scores" / Path(item["filename"])).is_file() for item in saved))

    def test_batch_category_move_rolls_back_files_when_save_fails(self):
        items = [self.sample_item(item_id, has_lyrics=False) for item_id in (501, 502)]
        for item in items:
            self.seed_item_files(item)
        (self.temp_root / "data.json").write_text(
            json.dumps(items, ensure_ascii=False), encoding="utf-8"
        )
        self.admin.sync_catalog(items)
        original_paths = [self.temp_root / "scores" / Path(item["filename"]) for item in items]
        self.login()

        with mock.patch.object(self.admin, "save_all", side_effect=OSError("模拟批量保存失败")):
            with self.assertRaises(OSError):
                self.client.post(
                    "/batch-update",
                    data={
                        "_csrf_token": self.csrf_token(),
                        "item_ids": ["501", "502"],
                        "batch_action": "set_category",
                        "target_category": "其他",
                        "next": "/manage?page=1",
                    },
                )

        saved = json.loads((self.temp_root / "data.json").read_text(encoding="utf-8"))
        self.assertEqual({item["category"] for item in saved}, {"艺术歌曲"})
        self.assertTrue(all(path.is_file() for path in original_paths))
        self.assertFalse((self.temp_root / "scores" / "其他").exists())

    def test_deleted_score_can_be_restored_from_trash(self):
        item = self.sample_item(30)
        self.seed_item_files(item)
        (self.temp_root / "data.json").write_text(
            json.dumps([item], ensure_ascii=False), encoding="utf-8"
        )
        self.admin.sync_catalog([item])
        self.login()

        deleted = self.client.post(
            "/delete/30",
            data={"_csrf_token": self.csrf_token(), "next": "/manage?page=1"},
        )
        self.assertEqual(deleted.status_code, 302)
        self.assertEqual(json.loads((self.temp_root / "data.json").read_text(encoding="utf-8")), [])
        entries = self.admin.load_deleted_entries()
        self.assertEqual(len(entries), 1)

        trash_page = self.client.get("/trash")
        self.assertIn(item["title"], trash_page.get_data(as_text=True))
        restored = self.client.post(
            f"/trash/{entries[0]['name']}/restore",
            data={"_csrf_token": self.csrf_token()},
        )
        self.assertEqual(restored.status_code, 302)
        restored_data = json.loads((self.temp_root / "data.json").read_text(encoding="utf-8"))
        self.assertEqual(restored_data[0]["public_id"], item["public_id"])
        self.assertTrue((self.temp_root / "scores" / Path(item["filename"])).is_file())
        self.assertTrue((self.temp_root / "lyrics" / "30.json").is_file())
        self.assertEqual(self.admin.load_deleted_entries(), [])


if __name__ == "__main__":
    unittest.main()
