from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.build_storage_manifest import ManifestError, build_manifest, manifest_text, write_manifest


class StorageManifestTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.scores = self.root / "scores"
        (self.scores / "艺术歌曲").mkdir(parents=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_item(self, public_id: str, filename: str) -> dict[str, object]:
        return {"id": 1, "public_id": public_id, "filename": filename}

    def test_builds_stable_sharded_keys_hashes_and_totals(self):
        first_id = "8b8bfd5d-91ea-47cf-bf9b-646615a6a287"
        second_id = "0a8bfd5d-91ea-47cf-bf9b-646615a6a288"
        first_content = b"%PDF-first"
        second_content = b"%PDF-second"
        (self.scores / "艺术歌曲" / "first.pdf").write_bytes(first_content)
        (self.scores / "艺术歌曲" / "second.pdf").write_bytes(second_content)

        manifest = build_manifest(
            [
                self.make_item(first_id, "艺术歌曲/first.pdf"),
                self.make_item(second_id, "艺术歌曲/second.pdf"),
            ],
            self.scores,
        )

        self.assertEqual(manifest["entry_count"], 2)
        self.assertEqual(manifest["unique_content_count"], 2)
        self.assertEqual(manifest["duplicate_content_groups"], 0)
        self.assertEqual(manifest["duplicate_file_count"], 0)
        self.assertEqual(manifest["total_size"], len(first_content) + len(second_content))
        self.assertEqual(
            [entry["storage_key"] for entry in manifest["entries"]],
            [f"scores/0a/{second_id}.pdf", f"scores/8b/{first_id}.pdf"],
        )
        first_entry = manifest["entries"][1]
        self.assertEqual(first_entry["source_path"], "scores/艺术歌曲/first.pdf")
        self.assertEqual(first_entry["sha256"], hashlib.sha256(first_content).hexdigest())

    def test_reports_duplicate_pdf_content_without_collapsing_object_keys(self):
        first_id = "8b8bfd5d-91ea-47cf-bf9b-646615a6a287"
        second_id = "0a8bfd5d-91ea-47cf-bf9b-646615a6a288"
        content = b"%PDF-identical"
        (self.scores / "艺术歌曲" / "first.pdf").write_bytes(content)
        (self.scores / "艺术歌曲" / "second.pdf").write_bytes(content)

        manifest = build_manifest(
            [
                self.make_item(first_id, "艺术歌曲/first.pdf"),
                self.make_item(second_id, "艺术歌曲/second.pdf"),
            ],
            self.scores,
        )

        self.assertEqual(manifest["entry_count"], 2)
        self.assertEqual(manifest["unique_content_count"], 1)
        self.assertEqual(manifest["duplicate_content_groups"], 1)
        self.assertEqual(manifest["duplicate_file_count"], 1)
        self.assertEqual(len({entry["storage_key"] for entry in manifest["entries"]}), 2)

    def test_manifest_output_is_deterministic_and_atomic(self):
        public_id = "8b8bfd5d-91ea-47cf-bf9b-646615a6a287"
        (self.scores / "艺术歌曲" / "first.pdf").write_bytes(b"%PDF-first")
        manifest = build_manifest(
            [self.make_item(public_id, "艺术歌曲/first.pdf")],
            self.scores,
        )
        output = self.root / "manifest.json"
        write_manifest(output, manifest)
        first = output.read_text(encoding="utf-8")
        write_manifest(output, manifest)
        self.assertEqual(output.read_text(encoding="utf-8"), first)
        self.assertEqual(json.loads(first), manifest)
        self.assertEqual(first, manifest_text(manifest))

    def test_rejects_missing_unsafe_and_duplicate_records(self):
        public_id = "8b8bfd5d-91ea-47cf-bf9b-646615a6a287"
        with self.assertRaisesRegex(ManifestError, "不存在"):
            build_manifest([self.make_item(public_id, "艺术歌曲/missing.pdf")], self.scores)
        with self.assertRaisesRegex(ManifestError, "安全的相对路径"):
            build_manifest([self.make_item(public_id, "../outside.pdf")], self.scores)

        (self.scores / "艺术歌曲" / "first.pdf").write_bytes(b"%PDF-first")
        item = self.make_item(public_id, "艺术歌曲/first.pdf")
        with self.assertRaisesRegex(ManifestError, "public_id 重复"):
            build_manifest([item, item.copy()], self.scores)


if __name__ == "__main__":
    unittest.main()
