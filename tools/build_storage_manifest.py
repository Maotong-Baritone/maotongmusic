"""Build a deterministic, provider-neutral upload manifest for score PDFs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import uuid
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_FILE = ROOT / "data.json"
DEFAULT_SCORES_DIR = ROOT / "scores"
DEFAULT_OUTPUT_FILE = ROOT / "storage-manifest.json"
HASH_CHUNK_SIZE = 1024 * 1024


class ManifestError(ValueError):
    """Raised when the catalog cannot be represented by a safe manifest."""


def load_catalog(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"无法读取目录 {path}: {exc}") from exc
    if not isinstance(data, list):
        raise ManifestError("data.json 的顶层必须是数组")
    return data


def normalize_relative_path(value: object, *, label: str) -> PurePosixPath:
    raw = str(value or "").replace("\\", "/")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ManifestError(f"{label} 不是安全的相对路径: {raw!r}")
    return path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def storage_key_for(public_id: str, object_prefix: str) -> str:
    canonical_id = str(uuid.UUID(public_id))
    prefix = normalize_relative_path(object_prefix, label="对象前缀").as_posix()
    return f"{prefix}/{canonical_id[:2]}/{canonical_id}.pdf"


def build_manifest(
    catalog: list[dict[str, Any]],
    scores_dir: Path,
    *,
    object_prefix: str = "scores",
) -> dict[str, Any]:
    scores_root = scores_dir.resolve()
    entries: list[dict[str, Any]] = []
    seen_public_ids: set[str] = set()
    seen_storage_keys: set[str] = set()

    for index, item in enumerate(catalog, start=1):
        if not isinstance(item, dict):
            raise ManifestError(f"记录 #{index} 不是对象")

        public_id = str(item.get("public_id", ""))
        try:
            canonical_id = str(uuid.UUID(public_id))
        except (ValueError, AttributeError) as exc:
            raise ManifestError(f"记录 #{index} 的 public_id 不是有效 UUID: {public_id!r}") from exc
        if canonical_id in seen_public_ids:
            raise ManifestError(f"public_id 重复: {canonical_id}")
        seen_public_ids.add(canonical_id)

        filename = normalize_relative_path(item.get("filename"), label=f"记录 #{index} 的 filename")
        if filename.suffix.lower() != ".pdf":
            raise ManifestError(f"记录 #{index} 引用的文件不是 PDF: {filename.as_posix()}")

        source = scores_root.joinpath(*filename.parts).resolve()
        try:
            source.relative_to(scores_root)
        except ValueError as exc:
            raise ManifestError(f"记录 #{index} 的文件路径越出 scores 目录") from exc
        if not source.is_file():
            raise ManifestError(f"记录 #{index} 引用的文件不存在: {filename.as_posix()}")

        storage_key = storage_key_for(canonical_id, object_prefix)
        if storage_key in seen_storage_keys:
            raise ManifestError(f"对象键重复: {storage_key}")
        seen_storage_keys.add(storage_key)

        entries.append(
            {
                "public_id": canonical_id,
                "source_path": f"scores/{filename.as_posix()}",
                "storage_key": storage_key,
                "file_size": source.stat().st_size,
                "sha256": file_sha256(source),
            }
        )

    entries.sort(key=lambda entry: entry["storage_key"])
    content_counts = Counter(entry["sha256"] for entry in entries)
    return {
        "schema_version": 1,
        "key_strategy": "public_id_sharded",
        "object_prefix": normalize_relative_path(object_prefix, label="对象前缀").as_posix(),
        "entry_count": len(entries),
        "unique_content_count": len(content_counts),
        "duplicate_content_groups": sum(count > 1 for count in content_counts.values()),
        "duplicate_file_count": sum(count - 1 for count in content_counts.values()),
        "total_size": sum(entry["file_size"] for entry in entries),
        "entries": entries,
    }


def manifest_text(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(manifest_text(manifest))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="扫描本地 PDF 并生成对象存储迁移清单")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_FILE, help="目录 JSON 路径")
    parser.add_argument("--scores-dir", type=Path, default=DEFAULT_SCORES_DIR, help="本地 PDF 根目录")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_FILE, help="清单输出路径")
    parser.add_argument("--object-prefix", default="scores", help="对象存储中的键前缀")
    parser.add_argument("--check", action="store_true", help="只检查现有清单是否为最新，不写文件")
    args = parser.parse_args()

    try:
        manifest = build_manifest(
            load_catalog(args.data),
            args.scores_dir,
            object_prefix=args.object_prefix,
        )
    except (ManifestError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    expected = manifest_text(manifest)
    if args.check:
        try:
            current = args.output.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"错误：无法读取现有清单 {args.output}: {exc}", file=sys.stderr)
            return 1
        if current != expected:
            print(f"错误：{args.output.name} 已过期，请重新生成。", file=sys.stderr)
            return 1
        action = "检查通过"
    else:
        write_manifest(args.output, manifest)
        action = f"已写入 {args.output}"

    total_gib = manifest["total_size"] / (1024 ** 3)
    print(f"{action}：{manifest['entry_count']} 个文件，共 {total_gib:.2f} GiB。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
