from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.build_storage_manifest import build_manifest, write_manifest
from tools.sync_object_storage import (
    LocalDirectoryTarget,
    SyncError,
    load_manifest,
    r2_endpoint_for,
    synchronize,
)


class ObjectStorageSyncTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.scores = self.root / "scores"
        self.source = self.scores / "艺术歌曲" / "first.pdf"
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b"%PDF-object-storage-test")
        self.public_id = "8b8bfd5d-91ea-47cf-bf9b-646615a6a287"
        manifest = build_manifest(
            [{"public_id": self.public_id, "filename": "艺术歌曲/first.pdf"}],
            self.scores,
        )
        self.manifest_path = self.root / "manifest.json"
        write_manifest(self.manifest_path, manifest)
        self.entries = load_manifest(self.manifest_path, self.root)
        self.destination = self.root / "object-store"
        self.target = LocalDirectoryTarget(
            self.destination,
            source_scores_dir=self.scores,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    @property
    def mirrored_pdf(self) -> Path:
        return self.destination / "scores" / "8b" / f"{self.public_id}.pdf"

    def test_preview_is_read_only(self):
        summary = synchronize(self.entries, self.target, execute=False, emit=lambda _line: None)

        self.assertEqual(summary.planned, 1)
        self.assertEqual(summary.uploaded, 0)
        self.assertFalse(self.mirrored_pdf.exists())

    def test_execute_copies_verifies_and_is_resumable(self):
        first = synchronize(self.entries, self.target, execute=True, emit=lambda _line: None)
        second = synchronize(self.entries, self.target, execute=True, emit=lambda _line: None)

        self.assertEqual(first.uploaded, 1)
        self.assertEqual(second.verified, 1)
        self.assertEqual(self.mirrored_pdf.read_bytes(), self.source.read_bytes())

    def test_execute_repairs_same_size_tampered_destination(self):
        self.mirrored_pdf.parent.mkdir(parents=True)
        self.mirrored_pdf.write_bytes(b"X" * len(self.source.read_bytes()))

        summary = synchronize(self.entries, self.target, execute=True, emit=lambda _line: None)

        self.assertEqual(summary.uploaded, 1)
        self.assertEqual(self.mirrored_pdf.read_bytes(), self.source.read_bytes())

    def test_source_hash_can_be_rechecked(self):
        self.source.write_bytes(b"%PDF-different-but-long" + b"X" * 2)
        raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        raw["entries"][0]["file_size"] = self.source.stat().st_size
        raw["total_size"] = self.source.stat().st_size
        self.manifest_path.write_text(json.dumps(raw), encoding="utf-8")
        entries = load_manifest(self.manifest_path, self.root)

        summary = synchronize(
            entries,
            self.target,
            execute=False,
            verify_source_hash=True,
            emit=lambda _line: None,
        )

        self.assertEqual(summary.failed, 1)
        self.assertEqual(summary.planned, 0)

    def test_rejects_inconsistent_manifest_summary_and_unsafe_target(self):
        raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        raw["entry_count"] = 2
        self.manifest_path.write_text(json.dumps(raw), encoding="utf-8")

        with self.assertRaisesRegex(SyncError, "entry_count"):
            load_manifest(self.manifest_path, self.root)
        with self.assertRaisesRegex(SyncError, "不能是 scores"):
            LocalDirectoryTarget(self.scores / "mirror", source_scores_dir=self.scores)

    def test_builds_and_validates_r2_endpoint(self):
        account_id = "0123456789abcdef0123456789ABCDEF"

        self.assertEqual(
            r2_endpoint_for(account_id),
            "https://0123456789abcdef0123456789abcdef.r2.cloudflarestorage.com",
        )
        with self.assertRaisesRegex(SyncError, "32 位十六进制"):
            r2_endpoint_for("not-an-account-id")

    def test_parallel_uploads_are_verified_and_resumable(self):
        catalog = []
        for index in range(4):
            public_id = f"00000000-0000-4000-8000-{index:012d}"
            relative = f"艺术歌曲/parallel-{index}.pdf"
            path = self.scores / relative
            path.write_bytes(f"%PDF-parallel-{index}".encode())
            catalog.append({"public_id": public_id, "filename": relative})

        manifest = build_manifest(catalog, self.scores)
        manifest_path = self.root / "parallel-manifest.json"
        write_manifest(manifest_path, manifest)
        entries = load_manifest(manifest_path, self.root)

        first = synchronize(entries, self.target, execute=True, workers=4, emit=lambda _line: None)
        second = synchronize(entries, self.target, execute=True, workers=4, emit=lambda _line: None)

        self.assertEqual(first.uploaded, 4)
        self.assertEqual(first.failed, 0)
        self.assertEqual(second.verified, 4)

    def test_rejects_invalid_worker_count(self):
        with self.assertRaisesRegex(SyncError, "--workers"):
            synchronize(self.entries, self.target, execute=False, workers=0)


if __name__ == "__main__":
    unittest.main()
