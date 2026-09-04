from __future__ import annotations

import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

import score_storage
from tools.sync_object_storage import ObjectState, SyncError


class MemoryTarget:
    def __init__(self, **_kwargs):
        self.description = "memory"
        self.objects = {}

    def inspect(self, entry):
        stored = self.objects.get(entry.storage_key)
        if stored == (entry.file_size, entry.sha256):
            return ObjectState("verified")
        return ObjectState("missing", "远端对象不存在")

    def upload(self, entry):
        self.objects[entry.storage_key] = (entry.file_size, entry.sha256)


class FailingTarget(MemoryTarget):
    def upload(self, entry):
        raise SyncError(f"模拟上传失败 {entry.storage_key}")


class ScoreStorageTest(unittest.TestCase):
    def setUp(self):
        self.temp_context = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_context.name)
        self.source = self.root / "scores" / "艺术歌曲" / "sample.pdf"
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b"%PDF-1.4\nscore storage test\n%%EOF\n")
        self.public_id = str(uuid.uuid4())

    def tearDown(self):
        self.temp_context.cleanup()

    def configured_environment(self):
        return {
            "SCORE_STORAGE_AUTO_SYNC": "1",
            "SCORE_STORAGE_BUCKET": "test-bucket",
            "SCORE_STORAGE_ENDPOINT_URL": "https://example.invalid",
            "SCORE_STORAGE_REGION": "auto",
            "SCORE_STORAGE_ACCESS_KEY_ID": "test-access-key",
            "SCORE_STORAGE_SECRET_ACCESS_KEY": "test-secret-key",
        }

    def test_builds_stable_entry_from_public_id(self):
        entry = score_storage.manifest_entry_for(
            self.source,
            public_id=self.public_id,
            catalog_filename="艺术歌曲/sample.pdf",
        )

        self.assertEqual(
            entry.storage_key,
            f"scores/{self.public_id[:2]}/{self.public_id}.pdf",
        )
        self.assertEqual(entry.source_path, "scores/艺术歌曲/sample.pdf")
        self.assertEqual(entry.file_size, self.source.stat().st_size)
        self.assertEqual(len(entry.sha256), 64)

    def test_auto_mode_without_credentials_is_read_only(self):
        with mock.patch.dict(
            os.environ,
            {
                "SCORE_STORAGE_AUTO_SYNC": "auto",
                "SCORE_STORAGE_BUCKET": "",
                "SCORE_STORAGE_R2_ACCOUNT_ID": "",
                "SCORE_STORAGE_ENDPOINT_URL": "",
                "SCORE_STORAGE_ACCESS_KEY_ID": "",
                "SCORE_STORAGE_SECRET_ACCESS_KEY": "",
            },
            clear=False,
        ):
            result = score_storage.publish_entries(
                [
                    score_storage.manifest_entry_for(
                        self.source,
                        public_id=self.public_id,
                        catalog_filename="艺术歌曲/sample.pdf",
                    )
                ]
            )

        self.assertFalse(result.enabled)
        self.assertIn("只保存在本地", result.detail)

    def test_uploads_then_verifies_with_configured_target(self):
        target = MemoryTarget()
        entry = score_storage.manifest_entry_for(
            self.source,
            public_id=self.public_id,
            catalog_filename="艺术歌曲/sample.pdf",
        )
        with (
            mock.patch.dict(os.environ, self.configured_environment(), clear=False),
            mock.patch.object(score_storage, "S3Target", return_value=target),
        ):
            result = score_storage.publish_entries([entry])
            second = score_storage.publish_entries([entry])

        self.assertTrue(result.enabled)
        self.assertIn("新上传 1 份", result.detail)
        self.assertIn("R2 已校验 1 份", second.detail)
        self.assertEqual(result.entries, (entry,))

    def test_failure_never_reports_a_verified_publish(self):
        entry = score_storage.manifest_entry_for(
            self.source,
            public_id=self.public_id,
            catalog_filename="艺术歌曲/sample.pdf",
        )
        with (
            mock.patch.dict(os.environ, self.configured_environment(), clear=False),
            mock.patch.object(score_storage, "S3Target", return_value=FailingTarget()),
        ):
            with self.assertRaises(score_storage.StoragePublishError):
                score_storage.publish_entries([entry])

    def test_manifest_upsert_is_atomic_and_recalculates_summary(self):
        entry = score_storage.manifest_entry_for(
            self.source,
            public_id=self.public_id,
            catalog_filename="艺术歌曲/sample.pdf",
        )
        manifest_path = self.root / "storage-manifest.json"

        score_storage.update_manifest_entries([entry], manifest_path)
        score_storage.update_manifest_entries([entry], manifest_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["entry_count"], 1)
        self.assertEqual(manifest["unique_content_count"], 1)
        self.assertEqual(manifest["total_size"], entry.file_size)
        self.assertEqual(manifest["entries"][0]["storage_key"], entry.storage_key)
        self.assertFalse(list(self.root.glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
