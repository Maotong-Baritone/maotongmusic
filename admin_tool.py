import os
import json
import datetime
import hashlib
import re
import secrets
import shutil
import threading
import time
import unicodedata
import uuid
from collections import Counter
from email.utils import parseaddr
from functools import wraps
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from flask import Flask, abort, render_template, render_template_string, request, redirect, url_for, flash, session, send_file
from dotenv import load_dotenv
import brahms_review as brahms_views

# 加载 .env 文件中的环境变量
load_dotenv()

from score_storage import (  # noqa: E402
    PublishResult,
    StoragePublishError,
    apply_storage_metadata,
    auto_sync_enabled,
    manifest_entry_for,
    manifest_public_ids,
    publish_entries,
    update_manifest_entries,
)

from submission_store import (  # noqa: E402
    create_submission,
    find_active_duplicate,
    get_submission,
    init_database,
    list_submissions,
    mark_approved,
    mark_rejected,
    now_utc,
    restore_pending,
    submission_counts,
    sync_catalog,
)

# ===⚙️ 配置区域 ===
SCORES_DIR = 'scores'
LYRICS_DIR = 'lyrics'
DATA_FILE = 'data.json'      # 修改这里：指向根目录的 data.json
LOGS_FILE = 'logs.json'      # 新增这里：指向根目录的 logs.json
BACKUP_DIR = 'backup'
BRAHMS_REVIEW_FILE = Path(os.environ.get(
    'BRAHMS_REVIEW_FILE',
    'imports/johannes_brahms/manifest.json',
))
PENDING_UPLOAD_DIR = Path(os.environ.get('PENDING_UPLOAD_DIR', 'private_uploads'))
try:
    BACKUP_KEEP_COUNT = max(1, int(os.environ.get('BACKUP_KEEP_COUNT', '10')))
except ValueError:
    BACKUP_KEEP_COUNT = 10
try:
    SUBMISSION_MAX_MB = min(100, max(1, int(os.environ.get('SUBMISSION_MAX_MB', '50'))))
except ValueError:
    SUBMISSION_MAX_MB = 50
SUBMISSION_MAX_BYTES = SUBMISSION_MAX_MB * 1024 * 1024
ADMIN_UPLOAD_MAX_MB = 100
ADMIN_UPLOAD_MAX_BYTES = ADMIN_UPLOAD_MAX_MB * 1024 * 1024
UPLOAD_FORM_OVERHEAD_BYTES = 1024 * 1024
LOGIN_MAX_BYTES = 64 * 1024
DEFAULT_FORM_MAX_BYTES = 2 * 1024 * 1024
try:
    BATCH_UPLOAD_MAX_FILES = min(100, max(1, int(os.environ.get('BATCH_UPLOAD_MAX_FILES', '30'))))
except ValueError:
    BATCH_UPLOAD_MAX_FILES = 30
try:
    BATCH_UPLOAD_MAX_MB = min(900, max(10, int(os.environ.get('BATCH_UPLOAD_MAX_MB', '500'))))
except ValueError:
    BATCH_UPLOAD_MAX_MB = 500
BATCH_UPLOAD_MAX_BYTES = BATCH_UPLOAD_MAX_MB * 1024 * 1024

AUTOMATIC_BACKUP_PATTERN = re.compile(
    r'^data_backup_\d{8}_\d{6}(?:_\d{6})?\.json$'
)
CATALOG_LOCK = threading.RLock()
BRAHMS_REVIEW_LOCK = threading.RLock()
ALLOWED_EXTENSIONS = {'pdf'}
ALLOWED_CATEGORIES = {
    '歌剧咏叹调', '歌剧重唱', '宗教声乐作品', '艺术歌曲', '音乐剧选段',
    '合唱作品', '音乐会咏叹调/世俗康塔塔', '声乐套曲', '乐谱书/曲集',
    '器乐独奏', '器乐分谱', '室内乐', '歌剧总谱', '管弦乐/交响曲', '协奏曲总谱',
    '宗教声乐作品总谱', '其他'
}
CANONICAL_LANGUAGES = {
    '意大利语', '德语', '法语', '英语', '俄语', '拉丁语', '捷克语', '汉语',
    '法语/拉丁语',
}
BRAHMS_REVIEW_DECISIONS = set(brahms_views.DECISION_LABELS)

ADMIN_USER = os.environ.get('ADMIN_USER', 'admin')
ADMIN_PASS = os.environ.get('ADMIN_PASS')
if not ADMIN_PASS:
    raise RuntimeError('缺少 ADMIN_PASS。请先在 .env 中设置后台密码。')
try:
    ADMIN_PORT = int(os.environ.get('ADMIN_PORT', '5000'))
    if not 1 <= ADMIN_PORT <= 65535:
        raise ValueError
except ValueError:
    ADMIN_PORT = 5000
AUTO_OPEN_BROWSER = os.environ.get('AUTO_OPEN_BROWSER', '1').strip().lower() in {'1', 'true', 'yes', 'on'}

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32),
    MAX_CONTENT_LENGTH=max(
        100 * 1024 * 1024,
        SUBMISSION_MAX_BYTES + 1024 * 1024,
        BATCH_UPLOAD_MAX_BYTES + 5 * 1024 * 1024,
    ),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)

# 确保目录存在
for folder in [SCORES_DIR, BACKUP_DIR, 'js', LYRICS_DIR, PENDING_UPLOAD_DIR]:
    if not os.path.exists(folder):
        os.makedirs(folder)


def csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_urlsafe(32)
    return session['_csrf_token']


app.jinja_env.globals['csrf_token'] = csrf_token


@app.before_request
def protect_post_requests():
    if request.method == 'POST':
        if request.endpoint not in {'login', 'submit_score'} and 'logged_in' not in session:
            return redirect(url_for('login', next=request.full_path))

        size_limits = {
            'login': LOGIN_MAX_BYTES,
            'submit_score': SUBMISSION_MAX_BYTES + UPLOAD_FORM_OVERHEAD_BYTES,
            'index': ADMIN_UPLOAD_MAX_BYTES + UPLOAD_FORM_OVERHEAD_BYTES,
            'batch_upload': BATCH_UPLOAD_MAX_BYTES + 5 * UPLOAD_FORM_OVERHEAD_BYTES,
        }
        size_limit = size_limits.get(request.endpoint, DEFAULT_FORM_MAX_BYTES)
        if size_limit and request.content_length and request.content_length > size_limit:
            abort(413)

        submitted = request.form.get('_csrf_token', '')
        expected = session.get('_csrf_token', '')
        if not expected or not secrets.compare_digest(submitted, expected):
            abort(400, description='表单已过期，请刷新页面后重试。')


@app.route('/health')
def health():
    return {'status': 'ok'}


def safe_next_url(target):
    if not target:
        return None
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or not target.startswith('/'):
        return None
    return target


def score_file_path(filename):
    relative = PurePosixPath(filename)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('非法乐谱文件路径')
    root = Path(SCORES_DIR).resolve()
    candidate = root.joinpath(*relative.parts).resolve()
    if root != candidate and root not in candidate.parents:
        raise ValueError('乐谱文件路径越界')
    return candidate


def pending_file_path(filename):
    if not filename or Path(filename).name != filename:
        raise ValueError('非法投稿文件路径')
    root = PENDING_UPLOAD_DIR.resolve()
    candidate = (root / filename).resolve()
    if root != candidate.parent:
        raise ValueError('投稿文件路径越界')
    return candidate


def publish_catalog_items_to_storage(item_paths, *, force=False):
    """Upload local PDFs and attach verified storage metadata to catalog items."""
    entries = [
        manifest_entry_for(
            path,
            public_id=item['public_id'],
            catalog_filename=item['filename'],
            sha256=sha256,
        )
        for item, path, sha256 in item_paths
    ]
    result = publish_entries(entries, force=force)
    if result.enabled:
        for (item, _path, _sha256), entry in zip(item_paths, result.entries):
            apply_storage_metadata(item, entry)
    return result


def update_manifest_after_publish(result):
    """Keep the audit manifest current without invalidating a successful publish."""
    if not result.enabled or not result.entries:
        return
    try:
        update_manifest_entries(result.entries)
    except (OSError, StoragePublishError) as error:
        app.logger.error('R2 已发布，但 storage-manifest.json 更新失败：%s', error)
        flash('PDF 已同步到 R2，但存储清单更新失败；请稍后重新生成清单。', 'warning')


def storage_status_for_item(item, migrated_public_ids):
    if item.get('storage_key') and item.get('storage_sha256') and item.get('storage_synced_at'):
        return {'code': 'verified', 'label': 'R2 已校验', 'class': 'success'}
    if str(item.get('public_id', '')) in migrated_public_ids:
        return {'code': 'manifest', 'label': 'R2 已同步', 'class': 'success'}
    if auto_sync_enabled():
        return {'code': 'pending', 'label': '等待同步', 'class': 'warning'}
    return {'code': 'disabled', 'label': '仅本地', 'class': 'secondary'}


def clean_original_filename(filename):
    leaf = re.split(r'[\\/]', filename or '')[-1]
    leaf = ''.join(char for char in leaf if char.isprintable()).strip()
    return leaf[:255] or 'score.pdf'


def validated_text(value, label, max_length, required=False):
    value = str(value or '').strip()
    if required and not value:
        raise ValueError(f'请填写{label}')
    if len(value) > max_length:
        raise ValueError(f'{label}不能超过 {max_length} 个字符')
    return value


def form_text(name, label, max_length, required=False):
    return validated_text(request.form.get(name, ''), label, max_length, required)


def valid_email(value):
    parsed = parseaddr(value)[1]
    return parsed == value and len(value) <= 254 and re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', value)


def save_pending_pdf(upload, public_id):
    final_path = pending_file_path(f'{public_id}.pdf')
    temp_path = pending_file_path(f'{public_id}.part')
    digest = hashlib.sha256()
    total = 0
    try:
        with temp_path.open('xb') as target:
            while True:
                chunk = upload.stream.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > SUBMISSION_MAX_BYTES:
                    raise ValueError(f'PDF 不能超过 {SUBMISSION_MAX_MB} MB')
                digest.update(chunk)
                target.write(chunk)
        if total < 5:
            raise ValueError('PDF 文件为空或不完整')
        with temp_path.open('rb') as source:
            if source.read(5) != b'%PDF-':
                raise ValueError('文件内容不是有效 PDF')
        temp_path.replace(final_path)
        return final_path, digest.hexdigest(), total
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        if final_path.exists():
            final_path.unlink()
        raise


def submission_file_location(submission):
    private_path = pending_file_path(submission['stored_filename'])
    if private_path.is_file():
        return private_path
    if submission.get('status') == 'approved' and submission.get('published_filename'):
        public_path = score_file_path(submission['published_filename'])
        if public_path.is_file():
            return public_path
    return None

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login', next=request.full_path))
        return f(*args, **kwargs)
    return decorated_function


def catalog_write_locked(f):
    """Serialize catalog mutations made by Flask's worker threads."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        with CATALOG_LOCK:
            return f(*args, **kwargs)
    return decorated_function


def write_json_atomic(path, value, *, indent=None):
    """Write one JSON file without ever exposing a partially written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    try:
        with temp_path.open('x', encoding='utf-8', newline='\n') as handle:
            json.dump(value, handle, indent=indent, ensure_ascii=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def load_brahms_review_manifest():
    """Load the isolated Brahms staging manifest without touching the catalog."""
    with BRAHMS_REVIEW_LOCK:
        if not BRAHMS_REVIEW_FILE.is_file():
            return None
        try:
            with BRAHMS_REVIEW_FILE.open('r', encoding='utf-8') as handle:
                manifest = json.load(handle)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f'勃拉姆斯审核清单已损坏，已停止写入: {exc}') from exc
        if not isinstance(manifest, dict) or not isinstance(manifest.get('works', []), list):
            raise RuntimeError('勃拉姆斯审核清单格式无效')
        return manifest


def brahms_review_rows(manifest):
    rows = []
    for work in (manifest or {}).get('works', []):
        for score_file in work.get('files', []):
            rows.append({'work': work, 'score_file': score_file})
    return rows


def find_brahms_review_file(manifest, imslp_id):
    imslp_id = str(imslp_id)
    for work in manifest.get('works', []):
        for score_file in work.get('files', []):
            if str(score_file.get('imslp_id', '')) == imslp_id:
                return work, score_file
    return None, None


def brahms_review_text(name, label, max_length, required=False):
    try:
        return form_text(name, label, max_length, required)
    except ValueError as exc:
        abort(400, description=str(exc))


def brahms_source_url(value):
    """Only link to the known source; imported metadata cannot supply scripts."""
    parsed = urlsplit(str(value or ''))
    return value if parsed.scheme == 'https' and parsed.hostname == 'imslp.org' else ''


def restore_file_bytes(path, previous_content):
    """Restore a file snapshot atomically; None means the file did not exist."""
    path = Path(path)
    if previous_content is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.restore')
    try:
        with temp_path.open('xb') as handle:
            handle.write(previous_content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

def load_data_and_log():
    with CATALOG_LOCK:
        music_data = []
        change_log = []

        # 读取 data.json
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                try:
                    music_data = json.load(f)
                except json.JSONDecodeError as e:
                    raise RuntimeError(f"data.json 已损坏，已停止操作以避免覆盖数据: {e}") from e

        # 读取 logs.json
        if os.path.exists(LOGS_FILE):
            with open(LOGS_FILE, 'r', encoding='utf-8') as f:
                try:
                    change_log = json.load(f)
                except json.JSONDecodeError as e:
                    raise RuntimeError(f"logs.json 已损坏，已停止操作以避免覆盖日志: {e}") from e

        return music_data, change_log


def initialize_submission_store():
    init_database()
    music_data, _ = load_data_and_log()
    sync_catalog(music_data)


initialize_submission_store()


def prune_automatic_backups():
    """只保留最近的自动数据备份，不影响阶段备份和删除回收站。"""
    backup_root = Path(BACKUP_DIR)
    automatic_backups = sorted(
        (
            path for path in backup_root.iterdir()
            if path.is_file() and AUTOMATIC_BACKUP_PATTERN.fullmatch(path.name)
        ),
        key=lambda path: path.name,
        reverse=True,
    )
    for old_backup in automatic_backups[BACKUP_KEEP_COUNT:]:
        old_backup.unlink()

def save_all(music_data, change_log):
    with CATALOG_LOCK:
        data_path = Path(DATA_FILE)
        logs_path = Path(LOGS_FILE)
        previous_data = data_path.read_bytes() if data_path.exists() else None
        previous_logs = logs_path.read_bytes() if logs_path.exists() else None
        previous_catalog = json.loads(previous_data.decode('utf-8-sig')) if previous_data else []

        # 备份机制
        if data_path.exists():
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            shutil.copy2(data_path, os.path.join(BACKUP_DIR, f"data_backup_{timestamp}.json"))
            prune_automatic_backups()

        # 按照 ID 倒序排列乐谱
        music_data.sort(key=lambda x: x['id'], reverse=True)
        data_temp = data_path.with_name(f'.{data_path.name}.{uuid.uuid4().hex}.tmp')
        logs_temp = logs_path.with_name(f'.{logs_path.name}.{uuid.uuid4().hex}.tmp')

        try:
            with data_temp.open('x', encoding='utf-8', newline='\n') as handle:
                json.dump(music_data, handle, indent=4, ensure_ascii=False)
                handle.write('\n')
                handle.flush()
                os.fsync(handle.fileno())
            with logs_temp.open('x', encoding='utf-8', newline='\n') as handle:
                json.dump(change_log, handle, indent=4, ensure_ascii=False)
                handle.write('\n')
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(data_temp, data_path)
            os.replace(logs_temp, logs_path)
            sync_catalog(music_data)
        except Exception as error:
            data_temp.unlink(missing_ok=True)
            logs_temp.unlink(missing_ok=True)
            rollback_errors = []
            for path, content in ((data_path, previous_data), (logs_path, previous_logs)):
                try:
                    restore_file_bytes(path, content)
                except Exception as rollback_error:
                    rollback_errors.append(f'{path.name}: {rollback_error}')
            try:
                sync_catalog(previous_catalog)
            except Exception as rollback_error:
                rollback_errors.append(f'数据库镜像: {rollback_error}')
            if rollback_errors:
                raise RuntimeError(
                    '保存失败，且自动回滚未完整完成: ' + '; '.join(rollback_errors)
                ) from error
            raise

def add_log(change_log, action_type, message):
    today = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    change_log.insert(0, {"date": today, "type": action_type, "msg": message})
    del change_log[50:]

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def is_pdf_upload(file):
    header = file.stream.read(5)
    file.stream.seek(0)
    return header == b'%PDF-'


def title_from_pdf_filename(filename):
    """Turn a local PDF filename into an editable default catalog title."""
    cleaned = clean_original_filename(filename)
    stem = cleaned[:-4] if cleaned.lower().endswith('.pdf') else Path(cleaned).stem
    title = re.sub(r'[_\s]+', ' ', stem).strip(' .-_')
    return title[:200] or '未命名乐谱'


def stage_batch_pdf(upload, staging_path, remaining_bytes):
    """Validate and stream one batch PDF without publishing it yet."""
    digest = hashlib.sha256()
    total = 0
    try:
        with staging_path.open('xb') as target:
            while True:
                chunk = upload.stream.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > remaining_bytes:
                    raise ValueError(f'批量上传总大小不能超过 {BATCH_UPLOAD_MAX_MB} MB')
                digest.update(chunk)
                target.write(chunk)
        if total < 5:
            raise ValueError(f'{clean_original_filename(upload.filename)} 文件为空或不完整')
        with staging_path.open('rb') as source:
            if source.read(5) != b'%PDF-':
                raise ValueError(f'{clean_original_filename(upload.filename)} 不是有效 PDF')
        return digest.hexdigest(), total
    except Exception:
        try:
            staging_path.unlink(missing_ok=True)
        except OSError as cleanup_error:
            app.logger.error('无法清理批量上传暂存文件 %s: %s', staging_path, cleanup_error)
        raise

# --- 歌词处理函数 ---
def save_lyrics(item_id, original, translation):
    path = Path(LYRICS_DIR) / f"{item_id}.json"
    if not original.strip() and not translation.strip():
        path.unlink(missing_ok=True)
        return False
    
    data = {
        "id": item_id,
        "original": original,
        "translation": translation
    }
    write_json_atomic(path, data)
    return True

def load_lyrics(item_id):
    path = os.path.join(LYRICS_DIR, f"{item_id}.json")
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"original": "", "translation": ""}


def deleted_entry_path(entry_name):
    if not entry_name or Path(entry_name).name != entry_name:
        raise ValueError('非法的回收站记录')
    root = (Path(BACKUP_DIR) / 'deleted').resolve()
    candidate = (root / entry_name).resolve()
    if candidate.parent != root:
        raise ValueError('回收站路径越界')
    return candidate


def load_deleted_entries():
    root = Path(BACKUP_DIR) / 'deleted'
    if not root.exists():
        return []
    entries = []
    for entry_dir in sorted((path for path in root.iterdir() if path.is_dir()), reverse=True):
        manifest_path = entry_dir / 'manifest.json'
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            item = manifest['item']
            if not isinstance(item, dict) or 'id' not in item or 'public_id' not in item:
                raise ValueError('缺少乐谱身份字段')
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
        entries.append({
            'name': entry_dir.name,
            'deleted_at': manifest.get('deleted_at', ''),
            'item': item,
            'files': manifest.get('files', {}),
        })
    return entries


def normalize_catalog_text(value):
    normalized = unicodedata.normalize('NFKC', str(value or '')).casefold()
    return ' '.join(normalized.split())


def duplicate_catalog_groups(items):
    groups = {}
    for item in items:
        key = (
            normalize_catalog_text(item.get('title')),
            normalize_catalog_text(item.get('composer')),
        )
        if not all(key):
            continue
        groups.setdefault(key, []).append(item)
    duplicates = [group for group in groups.values() if len(group) > 1]
    duplicates.sort(
        key=lambda group: (-len(group), normalize_catalog_text(group[0].get('composer')), normalize_catalog_text(group[0].get('title')))
    )
    return duplicates


def format_file_size(size):
    size = float(size)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024 or unit == 'TB':
            return f'{size:.1f} {unit}' if unit != 'B' else f'{int(size)} B'
        size /= 1024


def normalized_catalog_filename(filename):
    return PurePosixPath(str(filename or '').replace('\\', '/')).as_posix()


def catalog_health_report(items):
    referenced_files = set()
    missing_files = []
    invalid_paths = []
    for item in items:
        filename = str(item.get('filename', ''))
        normalized_filename = normalized_catalog_filename(filename)
        try:
            path = score_file_path(filename)
        except (TypeError, ValueError):
            invalid_paths.append({
                'item': item,
                'filename': normalized_filename,
                'reason': '记录的 PDF 路径不合法',
                'possible_matches': [],
            })
            continue
        referenced_files.add(normalized_filename.casefold())
        if not path.is_file():
            missing_files.append({
                'item': item,
                'filename': normalized_filename,
                'reason': '记录指向的 PDF 不存在',
                'possible_matches': [],
            })

    actual_paths = [path for path in Path(SCORES_DIR).rglob('*') if path.is_file()]
    actual_files = {
        path.relative_to(SCORES_DIR).as_posix(): path
        for path in actual_paths
    }
    orphan_filenames = sorted(
        filename for filename in actual_files
        if normalized_catalog_filename(filename).casefold() not in referenced_files
    )
    orphan_files = [
        {
            'filename': filename,
            'size': format_file_size(actual_files[filename].stat().st_size),
        }
        for filename in orphan_filenames
    ]
    orphans_by_basename = {}
    for orphan in orphan_files:
        basename = PurePosixPath(orphan['filename']).name.casefold()
        orphans_by_basename.setdefault(basename, []).append(orphan['filename'])
    for issue in missing_files:
        basename = PurePosixPath(issue['filename']).name.casefold()
        issue['possible_matches'] = orphans_by_basename.get(basename, [])

    return {
        'missing_files': missing_files,
        'invalid_paths': invalid_paths,
        'file_issues': missing_files + invalid_paths,
        'orphan_files': orphan_files,
        'actual_files': len(actual_files),
        'total_bytes': sum(path.stat().st_size for path in actual_paths),
        'missing_work': sum(1 for item in items if not str(item.get('work', '')).strip()),
        'missing_description': sum(1 for item in items if not str(item.get('description', '')).strip()),
        'healthy': not missing_files and not invalid_paths and not orphan_files,
    }


def catalog_dashboard_snapshot(items, change_log):
    health = catalog_health_report(items)
    backups = sorted(
        (
            path for path in Path(BACKUP_DIR).glob('data_backup_*.json')
            if AUTOMATIC_BACKUP_PATTERN.fullmatch(path.name)
        ),
        key=lambda path: path.name,
        reverse=True,
    )
    duplicates = duplicate_catalog_groups(items)
    category_counts = [
        {'name': name, 'count': count}
        for name, count in Counter(str(item.get('category', '')) for item in items).most_common()
    ]
    deleted_entries = load_deleted_entries()
    counts = submission_counts()
    return {
        'total_items': len(items),
        'actual_files': health['actual_files'],
        'missing_files': len(health['missing_files']),
        'invalid_paths': len(health['invalid_paths']),
        'orphan_files': len(health['orphan_files']),
        'storage_size': format_file_size(health['total_bytes']),
        'lyrics_files': len(list(Path(LYRICS_DIR).glob('*.json'))),
        'missing_work': health['missing_work'],
        'missing_description': health['missing_description'],
        'duplicate_groups': len(duplicates),
        'automatic_backups': len(backups),
        'latest_backup': backups[0].name if backups else '尚无',
        'deleted_count': len(deleted_entries),
        'pending_count': counts['pending'],
        'category_counts': category_counts,
        'recent_logs': change_log[:8],
        'healthy': health['healthy'],
    }

# --- HTML Templates ---
# 建议：为防止暴力破解，可以引入 flask-limiter 库对 /login 路由进行速率限制
LOGIN_HTML = """
<!doctype html>
<html lang="zh">
<head><meta charset="utf-8"><title>登录</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light d-flex align-items-center justify-content-center" style="height:100vh">
<div class="card p-4 shadow" style="width:350px">
    <h3 class="text-center mb-3">登录</h3>
    {% with messages = get_flashed_messages() %}{% if messages %}<div class="alert alert-danger py-2">{{ messages[0] }}</div>{% endif %}{% endwith %}
    <form method="post"><input type="hidden" name="_csrf_token" value="{{ csrf_token() }}"><input type="text" name="username" class="form-control mb-2" placeholder="用户名" aria-label="用户名" autocomplete="username" required><input type="password" name="password" class="form-control mb-3" placeholder="密码" aria-label="密码" autocomplete="current-password" required><button class="btn btn-primary w-100">登录</button></form>
</div>
</body></html>
"""

PUBLIC_SUBMISSION_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>乐谱投稿</title>
    <style>
        :root { --ink:#24323d; --muted:#65727c; --paper:#fffdf8; --teal:#287f75; --line:#d9dfdc; --warm:#f4eee2; --danger:#a23c36; }
        * { box-sizing:border-box; }
        body { margin:0; color:var(--ink); background:linear-gradient(145deg,#f5efe4,#eef6f3); font-family:"Microsoft YaHei","PingFang SC",sans-serif; }
        .shell { width:min(920px,calc(100% - 28px)); margin:36px auto; }
        .hero { padding:34px; color:white; border-radius:22px 22px 0 0; background:#214f4b; }
        .hero h1 { margin:0 0 8px; font-size:clamp(28px,5vw,42px); }
        .hero p { margin:0; max-width:680px; color:#d7ebe7; line-height:1.7; }
        .panel { padding:32px; background:var(--paper); border-radius:0 0 22px 22px; box-shadow:0 18px 45px rgba(38,55,52,.12); }
        .notice { padding:14px 16px; margin-bottom:22px; border-radius:12px; background:var(--warm); line-height:1.65; }
        .notice.error { background:#f8e5e2; color:var(--danger); }
        .notice.success { background:#e3f3ec; color:#1d6658; }
        fieldset { border:0; padding:0; margin:0 0 26px; }
        legend { width:100%; padding-bottom:10px; margin-bottom:16px; border-bottom:1px solid var(--line); font-weight:700; font-size:19px; }
        .grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; }
        .full { grid-column:1 / -1; }
        label { display:block; margin-bottom:7px; font-size:14px; font-weight:700; }
        input, select, textarea { width:100%; border:1px solid var(--line); border-radius:10px; padding:11px 12px; background:white; color:var(--ink); font:inherit; }
        textarea { min-height:98px; resize:vertical; }
        input:focus, select:focus, textarea:focus { outline:3px solid rgba(40,127,117,.16); border-color:var(--teal); }
        .help { margin-top:6px; color:var(--muted); font-size:13px; line-height:1.55; }
        .check { display:flex; align-items:flex-start; gap:10px; margin:20px 0; line-height:1.6; }
        .check input { width:auto; margin-top:5px; }
        button { width:100%; border:0; border-radius:12px; padding:14px; color:white; background:var(--teal); font:700 16px inherit; cursor:pointer; }
        button:hover { background:#1e6e65; }
        .trap { position:absolute !important; left:-10000px !important; width:1px !important; height:1px !important; overflow:hidden !important; }
        .receipt { text-align:center; padding:36px 10px; }
        .receipt strong { display:block; margin:14px 0; font-size:28px; color:var(--teal); }
        .receipt a { color:var(--teal); }
        @media (max-width:640px) { .shell { margin:14px auto; } .hero,.panel { padding:22px; } .grid { grid-template-columns:1fr; } }
    </style>
</head>
<body>
<main class="shell">
    <header class="hero">
        <h1>乐谱投稿</h1>
        <p>上传后会先进入私有待审核区。管理员确认资料与文件后，乐谱才会出现在公开网站。</p>
    </header>
    <section class="panel">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% for category, message in messages %}<div class="notice {{ category }}" role="alert">{{ message }}</div>{% endfor %}
        {% endwith %}

        {% if receipt %}
        <div class="receipt">
            <h2>投稿已安全保存</h2>
            <p>审核编号</p>
            <strong>#{{ receipt }}</strong>
            <p>管理员通过后才会公开。请保留这个编号，以便后续查询。</p>
            <a href="{{ url_for('submit_score') }}">继续投稿另一份乐谱</a>
        </div>
        {% else %}
        <div class="notice">第一版暂不要求注册账号。邮箱仅用于联系投稿人，不会在公开页面展示。</div>
        <form method="post" enctype="multipart/form-data">
            <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
            <div class="trap" aria-hidden="true"><label>网站<input name="website" tabindex="-1" autocomplete="off"></label></div>

            <fieldset>
                <legend>投稿人</legend>
                <div class="grid">
                    <div><label for="submitter_name">姓名或称呼 *</label><input id="submitter_name" name="submitter_name" maxlength="100" value="{{ form.get('submitter_name','') }}" required></div>
                    <div><label for="submitter_email">联系邮箱 *</label><input id="submitter_email" name="submitter_email" type="email" maxlength="254" value="{{ form.get('submitter_email','') }}" required></div>
                </div>
            </fieldset>

            <fieldset>
                <legend>乐谱资料</legend>
                <div class="grid">
                    <div><label for="title">曲名 *</label><input id="title" name="title" maxlength="200" value="{{ form.get('title','') }}" required></div>
                    <div><label for="composer">作曲家 *</label><input id="composer" name="composer" maxlength="200" value="{{ form.get('composer','') }}" required></div>
                    <div><label for="work">所属作品</label><input id="work" name="work" maxlength="200" value="{{ form.get('work','') }}"></div>
                    <div><label for="language">语言</label><input id="language" name="language" maxlength="100" value="{{ form.get('language','') }}"></div>
                    <div><label for="category">分类 *</label><select id="category" name="category" required><option value="" disabled {{ 'selected' if not form.get('category') }}>请选择分类</option>{% for category in categories %}<option value="{{ category }}" {{ 'selected' if form.get('category') == category }}>{{ category }}</option>{% endfor %}</select></div>
                    <div><label for="sub_category">体裁／子分类</label><input id="sub_category" name="sub_category" maxlength="120" value="{{ form.get('sub_category','') }}"></div>
                    <div><label for="voice_types">声部／乐器</label><input id="voice_types" name="voice_types" maxlength="150" value="{{ form.get('voice_types','') }}" placeholder="例如：Soprano / Piano"></div>
                    <div><label for="voice_count">数量／类型补充</label><input id="voice_count" name="voice_count" maxlength="100" value="{{ form.get('voice_count','') }}" placeholder="例如：二重唱"></div>
                    <div><label for="tonality">调性</label><input id="tonality" name="tonality" maxlength="80" value="{{ form.get('tonality','') }}"></div>
                    <div class="full"><label for="description">简介或补充说明</label><textarea id="description" name="description" maxlength="2000">{{ form.get('description','') }}</textarea></div>
                </div>
            </fieldset>

            <fieldset>
                <legend>歌词与译文（可选）</legend>
                <div class="grid">
                    <div><label for="lyrics_original">歌词原文</label><textarea id="lyrics_original" name="lyrics_original" maxlength="20000">{{ form.get('lyrics_original','') }}</textarea></div>
                    <div><label for="lyrics_translation">中文翻译</label><textarea id="lyrics_translation" name="lyrics_translation" maxlength="20000">{{ form.get('lyrics_translation','') }}</textarea></div>
                </div>
            </fieldset>

            <fieldset>
                <legend>PDF 文件</legend>
                <label for="file">选择乐谱 PDF *</label>
                <input id="file" name="file" type="file" accept="application/pdf,.pdf" required>
                <p class="help">仅接受 PDF，最大 {{ max_mb }} MB。文件在审核通过前不会公开。</p>
            </fieldset>

            <label class="check"><input type="checkbox" name="copyright_confirmed" value="1" required><span>我确认该文件允许分享，或已获得必要授权；我同意管理员对资料进行修改、驳回或下架处理。</span></label>
            <button type="submit">提交审核</button>
        </form>
        {% endif %}
    </section>
</main>
</body>
</html>
"""

SUBMISSION_ADMIN_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>投稿审核</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>body{background:#f8f9fa;padding:20px}.pdf-frame{width:100%;height:70vh;border:1px solid #dee2e6;border-radius:.5rem;background:#fff}</style>
</head>
<body>
<div class="container-fluid" style="max-width:1200px">
    <div class="d-flex justify-content-between mb-4"><h2>🎹 后台管理</h2><form method="post" action="/logout"><input type="hidden" name="_csrf_token" value="{{ csrf_token() }}"><button class="btn btn-outline-danger btn-sm">退出</button></form></div>
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% for category, message in messages %}<div class="alert {{ 'alert-danger' if category == 'error' else 'alert-success' }}">{{ message }}</div>{% endfor %}
    {% endwith %}
    <ul class="nav nav-tabs mb-4">
        <li class="nav-item"><a class="nav-link" href="/dashboard">📊 仪表盘</a></li>
        <li class="nav-item"><a class="nav-link" href="/">📤 上传发布</a></li>
        <li class="nav-item"><a class="nav-link" href="/manage">📋 公开乐谱</a></li>
        <li class="nav-item"><a class="nav-link active" href="/submissions">🛡️ 投稿审核 {% if counts.pending %}<span class="badge bg-danger">{{ counts.pending }}</span>{% endif %}</a></li>
        <li class="nav-item"><a class="nav-link" href="/trash">♻️ 回收站</a></li>
        <li class="nav-item ms-auto"><a class="nav-link" href="/submit" target="_blank">查看投稿页 ↗</a></li>
    </ul>

    {% if active_tab == 'submissions' %}
    <div class="d-flex flex-wrap gap-2 mb-3">
        <a class="btn {{ 'btn-primary' if status == 'pending' else 'btn-outline-primary' }}" href="?status=pending">待审核 {{ counts.pending }}</a>
        <a class="btn {{ 'btn-success' if status == 'approved' else 'btn-outline-success' }}" href="?status=approved">已通过 {{ counts.approved }}</a>
        <a class="btn {{ 'btn-secondary' if status == 'rejected' else 'btn-outline-secondary' }}" href="?status=rejected">已驳回 {{ counts.rejected }}</a>
        <a class="btn {{ 'btn-dark' if status == 'all' else 'btn-outline-dark' }}" href="?status=all">全部</a>
    </div>
    <div class="card shadow-sm"><div class="table-responsive"><table class="table table-hover align-middle mb-0">
        <thead class="table-light"><tr><th>编号／时间</th><th>乐谱</th><th>投稿人</th><th>状态</th><th></th></tr></thead>
        <tbody>
        {% for item in submissions %}
        <tr>
            <td>#{{ item.id }}<br><small class="text-muted">{{ item.submitted_at[:19].replace('T',' ') }} UTC</small></td>
            <td><strong>{{ item.title }}</strong><br><span class="text-muted">{{ item.composer }} · {{ item.category }}</span></td>
            <td>{{ item.submitter_name }}<br><small>{{ item.submitter_email }}</small></td>
            <td><span class="badge {{ 'bg-warning text-dark' if item.status == 'pending' else ('bg-success' if item.status == 'approved' else 'bg-secondary') }}">{{ {'pending':'待审核','approved':'已通过','rejected':'已驳回'}[item.status] }}</span></td>
            <td><a class="btn btn-sm btn-outline-primary" href="/submissions/{{ item.id }}">查看</a></td>
        </tr>
        {% else %}<tr><td colspan="5" class="text-center text-muted p-5">当前没有记录</td></tr>{% endfor %}
        </tbody>
    </table></div></div>
    {% endif %}

    {% if active_tab == 'submission_detail' %}
    <div class="mb-3"><a href="/submissions?status={{ submission.status }}">← 返回列表</a></div>
    <div class="row g-4">
        <div class="col-lg-5">
            <div class="card shadow-sm"><div class="card-body">
                <div class="d-flex justify-content-between align-items-start"><h3>{{ submission.title }}</h3><span class="badge {{ 'bg-warning text-dark' if submission.status == 'pending' else ('bg-success' if submission.status == 'approved' else 'bg-secondary') }}">{{ {'pending':'待审核','approved':'已通过','rejected':'已驳回'}[submission.status] }}</span></div>
                <dl class="row mt-4 mb-0">
                    <dt class="col-4">作曲家</dt><dd class="col-8">{{ submission.composer }}</dd>
                    <dt class="col-4">所属作品</dt><dd class="col-8">{{ submission.work or '—' }}</dd>
                    <dt class="col-4">分类</dt><dd class="col-8">{{ submission.category }}{% if submission.sub_category %} / {{ submission.sub_category }}{% endif %}</dd>
                    <dt class="col-4">语言／调性</dt><dd class="col-8">{{ submission.language or '—' }} / {{ submission.tonality or '—' }}</dd>
                    <dt class="col-4">编制</dt><dd class="col-8">{{ submission.voice_types or '—' }} {{ submission.voice_count }}</dd>
                    <dt class="col-4">简介</dt><dd class="col-8" style="white-space:pre-wrap">{{ submission.description or '—' }}</dd>
                    <dt class="col-4">投稿人</dt><dd class="col-8">{{ submission.submitter_name }}<br><a href="mailto:{{ submission.submitter_email }}">{{ submission.submitter_email }}</a></dd>
                    <dt class="col-4">文件</dt><dd class="col-8">{{ submission.original_filename }}<br>{{ file_size }} MB · SHA-256 {{ submission.sha256[:12] }}…</dd>
                    {% if submission.review_note %}<dt class="col-4">审核意见</dt><dd class="col-8">{{ submission.review_note }}</dd>{% endif %}
                    {% if submission.published_item_id %}<dt class="col-4">公开 ID</dt><dd class="col-8">{{ submission.published_item_id }}</dd>{% endif %}
                </dl>
            </div></div>

            {% if submission.status == 'pending' %}
            <div class="card shadow-sm mt-3"><div class="card-body">
                <form method="post" action="/submissions/{{ submission.id }}/approve" class="mb-3" onsubmit="return confirm('确认通过并公开这份乐谱吗？')">
                    <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
                    <label class="form-label fw-bold">审核备注（可选）</label><textarea class="form-control mb-2" name="review_note" maxlength="1000" rows="2"></textarea>
                    <button class="btn btn-success w-100">通过并发布</button>
                </form>
                <form method="post" action="/submissions/{{ submission.id }}/reject" onsubmit="return confirm('确认驳回这份投稿吗？')">
                    <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
                    <label class="form-label fw-bold">驳回原因 *</label><textarea class="form-control mb-2" name="review_note" maxlength="1000" rows="3" required></textarea>
                    <button class="btn btn-outline-danger w-100">驳回</button>
                </form>
            </div></div>
            {% elif submission.status == 'rejected' %}
            <form method="post" action="/submissions/{{ submission.id }}/restore" class="mt-3"><input type="hidden" name="_csrf_token" value="{{ csrf_token() }}"><button class="btn btn-outline-primary">恢复为待审核</button></form>
            {% endif %}
        </div>
        <div class="col-lg-7">
            {% if file_available %}<iframe class="pdf-frame" title="投稿 PDF 预览" src="/submissions/{{ submission.id }}/file"></iframe>{% else %}<div class="alert alert-warning">私有投稿文件不存在。{% if submission.status == 'approved' %}该文件已经移动到公开乐谱目录。{% endif %}</div>{% endif %}
        </div>
    </div>
    {% endif %}
</div>
</body>
</html>
"""

CATEGORY_SELECT_HTML = """
<div class="mb-3"><label class="form-label">分类</label><select class="form-select" name="category">
{% set current = item.category if item else '' %}
<optgroup label="🎤 声乐">
    <option value="歌剧咏叹调" {{ 'selected' if current == '歌剧咏叹调' }}>歌剧咏叹调</option>
    <option value="歌剧重唱" {{ 'selected' if current == '歌剧重唱' }}>歌剧重唱</option>
    <option value="宗教声乐作品" {{ 'selected' if current == '宗教声乐作品' }}>宗教声乐作品 (Sacred Vocal Music)</option>
    <option value="艺术歌曲" {{ 'selected' if current == '艺术歌曲' }}>艺术歌曲</option>
    <option value="音乐剧选段" {{ 'selected' if current == '音乐剧选段' }}>音乐剧选段</option>
    <option value="合唱作品" {{ 'selected' if current == '合唱作品' }}>合唱作品</option>
</optgroup>
<optgroup label="✨ 特殊/世俗康塔塔">
    <option value="音乐会咏叹调/世俗康塔塔" {{ 'selected' if current == '音乐会咏叹调/世俗康塔塔' }}>音乐会咏叹调/世俗康塔塔</option>
</optgroup>
<optgroup label="📚 曲集"><option value="声乐套曲" {{ 'selected' if current == '声乐套曲' }}>声乐套曲</option><option value="乐谱书/曲集" {{ 'selected' if current == '乐谱书/曲集' }}>乐谱书/曲集</option></optgroup>
<optgroup label="🎻 器乐"><option value="器乐独奏" {{ 'selected' if current == '器乐独奏' }}>器乐独奏</option><option value="器乐分谱" {{ 'selected' if current == '器乐分谱' }}>器乐分谱</option><option value="室内乐" {{ 'selected' if current == '室内乐' }}>室内乐</option></optgroup>
<optgroup label="🎼 总谱"><option value="歌剧总谱" {{ 'selected' if current == '歌剧总谱' }}>歌剧总谱</option><option value="管弦乐/交响曲" {{ 'selected' if current == '管弦乐/交响曲' }}>管弦乐/交响曲</option><option value="协奏曲总谱" {{ 'selected' if current == '协奏曲总谱' }}>协奏曲总谱</option><option value="宗教声乐作品总谱" {{ 'selected' if current == '宗教声乐作品总谱' }}>宗教声乐总谱</option></optgroup>
<option value="其他" {{ 'selected' if current == '其他' }}>其他</option>
</select></div>
"""

FORM_HTML = """
<div class="row mb-3">
    <div class="col-md-6"><label class="form-label">曲名 *</label><input type="text" class="form-control" name="title" value="{{ item.title if item else '' }}" required></div>
    <div class="col-md-6"><label class="form-label">作曲家 *</label><input type="text" class="form-control" name="composer" value="{{ item.composer if item else '' }}" required></div>
</div>
<div class="row mb-3">
    <div class="col-md-4"><label class="form-label">所属作品</label><input type="text" class="form-control" name="work" value="{{ item.work if item else '' }}"></div>
    <div class="col-md-4"><label class="form-label">语言</label><input type="text" class="form-control" name="language" value="{{ item.language if item else '' }}"></div>
    <div class="col-md-4"><label class="form-label">调性</label><input type="text" class="form-control" name="tonality" value="{{ item.tonality if item else '' }}"></div>
</div>
<div class="row mb-3 p-3 bg-light rounded border mx-0">
    <div class="col-md-4"><label class="form-label small">编制 (声部/乐器)</label><input type="text" class="form-control" name="voice_types" value="{{ item.voice_types if item else '' }}" placeholder="如: SATB"></div>
    <div class="col-md-4"><label class="form-label small">数量/类型补充</label><input type="text" class="form-control" name="voice_count" value="{{ item.voice_count if item else '' }}" placeholder="如: 二重唱"></div>
    <div class="col-md-4">
        <label class="form-label small fw-bold text-primary">体裁/子分类 (Sub-Genre)</label>
        <input type="text" class="form-control" name="sub_category" value="{{ item.sub_category if item else '' }}" placeholder="如: 弥撒, 康塔塔, 受难曲">
    </div>
</div>

""" + CATEGORY_SELECT_HTML + """

<div class="mb-3">
    <label class="form-label fw-bold">📝 简介 / 包含曲目列表 (Description)</label>
    <textarea class="form-control" name="description" rows="3" placeholder="填写乐谱简介或合集曲目列表...">{{ item.description if item and item.description else '' }}</textarea>
</div>

<hr class="my-4">
<h5 class="text-primary fw-bold">📖 歌词与剧本 (Lyrics & Libretto)</h5>
<div class="alert alert-info small">提示：可以直接粘贴文本。如果要实现“左右对照”，请尽量让原文和译文的段落数保持一致。</div>
<div class="row">
    <div class="col-md-6">
        <label class="form-label fw-bold">原文 (Original Text)</label>
        <textarea class="form-control font-monospace" name="lyrics_og" rows="10" style="font-size: 0.9rem;">{{ lyrics.original if lyrics else '' }}</textarea>
    </div>
    <div class="col-md-6">
        <label class="form-label fw-bold">中文翻译 (Translation)</label>
        <textarea class="form-control font-monospace" name="lyrics_cn" rows="10" style="font-size: 0.9rem;">{{ lyrics.translation if lyrics else '' }}</textarea>
    </div>
</div>
"""

HTML_TEMPLATE = """
<!doctype html>
<html lang="zh">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>后台管理</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color:#f8f9fa; padding:20px; }
        .stat-value { font-size:1.8rem; font-weight:700; }
        .compact-table td,.compact-table th { padding:.55rem; }
        .batch-toolbar { background:#eef4ff; }
        .duplicate-group>summary { cursor:pointer; padding:1rem; font-weight:600; list-style:none; }
        .duplicate-group>summary::-webkit-details-marker { display:none; }
        .duplicate-group[open]>summary { background:#eef4ff; }
        .duplicate-comparison { background:#f4f7fb; }
        .duplicate-score-card { min-width:0; }
        .duplicate-metadata { margin-bottom:0; }
        .duplicate-metadata dt { color:#6c757d; font-weight:500; }
        .duplicate-metadata dd { margin-bottom:.35rem; overflow-wrap:anywhere; }
        .duplicate-pdf-panel { margin-top:1rem; }
        .duplicate-pdf-frame { width:100%; height:560px; border:1px solid #ced4da; border-radius:.5rem; background:white; }
        .batch-file-name { max-width:34rem; overflow-wrap:anywhere; }
        .batch-review-item { background:#fff; }
        .batch-review-item+.batch-review-item { margin-top:1rem; }
        .batch-review-heading { background:#f8f9fa; }
        .health-stat-link { display:block; padding:.6rem; border-radius:.5rem; color:inherit; text-decoration:none; }
        .health-stat-link:hover,.health-stat-link:focus-visible { background:#eef4ff; color:inherit; }
        .health-path { white-space:normal; overflow-wrap:anywhere; }
        @media (max-width:767.98px) { .duplicate-pdf-frame { height:68vh; min-height:420px; } }
    </style>
</head>
<body>
<div class="container">
    <div class="d-flex justify-content-between mb-4"><h2>🎹 后台管理</h2><form method="post" action="/logout"><input type="hidden" name="_csrf_token" value="{{ csrf_token() }}"><button class="btn btn-outline-danger btn-sm">退出</button></form></div>
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% for category, message in messages %}
            {% set alert_type = 'danger' if category in ('error', 'danger') else ('warning' if category == 'warning' else 'success') %}
            <div class="alert alert-{{ alert_type }}" role="alert">{{ message }}</div>
        {% endfor %}
    {% endwith %}
    <ul class="nav nav-tabs mb-4 flex-wrap">
        <li class="nav-item"><a class="nav-link {{ 'active' if active_tab == 'dashboard' else '' }}" href="/dashboard">📊 仪表盘</a></li>
        <li class="nav-item"><a class="nav-link {{ 'active' if active_tab == 'health' else '' }}" href="/catalog-health">🩺 资料健康</a></li>
        <li class="nav-item"><a class="nav-link {{ 'active' if active_tab == 'upload' else '' }}" href="/">📤 上传</a></li>
        <li class="nav-item"><a class="nav-link {{ 'active' if active_tab == 'batch_upload' else '' }}" href="/batch-upload">📚 批量上传</a></li>
        <li class="nav-item"><a class="nav-link {{ 'active' if active_tab == 'brahms_review' else '' }}" href="/import-review/brahms">🧾 勃拉姆斯预审</a></li>
        <li class="nav-item"><a class="nav-link {{ 'active' if active_tab == 'manage' else '' }}" href="/manage">📋 管理</a></li>
        <li class="nav-item"><a class="nav-link {{ 'active' if active_tab == 'duplicates' else '' }}" href="/duplicates">🔎 重复检查</a></li>
        <li class="nav-item"><a class="nav-link" href="/submissions">🛡️ 投稿审核 {% set queue_count = pending_count|default(0, true) %}{% if queue_count %}<span class="badge bg-danger">{{ queue_count }}</span>{% endif %}</a></li>
        <li class="nav-item"><a class="nav-link {{ 'active' if active_tab == 'trash' else '' }}" href="/trash">♻️ 回收站 {% set recycle_count = deleted_count|default(0, true) %}{% if recycle_count %}<span class="badge bg-secondary">{{ recycle_count }}</span>{% endif %}</a></li>
        <li class="nav-item ms-auto"><a class="nav-link" href="/submit" target="_blank">查看投稿页 ↗</a></li>
    </ul>

    {% if storage_auto_sync is defined %}
    <div class="alert {{ 'alert-success' if storage_auto_sync else 'alert-warning' }} py-2" role="status">
        {% if storage_auto_sync %}
        ☁️ R2 自动同步已启用：新 PDF 只有在上传并校验成功后才会写入公开目录。
        {% else %}
        ⚠️ R2 自动同步未启用：新 PDF 目前只会保存在本地，请勿在同步前发布线上目录。
        {% endif %}
    </div>
    {% endif %}

    {% if active_tab == 'dashboard' %}
    <div class="row g-3 mb-4">
        <div class="col-6 col-lg-3"><div class="card h-100 shadow-sm"><div class="card-body"><div class="text-muted small">公开乐谱</div><div class="stat-value">{{ stats.total_items }}</div><div class="small text-muted">PDF {{ stats.actual_files }} 份 · {{ stats.storage_size }}</div></div></div></div>
        <div class="col-6 col-lg-3"><div class="card h-100 shadow-sm"><div class="card-body"><div class="text-muted small">待办</div><div class="stat-value">{{ stats.pending_count }}</div><div class="small text-muted">待审核投稿</div></div></div></div>
        <div class="col-6 col-lg-3"><a class="text-decoration-none text-reset" href="/duplicates"><div class="card h-100 shadow-sm"><div class="card-body"><div class="text-muted small">疑似重复组</div><div class="stat-value">{{ stats.duplicate_groups }}</div><div class="small text-primary">打开检查 →</div></div></div></a></div>
        <div class="col-6 col-lg-3"><a class="text-decoration-none text-reset" href="/trash"><div class="card h-100 shadow-sm"><div class="card-body"><div class="text-muted small">回收站</div><div class="stat-value">{{ stats.deleted_count }}</div><div class="small text-primary">查看可恢复项 →</div></div></div></a></div>
    </div>
    <div class="row g-3">
        <div class="col-lg-7">
            <div class="card shadow-sm mb-3">
                <div class="card-header bg-white d-flex justify-content-between"><strong>资料健康</strong><a class="badge text-decoration-none {{ 'bg-success' if stats.healthy else 'bg-danger' }}" href="{{ url_for('catalog_health') }}">{{ '正常' if stats.healthy else '需处理' }}</a></div>
                <div class="card-body"><div class="row text-center g-3">
                    <div class="col-4"><a class="health-stat-link" href="{{ url_for('catalog_health', issue='pdf') }}"><div class="fw-bold fs-4">{{ stats.missing_files + stats.invalid_paths }}</div><small class="text-muted">缺失/非法 PDF</small><div class="small text-primary mt-1">查看明细</div></a></div>
                    <div class="col-4"><a class="health-stat-link" href="{{ url_for('catalog_health', issue='orphan') }}"><div class="fw-bold fs-4">{{ stats.orphan_files }}</div><small class="text-muted">未引用文件</small><div class="small text-primary mt-1">查看明细</div></a></div>
                    <div class="col-4"><div class="fw-bold fs-4">{{ stats.lyrics_files }}</div><small class="text-muted">歌词文件</small></div>
                    <div class="col-6"><a class="health-stat-link" href="{{ url_for('catalog_health', issue='missing_work') }}"><div class="fw-bold fs-4">{{ stats.missing_work }}</div><small class="text-muted">未填所属作品</small><div class="small text-primary mt-1">查看明细</div></a></div>
                    <div class="col-6"><a class="health-stat-link" href="{{ url_for('catalog_health', issue='missing_description') }}"><div class="fw-bold fs-4">{{ stats.missing_description }}</div><small class="text-muted">未填简介</small><div class="small text-primary mt-1">查看明细</div></a></div>
                </div></div>
            </div>
            <div class="card shadow-sm"><div class="card-header bg-white"><strong>分类分布</strong></div><div class="table-responsive"><table class="table compact-table mb-0"><tbody>{% for category in stats.category_counts %}<tr><td>{{ category.name }}</td><td class="text-end fw-bold">{{ category.count }}</td></tr>{% endfor %}</tbody></table></div></div>
        </div>
        <div class="col-lg-5">
            <div class="card shadow-sm mb-3"><div class="card-header bg-white"><strong>备份状态</strong></div><div class="card-body"><div>自动备份：<strong>{{ stats.automatic_backups }}</strong> 份</div><div class="small text-muted text-break mt-1">最新：{{ stats.latest_backup }}</div></div></div>
            <div class="card shadow-sm"><div class="card-header bg-white"><strong>最近操作</strong></div><ul class="list-group list-group-flush">{% for log in stats.recent_logs %}<li class="list-group-item"><div>{{ log.msg }}</div><small class="text-muted">{{ log.date }}</small></li>{% else %}<li class="list-group-item text-muted">暂无记录</li>{% endfor %}</ul></div>
        </div>
    </div>
    {% endif %}

    {% if active_tab == 'health' %}
    <div class="card shadow">
        <div class="card-header bg-white d-flex flex-wrap justify-content-between align-items-center gap-2">
            <div><strong>资料健康明细</strong><div class="small text-muted mt-1">这里只显示目录相对路径，不会自动移动或删除文件。</div></div>
            <span class="badge {{ 'bg-success' if health.healthy else 'bg-danger' }}">{{ 'PDF 目录正常' if health.healthy else 'PDF 目录需处理' }}</span>
        </div>
        <div class="card-body border-bottom">
            <div class="nav nav-pills gap-2 flex-wrap" aria-label="资料问题类型">
                <a class="nav-link {{ 'active' if health_issue == 'pdf' }}" href="{{ url_for('catalog_health', issue='pdf') }}">缺失/非法 PDF <span class="badge bg-light text-dark ms-1">{{ health.file_issues|length }}</span></a>
                <a class="nav-link {{ 'active' if health_issue == 'orphan' }}" href="{{ url_for('catalog_health', issue='orphan') }}">未引用文件 <span class="badge bg-light text-dark ms-1">{{ health.orphan_files|length }}</span></a>
                <a class="nav-link {{ 'active' if health_issue == 'missing_work' }}" href="{{ url_for('catalog_health', issue='missing_work') }}">未填所属作品 <span class="badge bg-light text-dark ms-1">{{ health.missing_work }}</span></a>
                <a class="nav-link {{ 'active' if health_issue == 'missing_description' }}" href="{{ url_for('catalog_health', issue='missing_description') }}">未填简介 <span class="badge bg-light text-dark ms-1">{{ health.missing_description }}</span></a>
            </div>
        </div>

        {% if health_issue == 'pdf' %}
        <div class="table-responsive"><table class="table table-hover align-middle mb-0">
            <thead class="table-light"><tr><th>问题</th><th>乐谱资料</th><th>记录路径</th><th>操作</th></tr></thead>
            <tbody>{% for problem in health_items %}
                <tr>
                    <td><span class="badge bg-danger">{{ problem.reason }}</span></td>
                    <td><strong>{{ problem.item.title }}</strong><div class="small text-muted">ID {{ problem.item.id }} · {{ problem.item.composer or '未填作曲家' }}</div></td>
                    <td><code class="health-path">scores/{{ problem.filename }}</code>{% if problem.possible_matches %}<div class="small text-warning-emphasis mt-2">发现同名的未引用文件，可能放错目录：</div>{% for match in problem.possible_matches %}<code class="health-path d-block">scores/{{ match }}</code>{% endfor %}{% endif %}</td>
                    <td><a class="btn btn-sm btn-outline-primary" href="{{ url_for('edit', item_id=problem.item.id) }}">编辑资料</a></td>
                </tr>
            {% else %}<tr><td colspan="4" class="text-center p-5 text-muted">没有缺失或非法的 PDF 记录。</td></tr>{% endfor %}</tbody>
        </table></div>
        {% elif health_issue == 'orphan' %}
        <div class="alert alert-warning rounded-0 border-start-0 border-end-0 mb-0">未引用文件可能只是放错目录，请先与“缺失/非法 PDF”中的同名提示核对，不要直接删除。</div>
        <div class="table-responsive"><table class="table table-hover align-middle mb-0">
            <thead class="table-light"><tr><th>实际文件路径</th><th>大小</th></tr></thead>
            <tbody>{% for orphan in health_items %}<tr><td><code class="health-path">scores/{{ orphan.filename }}</code></td><td>{{ orphan.size }}</td></tr>{% else %}<tr><td colspan="2" class="text-center p-5 text-muted">没有未引用的文件。</td></tr>{% endfor %}</tbody>
        </table></div>
        {% else %}
        <div class="table-responsive"><table class="table table-hover align-middle mb-0">
            <thead class="table-light"><tr><th>曲名</th><th>作曲家</th><th>分类</th><th>缺少内容</th><th>操作</th></tr></thead>
            <tbody>{% for item in health_items %}<tr><td><strong>{{ item.title }}</strong><div class="small text-muted">ID {{ item.id }}</div></td><td>{{ item.composer or '—' }}</td><td>{{ item.category or '—' }}</td><td><span class="badge bg-warning text-dark">{{ health_issue_label }}</span></td><td><a class="btn btn-sm btn-outline-primary" href="{{ url_for('edit', item_id=item.id) }}">补充资料</a></td></tr>{% else %}<tr><td colspan="5" class="text-center p-5 text-muted">没有此类资料问题。</td></tr>{% endfor %}</tbody>
        </table></div>
        {% endif %}

        <div class="card-footer bg-white d-flex flex-wrap justify-content-between align-items-center gap-2">
            <span class="small text-muted">共 {{ health_total_items }} 条 · 第 {{ page }} / {{ total_pages }} 页</span>
            <div class="d-flex align-items-center gap-3">
                <span class="small">每页：<a class="{{ 'fw-bold' if per_page == 50 }}" href="{{ url_for('catalog_health', issue=health_issue, per_page=50, page=1) }}">50</a> · <a class="{{ 'fw-bold' if per_page == 100 }}" href="{{ url_for('catalog_health', issue=health_issue, per_page=100, page=1) }}">100</a></span>
                {% if total_pages > 1 %}<nav aria-label="健康问题分页"><ul class="pagination pagination-sm mb-0"><li class="page-item {{ 'disabled' if page == 1 }}"><a class="page-link" href="{{ url_for('catalog_health', issue=health_issue, per_page=per_page, page=page-1) }}">上一页</a></li><li class="page-item disabled"><span class="page-link">{{ page }}/{{ total_pages }}</span></li><li class="page-item {{ 'disabled' if page == total_pages }}"><a class="page-link" href="{{ url_for('catalog_health', issue=health_issue, per_page=per_page, page=page+1) }}">下一页</a></li></ul></nav>{% endif %}
            </div>
        </div>
    </div>
    {% endif %}

    {% if active_tab == 'duplicates' %}
    <div class="card shadow">
        <div class="card-header bg-white"><strong>疑似重复乐谱</strong><div class="small text-muted mt-1">按规范化后的“曲名 + 作曲家”分组。可以同时展开多份 PDF 对照；删除会移入回收站，可随时恢复。</div></div>
        <div id="duplicate-groups">
        {% for group in duplicate_groups %}
            <details class="duplicate-group border-bottom" {{ 'open' if loop.first }}>
                <summary>{{ group[0].title }} · {{ group[0].composer }} <span class="badge bg-secondary ms-2">{{ group|length }}</span></summary>
                <div class="duplicate-comparison p-3">
                    <div class="row g-3">
                    {% for item in group %}
                        <div class="col-12 col-xl-6">
                            <article class="card duplicate-score-card h-100 border-0 shadow-sm">
                                <div class="card-body">
                                    <div class="d-flex justify-content-between align-items-start gap-2 mb-3">
                                        <div><span class="badge bg-light text-dark border me-1">ID {{ item.id }}</span><strong>{{ item.title }}</strong></div>
                                        <span class="badge bg-light text-dark border">{{ item.category }}</span>
                                    </div>
                                    <dl class="row duplicate-metadata small">
                                        <dt class="col-4">作曲家</dt><dd class="col-8">{{ item.composer or '—' }}</dd>
                                        <dt class="col-4">所属作品</dt><dd class="col-8">{{ item.work or '—' }}</dd>
                                        <dt class="col-4">调性</dt><dd class="col-8">{{ item.tonality or '—' }}</dd>
                                        <dt class="col-4">语言</dt><dd class="col-8">{{ item.language or '—' }}</dd>
                                    </dl>
                                    <div class="d-flex flex-wrap gap-2 mt-3">
                                        <button class="btn btn-sm btn-primary duplicate-preview-toggle" type="button" data-preview-target="duplicate-pdf-{{ item.id }}" aria-controls="duplicate-pdf-{{ item.id }}" aria-expanded="false">预览 PDF</button>
                                        <a class="btn btn-sm btn-outline-primary" href="{{ url_for('catalog_score_file', item_id=item.id) }}" target="_blank" rel="noopener">新窗口打开</a>
                                        <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('edit', item_id=item.id) }}">编辑资料</a>
                                        <form method="post" action="{{ url_for('delete', item_id=item.id) }}" class="d-inline-flex m-0" onsubmit="return confirm('确定将这条乐谱移入回收站吗？删除后可在回收站恢复。')">
                                            <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
                                            <input type="hidden" name="next" value="{{ url_for('duplicates') }}">
                                            <button class="btn btn-sm btn-outline-danger" type="submit">删除</button>
                                        </form>
                                    </div>
                                    <div class="duplicate-pdf-panel" id="duplicate-pdf-{{ item.id }}" hidden>
                                        <iframe class="duplicate-pdf-frame" title="{{ item.title }} PDF 预览" data-src="{{ url_for('catalog_score_file', item_id=item.id) }}" loading="lazy"></iframe>
                                        <div class="small text-muted mt-2">如果浏览器无法内嵌显示，请使用“新窗口打开”。</div>
                                    </div>
                                </div>
                            </article>
                        </div>
                    {% endfor %}
                    </div>
                </div>
            </details>
        {% else %}<div class="p-5 text-center text-muted">未发现同曲名且同作曲家的记录。</div>{% endfor %}
        </div>
    </div>
    <script>
    (() => {
        document.querySelectorAll('.duplicate-preview-toggle').forEach((button) => {
            button.addEventListener('click', () => {
                const panel = document.getElementById(button.dataset.previewTarget);
                if (!panel) return;
                const shouldOpen = panel.hidden;
                panel.hidden = !shouldOpen;
                button.setAttribute('aria-expanded', String(shouldOpen));
                button.textContent = shouldOpen ? '收起 PDF' : '预览 PDF';
                if (shouldOpen) {
                    const frame = panel.querySelector('iframe[data-src]');
                    if (frame && !frame.getAttribute('src')) frame.setAttribute('src', frame.dataset.src);
                }
            });
        });
    })();
    </script>
    {% endif %}

    {% if active_tab == 'upload' %}
    <div class="card shadow"><div class="card-body">
        <form method="post" enctype="multipart/form-data">
            <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
            <input type="hidden" name="action" value="upload">
            """ + FORM_HTML + """
            <div class="mb-4 mt-3"><label class="form-label">文件 (PDF) *</label><input type="file" class="form-control" name="file" accept="application/pdf,.pdf" required></div>
            <button type="submit" class="btn btn-success w-100">保存并发布</button>
        </form>
    </div></div>
    {% endif %}

    {% if active_tab == 'batch_upload' %}
    <div class="card shadow">
        <div class="card-header bg-white">
            <strong>批量上传乐谱</strong>
            <div class="small text-muted mt-1">先填写批量默认资料，再逐份确认曲名、作曲家、所属作品、调性和编制。任意一份校验或保存失败时，整批都不会发布。</div>
        </div>
        <div class="card-body">
            <form id="batch-upload-form" method="post" enctype="multipart/form-data" action="{{ url_for('batch_upload') }}">
                <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
                <fieldset class="mb-4">
                    <legend class="h5 mb-1">1. 填写批量默认资料</legend>
                    <div class="small text-muted mb-3">同一批大多相同的内容只需填一次；选择 PDF 后，仍可在每份乐谱中单独覆盖。</div>
                    <div class="row g-3">
                        <div class="col-md-6">
                            <label class="form-label" for="batch-composer">作曲家（默认值）</label>
                            <input class="form-control" id="batch-composer" name="composer" maxlength="200" value="{{ form.get('composer', '') if form else '' }}" placeholder="同一位作曲家时填写">
                        </div>
                        <div class="col-md-6">
                            <label class="form-label" for="batch-category">分类 *</label>
                            <select class="form-select" id="batch-category" name="category" required>
                                <option value="">请选择分类</option>
                                {% for category in categories %}<option value="{{ category }}" {{ 'selected' if form and form.get('category') == category }}>{{ category }}</option>{% endfor %}
                            </select>
                        </div>
                        <div class="col-md-6">
                            <label class="form-label" for="batch-work">所属作品（默认值）</label>
                            <input class="form-control" id="batch-work" name="work" maxlength="200" value="{{ form.get('work', '') if form else '' }}">
                        </div>
                        <div class="col-md-6">
                            <label class="form-label" for="batch-language">语言</label>
                            <input class="form-control" id="batch-language" name="language" maxlength="100" list="batch-language-options" value="{{ form.get('language', '') if form else '' }}">
                            <datalist id="batch-language-options">{% for language in languages %}<option value="{{ language }}">{% endfor %}</datalist>
                        </div>
                    </div>
                    <details class="mt-3">
                        <summary class="text-primary">填写更多默认资料（可选）</summary>
                        <div class="row g-3 mt-1">
                            <div class="col-md-4"><label class="form-label" for="batch-sub-category">体裁/子分类</label><input class="form-control" id="batch-sub-category" name="sub_category" maxlength="120" value="{{ form.get('sub_category', '') if form else '' }}"></div>
                            <div class="col-md-4"><label class="form-label" for="batch-voice-types">编制（默认值）</label><input class="form-control" id="batch-voice-types" name="voice_types" maxlength="150" value="{{ form.get('voice_types', '') if form else '' }}"></div>
                            <div class="col-md-4"><label class="form-label" for="batch-voice-count">数量/类型补充</label><input class="form-control" id="batch-voice-count" name="voice_count" maxlength="100" value="{{ form.get('voice_count', '') if form else '' }}"></div>
                            <div class="col-md-4"><label class="form-label" for="batch-tonality">调性（默认值）</label><input class="form-control" id="batch-tonality" name="tonality" maxlength="80" value="{{ form.get('tonality', '') if form else '' }}"></div>
                            <div class="col-md-8"><label class="form-label" for="batch-description">简介</label><textarea class="form-control" id="batch-description" name="description" maxlength="2000" rows="2">{{ form.get('description', '') if form else '' }}</textarea></div>
                        </div>
                    </details>
                </fieldset>

                <fieldset class="mb-4">
                    <legend class="h5 mb-3">2. 选择 PDF</legend>
                    <input class="form-control" id="batch-files" type="file" name="files" accept="application/pdf,.pdf" multiple required aria-describedby="batch-files-help batch-file-summary">
                    <div class="form-text" id="batch-files-help">每批最多 {{ batch_max_files }} 份，总大小不超过 {{ batch_max_mb }} MB。批量页不填写歌词，发布后仍可单独编辑补充。</div>
                    <div class="small fw-semibold mt-2" id="batch-file-summary" role="status" aria-live="polite">尚未选择文件</div>
                    <div class="alert alert-danger mt-3 mb-0" id="batch-client-error" role="alert" tabindex="-1" hidden></div>
                </fieldset>

                <fieldset class="mb-4" id="batch-review" hidden>
                    <div class="d-flex flex-wrap justify-content-between align-items-start gap-2 mb-3">
                        <div>
                            <legend class="h5 mb-1">3. 逐份确认资料</legend>
                            <div class="small text-muted">每份乐谱都可以使用不同资料；作曲家为必填项。</div>
                        </div>
                        <button class="btn btn-outline-primary btn-sm" id="batch-apply-defaults" type="button">将默认资料应用到全部</button>
                    </div>
                    <div id="batch-file-list"></div>
                </fieldset>

                <button class="btn btn-success w-100" id="batch-submit" type="submit" disabled>选择 PDF 后发布</button>
            </form>
        </div>
    </div>
    <script>
    (() => {
        const form = document.getElementById('batch-upload-form');
        const input = document.getElementById('batch-files');
        const review = document.getElementById('batch-review');
        const list = document.getElementById('batch-file-list');
        const summary = document.getElementById('batch-file-summary');
        const errorBox = document.getElementById('batch-client-error');
        const submit = document.getElementById('batch-submit');
        const applyDefaults = document.getElementById('batch-apply-defaults');
        const maxFiles = {{ batch_max_files }};
        const maxBytes = {{ batch_max_bytes }};
        const formatSize = (bytes) => bytes < 1024 * 1024
            ? `${(bytes / 1024).toFixed(1)} KB`
            : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
        const defaultTitle = (name) => (name.replace(/\\.pdf$/i, '').replace(/[_\\s]+/g, ' ').replace(/^[.\\s_-]+|[.\\s_-]+$/g, '') || '未命名乐谱').slice(0, 200);
        const defaultFields = () => ({
            item_composers: document.getElementById('batch-composer').value,
            item_works: document.getElementById('batch-work').value,
            item_tonalities: document.getElementById('batch-tonality').value,
            item_voice_types: document.getElementById('batch-voice-types').value,
        });
        const appendField = (container, fileName, labelText, name, value, maxLength, required = false, columnClass = 'col-md-6') => {
            const wrapper = document.createElement('div');
            wrapper.className = columnClass;
            const label = document.createElement('label');
            label.className = 'form-label small mb-1';
            label.textContent = labelText;
            const field = document.createElement('input');
            field.className = 'form-control form-control-sm';
            field.name = name;
            field.value = value;
            field.maxLength = maxLength;
            field.required = required;
            field.setAttribute('aria-label', `${fileName} 的${labelText.replace(' *', '')}`);
            wrapper.append(label, field);
            container.append(wrapper);
            return field;
        };

        input.addEventListener('change', () => {
            const files = Array.from(input.files || []);
            const totalBytes = files.reduce((total, file) => total + file.size, 0);
            const invalidFile = files.find((file) => !file.name.toLowerCase().endsWith('.pdf'));
            let error = '';
            if (files.length > maxFiles) error = `一次最多选择 ${maxFiles} 份 PDF。`;
            else if (totalBytes > maxBytes) error = `本批文件共 ${formatSize(totalBytes)}，超过总大小限制。`;
            else if (invalidFile) error = `${invalidFile.name} 不是 PDF 文件。`;

            list.replaceChildren();
            const defaults = defaultFields();
            files.forEach((file, index) => {
                const item = document.createElement('section');
                item.className = 'batch-review-item border rounded overflow-hidden';
                item.dataset.batchItem = '1';
                const heading = document.createElement('div');
                heading.className = 'batch-review-heading d-flex flex-wrap justify-content-between align-items-center gap-2 px-3 py-2 border-bottom';
                const fileInfo = document.createElement('div');
                const fileName = document.createElement('div');
                fileName.className = 'batch-file-name fw-semibold';
                fileName.textContent = `${index + 1}. ${file.name}`;
                const fileSize = document.createElement('small');
                fileSize.className = 'text-muted';
                fileSize.textContent = formatSize(file.size);
                fileInfo.append(fileName, fileSize);
                heading.append(fileInfo);
                if (index > 0) {
                    const copyPrevious = document.createElement('button');
                    copyPrevious.className = 'btn btn-outline-secondary btn-sm';
                    copyPrevious.type = 'button';
                    copyPrevious.textContent = '复制上一份资料';
                    copyPrevious.addEventListener('click', () => {
                        const previous = list.querySelectorAll('[data-batch-item]')[index - 1];
                        ['item_composers', 'item_works', 'item_tonalities', 'item_voice_types'].forEach((name) => {
                            item.querySelector(`[name="${name}"]`).value = previous.querySelector(`[name="${name}"]`).value;
                        });
                    });
                    heading.append(copyPrevious);
                }
                const fields = document.createElement('div');
                fields.className = 'row g-3 p-3 pt-2';
                appendField(fields, file.name, '网站曲名 *', 'titles', defaultTitle(file.name), 200, true, 'col-lg-6');
                appendField(fields, file.name, '作曲家 *', 'item_composers', defaults.item_composers, 200, true, 'col-lg-6');
                appendField(fields, file.name, '所属作品', 'item_works', defaults.item_works, 200, false, 'col-lg-5');
                appendField(fields, file.name, '调性', 'item_tonalities', defaults.item_tonalities, 80, false, 'col-lg-3 col-md-6');
                appendField(fields, file.name, '编制（声部/乐器）', 'item_voice_types', defaults.item_voice_types, 150, false, 'col-lg-4 col-md-6');
                item.append(heading, fields);
                list.append(item);
            });

            review.hidden = files.length === 0;
            summary.textContent = files.length
                ? `已选择 ${files.length} 份，共 ${formatSize(totalBytes)}。请检查下方逐份资料。`
                : '尚未选择文件';
            errorBox.textContent = error;
            errorBox.hidden = !error;
            submit.disabled = files.length === 0 || Boolean(error);
            submit.textContent = files.length && !error ? `一次发布 ${files.length} 份乐谱` : '选择 PDF 后发布';
            if (error) errorBox.focus();
        });

        applyDefaults.addEventListener('click', () => {
            const defaults = defaultFields();
            list.querySelectorAll('[data-batch-item]').forEach((item) => {
                Object.entries(defaults).forEach(([name, value]) => {
                    item.querySelector(`[name="${name}"]`).value = value;
                });
            });
        });

        form.addEventListener('submit', () => {
            const count = input.files ? input.files.length : 0;
            submit.disabled = true;
            submit.textContent = `正在上传 ${count} 份，请稍候…`;
        });
    })();
    </script>
    {% endif %}

{% if active_tab == 'manage' %}
    <div class="card shadow">
        <div class="card-header bg-white p-3">
            <form class="row g-2 align-items-center" action="/manage">
                <input type="hidden" name="per_page" value="{{ per_page }}">
                <div class="col-md-3">
                    <input class="form-control" type="search" name="keyword" value="{{ keyword }}" placeholder="🔍 搜曲名/作品号/简介...">
                </div>
                
                <div class="col-md-3">
                    <input class="form-control" type="search" name="composer" value="{{ composer_filter }}" placeholder="👤 搜作曲家...">
                </div>
                
                <div class="col-md-3">
                    <select class="form-select" name="category">
                        <option value="all">📂 所有分类</option>
                        <option value="歌剧咏叹调" {{ 'selected' if category_filter == '歌剧咏叹调' }}>歌剧咏叹调</option>
                        <option value="歌剧重唱" {{ 'selected' if category_filter == '歌剧重唱' }}>歌剧重唱</option>
                        <option value="宗教声乐作品" {{ 'selected' if category_filter == '宗教声乐作品' }}>宗教声乐作品</option>
                        <option value="艺术歌曲" {{ 'selected' if category_filter == '艺术歌曲' }}>艺术歌曲</option>
                        <option value="音乐剧选段" {{ 'selected' if category_filter == '音乐剧选段' }}>音乐剧选段</option>
                        <option value="合唱作品" {{ 'selected' if category_filter == '合唱作品' }}>合唱作品</option>
                        <option value="声乐套曲" {{ 'selected' if category_filter == '声乐套曲' }}>声乐套曲</option>
                        <option value="乐谱书/曲集" {{ 'selected' if category_filter == '乐谱书/曲集' }}>乐谱书/曲集</option>
                        <option value="器乐独奏" {{ 'selected' if category_filter == '器乐独奏' }}>器乐独奏</option>
                        <option value="器乐分谱" {{ 'selected' if category_filter == '器乐分谱' }}>器乐分谱</option>
                        <option value="室内乐" {{ 'selected' if category_filter == '室内乐' }}>室内乐</option>
                        <option value="歌剧总谱" {{ 'selected' if category_filter == '歌剧总谱' }}>歌剧总谱</option>
                        <option value="管弦乐/交响曲" {{ 'selected' if category_filter == '管弦乐/交响曲' }}>管弦乐/交响曲</option>
                        <option value="协奏曲总谱" {{ 'selected' if category_filter == '协奏曲总谱' }}>协奏曲总谱</option>
                        <option value="宗教声乐作品总谱" {{ 'selected' if category_filter == '宗教声乐作品总谱' }}>宗教声乐作品总谱</option>
                        <option value="音乐会咏叹调/世俗康塔塔" {{ 'selected' if category_filter == '音乐会咏叹调/世俗康塔塔' }}>音乐会咏叹调/世俗康塔塔</option>
                        <option value="其他" {{ 'selected' if category_filter == '其他' }}>其他</option>
                    </select>
                </div>
                
                <div class="col-md-3 d-flex gap-2">
                    <button class="btn btn-primary w-100">筛选</button>
                    <a href="/manage" class="btn btn-outline-secondary w-50 text-center text-decoration-none" style="line-height: 2.3;">重置</a>
                </div>
            </form>
        </div>
        <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 border-bottom bg-light px-3 py-2 small text-muted">
            <span>共 {{ total_items }} 条 · 第 {{ page }} / {{ total_pages }} 页</span>
            <span>每页：
                <a class="{{ 'fw-bold' if per_page == 50 }}" href="{{ url_for('manage', keyword=keyword, composer=composer_filter, category=category_filter, per_page=50, page=1) }}">50</a>
                · <a class="{{ 'fw-bold' if per_page == 100 }}" href="{{ url_for('manage', keyword=keyword, composer=composer_filter, category=category_filter, per_page=100, page=1) }}">100</a>
            </span>
        </div>
        <form id="batch-form" method="post" action="/batch-update" class="batch-toolbar border-bottom p-3">
            <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
            <input type="hidden" name="next" value="{{ request.full_path }}">
            <div class="d-flex flex-wrap align-items-center gap-2">
                <strong class="me-2">已选 <span id="selected-count">0</span> 条</strong>
                <select class="form-select form-select-sm" style="width:auto" name="target_category" aria-label="批量目标分类"><option value="">选择目标分类</option>{% for category in categories %}<option value="{{ category }}">{{ category }}</option>{% endfor %}</select>
                <button class="btn btn-sm btn-outline-primary" name="batch_action" value="set_category" type="submit">修改分类</button>
                <select class="form-select form-select-sm ms-md-3" style="width:auto" name="target_language" aria-label="批量目标语言"><option value="">选择目标语言</option>{% for language in languages %}<option value="{{ language }}">{{ language }}</option>{% endfor %}</select>
                <button class="btn btn-sm btn-outline-primary" name="batch_action" value="set_language" type="submit">修改语言</button>
            </div>
        </form>
        
        <div class="table-responsive">
            <table class="table table-striped table-hover mb-0 align-middle">
                <thead class="table-light">
                    <tr>
                        <th style="width:42px"><input class="form-check-input" id="select-page" type="checkbox" aria-label="选择本页全部乐谱"></th>
                        <th>曲名</th>
                        <th>作曲家</th>
                        <th>分类/体裁</th>
                        <th>R2</th>
                        <th>操作</th>
                    </tr>
                </thead>
                <tbody>
                    {% for item in items %}
                    <tr>
                        <td><input class="form-check-input item-selector" type="checkbox" name="item_ids" value="{{ item.id }}" form="batch-form" aria-label="选择 {{ item.title }}"></td>
                        <td class="fw-bold">
                            {{ item.title }} 
                            {% if item.has_lyrics %}<span class="badge bg-info text-dark" style="font-size:0.6rem">词</span>{% endif %}
                            <br><small class="text-muted fw-normal">{{ item.work }}</small>
                        </td>
                        <td>{{ item.composer }}</td>
                        <td>
                            <span class="badge bg-light text-dark border">{{ item.category }}</span>
                            {% if item.sub_category %}
                                <br><span class="badge bg-secondary" style="font-size:0.6rem; opacity:0.8">{{ item.sub_category }}</span>
                            {% endif %}
                        </td>
                        <td>
                            <span class="badge bg-{{ item.storage_status.class }}">{{ item.storage_status.label }}</span>
                        </td>
                        <td>
                            <a href="/edit/{{ item.id }}" class="btn btn-sm btn-outline-primary">✏️</a> 
                            <form method="post" action="{{ url_for('sync_score_storage', item_id=item.id) }}" class="d-inline"><input type="hidden" name="_csrf_token" value="{{ csrf_token() }}"><input type="hidden" name="next" value="{{ request.full_path }}"><button class="btn btn-sm btn-outline-success" type="submit" aria-label="校验或重新同步 {{ item.title }} 到 R2">☁️</button></form>
                            <form method="post" action="/delete/{{ item.id }}" class="d-inline" onsubmit="return confirm('确定将这条乐谱移入回收站吗？之后可以恢复。')"><input type="hidden" name="_csrf_token" value="{{ csrf_token() }}"><input type="hidden" name="next" value="{{ request.full_path }}"><button class="btn btn-sm btn-outline-danger" type="submit" aria-label="删除 {{ item.title }}">🗑️</button></form>
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="6" class="text-center p-5 text-muted">没有找到符合条件的乐谱<br><small>请尝试调整筛选条件</small></td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% if total_pages > 1 %}
        <div class="card-footer bg-white">
            <nav aria-label="乐谱分页"><ul class="pagination justify-content-center mb-0 flex-wrap">
                <li class="page-item {{ 'disabled' if page == 1 }}"><a class="page-link" href="{{ url_for('manage', keyword=keyword, composer=composer_filter, category=category_filter, per_page=per_page, page=page-1) }}">上一页</a></li>
                {% for page_number in page_numbers %}
                <li class="page-item {{ 'active' if page_number == page }}"><a class="page-link" href="{{ url_for('manage', keyword=keyword, composer=composer_filter, category=category_filter, per_page=per_page, page=page_number) }}">{{ page_number }}</a></li>
                {% endfor %}
                <li class="page-item {{ 'disabled' if page == total_pages }}"><a class="page-link" href="{{ url_for('manage', keyword=keyword, composer=composer_filter, category=category_filter, per_page=per_page, page=page+1) }}">下一页</a></li>
            </ul></nav>
        </div>
        {% endif %}
    </div>
    <script>
    (() => {
        const toggle = document.getElementById('select-page');
        const items = Array.from(document.querySelectorAll('.item-selector'));
        const count = document.getElementById('selected-count');
        const refresh = () => { count.textContent = items.filter(item => item.checked).length; };
        if (toggle) toggle.addEventListener('change', () => { items.forEach(item => { item.checked = toggle.checked; }); refresh(); });
        items.forEach(item => item.addEventListener('change', refresh));
    })();
    </script>
    {% endif %}

    {% if active_tab == 'trash' %}
    <div class="card shadow">
        <div class="card-header bg-white"><strong>回收站</strong><div class="small text-muted mt-1">删除的乐谱及歌词会保留在这里，可恢复到原分类。</div></div>
        <div class="table-responsive"><table class="table table-hover align-middle mb-0">
            <thead class="table-light"><tr><th>删除时间</th><th>曲名</th><th>作曲家</th><th>原分类</th><th>操作</th></tr></thead>
            <tbody>
            {% for entry in deleted_entries %}
            <tr>
                <td><small>{{ entry.deleted_at[:19].replace('T', ' ') }}</small></td>
                <td class="fw-bold">{{ entry.item.title }}</td>
                <td>{{ entry.item.composer }}</td>
                <td><span class="badge bg-light text-dark border">{{ entry.item.category }}</span></td>
                <td><form method="post" action="{{ url_for('restore_deleted', entry_name=entry.name) }}" onsubmit="return confirm('确认恢复这条乐谱吗？')"><input type="hidden" name="_csrf_token" value="{{ csrf_token() }}"><button class="btn btn-sm btn-outline-success">恢复</button></form></td>
            </tr>
            {% else %}
            <tr><td colspan="5" class="text-center p-5 text-muted">回收站为空</td></tr>
            {% endfor %}
            </tbody>
        </table></div>
    </div>
    {% endif %}

    {% if active_tab == 'edit' %}
    <div class="card shadow"><div class="card-header bg-warning"><h5>✏️ 编辑</h5></div><div class="card-body">
        <form method="post">
            <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
            <input type="hidden" name="action" value="update">
            """ + FORM_HTML + """
            <div class="d-flex justify-content-between mt-4"><a href="/manage" class="btn btn-secondary">取消</a><button type="submit" class="btn btn-primary">保存修改</button></div>
        </form>
    </div></div>
    {% endif %}
</div></body></html>
"""


BRAHMS_REVIEW_TEMPLATE = """
<!doctype html>
<html lang="zh">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>勃拉姆斯导入预审</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background:#f8f9fa; }
        .review-card { scroll-margin-top:1rem; }
        .review-source { overflow-wrap:anywhere; }
        .review-warning { white-space:normal; text-align:left; }
        .review-title { min-width:0; }
        .review-meta dt { color:#6c757d; font-weight:500; }
        .review-meta dd { overflow-wrap:anywhere; }
    </style>
</head>
<body>
<main class="container py-4">
    <div class="d-flex flex-wrap justify-content-between align-items-center gap-3 mb-4">
        <div><h2 class="mb-1">🧾 勃拉姆斯导入预审</h2><div class="text-muted">这里只保存审核意见，不下载 PDF，也不会修改正式目录、data.json 或 logs.json。</div><a href="{{ url_for('brahms_import_review', view='samples') }}">← 规则样例</a> · <a href="{{ url_for('brahms_import_review', view='works') }}">按作品查看</a> · <a href="{{ url_for('brahms_import_review', view='issues') }}">集中处理疑点</a></div>
        <div class="d-flex gap-2"><a class="btn btn-outline-secondary" href="{{ url_for('dashboard') }}">返回后台</a><form method="post" action="/logout"><input type="hidden" name="_csrf_token" value="{{ csrf_token() }}"><button class="btn btn-outline-danger">退出</button></form></div>
    </div>

    {% with messages = get_flashed_messages(with_categories=true) %}
        {% for category, message in messages %}
            {% set alert_type = 'danger' if category in ('error', 'danger') else ('warning' if category == 'warning' else 'success') %}
            <div class="alert alert-{{ alert_type }}" role="alert">{{ message }}</div>
        {% endfor %}
    {% endwith %}

    {% if not manifest %}
        <div class="alert alert-info">尚未生成勃拉姆斯元数据清单。请先运行只抓取元数据的导入命令。</div>
    {% else %}
        <div class="row g-3 mb-4">
            <div class="col-6 col-lg"><div class="card h-100"><div class="card-body"><div class="text-muted small">作品页</div><div class="fs-3 fw-bold">{{ stats.works }}</div></div></div></div>
            <div class="col-6 col-lg"><div class="card h-100"><div class="card-body"><div class="text-muted small">PDF 候选</div><div class="fs-3 fw-bold">{{ stats.total }}</div></div></div></div>
            <div class="col-6 col-lg"><div class="card h-100 border-warning"><div class="card-body"><div class="text-muted small">待审核</div><div class="fs-3 fw-bold text-warning-emphasis">{{ stats.pending }}</div></div></div></div>
            <div class="col-6 col-lg"><div class="card h-100 border-success"><div class="card-body"><div class="text-muted small">已批准</div><div class="fs-3 fw-bold text-success">{{ stats.approved }}</div></div></div></div>
            <div class="col-6 col-lg"><div class="card h-100"><div class="card-body"><div class="text-muted small">已排除</div><div class="fs-3 fw-bold text-secondary">{{ stats.excluded }}</div></div></div></div>
            <div class="col-6 col-lg"><div class="card h-100 border-danger"><div class="card-body"><div class="text-muted small">有警告</div><div class="fs-3 fw-bold text-danger">{{ stats.warning }}</div></div></div></div>
        </div>

        <div class="alert alert-light border small d-flex flex-wrap justify-content-between gap-2">
            <span>清单生成时间：{{ manifest.generated_at|default('')|replace('T', ' ') }}</span>
            <span><strong>本页不执行下载或发布</strong></span>
        </div>
        <p class="small text-muted">本页只审核元数据；隔离试下载与谱面核对结果另行记录。版权依据 IMSLP 页面标注，批准不代表已完成发布许可核验。正式发布时才同步首页更新记录。</p>

        <div class="card mb-3">
            <div class="card-body">
                <form class="row g-2 align-items-end" method="get">
                    <input type="hidden" name="view" value="files">
                    <div class="col-lg-4"><label class="form-label small">搜索</label><input class="form-control" type="search" name="keyword" value="{{ keyword }}" placeholder="标题、作品号、IMSLP号、警告内容"></div>
                    <div class="col-md-3 col-lg-2"><label class="form-label small">审核状态</label><select class="form-select" name="decision"><option value="all">全部</option>{% for value, label in [('pending','待审核'),('approved','已批准'),('deferred','暂缓'),('excluded','已排除')] %}<option value="{{ value }}" {{ 'selected' if decision == value }}>{{ label }}</option>{% endfor %}</select></div>
                    <div class="col-md-3 col-lg-2"><label class="form-label small">分类</label><select class="form-select" name="category"><option value="all">全部</option>{% for value in categories %}<option value="{{ value }}" {{ 'selected' if category == value }}>{{ value }}</option>{% endfor %}</select></div>
                    <div class="col-md-3 col-lg-2"><label class="form-label small">警告</label><select class="form-select" name="warning"><option value="all">全部</option><option value="yes" {{ 'selected' if warning == 'yes' }}>仅有警告</option><option value="no" {{ 'selected' if warning == 'no' }}>仅无警告</option></select></div>
                    <div class="col-md-3 col-lg-2 d-flex gap-2"><button class="btn btn-primary flex-grow-1">筛选</button><a class="btn btn-outline-secondary" href="{{ url_for('brahms_import_review') }}">重置</a></div>
                    <input type="hidden" name="per_page" value="{{ per_page }}">
                    <div class="col-md-4"><label class="form-label small">谱面范围</label><select class="form-select" name="scope"><option value="all">全部</option>{% for value, label in [('individual_movement','单乐章 / 单首'),('selection','多首选段'),('whole_work','整部 / 未识别选段')] %}<option value="{{ value }}" {{ 'selected' if scope == value }}>{{ label }}</option>{% endfor %}</select></div>
                </form>
            </div>
        </div>

        <form id="brahms-batch-form" method="post" action="{{ url_for('batch_update_brahms_review') }}" class="card card-body mb-3 bg-primary-subtle border-primary-subtle">
            <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
            <input type="hidden" name="next" value="{{ request.full_path }}">
            <div class="d-flex flex-wrap align-items-center gap-2">
                <label class="form-check me-2"><input class="form-check-input" id="select-review-page" type="checkbox"> <span class="form-check-label">选择本页</span></label>
                <strong>已选 <span id="review-selected-count">0</span> 条</strong>
                <select class="form-select form-select-sm ms-md-3" name="decision" style="width:auto" required><option value="">批量设置状态</option><option value="pending">待审核</option><option value="approved">批准</option><option value="deferred">暂缓</option><option value="excluded">排除</option></select>
                <button class="btn btn-sm btn-primary" type="submit">应用到所选项目</button>
                <span class="small text-muted">批量操作仅保存状态；字段修改请逐条保存。版权检查未通过的项目不能批准。</span>
            </div>
        </form>

        <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-3 small text-muted">
            <span>筛选后 {{ filtered_total }} 条 · 第 {{ page }} / {{ total_pages }} 页</span>
            <span>每页：<a class="{{ 'fw-bold' if per_page == 20 }}" href="{{ page_url(1, 20) }}">20</a> · <a class="{{ 'fw-bold' if per_page == 50 }}" href="{{ page_url(1, 50) }}">50</a> · <a class="{{ 'fw-bold' if per_page == 100 }}" href="{{ page_url(1, 100) }}">100</a></span>
        </div>

        {% for row in rows %}
        {% set item = row.score_file %}{% set work = row.work %}
        <article class="card shadow-sm mb-3 review-card" id="imslp-{{ item.imslp_id }}">
            <div class="card-header bg-white d-flex align-items-start gap-3">
                <input class="form-check-input mt-1 review-selector" type="checkbox" name="imslp_ids" value="{{ item.imslp_id }}" form="brahms-batch-form" aria-label="选择 IMSLP {{ item.imslp_id }}">
                <div class="review-title flex-grow-1">
                    <div class="d-flex flex-wrap gap-2 align-items-center">
                        <strong>{{ item.proposed_title }}</strong>
                        {% if item.decision == 'approved' %}<span class="badge bg-success">已批准</span>{% elif item.decision == 'excluded' %}<span class="badge bg-secondary">已排除</span>{% elif item.decision == 'deferred' %}<span class="badge bg-secondary">暂缓</span>{% else %}<span class="badge bg-warning text-dark">待审核</span>{% endif %}
                        {% if item.title_scope == 'individual_movement' %}<span class="badge bg-info text-dark">单乐章</span>{% elif item.title_scope == 'selection' %}<span class="badge bg-primary-subtle text-primary-emphasis border border-primary-subtle">多首选段</span>{% else %}<span class="badge bg-light text-dark border">整部/未识别选段</span>{% endif %}
                        <span class="badge bg-light text-dark border">{{ item.category }}</span>
                    </div>
                    <div class="small text-muted mt-1">IMSLP #{{ item.imslp_id }} · {{ item.description_en or item.description or '无文件说明' }}</div>
                </div>
            </div>
            <div class="card-body">
                {% if item.warnings %}<div class="mb-3">{% for message in item.warnings %}<span class="badge bg-danger-subtle text-danger-emphasis border border-danger-subtle review-warning me-1 mb-1">{{ message }}</span>{% endfor %}</div>{% endif %}
                <form method="post" action="{{ url_for('update_brahms_review', imslp_id=item.imslp_id) }}">
                    <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
                    <input type="hidden" name="next" value="{{ request.full_path }}#imslp-{{ item.imslp_id }}">
                    <div class="row g-3">
                        <div class="col-lg-6"><label class="form-label small fw-semibold">最终标题 *</label><input class="form-control" name="proposed_title" maxlength="200" required value="{{ item.proposed_title }}"></div>
                        <div class="col-lg-6"><label class="form-label small fw-semibold">所属作品</label><input class="form-control" name="proposed_work" maxlength="200" value="{{ item.proposed_work }}" placeholder="完整总谱留空；单乐章填写总作品标题"></div>
                        <div class="col-md-4"><label class="form-label small fw-semibold">审核状态</label><select class="form-select" name="decision">{% for value, label in [('pending','待审核'),('approved','批准'),('deferred','暂缓'),('excluded','排除')] %}<option value="{{ value }}" {{ 'selected' if item.decision == value }}>{{ label }}</option>{% endfor %}</select></div>
                        <div class="col-md-4"><label class="form-label small fw-semibold">一级分类</label><select class="form-select" name="category">{% for value in categories %}<option value="{{ value }}" {{ 'selected' if item.category == value }}>{{ value }}</option>{% endfor %}</select></div>
                        <div class="col-md-4"><label class="form-label small fw-semibold">子分类</label><input class="form-control" name="sub_category" maxlength="80" value="{{ item.sub_category }}"></div>
                        <div class="col-md-6"><label class="form-label small fw-semibold">编制（中文简写）</label><input class="form-control" name="voice_types" maxlength="150" value="{{ item.voice_types }}"></div>
                        <div class="col-md-3"><label class="form-label small fw-semibold">调性</label><input class="form-control" name="tonality" maxlength="80" value="{{ item.tonality }}"></div>
                        <div class="col-md-3"><label class="form-label small fw-semibold">作品号</label><input class="form-control" value="{{ work.catalogue_number }}" disabled></div>
                        <div class="col-md-6"><label class="form-label small fw-semibold">歌词语言（器乐留空）</label><input class="form-control" name="language_cn" maxlength="80" value="{{ item.language_cn|default('') }}"></div>
                        <div class="col-12"><label class="form-label small fw-semibold">审核备注</label><textarea class="form-control" name="review_notes" rows="2" maxlength="1000">{{ item.review_notes }}</textarea></div>
                    </div>
                    <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mt-3">
                        <div class="small review-source"><a href="{{ source_url(work.source_url) }}" target="_blank" rel="noopener noreferrer">打开作品页 ↗</a> · <a href="{{ source_url(item.handler_url) }}" target="_blank" rel="noopener noreferrer">打开 IMSLP 文件页 ↗</a> · 版权：{{ item.copyright or '未识别' }}{% if item.arranger %} · 改编：{{ item.arranger }}{% endif %}</div>
                        <button class="btn btn-outline-primary" type="submit">保存这一条</button>
                    </div>
                </form>
                <details class="mt-3 small"><summary class="text-muted">查看抓取原文</summary><dl class="row review-meta mt-2 mb-0"><dt class="col-sm-2">作品页标题</dt><dd class="col-sm-10">{{ work.display_work_title }}</dd><dt class="col-sm-2">乐章列表</dt><dd class="col-sm-10">{{ work.movements_text or '无' }}</dd><dt class="col-sm-2">原文件名</dt><dd class="col-sm-10">{{ item.original_filename or '未提供' }}</dd><dt class="col-sm-2">出版信息</dt><dd class="col-sm-10">{{ item.publisher or '未提供' }}</dd></dl></details>
            </div>
        </article>
        {% else %}
            <div class="alert alert-light border text-center text-muted py-5">没有符合当前筛选条件的项目。</div>
        {% endfor %}

        {% if total_pages > 1 %}<nav aria-label="审核分页"><ul class="pagination justify-content-center flex-wrap"><li class="page-item {{ 'disabled' if page == 1 }}"><a class="page-link" href="{{ page_url(page - 1, per_page) }}">上一页</a></li>{% for number in page_numbers %}<li class="page-item {{ 'active' if number == page }}"><a class="page-link" href="{{ page_url(number, per_page) }}">{{ number }}</a></li>{% endfor %}<li class="page-item {{ 'disabled' if page == total_pages }}"><a class="page-link" href="{{ page_url(page + 1, per_page) }}">下一页</a></li></ul></nav>{% endif %}
    {% endif %}
</main>
<script>
(() => {
    const toggle = document.getElementById('select-review-page');
    const items = Array.from(document.querySelectorAll('.review-selector'));
    const count = document.getElementById('review-selected-count');
    const refresh = () => { if (count) count.textContent = items.filter(item => item.checked).length; };
    if (toggle) toggle.addEventListener('change', () => { items.forEach(item => { item.checked = toggle.checked; }); refresh(); });
    items.forEach(item => item.addEventListener('change', refresh));
})();
</script>
</body>
</html>
"""

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['username'] == ADMIN_USER and request.form['password'] == ADMIN_PASS:
            session['logged_in'] = True
            return redirect(safe_next_url(request.args.get('next')) or url_for('dashboard'))
        flash('用户名或密码不正确')
    return render_template_string(LOGIN_HTML)

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))


@app.route('/import-review/brahms')
@login_required
def brahms_import_review():
    manifest = load_brahms_review_manifest()
    if manifest is None:
        return render_template_string(BRAHMS_REVIEW_TEMPLATE, manifest=None)

    # Old bookmarked filters retain the detailed view; new entry opens samples.
    legacy_filters = any(key in request.args for key in ('keyword', 'scope', 'warning', 'page'))
    view = request.args.get('view', 'files' if legacy_filters else 'samples')
    if view in {'samples', 'works', 'issues'}:
        return brahms_review_overview(manifest, view)

    all_rows = brahms_review_rows(manifest)
    decision = request.args.get('decision', 'all')
    if decision not in BRAHMS_REVIEW_DECISIONS | {'all'}:
        decision = 'all'
    category = request.args.get('category', 'all')
    if category not in ALLOWED_CATEGORIES | {'all'}:
        category = 'all'
    warning = request.args.get('warning', 'all')
    if warning not in {'all', 'yes', 'no'}:
        warning = 'all'
    scope = request.args.get('scope', 'all')
    if scope not in {'all', 'individual_movement', 'selection', 'whole_work'}:
        scope = 'all'
    keyword = request.args.get('keyword', '').strip()[:200]
    keyword_normalized = normalize_catalog_text(keyword)
    exact_file = request.args.get('file', '').strip()

    def matches(row):
        item = row['score_file']
        work = row['work']
        if exact_file and str(item.get('imslp_id')) != exact_file:
            return False
        if decision != 'all' and item.get('decision', 'pending') != decision:
            return False
        if category != 'all' and item.get('category') != category:
            return False
        if scope != 'all' and item.get('title_scope') != scope:
            return False
        has_warning = bool(item.get('warnings'))
        if warning == 'yes' and not has_warning:
            return False
        if warning == 'no' and has_warning:
            return False
        if keyword_normalized:
            search_blob = normalize_catalog_text(' '.join(str(value or '') for value in (
                item.get('proposed_title'), item.get('proposed_work'),
                work.get('display_work_title'), work.get('catalogue_number'),
                item.get('imslp_id'), item.get('description_en'),
                item.get('description'), item.get('original_filename'),
                item.get('review_notes'), ' '.join(item.get('warnings', [])),
            )))
            if keyword_normalized not in search_blob:
                return False
        return True

    filtered_rows = [row for row in all_rows if matches(row)]
    filtered_rows.sort(key=lambda row: (
        normalize_catalog_text(row['score_file'].get('proposed_title')),
        int(row['score_file'].get('imslp_id') or 0),
    ))
    try:
        per_page = int(request.args.get('per_page', '20'))
    except ValueError:
        per_page = 20
    if per_page not in {20, 50, 100}:
        per_page = 20
    try:
        page = max(1, int(request.args.get('page', '1')))
    except ValueError:
        page = 1
    filtered_total = len(filtered_rows)
    total_pages = max(1, (filtered_total + per_page - 1) // per_page)
    page = min(page, total_pages)
    start = (page - 1) * per_page
    rows = filtered_rows[start:start + per_page]
    page_numbers = list(range(max(1, page - 2), min(total_pages, page + 2) + 1))
    decisions = Counter(row['score_file'].get('decision', 'pending') for row in all_rows)
    stats = {
        'works': len(manifest.get('works', [])),
        'total': len(all_rows),
        'pending': decisions.get('pending', 0),
        'approved': decisions.get('approved', 0),
        'excluded': decisions.get('excluded', 0),
        'warning': sum(bool(row['score_file'].get('warnings')) for row in all_rows),
    }

    def page_url(page_number, per_page_override):
        return url_for(
            'brahms_import_review', view='files', file=exact_file, keyword=keyword, decision=decision,
            category=category, warning=warning, scope=scope,
            page=max(1, min(int(page_number), total_pages)),
            per_page=per_page_override,
        )

    return render_template_string(
        BRAHMS_REVIEW_TEMPLATE, manifest=manifest, rows=rows, stats=stats,
        keyword=keyword, decision=decision, category=category, warning=warning, scope=scope,
        categories=sorted(ALLOWED_CATEGORIES), filtered_total=filtered_total,
        page=page, per_page=per_page, total_pages=total_pages,
        page_numbers=page_numbers, page_url=page_url, source_url=brahms_source_url,
        exact_file=exact_file,
    )


def brahms_review_overview(manifest, view):
    all_rows = brahms_views.rows_for(manifest)
    counts = Counter(r['score_file'].get('decision', 'pending') for r in all_rows)
    decision = request.args.get('decision', 'pending' if view == 'issues' else 'active')
    if decision not in BRAHMS_REVIEW_DECISIONS | {'all', 'active'}:
        decision = 'active'
    keyword = request.args.get('keyword', '').strip()[:200]
    filtered = brahms_views.filter_rows(all_rows, decision=decision, keyword=keyword)
    works = brahms_views.grouped_works(filtered) if view == 'works' else []
    work_key = request.args.get('work', '')
    selected_work = next((w for w in works if w['key'] == work_key), None)
    if work_key and view == 'works' and selected_work is None:
        abort(404, description='该作品不存在或不符合当前筛选条件')
    issues = brahms_views.issue_groups(filtered) if view == 'issues' else []
    selected_issue = next((g for g in issues if g['key'] == request.args.get('issue')), None)
    if selected_issue is None and issues:
        selected_issue = issues[0]
    samples = brahms_views.sample_rows(all_rows)
    signature = brahms_views.style_signature(samples)
    confirmed = manifest.get('review_workflow', {}).get('style_confirmation', {})
    stats = dict(counts, works=len(manifest.get('works', [])), pending_issues=sum(
        bool(r['score_file'].get('warnings')) and r['score_file'].get('decision') == 'pending' for r in all_rows
    ))
    for status in BRAHMS_REVIEW_DECISIONS:
        stats.setdefault(status, 0)
    return render_template(
        'brahms_review.html', view=view, manifest=manifest, stats=stats,
        decision=decision, keyword=keyword, works=works, selected_work=selected_work,
        issues=issues, selected_issue=selected_issue, samples=samples,
        style_signature=signature, style_confirmed=confirmed.get('signature') == signature,
        decision_labels=brahms_views.DECISION_LABELS, categories=sorted(ALLOWED_CATEGORIES),
        source_url=brahms_source_url,
        scope_labels={'whole_work': '整部 / 范围待确认', 'individual_movement': '单乐章 / 单首', 'selection': '多首选段'},
        edit_fields=[('proposed_title', '最终标题', 200), ('proposed_work', '所属作品', 200),
                     ('category', '分类', 80), ('sub_category', '子分类', 80),
                     ('voice_types', '中文编制 / 几重唱', 150), ('tonality', '调性', 80),
                     ('language_cn', '歌词语言（器乐留空）', 80)],
    )


@app.route('/import-review/brahms/style', methods=['POST'])
@login_required
def confirm_brahms_style():
    with BRAHMS_REVIEW_LOCK:
        manifest = load_brahms_review_manifest()
        if manifest is None:
            abort(404)
        samples = brahms_views.sample_rows(brahms_views.rows_for(manifest))
        signature = brahms_views.style_signature(samples)
        if not samples or request.form.get('signature') != signature:
            abort(409, description='样例已变化，请刷新页面重新确认')
        manifest.setdefault('review_workflow', {})['style_confirmation'] = {
            'signature': signature, 'version': brahms_views.STYLE_VERSION,
            'confirmed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'sample_ids': [r['score_file']['imslp_id'] for r in samples],
        }
        write_json_atomic(BRAHMS_REVIEW_FILE, manifest, indent=2)
    flash('已记录这组整理风格的确认；没有批准、下载或发布任何文件。')
    return redirect(url_for('brahms_import_review', view='samples'))


@app.route('/import-review/brahms/group/<group_key>', methods=['POST'])
@login_required
def update_brahms_group(group_key):
    if request.form.get('confirm_group') != '1':
        abort(400, description='请确认共同信息的适用范围')
    with BRAHMS_REVIEW_LOCK:
        manifest = load_brahms_review_manifest()
        if manifest is None:
            abort(404)
        group = brahms_views.find_group(manifest, group_key)
        if group is None:
            abort(409, description='分组已变化，请刷新后重新编辑')
        ids = set(request.form.getlist('imslp_ids'))
        rows = [r for r in group['rows'] if str(r['score_file']['imslp_id']) in ids]
        if not rows or len(rows) != len(ids) or request.form.get('signature') != brahms_views.row_signature(rows):
            abort(409, description='文件范围或审核内容已变化，请刷新页面')
        updates = {
            'proposed_title': brahms_review_text('proposed_title', '最终标题', 200, required=True),
            'proposed_work': brahms_review_text('proposed_work', '所属作品', 200),
            'category': brahms_review_text('category', '分类', 80, required=True),
            'sub_category': brahms_review_text('sub_category', '子分类', 80),
            'voice_types': brahms_review_text('voice_types', '编制', 150),
            'tonality': brahms_review_text('tonality', '调性', 80),
            'language_cn': brahms_review_text('language_cn', '歌词语言', 80),
        }
        if updates['category'] not in ALLOWED_CATEGORIES:
            abort(400, description='无效分类')
        if updates['sub_category'] == updates['category']:
            updates['sub_category'] = ''
        for row in rows:
            row['score_file'].update(updates, review_edited=True,
                reviewed_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        write_json_atomic(BRAHMS_REVIEW_FILE, manifest, indent=2)
    flash(f'已更新这 {len(rows)} 个版本的共同信息，审核状态没有改变。')
    return redirect(safe_next_url(request.form.get('next')) or url_for('brahms_import_review', view='works'))


@app.route('/import-review/brahms/issue/<issue_key>/defer', methods=['POST'])
@login_required
def defer_brahms_issue(issue_key):
    with BRAHMS_REVIEW_LOCK:
        manifest = load_brahms_review_manifest()
        if manifest is None:
            abort(404)
        groups = brahms_views.issue_groups(brahms_views.filter_rows(brahms_views.rows_for(manifest), decision='pending'))
        group = next((g for g in groups if g['key'] == issue_key), None)
        if group is None or request.form.get('signature') != group['signature']:
            abort(409, description='该组待审核文件已变化，请刷新页面')
        for row in group['pending']:
            row['score_file'].update(decision='deferred', review_edited=True,
                reviewed_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        write_json_atomic(BRAHMS_REVIEW_FILE, manifest, indent=2)
    flash(f"已暂缓 {len(group['pending'])} 个文件；未删除文件，可在暂缓列表恢复待审核。")
    return redirect(url_for('brahms_import_review', view='issues', decision='pending'))


@app.route('/import-review/brahms/<imslp_id>', methods=['POST'])
@login_required
def update_brahms_review(imslp_id):
    with BRAHMS_REVIEW_LOCK:
        manifest = load_brahms_review_manifest()
        if manifest is None:
            abort(404, description='尚未生成勃拉姆斯审核清单')
        _work, item = find_brahms_review_file(manifest, imslp_id)
        if item is None:
            abort(404, description='审核项目不存在')
        decision = brahms_review_text('decision', '审核状态', 20, required=True)
        if decision not in BRAHMS_REVIEW_DECISIONS:
            abort(400, description='无效审核状态')
        if decision == 'approved' and not item.get('eligible'):
            abort(400, description='当前版权状态不适合匿名下载，不能批准')
        category = brahms_review_text('category', '一级分类', 80, required=True)
        if category not in ALLOWED_CATEGORIES:
            abort(400, description='无效分类')
        item.update({
            'proposed_title': brahms_review_text('proposed_title', '最终标题', 200, required=True),
            'proposed_work': brahms_review_text('proposed_work', '所属作品', 200),
            'decision': decision,
            'category': category,
            'sub_category': brahms_review_text('sub_category', '子分类', 80),
            'voice_types': brahms_review_text('voice_types', '编制', 150),
            'tonality': brahms_review_text('tonality', '调性', 80),
            'language_cn': brahms_review_text('language_cn', '歌词语言', 80),
            'review_notes': brahms_review_text('review_notes', '审核备注', 1000),
            'review_edited': True,
            'reviewed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })
        write_json_atomic(BRAHMS_REVIEW_FILE, manifest, indent=2)
    flash(f"已保存 IMSLP #{imslp_id}：{item['proposed_title']}")
    return redirect(safe_next_url(request.form.get('next')) or url_for('brahms_import_review'))


@app.route('/import-review/brahms/batch', methods=['POST'])
@login_required
def batch_update_brahms_review():
    selected = list(dict.fromkeys(request.form.getlist('imslp_ids')))
    if not selected:
        flash('请至少选择一条审核项目。', 'warning')
        return redirect(safe_next_url(request.form.get('next')) or url_for('brahms_import_review'))
    decision = brahms_review_text('decision', '审核状态', 20, required=True)
    if decision not in BRAHMS_REVIEW_DECISIONS:
        abort(400, description='无效审核状态')
    changed = 0
    skipped = 0
    selected_set = set(selected)
    with BRAHMS_REVIEW_LOCK:
        manifest = load_brahms_review_manifest()
        if manifest is None:
            abort(404, description='尚未生成勃拉姆斯审核清单')
        for row in brahms_review_rows(manifest):
            item = row['score_file']
            if str(item.get('imslp_id', '')) not in selected_set:
                continue
            if decision == 'approved' and not item.get('eligible'):
                skipped += 1
                continue
            item['decision'] = decision
            item['review_edited'] = True
            item['reviewed_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            changed += 1
        if changed:
            write_json_atomic(BRAHMS_REVIEW_FILE, manifest, indent=2)
    label = brahms_views.DECISION_LABELS[decision]
    message = f'已将 {changed} 条审核项目设为“{label}”。'
    if skipped:
        message += f' 另有 {skipped} 条因版权状态不适合匿名下载而跳过。'
    flash(message, 'warning' if skipped else 'success')
    return redirect(safe_next_url(request.form.get('next')) or url_for('brahms_import_review'))


@app.errorhandler(413)
def upload_too_large(_error):
    if request.path == '/batch-upload':
        return f'批量上传内容过大，总大小上限为 {BATCH_UPLOAD_MAX_MB} MB。', 413
    if request.path == '/':
        return f'单份后台上传不能超过 {ADMIN_UPLOAD_MAX_MB} MB。', 413
    if request.path == '/submit':
        return f'上传内容过大。投稿 PDF 上限为 {SUBMISSION_MAX_MB} MB。', 413
    if request.path == '/login':
        return '登录请求内容过大，请刷新页面后重试。', 413
    return '请求内容过大，请减少填写内容后重试。', 413


@app.route('/dashboard')
@login_required
def dashboard():
    data, change_log = load_data_and_log()
    stats = catalog_dashboard_snapshot(data, change_log)
    return render_template_string(
        HTML_TEMPLATE,
        active_tab='dashboard', stats=stats,
        pending_count=stats['pending_count'],
        deleted_count=stats['deleted_count'],
    )


@app.route('/catalog-health')
@login_required
def catalog_health():
    issue = request.args.get('issue', 'pdf')
    issue_labels = {
        'pdf': '缺失/非法 PDF',
        'orphan': '未引用文件',
        'missing_work': '未填所属作品',
        'missing_description': '未填简介',
    }
    if issue not in issue_labels:
        abort(400, description='未知的资料问题类型')
    try:
        page = max(1, int(request.args.get('page', '1')))
    except ValueError:
        page = 1
    try:
        per_page = int(request.args.get('per_page', '50'))
    except ValueError:
        per_page = 50
    if per_page not in {50, 100}:
        per_page = 50

    data, _ = load_data_and_log()
    health = catalog_health_report(data)
    if issue == 'pdf':
        issue_items = health['file_issues']
    elif issue == 'orphan':
        issue_items = health['orphan_files']
    elif issue == 'missing_work':
        issue_items = [item for item in data if not str(item.get('work', '')).strip()]
    else:
        issue_items = [item for item in data if not str(item.get('description', '')).strip()]

    total_items = len(issue_items)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    page = min(page, total_pages)
    start = (page - 1) * per_page
    return render_template_string(
        HTML_TEMPLATE,
        active_tab='health',
        health=health,
        health_issue=issue,
        health_issue_label=issue_labels[issue],
        health_items=issue_items[start:start + per_page],
        health_total_items=total_items,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        pending_count=submission_counts()['pending'],
        deleted_count=len(load_deleted_entries()),
    )


@app.route('/duplicates')
@login_required
def duplicates():
    data, _ = load_data_and_log()
    groups = duplicate_catalog_groups(data)
    return render_template_string(
        HTML_TEMPLATE,
        active_tab='duplicates', duplicate_groups=groups,
        pending_count=submission_counts()['pending'],
        deleted_count=len(load_deleted_entries()),
    )


@app.route('/scores/<int:item_id>/file')
@login_required
def catalog_score_file(item_id):
    data, _ = load_data_and_log()
    item = next((entry for entry in data if entry.get('id') == item_id), None)
    if not item:
        abort(404)

    try:
        file_path = score_file_path(item.get('filename', ''))
    except (TypeError, ValueError):
        abort(404)
    if not file_path.is_file():
        abort(404)

    download_name = clean_original_filename(str(item.get('title') or f'score-{item_id}'))
    if not download_name.lower().endswith('.pdf'):
        download_name += '.pdf'
    return send_file(
        file_path,
        mimetype='application/pdf',
        as_attachment=False,
        download_name=download_name,
        conditional=True,
    )


@app.route('/submit', methods=['GET', 'POST'])
def submit_score():
    receipt = session.pop('submission_receipt', None)
    if request.method == 'POST':
        saved_path = None
        try:
            if request.form.get('website'):
                abort(400)

            submitter_name = form_text('submitter_name', '姓名或称呼', 100, required=True)
            submitter_email = form_text('submitter_email', '联系邮箱', 254, required=True).lower()
            if not valid_email(submitter_email):
                raise ValueError('请填写有效的联系邮箱')

            title = form_text('title', '曲名', 200, required=True)
            composer = form_text('composer', '作曲家', 200, required=True)
            category = form_text('category', '分类', 100, required=True)
            if category not in ALLOWED_CATEGORIES:
                raise ValueError('请选择有效的乐谱分类')
            if request.form.get('copyright_confirmed') != '1':
                raise ValueError('请先确认文件的分享授权')

            upload = request.files.get('file')
            if not upload or not upload.filename or not allowed_file(upload.filename):
                raise ValueError('请选择 PDF 文件')

            public_id = str(uuid.uuid4())
            saved_path, sha256, file_size = save_pending_pdf(upload, public_id)
            duplicate = find_active_duplicate(sha256)
            if duplicate:
                saved_path.unlink(missing_ok=True)
                saved_path = None
                raise ValueError(f"这份 PDF 已经投稿过，现有审核编号为 #{duplicate['id']}")

            submission_id = create_submission({
                'public_id': public_id,
                'status': 'pending',
                'submitter_name': submitter_name,
                'submitter_email': submitter_email,
                'title': title,
                'composer': composer,
                'work': form_text('work', '所属作品', 200),
                'language': form_text('language', '语言', 100),
                'category': category,
                'sub_category': form_text('sub_category', '体裁或子分类', 120),
                'voice_count': form_text('voice_count', '数量或类型补充', 100),
                'voice_types': form_text('voice_types', '声部或乐器', 150),
                'tonality': form_text('tonality', '调性', 80),
                'description': form_text('description', '简介', 2000),
                'lyrics_original': form_text('lyrics_original', '歌词原文', 20000),
                'lyrics_translation': form_text('lyrics_translation', '中文翻译', 20000),
                'copyright_confirmed': 1,
                'original_filename': clean_original_filename(upload.filename),
                'stored_filename': saved_path.name,
                'sha256': sha256,
                'file_size': file_size,
                'submitted_at': now_utc(),
            })
            session['submission_receipt'] = submission_id
            return redirect(url_for('submit_score'))
        except ValueError as error:
            if saved_path and saved_path.exists():
                saved_path.unlink()
            flash(str(error), 'error')
        except Exception:
            if saved_path and saved_path.exists():
                saved_path.unlink()
            raise

    return render_template_string(
        PUBLIC_SUBMISSION_HTML,
        receipt=receipt,
        form=request.form,
        categories=sorted(ALLOWED_CATEGORIES),
        max_mb=SUBMISSION_MAX_MB,
    )


@app.route('/submissions')
@login_required
def review_submissions():
    status = request.args.get('status', 'pending')
    if status not in {'pending', 'approved', 'rejected', 'all'}:
        status = 'pending'
    return render_template_string(
        SUBMISSION_ADMIN_HTML,
        active_tab='submissions',
        submissions=list_submissions(status),
        status=status,
        counts=submission_counts(),
    )


@app.route('/submissions/<int:submission_id>')
@login_required
def review_submission(submission_id):
    submission = get_submission(submission_id)
    if not submission:
        abort(404)
    file_path = submission_file_location(submission)
    return render_template_string(
        SUBMISSION_ADMIN_HTML,
        active_tab='submission_detail',
        submission=submission,
        counts=submission_counts(),
        file_available=bool(file_path),
        file_size=f"{submission['file_size'] / (1024 * 1024):.2f}",
    )


@app.route('/submissions/<int:submission_id>/file')
@login_required
def submission_file(submission_id):
    submission = get_submission(submission_id)
    if not submission:
        abort(404)
    file_path = submission_file_location(submission)
    if not file_path:
        abort(404)
    return send_file(
        file_path,
        mimetype='application/pdf',
        as_attachment=False,
        download_name=submission['original_filename'],
        conditional=True,
    )


@app.route('/submissions/<int:submission_id>/approve', methods=['POST'])
@login_required
@catalog_write_locked
def approve_submission(submission_id):
    submission = get_submission(submission_id)
    if not submission:
        abort(404)
    if submission['status'] != 'pending':
        flash('这份投稿已经处理过，请刷新列表。', 'error')
        return redirect(url_for('review_submission', submission_id=submission_id))

    review_note = form_text('review_note', '审核备注', 1000)
    source_path = pending_file_path(submission['stored_filename'])
    if not source_path.is_file():
        flash('待审核 PDF 不存在，无法发布。', 'error')
        return redirect(url_for('review_submission', submission_id=submission_id))

    music_data, change_log = load_data_and_log()
    original_data = [dict(item) for item in music_data]
    original_log = [dict(item) for item in change_log]
    new_id = max([int(item['id']) for item in music_data] + [0, int(time.time() * 1000)]) + 1
    filename = f"{submission['public_id']}.pdf"
    target_dir = Path(SCORES_DIR) / submission['category']
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = (target_dir / filename).resolve()
    if target_path.exists():
        abort(409, description='公开乐谱目录中已存在同名文件')

    has_lyrics = False
    data_saved = False
    storage_result = PublishResult(enabled=False)
    try:
        shutil.move(str(source_path), str(target_path))
        has_lyrics = save_lyrics(
            new_id,
            submission['lyrics_original'],
            submission['lyrics_translation'],
        )
        item = {
            'id': new_id,
            'public_id': submission['public_id'],
            'title': submission['title'],
            'composer': submission['composer'],
            'work': submission['work'],
            'language': submission['language'],
            'category': submission['category'],
            'sub_category': submission['sub_category'],
            'voice_count': submission['voice_count'],
            'voice_types': submission['voice_types'],
            'tonality': submission['tonality'],
            'description': submission['description'],
            'filename': f"{submission['category']}/{filename}",
            'date': datetime.date.today().isoformat(),
            'has_lyrics': has_lyrics,
        }
        storage_result = publish_catalog_items_to_storage(
            [(item, target_path, submission.get('sha256'))]
        )
        music_data.append(item)
        add_log(change_log, 'add', f"审核通过投稿 #{submission_id}: {item['title']}")
        save_all(music_data, change_log)
        data_saved = True
        mark_approved(submission_id, new_id, item['filename'], review_note)
    except Exception as error:
        if data_saved:
            save_all(original_data, original_log)
        lyric_path = Path(LYRICS_DIR) / f'{new_id}.json'
        if has_lyrics and lyric_path.exists():
            lyric_path.unlink()
        if target_path.exists() and not source_path.exists():
            shutil.move(str(target_path), str(source_path))
        if isinstance(error, StoragePublishError):
            flash(str(error) + '；投稿仍保持待审核状态。', 'error')
            return redirect(url_for('review_submission', submission_id=submission_id))
        raise

    update_manifest_after_publish(storage_result)
    message = f"投稿 #{submission_id} 已通过并发布。"
    if storage_result.enabled:
        message += f" {storage_result.detail}。"
    else:
        flash(storage_result.detail, 'warning')
    flash(message, 'success')
    return redirect(url_for('review_submission', submission_id=submission_id))


@app.route('/submissions/<int:submission_id>/reject', methods=['POST'])
@login_required
def reject_submission(submission_id):
    review_note = form_text('review_note', '驳回原因', 1000, required=True)
    try:
        mark_rejected(submission_id, review_note)
    except ValueError as error:
        flash(str(error), 'error')
    else:
        flash(f'投稿 #{submission_id} 已驳回，PDF 仍保存在私有目录。', 'success')
    return redirect(url_for('review_submission', submission_id=submission_id))


@app.route('/submissions/<int:submission_id>/restore', methods=['POST'])
@login_required
def restore_submission(submission_id):
    try:
        restore_pending(submission_id)
    except ValueError as error:
        flash(str(error), 'error')
    else:
        flash(f'投稿 #{submission_id} 已恢复为待审核。', 'success')
    return redirect(url_for('review_submission', submission_id=submission_id))


@app.route('/batch-upload', methods=['GET', 'POST'])
@login_required
@catalog_write_locked
def batch_upload():
    staging_dir = None
    published_paths = []
    storage_result = PublishResult(enabled=False)
    if request.method == 'POST':
        try:
            composer = form_text('composer', '默认作曲家', 200)
            category = form_text('category', '分类', 100, required=True)
            if category not in ALLOWED_CATEGORIES:
                raise ValueError('请选择有效的乐谱分类')

            common_fields = {
                'composer': composer,
                'work': form_text('work', '所属作品', 200),
                'language': form_text('language', '语言', 100),
                'category': category,
                'sub_category': form_text('sub_category', '体裁或子分类', 120),
                'voice_count': form_text('voice_count', '数量或类型补充', 100),
                'voice_types': form_text('voice_types', '声部或乐器', 150),
                'tonality': form_text('tonality', '调性', 80),
                'description': form_text('description', '简介', 2000),
            }

            uploads = [upload for upload in request.files.getlist('files') if upload and upload.filename]
            if not uploads:
                raise ValueError('请至少选择一份 PDF')
            if len(uploads) > BATCH_UPLOAD_MAX_FILES:
                raise ValueError(f'一次最多上传 {BATCH_UPLOAD_MAX_FILES} 份 PDF')

            raw_titles = request.form.getlist('titles')
            if raw_titles and len(raw_titles) != len(uploads):
                raise ValueError('文件与曲名列表不一致，请重新选择 PDF 后再试')

            titles = []
            for index, upload in enumerate(uploads, start=1):
                original_name = clean_original_filename(upload.filename)
                if not allowed_file(original_name):
                    raise ValueError(f'{original_name} 不是 PDF 文件')
                supplied_title = raw_titles[index - 1] if raw_titles else title_from_pdf_filename(original_name)
                titles.append(validated_text(supplied_title, f'第 {index} 份乐谱的曲名', 200, required=True))

            per_item_specs = (
                ('item_composers', '作曲家', 200, common_fields['composer'], True),
                ('item_works', '所属作品', 200, common_fields['work'], False),
                ('item_tonalities', '调性', 80, common_fields['tonality'], False),
                ('item_voice_types', '编制', 150, common_fields['voice_types'], False),
            )
            per_item_values = {}
            for field_name, label, max_length, fallback, required in per_item_specs:
                values = request.form.getlist(field_name)
                if values and len(values) != len(uploads):
                    raise ValueError(f'文件与{label}列表不一致，请重新选择 PDF 后再试')
                if not values:
                    values = [fallback] * len(uploads)
                per_item_values[field_name] = [
                    validated_text(value, f'第 {index} 份乐谱的{label}', max_length, required=required)
                    for index, value in enumerate(values, start=1)
                ]

            music_data, change_log = load_data_and_log()
            new_id = max([int(item['id']) for item in music_data] + [0, int(time.time() * 1000)]) + 1
            staging_dir = Path(BACKUP_DIR) / 'batch_uploads' / uuid.uuid4().hex
            staging_dir.mkdir(parents=True, exist_ok=False)

            prepared = []
            seen_hashes = {}
            total_bytes = 0
            for index, (upload, title) in enumerate(zip(uploads, titles)):
                original_name = clean_original_filename(upload.filename)
                public_id = str(uuid.uuid4())
                staging_path = staging_dir / f'{public_id}.pdf'
                sha256, file_size = stage_batch_pdf(
                    upload,
                    staging_path,
                    BATCH_UPLOAD_MAX_BYTES - total_bytes,
                )
                if sha256 in seen_hashes:
                    raise ValueError(
                        f'{original_name} 与 {seen_hashes[sha256]} 内容完全相同，请移除重复文件后再上传'
                    )
                seen_hashes[sha256] = original_name
                total_bytes += file_size

                catalog_filename = f'{category}/{public_id}.pdf'
                target_path = score_file_path(catalog_filename)
                if target_path.exists():
                    abort(409, description='公开乐谱目录中已存在同名文件')
                prepared.append({
                    'staging_path': staging_path,
                    'target_path': target_path,
                    'sha256': sha256,
                    'item': {
                        'id': new_id + index,
                        'public_id': public_id,
                        'title': title,
                        **common_fields,
                        'composer': per_item_values['item_composers'][index],
                        'work': per_item_values['item_works'][index],
                        'tonality': per_item_values['item_tonalities'][index],
                        'voice_types': per_item_values['item_voice_types'][index],
                        'filename': catalog_filename,
                        'date': datetime.date.today().isoformat(),
                        'has_lyrics': False,
                    },
                })

            existing_keys = {
                (normalize_catalog_text(item.get('title')), normalize_catalog_text(item.get('composer')))
                for item in music_data
            }
            possible_duplicates = 0
            for entry in prepared:
                item = entry['item']
                key = (normalize_catalog_text(item['title']), normalize_catalog_text(item['composer']))
                if key in existing_keys:
                    possible_duplicates += 1
                existing_keys.add(key)

                target_path = entry['target_path']
                target_path.parent.mkdir(parents=True, exist_ok=True)
                entry['staging_path'].replace(target_path)
                published_paths.append(target_path)

            new_items = [entry['item'] for entry in prepared]
            storage_result = publish_catalog_items_to_storage(
                [
                    (entry['item'], entry['target_path'], entry['sha256'])
                    for entry in prepared
                ]
            )
            music_data.extend(new_items)
            title_preview = '、'.join(item['title'] for item in new_items[:3])
            if len(new_items) > 3:
                title_preview += '等'
            add_log(change_log, 'batch_add', f'批量添加 {len(new_items)} 份乐谱：{title_preview}')
            save_all(music_data, change_log)
        except Exception as error:
            rollback_errors = []
            for path in reversed(published_paths):
                try:
                    path.unlink(missing_ok=True)
                except OSError as rollback_error:
                    rollback_errors.append(f'{path.name}: {rollback_error}')
            if rollback_errors:
                raise RuntimeError('批量上传失败，且文件回滚未完整完成：' + '; '.join(rollback_errors)) from error
            if isinstance(error, (ValueError, StoragePublishError)):
                flash(str(error), 'error')
            else:
                raise
        else:
            update_manifest_after_publish(storage_result)
            message = f'已成功批量发布 {len(prepared)} 份乐谱。'
            if storage_result.enabled:
                message += f' {storage_result.detail}。'
            else:
                flash(storage_result.detail, 'warning')
            flash(message, 'success')
            if possible_duplicates:
                flash(f'其中 {possible_duplicates} 份与目录中的“曲名 + 作曲家”相同，请到重复检查页面核对。', 'warning')
            return redirect(url_for('manage'))
        finally:
            if staging_dir and staging_dir.exists():
                for path in staging_dir.iterdir():
                    if path.is_file():
                        try:
                            path.unlink(missing_ok=True)
                        except OSError as cleanup_error:
                            app.logger.error('无法清理批量上传暂存文件 %s: %s', path, cleanup_error)
                try:
                    staging_dir.rmdir()
                    staging_dir.parent.rmdir()
                except OSError:
                    pass

    return render_template_string(
        HTML_TEMPLATE,
        active_tab='batch_upload',
        form=request.form,
        categories=sorted(ALLOWED_CATEGORIES),
        languages=sorted(CANONICAL_LANGUAGES),
        batch_max_files=BATCH_UPLOAD_MAX_FILES,
        batch_max_mb=BATCH_UPLOAD_MAX_MB,
        batch_max_bytes=BATCH_UPLOAD_MAX_BYTES,
        storage_auto_sync=auto_sync_enabled(),
        pending_count=submission_counts()['pending'],
        deleted_count=len(load_deleted_entries()),
    )

@app.route('/', methods=['GET', 'POST'])
@login_required
@catalog_write_locked
def index():
    if request.method == 'POST':
        file = request.files.get('file')
        category = request.form.get('category', '')
        if category not in ALLOWED_CATEGORIES:
            abort(400, description='无效分类')
        if not file or not file.filename or not allowed_file(file.filename):
            flash('请上传 PDF 文件')
            return redirect(url_for('index'))
        if not is_pdf_upload(file):
            flash('文件内容不是有效 PDF')
            return redirect(url_for('index'))

        music_data, change_log = load_data_and_log()
        new_id = max([int(item['id']) for item in music_data] + [0, int(time.time() * 1000)]) + 1
        filename = f"{uuid.uuid4().hex}.pdf"
        cat_dir = Path(SCORES_DIR) / category
        cat_dir.mkdir(parents=True, exist_ok=True)
        target_path = cat_dir / filename
        file.save(target_path)

        has_lyrics = save_lyrics(new_id, request.form.get('lyrics_og', ''), request.form.get('lyrics_cn', ''))
        item = {
            "id": new_id,
            "public_id": str(uuid.uuid4()),
            "title": request.form['title'].strip(),
            "composer": request.form['composer'].strip(),
            "work": request.form.get('work', '').strip(),
            "language": request.form.get('language', '').strip(),
            "category": category,
            "sub_category": request.form.get('sub_category', '').strip(),
            "voice_count": request.form.get('voice_count', '').strip(),
            "voice_types": request.form.get('voice_types', '').strip(),
            "tonality": request.form.get('tonality', '').strip(),
            "description": request.form.get('description', '').strip(),
            "filename": f"{category}/{filename}",
            "date": datetime.date.today().strftime("%Y-%m-%d"),
            "has_lyrics": has_lyrics
        }
        storage_result = PublishResult(enabled=False)
        try:
            storage_result = publish_catalog_items_to_storage([(item, target_path, None)])
            music_data.append(item)
            add_log(change_log, 'add', f"添加: {item['title']}")
            save_all(music_data, change_log)
        except Exception as error:
            if target_path.exists():
                target_path.unlink()
            lyric_path = Path(LYRICS_DIR) / f"{new_id}.json"
            if lyric_path.exists():
                lyric_path.unlink()
            if isinstance(error, StoragePublishError):
                flash(str(error) + '；没有写入公开目录。', 'error')
                return redirect(url_for('index'))
            raise
        update_manifest_after_publish(storage_result)
        if storage_result.enabled:
            flash(f'发布成功；{storage_result.detail}。', 'success')
        else:
            flash('本地保存成功。', 'success')
            flash(storage_result.detail, 'warning')
        return redirect(url_for('index'))
    return render_template_string(
        HTML_TEMPLATE.replace("{% include 'category_select.html' %}", CATEGORY_SELECT_HTML),
        active_tab='upload', item=None, lyrics=None,
        storage_auto_sync=auto_sync_enabled(),
        pending_count=submission_counts()['pending'],
        deleted_count=len(load_deleted_entries()),
    )

@app.route('/manage')
@login_required
def manage():
    # 获取筛选参数
    keyword = request.args.get('keyword', '').strip().lower()
    composer_filter = request.args.get('composer', '').strip().lower()
    category_filter = request.args.get('category', 'all')
    try:
        page = max(1, int(request.args.get('page', '1')))
    except ValueError:
        page = 1
    try:
        per_page = int(request.args.get('per_page', '50'))
    except ValueError:
        per_page = 50
    if per_page not in {50, 100}:
        per_page = 50
    
    data, _ = load_data_and_log()
    
    # 1. 关键词筛选 (匹配曲名、作品号、简介)
    if keyword:
        data = [i for i in data if 
                keyword in i['title'].lower() or 
                keyword in (i.get('work') or '').lower() or
                keyword in (i.get('description') or '').lower()]
    
    # 2. 作曲家筛选 (独立匹配)
    if composer_filter:
        data = [i for i in data if composer_filter in i['composer'].lower()]
        
    # 3. 分类筛选 (精确匹配)
    if category_filter and category_filter != 'all':
        data = [i for i in data if i['category'] == category_filter]

    total_items = len(data)
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    page = min(page, total_pages)
    start = (page - 1) * per_page
    migrated_public_ids = manifest_public_ids()
    items = [dict(item) for item in data[start:start + per_page]]
    for item in items:
        item['storage_status'] = storage_status_for_item(item, migrated_public_ids)
    page_numbers = list(range(max(1, page - 2), min(total_pages, page + 2) + 1))

    return render_template_string(
        HTML_TEMPLATE, active_tab='manage', items=items,
        keyword=keyword, composer_filter=composer_filter, category_filter=category_filter,
        page=page, per_page=per_page, total_items=total_items,
        total_pages=total_pages, page_numbers=page_numbers,
        categories=sorted(ALLOWED_CATEGORIES), languages=sorted(CANONICAL_LANGUAGES),
        storage_auto_sync=auto_sync_enabled(),
        pending_count=submission_counts()['pending'],
        deleted_count=len(load_deleted_entries()),
    )


@app.route('/storage/sync/<int:item_id>', methods=['POST'])
@login_required
@catalog_write_locked
def sync_score_storage(item_id):
    music_data, change_log = load_data_and_log()
    item = next((candidate for candidate in music_data if int(candidate['id']) == item_id), None)
    if not item:
        abort(404)

    try:
        source_path = score_file_path(item['filename'])
        result = publish_catalog_items_to_storage(
            [(item, source_path, None)],
            force=True,
        )
        add_log(change_log, 'storage_sync', f"R2 校验/同步: {item['title']}")
        save_all(music_data, change_log)
        update_manifest_after_publish(result)
    except (OSError, ValueError, StoragePublishError) as error:
        flash(f'R2 同步失败：{error}', 'error')
    else:
        flash(f'{item["title"]}：{result.detail}。', 'success')

    return redirect(safe_next_url(request.form.get('next')) or url_for('manage'))


@app.route('/batch-update', methods=['POST'])
@login_required
@catalog_write_locked
def batch_update():
    raw_ids = request.form.getlist('item_ids')
    if not raw_ids:
        flash('请先选择要修改的乐谱。')
        return redirect(safe_next_url(request.form.get('next')) or url_for('manage'))
    if len(raw_ids) > 100:
        abort(400, description='一次最多批量修改 100 条乐谱')
    try:
        item_ids = {int(value) for value in raw_ids}
    except ValueError:
        abort(400, description='乐谱 ID 无效')
    if len(item_ids) != len(raw_ids):
        abort(400, description='批量选择中存在重复 ID')

    data, change_log = load_data_and_log()
    selected = [item for item in data if int(item.get('id', -1)) in item_ids]
    if len(selected) != len(item_ids):
        abort(400, description='部分乐谱已不存在，请刷新后重试')

    action = request.form.get('batch_action', '')
    if action == 'set_language':
        target_language = request.form.get('target_language', '').strip()
        if target_language not in CANONICAL_LANGUAGES:
            flash('请选择有效的目标语言。')
            return redirect(safe_next_url(request.form.get('next')) or url_for('manage'))
        changed = [item for item in selected if item.get('language') != target_language]
        if not changed:
            flash('所选乐谱已经使用该语言，无需修改。')
            return redirect(safe_next_url(request.form.get('next')) or url_for('manage'))
        for item in changed:
            item['language'] = target_language
        add_log(change_log, 'batch_update', f"批量修改语言为 {target_language}: {len(changed)} 条")
        save_all(data, change_log)
        flash(f'已将 {len(changed)} 条乐谱的语言修改为 {target_language}。')
    elif action == 'set_category':
        target_category = request.form.get('target_category', '').strip()
        if target_category not in ALLOWED_CATEGORIES:
            flash('请选择有效的目标分类。')
            return redirect(safe_next_url(request.form.get('next')) or url_for('manage'))
        changed = [item for item in selected if item.get('category') != target_category]
        if not changed:
            flash('所选乐谱已经属于该分类，无需修改。')
            return redirect(safe_next_url(request.form.get('next')) or url_for('manage'))

        move_plan = []
        planned_targets = set()
        for item in changed:
            source = score_file_path(item['filename'])
            if not source.is_file():
                flash(f"乐谱 PDF 不存在，已取消整批修改：{item['title']}")
                return redirect(safe_next_url(request.form.get('next')) or url_for('manage'))
            target = (Path(SCORES_DIR) / target_category / source.name).resolve()
            if target.exists() or target in planned_targets:
                flash(f"目标分类中已存在同名 PDF，已取消整批修改：{item['title']}")
                return redirect(safe_next_url(request.form.get('next')) or url_for('manage'))
            planned_targets.add(target)
            move_plan.append((item, source, target, item['category'], item['filename']))

        moved_files = []
        created_dirs = []
        try:
            for item, source, target, _old_category, _old_filename in move_plan:
                if not target.parent.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    created_dirs.append(target.parent)
                source.replace(target)
                moved_files.append((source, target))
                item['category'] = target_category
                item['filename'] = f"{target_category}/{target.name}"
            add_log(change_log, 'batch_update', f"批量修改分类为 {target_category}: {len(changed)} 条")
            save_all(data, change_log)
        except Exception:
            for source, target in reversed(moved_files):
                if target.exists():
                    source.parent.mkdir(parents=True, exist_ok=True)
                    target.replace(source)
            for item, _source, _target, old_category, old_filename in move_plan:
                item['category'] = old_category
                item['filename'] = old_filename
            for directory in reversed(created_dirs):
                scores_root = Path(SCORES_DIR).resolve()
                current = directory
                while current != scores_root and scores_root in current.parents:
                    try:
                        current.rmdir()
                    except OSError:
                        break
                    current = current.parent
            raise
        flash(f'已将 {len(changed)} 条乐谱移入分类“{target_category}”。')
    else:
        abort(400, description='未知批量操作')

    return redirect(safe_next_url(request.form.get('next')) or url_for('manage'))


@app.route('/edit/<int:item_id>', methods=['GET', 'POST'])
@login_required
@catalog_write_locked
def edit(item_id):
    data, log = load_data_and_log()
    item = next((i for i in data if i['id'] == item_id), None)
    if not item: return "404", 404
    
    if request.method == 'POST':
        category = request.form.get('category', '')
        if category not in ALLOWED_CATEGORIES:
            abort(400, description='无效分类')

        old_path = score_file_path(item['filename'])
        new_path = old_path
        old_filename = item['filename']
        new_filename = old_filename
        lyric_path = Path(LYRICS_DIR) / f"{item_id}.json"
        previous_lyrics = lyric_path.read_bytes() if lyric_path.exists() else None
        if category != item['category']:
            new_filename = f"{category}/{old_path.name}"
            new_path = score_file_path(new_filename)
            new_path.parent.mkdir(parents=True, exist_ok=True)
            if new_path.exists():
                abort(409, description='目标分类中已存在同名文件')
            old_path.replace(new_path)

        item.update({
            "title": request.form['title'].strip(), "composer": request.form['composer'].strip(),
            "work": request.form.get('work', '').strip(), "language": request.form.get('language', '').strip(),
            "category": category,
            "sub_category": request.form.get('sub_category', '').strip(),
            "voice_count": request.form.get('voice_count', '').strip(),
            "voice_types": request.form.get('voice_types', '').strip(), "tonality": request.form.get('tonality', '').strip(),
            "description": request.form.get('description', '').strip(),
            "filename": new_filename,
        })
        has_lyrics = save_lyrics(item_id, request.form.get('lyrics_og', ''), request.form.get('lyrics_cn', ''))
        item['has_lyrics'] = has_lyrics
        
        add_log(log, 'update', f"更新: {item['title']}")
        try:
            save_all(data, log)
        except Exception:
            if new_path != old_path and new_path.exists() and not old_path.exists():
                old_path.parent.mkdir(parents=True, exist_ok=True)
                new_path.replace(old_path)
            restore_file_bytes(lyric_path, previous_lyrics)
            item['filename'] = old_filename
            raise
        flash('更新成功')
        return redirect(url_for('manage'))

    lyrics = load_lyrics(item_id)
    return render_template_string(
        HTML_TEMPLATE.replace("{% include 'category_select.html' %}", CATEGORY_SELECT_HTML),
        active_tab='edit', item=item, lyrics=lyrics,
        pending_count=submission_counts()['pending'],
        deleted_count=len(load_deleted_entries()),
    )

@app.route('/trash')
@login_required
def trash():
    entries = load_deleted_entries()
    return render_template_string(
        HTML_TEMPLATE,
        active_tab='trash', deleted_entries=entries,
        pending_count=submission_counts()['pending'],
        deleted_count=len(entries),
    )


@app.route('/trash/<entry_name>/restore', methods=['POST'])
@login_required
@catalog_write_locked
def restore_deleted(entry_name):
    try:
        entry_dir = deleted_entry_path(entry_name)
        manifest_path = entry_dir / 'manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        item = dict(manifest['item'])
        files = manifest.get('files', {})
    except (ValueError, OSError, json.JSONDecodeError, KeyError, TypeError):
        abort(404)

    data, log = load_data_and_log()
    if any(existing.get('id') == item.get('id') or existing.get('public_id') == item.get('public_id') for existing in data):
        flash('目录中已存在同 ID 或同 public_id 的乐谱，未执行恢复。')
        return redirect(url_for('trash'))

    score_filename = files.get('score')
    lyric_filename = files.get('lyrics')
    if not score_filename or Path(score_filename).name != score_filename:
        flash('回收站中缺少可恢复的 PDF，未执行恢复。')
        return redirect(url_for('trash'))
    if lyric_filename and Path(lyric_filename).name != lyric_filename:
        abort(400, description='回收站歌词文件名无效')

    score_source = entry_dir / score_filename
    score_target = score_file_path(item['filename'])
    lyric_source = entry_dir / lyric_filename if lyric_filename else None
    lyric_target = Path(LYRICS_DIR) / f"{item['id']}.json"
    if not score_source.is_file():
        flash('回收站中的 PDF 文件不存在，未执行恢复。')
        return redirect(url_for('trash'))
    if item.get('has_lyrics') and (not lyric_source or not lyric_source.is_file()):
        flash('这条乐谱标记了歌词，但回收站中的歌词文件不存在，未执行恢复。')
        return redirect(url_for('trash'))
    if score_target.exists() or (lyric_source and lyric_target.exists()):
        flash('目标位置已有同名文件，未执行恢复。')
        return redirect(url_for('trash'))

    moved_files = []
    try:
        score_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(score_source), str(score_target))
        moved_files.append((score_source, score_target))
        if lyric_source and lyric_source.is_file():
            lyric_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(lyric_source), str(lyric_target))
            moved_files.append((lyric_source, lyric_target))
        data.append(item)
        add_log(log, 'restore', f"从回收站恢复: {item['title']}")
        save_all(data, log)
    except Exception:
        for source, target in reversed(moved_files):
            if target.exists():
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(source))
        raise

    manifest_path.unlink(missing_ok=True)
    try:
        entry_dir.rmdir()
    except OSError:
        pass
    flash(f"已恢复：{item['title']}")
    return redirect(url_for('trash'))


@app.route('/delete/<int:item_id>', methods=['POST'])
@login_required
@catalog_write_locked
def delete(item_id):
    data, log = load_data_and_log()
    item = next((i for i in data if i['id'] == item_id), None)
    if item:
        data = [i for i in data if i['id'] != item_id]
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        deleted_dir = deleted_entry_path(f"{timestamp}_{item_id}")
        deleted_dir.mkdir(parents=True, exist_ok=False)
        moved_files = []
        manifest_path = deleted_dir / 'manifest.json'
        lyric_path = Path(LYRICS_DIR) / f"{item_id}.json"
        score_path = score_file_path(item['filename'])
        files = {}
        try:
            for label, source in (('score', score_path), ('lyrics', lyric_path)):
                if source.exists():
                    target = deleted_dir / source.name
                    shutil.move(str(source), str(target))
                    moved_files.append((source, target))
                    files[label] = target.name
            write_json_atomic(manifest_path, {
                'version': 1,
                'deleted_at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
                'item': item,
                'files': files,
            }, indent=2)
            add_log(log, 'delete', f"移入回收站: {item['title']}")
            save_all(data, log)
        except Exception:
            manifest_path.unlink(missing_ok=True)
            for source, target in reversed(moved_files):
                if target.exists():
                    source.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(target), str(source))
            try:
                deleted_dir.rmdir()
            except OSError:
                pass
            raise
        flash(f"已移入回收站：{item['title']}")
    return redirect(safe_next_url(request.form.get('next')) or url_for('manage'))

def admin_port_is_open():
    import socket

    try:
        with socket.create_connection(('127.0.0.1', ADMIN_PORT), timeout=0.5):
            return True
    except OSError:
        return False


def existing_admin_is_healthy():
    from urllib.request import urlopen

    try:
        with urlopen(f'http://127.0.0.1:{ADMIN_PORT}/health', timeout=1) as response:
            payload = json.loads(response.read().decode('utf-8'))
            return response.status == 200 and payload.get('status') == 'ok'
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def open_admin_browser(login_url):
    try:
        import webbrowser
        webbrowser.open_new_tab(login_url)
    except Exception as error:
        print(f'无法自动打开浏览器：{error}')


def run_local_admin():
    """Run one local admin instance and optionally open its login page."""
    login_url = f'http://127.0.0.1:{ADMIN_PORT}/login'
    if admin_port_is_open():
        if existing_admin_is_healthy():
            print(f'检测到后台已在运行：{login_url}')
            if AUTO_OPEN_BROWSER:
                open_admin_browser(login_url)
            return
        raise RuntimeError(
            f'端口 {ADMIN_PORT} 已被其他程序占用。'
            '请关闭占用端口的程序，或在 .env 中修改 ADMIN_PORT。'
        )

    from waitress import serve

    print('Maotong 后台已启动')
    print(f'管理地址：{login_url}')
    print('按 Ctrl+C 停止服务。')
    if AUTO_OPEN_BROWSER:
        timer = threading.Timer(0.8, open_admin_browser, args=(login_url,))
        timer.daemon = True
        timer.start()
    # 管理工具仅供本机使用；不要直接监听 0.0.0.0 或暴露到公网。
    serve(app, host='127.0.0.1', port=ADMIN_PORT, threads=4)


if __name__ == '__main__':
    run_local_admin()
