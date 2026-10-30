"""Publish public catalog snapshots to R2; switch the live pointer only after verification."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import score_storage
from tools.sync_object_storage import S3Target

PREFIX = 'website'
POINTER_KEY = f'{PREFIX}/current.json'
SOURCE_NAMES = ('data.json', 'logs.json', 'literature.json')


class WebsiteSyncError(RuntimeError):
    pass


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def digest(content):
    return hashlib.sha256(content).hexdigest()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_bytes(encoded(value) + b'\n')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def state_dir(root):
    return Path(root) / 'backup' / 'website_sync'


def read_receipt(root):
    try:
        return json.loads((state_dir(root) / 'last_success.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def load_bundle(root):
    root = Path(root).resolve()
    files = {name: (root / name).read_bytes() for name in SOURCE_NAMES}
    lyrics = {}
    for path in sorted((root / 'lyrics').glob('*.json')):
        if path.is_symlink() or not path.resolve().is_relative_to(root / 'lyrics'):
            raise WebsiteSyncError('歌词文件路径不安全。')
        relative = path.relative_to(root).as_posix()
        files[relative] = path.read_bytes()
        lyrics[path.stem] = json.loads(files[relative].decode('utf-8-sig'))
    bundle = dict(schema_version=1, scores=json.loads(files['data.json'].decode('utf-8-sig')),
                  logs=json.loads(files['logs.json'].decode('utf-8-sig')),
                  literature=json.loads(files['literature.json'].decode('utf-8-sig')), lyrics=lyrics)
    if not isinstance(bundle['scores'], list) or not isinstance(bundle['logs'], list):
        raise WebsiteSyncError('乐谱目录或更新记录格式错误。')
    if not isinstance(bundle['literature'], dict) or not isinstance(bundle['literature'].get('documents'), list):
        raise WebsiteSyncError('文献目录格式错误。')
    return bundle, files


def local_status(root):
    receipt = read_receipt(root)
    try:
        bundle, _ = load_bundle(root)
        revision = digest(encoded(bundle))
        return dict(label='已同步' if receipt.get('revision') == revision else '有未同步改动',
                    synced=receipt.get('revision') == revision, score_count=len(bundle['scores']),
                    document_count=len(bundle['literature']['documents']),
                    published_at=receipt.get('published_at'), revision=revision)
    except (OSError, ValueError, WebsiteSyncError):
        return dict(label='同步资料待检查', synced=False, score_count=None, published_at=None)


@contextmanager
def publication_lock(root):
    directory = state_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'publish.lock').open('a+b') as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise WebsiteSyncError('已有网站同步正在进行，请稍后查看结果。') from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def storage_target():
    configuration = score_storage._configuration(force=True)
    return S3Target(**vars(configuration))


def public_origin(root):
    config = json.loads((Path(root) / 'site-config.json').read_text(encoding='utf-8'))
    base = config['scoreStorage']['baseUrl'].rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.query or parsed.fragment:
        raise WebsiteSyncError('公开存储地址必须是完整的 HTTPS 地址。')
    return base


def verify_public(url, content):
    for attempt in range(4):
        try:
            request = Request(url, headers={'Cache-Control': 'no-cache', 'Origin': 'https://maotong.me',
                                           'User-Agent': 'MaoTongMusic-WebsiteSync/1.0'})
            with urlopen(request, timeout=30) as response:
                actual = response.read()
                cors = response.headers.get('Access-Control-Allow-Origin')
                if response.status != 200 or actual != content:
                    raise WebsiteSyncError('公开下载的目录内容校验不一致。')
                if cors not in ('*', 'https://maotong.me'):
                    raise WebsiteSyncError('R2 尚未允许网站读取目录，请检查跨域配置。')
            return
        except (OSError, WebsiteSyncError):
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def get_pointer(target):
    from botocore.exceptions import ClientError
    try:
        result = target.client.get_object(Bucket=target.bucket, Key=POINTER_KEY)
        content = result['Body'].read()
        pointer = json.loads(content)
        if pointer.get('schema_version') != 1 or not pointer.get('revision'):
            raise WebsiteSyncError('现有云端目录指针格式错误，未覆盖。')
        return pointer, result['ETag']
    except ClientError as error:
        if error.response.get('Error', {}).get('Code') in ('NoSuchKey', '404', 'NotFound'):
            return None, None
        raise


def verify_references(root, bundle, target, previous, progress):
    """Check new/changed local bytes and previously unverified remote PDFs."""
    root = Path(root).resolve()
    manifest = json.loads((root / 'storage-manifest.json').read_text(encoding='utf-8'))
    entries = {row['public_id']: row for row in manifest['entries']}
    fingerprints = previous.get('local_pdfs', {})
    verified = previous.get('remote_pdfs', {})
    next_fingerprints, references = {}, {}
    seen = set()
    progress(f'Checking local catalog and {len(bundle["scores"])} PDF fingerprints...')
    from validate_library import ALLOWED_CATEGORIES, CANONICAL_LANGUAGES, LANGUAGE_OPTIONAL_CATEGORIES
    for row in bundle['scores']:
        identifier = row['public_id']
        if identifier in seen or str(uuid.UUID(identifier)) != identifier:
            raise WebsiteSyncError('目录含重复或无效的乐谱标识。')
        seen.add(identifier)
        if not row.get('title') or not row.get('composer') or row.get('category') not in ALLOWED_CATEGORIES:
            raise WebsiteSyncError('目录存在未填写或无效的曲名、作曲家、分类。')
        language = str(row.get('language', '')).strip()
        optional_language = (row['category'] in LANGUAGE_OPTIONAL_CATEGORIES or
                             str(row.get('sub_category', '')).strip() == '练声曲' or
                             'vocalise' in row['title'].casefold())
        if language not in CANONICAL_LANGUAGES and not (not language and optional_language):
            raise WebsiteSyncError('目录存在无效的语言标记。')
        entry = entries.get(identifier)
        expected_key = score_storage.storage_key_for(identifier)
        if not entry or entry['storage_key'] != expected_key:
            raise WebsiteSyncError('有乐谱尚未核验到 R2，请先点击管理页对应的云朵按钮。')
        if any(row.get(key, entry[field]) != entry[field] for key, field in
               [('storage_key', 'storage_key'), ('storage_sha256', 'sha256'), ('storage_size', 'file_size')]):
            raise WebsiteSyncError('乐谱目录与 R2 核验清单不一致。')
        path = (root / 'scores' / row['filename']).resolve()
        if not path.is_relative_to(root / 'scores') or not path.is_file():
            raise WebsiteSyncError('有本地乐谱文件缺失，请在资料健康页核对。')
        stat = path.stat()
        fingerprint = dict(size=stat.st_size, mtime_ns=stat.st_mtime_ns, sha256=entry['sha256'])
        if stat.st_size != entry['file_size']:
            raise WebsiteSyncError('本地 PDF 大小已变化，必须先重新核验并同步文件。')
        if fingerprints.get(identifier) != fingerprint:
            if score_storage.file_sha256(path) != entry['sha256']:
                raise WebsiteSyncError('本地 PDF 内容已变化，必须先重新核验并同步文件。')
        next_fingerprints[identifier] = fingerprint
        references[expected_key] = dict(size=entry['file_size'], sha256=entry['sha256'])
        if len(seen) % 1000 == 0:
            progress(f'Checked {len(seen)} local PDF fingerprints.')
        if row.get('has_lyrics') and str(row['id']) not in bundle['lyrics']:
            raise WebsiteSyncError('有乐谱的歌词译文文件缺失。')
    from tools.validate_literature import validate
    if validate(bundle['literature'], root):
        raise WebsiteSyncError('文献目录核验失败，请检查书目、封面和文件资料。')
    for book in bundle['literature']['documents']:
        references[book['storage_key']] = dict(size=book['file_size'], sha256=book['sha256'])
    pending = [(key, value) for key, value in references.items() if verified.get(key) != value]
    progress(f'Checking {len(pending)} new/unverified public PDF references; {len(references)} active references total.')
    def check(pair):
        key, expected = pair
        result = target.client.head_object(Bucket=target.bucket, Key=key)
        if result['ContentLength'] != expected['size'] or result.get('Metadata', {}).get('sha256') != expected['sha256']:
            raise WebsiteSyncError('R2 中有 PDF 未通过大小或摘要校验，线上目录未更新。')
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(check, pending))
    return next_fingerprints, references


def publish(root=Path('.'), *, target=None, verifier=verify_public, progress=lambda message: None):
    root = Path(root).resolve()
    with publication_lock(root):
        bundle, sources = load_bundle(root)
        content = encoded(bundle); revision = digest(content)
        previous = read_receipt(root)
        base = public_origin(root)
        target = target or storage_target()
        current, etag = get_pointer(target)
        if current and current['revision'] not in (previous.get('revision'), revision):
            raise WebsiteSyncError('云端已有其他发布者的新版本，请先核对本地资料，未覆盖线上版本。')
        local_pdfs, remote_pdfs = verify_references(root, bundle, target, previous, progress)
        key = f'{PREFIX}/releases/{revision}.json'
        unchanged = bool(current and current['revision'] == revision)
        backup = state_dir(root) / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ-') + revision[:12])
        backup.mkdir(parents=True)
        (backup / 'snapshot.json').write_bytes(content)
        atomic_json(backup / 'previous_pointer.json', current)
        if not unchanged:
            target.client.put_object(Bucket=target.bucket, Key=key, Body=content, ContentType='application/json; charset=utf-8',
                                     CacheControl='public, max-age=31536000, immutable', Metadata={'sha256': revision})
        verifier(base + '/' + key, content)
        # Another local edit during a CLI sync must not silently be omitted.
        if load_bundle(root)[1] != sources:
            raise WebsiteSyncError('同步期间本地资料发生变化，请重新同步；线上仍使用上次版本。')
        pointer = current if unchanged else dict(schema_version=1, revision=revision, key=key,
                    published_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    score_count=len(bundle['scores']), document_count=len(bundle['literature']['documents']))
        pointer_content = encoded(pointer)
        if not unchanged:
            condition = {'IfMatch': etag} if etag else {'IfNoneMatch': '*'}
            target.client.put_object(Bucket=target.bucket, Key=POINTER_KEY, Body=pointer_content,
                ContentType='application/json; charset=utf-8', CacheControl='no-store, max-age=0, must-revalidate', **condition)
        receipt = dict(pointer, status='verification_pending', unchanged=unchanged, local_pdfs=local_pdfs, remote_pdfs=remote_pdfs)
        atomic_json(backup / 'receipt.json', receipt)
        # A random query also avoids a previously cached missing pointer during bootstrap.
        verifier(base + '/' + POINTER_KEY + '?v=' + uuid.uuid4().hex, pointer_content)
        receipt['status'] = 'verified_live'
        atomic_json(backup / 'receipt.json', receipt)
        atomic_json(state_dir(root) / 'last_success.json', receipt)
        return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv()
    if not args.execute:
        print(json.dumps(local_status(Path.cwd()), ensure_ascii=False)); return
    result = publish(progress=lambda value: print(value, flush=True))
    print(json.dumps({key: result[key] for key in ['status', 'revision', 'score_count', 'document_count', 'published_at', 'unchanged']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
