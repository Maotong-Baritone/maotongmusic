"""Safely synchronize score PDFs from a migration manifest.

The command is intentionally non-destructive: it never removes destination
objects and defaults to a read-only preview. Pass ``--execute`` to copy or
upload files. S3-compatible providers such as Cloudflare R2, Amazon S3,
Alibaba OSS, and Tencent COS can be used through boto3.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Protocol

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "storage-manifest.json"
HASH_CHUNK_SIZE = 1024 * 1024
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
R2_ACCOUNT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)


class SyncError(ValueError):
    """Raised when a manifest or synchronization target is unsafe."""


@dataclass(frozen=True)
class ManifestEntry:
    public_id: str
    source_path: str
    storage_key: str
    file_size: int
    sha256: str
    source: Path


@dataclass(frozen=True)
class ObjectState:
    status: str
    detail: str = ""


@dataclass
class SyncSummary:
    selected: int = 0
    total_bytes: int = 0
    verified: int = 0
    planned: int = 0
    uploaded: int = 0
    failed: int = 0


class SyncTarget(Protocol):
    description: str

    def inspect(self, entry: ManifestEntry) -> ObjectState: ...

    def upload(self, entry: ManifestEntry) -> None: ...


def r2_endpoint_for(account_id: str) -> str:
    """Build Cloudflare R2's S3 endpoint from an account ID."""

    normalized = account_id.strip().lower()
    if not R2_ACCOUNT_ID_PATTERN.fullmatch(normalized):
        raise SyncError("Cloudflare R2 Account ID 应为 32 位十六进制字符串")
    return f"https://{normalized}.r2.cloudflarestorage.com"


def file_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative_path(value: object, *, label: str) -> PurePosixPath:
    raw = str(value or "").replace("\\", "/")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise SyncError(f"{label} 不是安全的相对路径: {raw!r}")
    return path


def resolve_inside(root: Path, relative: PurePosixPath, *, label: str) -> Path:
    root = root.resolve()
    resolved = root.joinpath(*relative.parts).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SyncError(f"{label} 越出允许目录: {relative.as_posix()}") from exc
    return resolved


def load_manifest(path: Path, source_root: Path) -> list[ManifestEntry]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SyncError(f"无法读取迁移清单 {path}: {exc}") from exc

    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise SyncError("只支持 schema_version 为 1 的迁移清单")
    if manifest.get("key_strategy") != "public_id_sharded":
        raise SyncError("迁移清单必须使用 public_id_sharded 对象键策略")

    prefix = safe_relative_path(manifest.get("object_prefix"), label="对象前缀").as_posix()
    raw_entries = manifest.get("entries")
    if not isinstance(raw_entries, list):
        raise SyncError("迁移清单的 entries 必须是数组")
    if manifest.get("entry_count") != len(raw_entries):
        raise SyncError("迁移清单的 entry_count 与 entries 数量不一致")

    entries: list[ManifestEntry] = []
    seen_public_ids: set[str] = set()
    seen_storage_keys: set[str] = set()
    for index, raw_entry in enumerate(raw_entries, start=1):
        if not isinstance(raw_entry, dict):
            raise SyncError(f"迁移清单记录 #{index} 不是对象")

        public_id = str(raw_entry.get("public_id", ""))
        try:
            public_id = str(uuid.UUID(public_id))
        except (ValueError, AttributeError) as exc:
            raise SyncError(f"迁移清单记录 #{index} 的 public_id 无效") from exc
        if public_id in seen_public_ids:
            raise SyncError(f"迁移清单中的 public_id 重复: {public_id}")
        seen_public_ids.add(public_id)

        source_relative = safe_relative_path(
            raw_entry.get("source_path"), label=f"记录 #{index} 的 source_path"
        )
        if source_relative.parts[0] != "scores" or source_relative.suffix.lower() != ".pdf":
            raise SyncError(f"记录 #{index} 的源文件必须位于 scores/ 且为 PDF")
        source = resolve_inside(source_root, source_relative, label=f"记录 #{index} 的源文件")
        if not source.is_file():
            raise SyncError(f"迁移清单引用的源文件不存在: {source_relative.as_posix()}")

        storage_key = safe_relative_path(
            raw_entry.get("storage_key"), label=f"记录 #{index} 的 storage_key"
        ).as_posix()
        expected_key = f"{prefix}/{public_id[:2]}/{public_id}.pdf"
        if storage_key != expected_key:
            raise SyncError(
                f"记录 #{index} 的对象键与 public_id_sharded 规则不一致: {storage_key}"
            )
        if storage_key in seen_storage_keys:
            raise SyncError(f"迁移清单中的对象键重复: {storage_key}")
        seen_storage_keys.add(storage_key)

        file_size = raw_entry.get("file_size")
        if not isinstance(file_size, int) or isinstance(file_size, bool) or file_size < 0:
            raise SyncError(f"记录 #{index} 的 file_size 无效")
        actual_size = source.stat().st_size
        if actual_size != file_size:
            raise SyncError(
                f"源文件大小与清单不一致: {source_relative.as_posix()} "
                f"（清单 {file_size}，实际 {actual_size}）"
            )

        sha256 = str(raw_entry.get("sha256", "")).lower()
        if not SHA256_PATTERN.fullmatch(sha256):
            raise SyncError(f"记录 #{index} 的 SHA-256 无效")

        entries.append(
            ManifestEntry(
                public_id=public_id,
                source_path=source_relative.as_posix(),
                storage_key=storage_key,
                file_size=file_size,
                sha256=sha256,
                source=source,
            )
        )

    if manifest.get("total_size") != sum(entry.file_size for entry in entries):
        raise SyncError("迁移清单的 total_size 与 entries 汇总不一致")
    return entries


class LocalDirectoryTarget:
    """A local object-store simulation used for safe rehearsals and tests."""

    def __init__(self, root: Path, *, source_scores_dir: Path | None = None):
        self.root = root.resolve()
        if source_scores_dir is not None:
            scores_root = source_scores_dir.resolve()
            if self.root == scores_root or scores_root in self.root.parents:
                raise SyncError("本地演练目录不能是 scores/ 或其子目录")
        self.description = f"本地演练目录 {self.root}"

    def destination_for(self, entry: ManifestEntry) -> Path:
        relative = safe_relative_path(entry.storage_key, label="对象键")
        return resolve_inside(self.root, relative, label="本地目标文件")

    def inspect(self, entry: ManifestEntry) -> ObjectState:
        destination = self.destination_for(entry)
        if not destination.is_file():
            return ObjectState("missing", "目标文件不存在")
        if destination.stat().st_size != entry.file_size:
            return ObjectState("different", "文件大小不一致")
        if file_sha256(destination) != entry.sha256:
            return ObjectState("different", "SHA-256 不一致")
        return ObjectState("verified")

    def upload(self, entry: ManifestEntry) -> None:
        destination = self.destination_for(entry)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.part")
        try:
            shutil.copyfile(entry.source, temporary)
            if temporary.stat().st_size != entry.file_size or file_sha256(temporary) != entry.sha256:
                raise SyncError(f"复制后校验失败: {entry.storage_key}")
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)


class S3Target:
    """S3-compatible destination with metadata-based integrity checks."""

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None,
        region: str | None,
        access_key_id: str | None,
        secret_access_key: str | None,
    ):
        if not bucket.strip():
            raise SyncError("对象存储桶名称不能为空")
        if bool(access_key_id) != bool(secret_access_key):
            raise SyncError("访问密钥 ID 和秘密访问密钥必须同时设置")
        try:
            import boto3
            from botocore.exceptions import BotoCoreError, ClientError
        except ImportError as exc:
            raise SyncError("S3 同步需要安装 boto3，请先重新安装 requirements.txt") from exc

        client_options: dict[str, Any] = {}
        if endpoint_url:
            client_options["endpoint_url"] = endpoint_url
        if region:
            client_options["region_name"] = region
        if access_key_id and secret_access_key:
            client_options["aws_access_key_id"] = access_key_id
            client_options["aws_secret_access_key"] = secret_access_key

        self.bucket = bucket
        self.client = boto3.client("s3", **client_options)
        self.boto_core_error = BotoCoreError
        self.client_error = ClientError
        endpoint_label = endpoint_url or "AWS 默认端点"
        self.description = f"S3 存储桶 {bucket}（{endpoint_label}）"

    def inspect(self, entry: ManifestEntry) -> ObjectState:
        try:
            response = self.client.head_object(Bucket=self.bucket, Key=entry.storage_key)
        except self.client_error as exc:
            response = getattr(exc, "response", {})
            status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            code = str(response.get("Error", {}).get("Code", ""))
            if status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
                return ObjectState("missing", "远端对象不存在")
            raise SyncError(f"无法检查远端对象 {entry.storage_key}: {exc}") from exc
        except self.boto_core_error as exc:
            raise SyncError(f"无法连接对象存储以检查 {entry.storage_key}: {exc}") from exc

        remote_size = response.get("ContentLength")
        remote_hash = str(response.get("Metadata", {}).get("sha256", "")).lower()
        if remote_size != entry.file_size:
            return ObjectState("different", "远端文件大小不一致")
        if remote_hash != entry.sha256:
            return ObjectState("different", "远端缺少或不匹配 SHA-256 元数据")
        return ObjectState("verified")

    def upload(self, entry: ManifestEntry) -> None:
        try:
            self.client.upload_file(
                str(entry.source),
                self.bucket,
                entry.storage_key,
                ExtraArgs={
                    "ContentType": "application/pdf",
                    "CacheControl": "public, max-age=31536000, immutable",
                    "Metadata": {"sha256": entry.sha256},
                },
            )
        except Exception as exc:
            raise SyncError(f"上传失败 {entry.storage_key}: {exc}") from exc


def synchronize(
    entries: list[ManifestEntry],
    target: SyncTarget,
    *,
    execute: bool,
    limit: int | None = None,
    verify_source_hash: bool = False,
    progress_every: int = 100,
    workers: int = 1,
    emit: Callable[[str], None] = print,
) -> SyncSummary:
    if limit is not None and limit <= 0:
        raise SyncError("--limit 必须大于 0")
    if progress_every <= 0:
        raise SyncError("--progress-every 必须大于 0")
    if workers <= 0:
        raise SyncError("--workers 必须大于 0")

    selected = entries[:limit] if limit is not None else entries
    summary = SyncSummary(
        selected=len(selected),
        total_bytes=sum(entry.file_size for entry in selected),
    )
    verbose = len(selected) <= 20

    def process_entry(index: int, entry: ManifestEntry) -> tuple[int, ManifestEntry, str, str]:
        try:
            if verify_source_hash and file_sha256(entry.source) != entry.sha256:
                raise SyncError(f"源文件 SHA-256 与清单不一致: {entry.source_path}")

            state = target.inspect(entry)
            if state.status == "verified":
                outcome = "verified"
                action = "已校验，跳过"
            elif not execute:
                outcome = "planned"
                action = f"计划上传（{state.detail}）"
            else:
                target.upload(entry)
                verified = target.inspect(entry)
                if verified.status != "verified":
                    raise SyncError(f"上传后校验失败: {entry.storage_key}（{verified.detail}）")
                outcome = "uploaded"
                action = "上传并校验通过"
            return index, entry, outcome, action
        except (OSError, SyncError) as exc:
            return index, entry, "failed", str(exc)

    if workers == 1 or len(selected) <= 1:
        results = (process_entry(index, entry) for index, entry in enumerate(selected, start=1))
        executor = None
    else:
        executor = ThreadPoolExecutor(max_workers=min(workers, len(selected)))
        futures = [
            executor.submit(process_entry, index, entry)
            for index, entry in enumerate(selected, start=1)
        ]
        results = (future.result() for future in as_completed(futures))

    completed = 0
    try:
        for index, entry, outcome, detail in results:
            completed += 1
            if outcome == "failed":
                summary.failed += 1
                emit(f"[{index}/{len(selected)}] 失败: {entry.storage_key}: {detail}")
            else:
                setattr(summary, outcome, getattr(summary, outcome) + 1)
                if verbose:
                    emit(f"[{index}/{len(selected)}] {detail}: {entry.storage_key}")

            if not verbose and (completed % progress_every == 0 or completed == len(selected)):
                emit(
                    f"进度 {completed}/{len(selected)}：已存在 {summary.verified}，"
                    f"计划 {summary.planned}，已上传 {summary.uploaded}，失败 {summary.failed}"
                )
    finally:
        if executor is not None:
            executor.shutdown(wait=True)

    return summary


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(line_buffering=True)
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(
        description="按 storage-manifest.json 安全同步 PDF；默认仅预演，不写目标"
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="迁移清单路径")
    parser.add_argument("--root", type=Path, default=ROOT, help="清单 source_path 的根目录")
    parser.add_argument("--local-dir", type=Path, help="使用本地目录模拟对象存储")
    parser.add_argument("--bucket", help="S3 兼容存储桶；也可用 SCORE_STORAGE_BUCKET")
    parser.add_argument(
        "--endpoint-url",
        help="S3 兼容 API 地址；也可用 SCORE_STORAGE_ENDPOINT_URL",
    )
    parser.add_argument(
        "--r2-account-id",
        help="Cloudflare Account ID；也可用 SCORE_STORAGE_R2_ACCOUNT_ID，并自动生成 R2 endpoint",
    )
    parser.add_argument("--region", help="存储区域；也可用 SCORE_STORAGE_REGION")
    parser.add_argument("--execute", action="store_true", help="实际复制或上传；省略时只预演")
    parser.add_argument("--limit", type=int, help="只处理清单前 N 项，用于小规模演练")
    parser.add_argument(
        "--verify-source-hash",
        action="store_true",
        help="同步时再次计算每个源 PDF 的 SHA-256",
    )
    parser.add_argument("--progress-every", type=int, default=100, help="每 N 项输出一次进度")
    parser.add_argument(
        "--workers",
        type=int,
        help="并发检查/上传数量；默认本地 1，S3 兼容对象存储 8",
    )
    args = parser.parse_args()

    if args.local_dir and args.bucket:
        parser.error("--local-dir 与 S3 存储桶不能同时使用")
    bucket = None if args.local_dir else (args.bucket or os.getenv("SCORE_STORAGE_BUCKET"))
    if not args.local_dir and not bucket:
        parser.error("请指定 --local-dir，或配置 --bucket / SCORE_STORAGE_BUCKET")

    try:
        entries = load_manifest(args.manifest, args.root)
        if args.local_dir:
            target: SyncTarget = LocalDirectoryTarget(
                args.local_dir,
                source_scores_dir=args.root / "scores",
            )
        else:
            r2_account_id = args.r2_account_id or os.getenv("SCORE_STORAGE_R2_ACCOUNT_ID")
            endpoint_url = args.endpoint_url or os.getenv("SCORE_STORAGE_ENDPOINT_URL")
            if not endpoint_url and r2_account_id:
                endpoint_url = r2_endpoint_for(r2_account_id)
            region = args.region or os.getenv("SCORE_STORAGE_REGION")
            if not region and r2_account_id:
                region = "auto"
            target = S3Target(
                bucket=bucket or "",
                endpoint_url=endpoint_url,
                region=region,
                access_key_id=os.getenv("SCORE_STORAGE_ACCESS_KEY_ID"),
                secret_access_key=os.getenv("SCORE_STORAGE_SECRET_ACCESS_KEY"),
            )

        mode = "执行" if args.execute else "只读预演"
        workers = args.workers if args.workers is not None else (1 if args.local_dir else 8)
        print(f"模式：{mode}")
        print(f"目标：{target.description}")
        print(f"并发：{workers}")
        if args.limit is not None:
            print(f"范围：仅清单前 {args.limit} 项（演练模式）")

        summary = synchronize(
            entries,
            target,
            execute=args.execute,
            limit=args.limit,
            verify_source_hash=args.verify_source_hash,
            progress_every=args.progress_every,
            workers=workers,
        )
    except SyncError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    gib = summary.total_bytes / (1024**3)
    print(
        f"完成：选中 {summary.selected} 个文件，共 {gib:.2f} GiB；"
        f"已存在 {summary.verified}，计划 {summary.planned}，"
        f"已上传 {summary.uploaded}，失败 {summary.failed}。"
    )
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
