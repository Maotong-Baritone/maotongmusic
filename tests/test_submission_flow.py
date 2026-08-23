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

        cls.original_cwd = Path.cwd()
        os.chdir(cls.temp_root)
        cls.admin = importlib.import_module("admin_tool")
        cls.admin.app.config.update(TESTING=True)

    def setUp(self):
        for folder_name in ("scores", "lyrics", "backup", "private_uploads"):
            shutil.rmtree(self.temp_root / folder_name, ignore_errors=True)
            (self.temp_root / folder_name).mkdir(parents=True, exist_ok=True)
        (self.temp_root / "data.json").write_text("[]\n", encoding="utf-8")
        (self.temp_root / "logs.json").write_text("[]\n", encoding="utf-8")
        database_path = Path(os.environ["SUBMISSIONS_DB"])
        database_path.unlink(missing_ok=True)
        self.admin.init_database()
        self.admin.sync_catalog([])
        self.client = self.admin.app.test_client()

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
