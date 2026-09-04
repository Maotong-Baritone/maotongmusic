"""Publish individual score PDFs to the configured object storage.

The public catalog is allowed to reference a new PDF only after the object has
been uploaded and verified by size and SHA-256 metadata.  Local PDFs remain the
source of truth and the bulk migration CLI continues to use
``storage-manifest.json`` for repair and audit runs.
"""

from __future__ import annotations

import datetime
import json
import os
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from tools.build_storage_manifest import write_manifest
from tools.sync_object_storage import (
    ManifestEntry,
    S3Target,
    SyncError,
    file_sha256,
    r2_endpoint_for,
    synchronize,
)


DEFAULT_MANIFEST_PATH = Path("storage-manifest.json")
OBJECT_PREFIX = "scores"
TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


class StoragePublishError(RuntimeError):
    """Raised when a PDF cannot be verified in object storage."""


@dataclass(frozen=True)
class StorageConfiguration:
    bucket: str
    endpoint_url: str | None
    region: str | None
    access_key_id: str | None
    secret_access_key: str | None


@dataclass(frozen=True)
class PublishResult:
    enabled: bool
    entries: tuple[ManifestEntry, ...] = ()
    detail: str = ""


def _configuration(*, force: bool = False) -> StorageConfiguration | None:
    mode = os.environ.get("SCORE_STORAGE_AUTO_SYNC", "auto").strip().lower()
    if mode in FALSE_VALUES and not force:
        return None
    if mode not in TRUE_VALUES | FALSE_VALUES | {"auto", ""}:
        raise StoragePublishError(
            "SCORE_STORAGE_AUTO_SYNC 只能填写 auto、1 或 0"
        )

    bucket = os.environ.get("SCORE_STORAGE_BUCKET", "").strip()
    account_id = os.environ.get("SCORE_STORAGE_R2_ACCOUNT_ID", "").strip()
    endpoint_url = os.environ.get("SCORE_STORAGE_ENDPOINT_URL", "").strip()
    region = os.environ.get("SCORE_STORAGE_REGION", "auto").strip() or None
    access_key_id = os.environ.get("SCORE_STORAGE_ACCESS_KEY_ID", "").strip()
    secret_access_key = os.environ.get("SCORE_STORAGE_SECRET_ACCESS_KEY", "").strip()

    configured = bool(
        bucket
        and (endpoint_url or account_id)
        and access_key_id
        and secret_access_key
    )
    if not configured:
        if mode in TRUE_VALUES or force:
            raise StoragePublishError(
                "R2 自动同步已启用，但存储桶、endpoint/Account ID 或访问密钥不完整"
            )
        return None

    if not endpoint_url:
        try:
            endpoint_url = r2_endpoint_for(account_id)
        except SyncError as exc:
            raise StoragePublishError(str(exc)) from exc

    return StorageConfiguration(
        bucket=bucket,
        endpoint_url=endpoint_url,
        region=region,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
    )


def auto_sync_enabled() -> bool:
    """Return whether automatic publishing is configured without raising."""
    try:
        return _configuration() is not None
    except StoragePublishError:
        return False


def storage_key_for(public_id: str, object_prefix: str = OBJECT_PREFIX) -> str:
    canonical_id = str(uuid.UUID(str(public_id)))
    prefix = PurePosixPath(object_prefix)
    if prefix.is_absolute() or any(part in ("", ".", "..") for part in prefix.parts):
        raise StoragePublishError("对象存储前缀无效")
    return f"{prefix.as_posix()}/{canonical_id[:2]}/{canonical_id}.pdf"


def manifest_entry_for(
    source: Path,
    *,
    public_id: str,
    catalog_filename: str,
    sha256: str | None = None,
) -> ManifestEntry:
    source = Path(source).resolve()
    if not source.is_file():
        raise StoragePublishError(f"本地 PDF 不存在：{source}")

    relative = PurePosixPath(str(catalog_filename).replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".pdf":
        raise StoragePublishError(f"目录中的 PDF 路径无效：{catalog_filename}")

    canonical_id = str(uuid.UUID(str(public_id)))
    actual_sha256 = (sha256 or file_sha256(source)).lower()
    if len(actual_sha256) != 64 or any(char not in "0123456789abcdef" for char in actual_sha256):
        raise StoragePublishError("PDF 的 SHA-256 无效")

    return ManifestEntry(
        public_id=canonical_id,
        source_path=f"scores/{relative.as_posix()}",
        storage_key=storage_key_for(canonical_id),
        file_size=source.stat().st_size,
        sha256=actual_sha256,
        source=source,
    )


def publish_entries(
    entries: list[ManifestEntry],
    *,
    force: bool = False,
    workers: int = 4,
) -> PublishResult:
    """Upload and verify entries; return disabled when auto mode has no config."""
    if not entries:
        return PublishResult(enabled=_configuration(force=force) is not None)

    configuration = _configuration(force=force)
    if configuration is None:
        return PublishResult(
            enabled=False,
            detail="R2 自动同步未启用；PDF 目前只保存在本地",
        )

    try:
        target = S3Target(
            bucket=configuration.bucket,
            endpoint_url=configuration.endpoint_url,
            region=configuration.region,
            access_key_id=configuration.access_key_id,
            secret_access_key=configuration.secret_access_key,
        )
        messages: list[str] = []
        summary = synchronize(
            entries,
            target,
            execute=True,
            verify_source_hash=True,
            workers=max(1, min(workers, len(entries))),
            emit=messages.append,
        )
    except (OSError, SyncError) as exc:
        raise StoragePublishError(f"R2 同步失败：{exc}") from exc

    if summary.failed:
        failures = [message for message in messages if "失败" in message]
        detail = failures[0] if failures else f"{summary.failed} 份文件上传或校验失败"
        raise StoragePublishError(f"R2 同步失败：{detail}")

    detail = f"R2 已校验 {summary.verified} 份，新上传 {summary.uploaded} 份"
    return PublishResult(enabled=True, entries=tuple(entries), detail=detail)


def apply_storage_metadata(item: dict, entry: ManifestEntry) -> None:
    item.update(
        {
            "storage_key": entry.storage_key,
            "storage_sha256": entry.sha256,
            "storage_size": entry.file_size,
            "storage_synced_at": datetime.datetime.now(datetime.timezone.utc).isoformat(
                timespec="seconds"
            ),
        }
    )


def update_manifest_entries(
    entries: list[ManifestEntry] | tuple[ManifestEntry, ...],
    path: Path = DEFAULT_MANIFEST_PATH,
) -> None:
    """Atomically add or replace verified entries in the migration manifest."""
    if not entries:
        return

    path = Path(path)
    if path.exists():
        try:
            manifest = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StoragePublishError(f"无法更新 {path.name}：{exc}") from exc
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_version") != 1
            or manifest.get("key_strategy") != "public_id_sharded"
        ):
            raise StoragePublishError(f"{path.name} 格式不受支持")
        raw_entries = manifest.get("entries")
        if not isinstance(raw_entries, list):
            raise StoragePublishError(f"{path.name} 缺少 entries")
    else:
        manifest = {
            "schema_version": 1,
            "key_strategy": "public_id_sharded",
            "object_prefix": OBJECT_PREFIX,
            "entries": [],
        }
        raw_entries = manifest["entries"]

    by_public_id = {
        str(entry.get("public_id")): dict(entry)
        for entry in raw_entries
        if isinstance(entry, dict) and entry.get("public_id")
    }
    for entry in entries:
        by_public_id[entry.public_id] = {
            "public_id": entry.public_id,
            "source_path": entry.source_path,
            "storage_key": entry.storage_key,
            "file_size": entry.file_size,
            "sha256": entry.sha256,
        }

    normalized = sorted(by_public_id.values(), key=lambda entry: entry["storage_key"])
    content_counts = Counter(entry["sha256"] for entry in normalized)
    manifest.update(
        {
            "object_prefix": OBJECT_PREFIX,
            "entry_count": len(normalized),
            "unique_content_count": len(content_counts),
            "duplicate_content_groups": sum(count > 1 for count in content_counts.values()),
            "duplicate_file_count": sum(count - 1 for count in content_counts.values()),
            "total_size": sum(int(entry["file_size"]) for entry in normalized),
            "entries": normalized,
        }
    )
    write_manifest(path, manifest)


def manifest_public_ids(path: Path = DEFAULT_MANIFEST_PATH) -> set[str]:
    try:
        manifest = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return set()
    entries = manifest.get("entries", []) if isinstance(manifest, dict) else []
    return {
        str(entry.get("public_id"))
        for entry in entries
        if isinstance(entry, dict) and entry.get("public_id")
    }
