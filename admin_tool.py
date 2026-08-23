import os
import json
import datetime
import hashlib
import re
import secrets
import shutil
import threading
import time
import uuid
from email.utils import parseaddr
from functools import wraps
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from flask import Flask, abort, render_template_string, request, redirect, url_for, flash, session, send_file
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()

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

AUTOMATIC_BACKUP_PATTERN = re.compile(
    r'^data_backup_\d{8}_\d{6}(?:_\d{6})?\.json$'
)
CATALOG_LOCK = threading.RLock()
ALLOWED_EXTENSIONS = {'pdf'}
ALLOWED_CATEGORIES = {
    '歌剧咏叹调', '歌剧重唱', '宗教声乐作品', '艺术歌曲', '音乐剧选段',
    '合唱作品', '音乐会咏叹调/世俗康塔塔', '声乐套曲', '乐谱书/曲集',
    '器乐独奏', '室内乐', '歌剧总谱', '管弦乐/交响曲', '协奏曲总谱',
    '宗教声乐作品总谱', '其他'
}

ADMIN_USER = os.environ.get('ADMIN_USER', 'admin')
ADMIN_PASS = os.environ.get('ADMIN_PASS')
if not ADMIN_PASS:
    raise RuntimeError('缺少 ADMIN_PASS。请先在 .env 中设置后台密码。')

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32),
    MAX_CONTENT_LENGTH=max(100 * 1024 * 1024, SUBMISSION_MAX_BYTES + 1024 * 1024),
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
        submitted = request.form.get('_csrf_token', '')
        expected = session.get('_csrf_token', '')
        if not expected or not secrets.compare_digest(submitted, expected):
            abort(400, description='表单已过期，请刷新页面后重试。')


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


def clean_original_filename(filename):
    leaf = re.split(r'[\\/]', filename or '')[-1]
    leaf = ''.join(char for char in leaf if char.isprintable()).strip()
    return leaf[:255] or 'score.pdf'


def form_text(name, label, max_length, required=False):
    value = request.form.get(name, '').strip()
    if required and not value:
        raise ValueError(f'请填写{label}')
    if len(value) > max_length:
        raise ValueError(f'{label}不能超过 {max_length} 个字符')
    return value


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
<optgroup label="🎻 器乐"><option value="器乐独奏" {{ 'selected' if current == '器乐独奏' }}>器乐独奏</option><option value="室内乐" {{ 'selected' if current == '室内乐' }}>室内乐</option></optgroup>
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
    <title>后台管理</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>body { background-color: #f8f9fa; padding: 20px; }</style>
</head>
<body>
<div class="container">
    <div class="d-flex justify-content-between mb-4"><h2>🎹 后台管理</h2><form method="post" action="/logout"><input type="hidden" name="_csrf_token" value="{{ csrf_token() }}"><button class="btn btn-outline-danger btn-sm">退出</button></form></div>
    {% with messages = get_flashed_messages() %}
        {% if messages %}<div class="alert alert-success">{{ messages[0] }}</div>{% endif %}
    {% endwith %}
    <ul class="nav nav-tabs mb-4">
        <li class="nav-item"><a class="nav-link {{ 'active' if active_tab == 'upload' else '' }}" href="/">📤 上传</a></li>
        <li class="nav-item"><a class="nav-link {{ 'active' if active_tab == 'manage' else '' }}" href="/manage">📋 管理</a></li>
        <li class="nav-item"><a class="nav-link" href="/submissions">🛡️ 投稿审核 {% set queue_count = pending_count|default(0, true) %}{% if queue_count %}<span class="badge bg-danger">{{ queue_count }}</span>{% endif %}</a></li>
        <li class="nav-item"><a class="nav-link {{ 'active' if active_tab == 'trash' else '' }}" href="/trash">♻️ 回收站 {% set recycle_count = deleted_count|default(0, true) %}{% if recycle_count %}<span class="badge bg-secondary">{{ recycle_count }}</span>{% endif %}</a></li>
        <li class="nav-item ms-auto"><a class="nav-link" href="/submit" target="_blank">查看投稿页 ↗</a></li>
    </ul>

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
        
        <div class="table-responsive">
            <table class="table table-striped table-hover mb-0 align-middle">
                <thead class="table-light">
                    <tr>
                        <th>曲名</th>
                        <th>作曲家</th>
                        <th>分类/体裁</th>
                        <th>操作</th>
                    </tr>
                </thead>
                <tbody>
                    {% for item in items %}
                    <tr>
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
                            <a href="/edit/{{ item.id }}" class="btn btn-sm btn-outline-primary">✏️</a> 
                            <form method="post" action="/delete/{{ item.id }}" class="d-inline" onsubmit="return confirm('确定将这条乐谱移入回收站吗？之后可以恢复。')"><input type="hidden" name="_csrf_token" value="{{ csrf_token() }}"><input type="hidden" name="next" value="{{ request.full_path }}"><button class="btn btn-sm btn-outline-danger" type="submit" aria-label="删除 {{ item.title }}">🗑️</button></form>
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="4" class="text-center p-5 text-muted">没有找到符合条件的乐谱<br><small>请尝试调整筛选条件</small></td></tr>
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

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['username'] == ADMIN_USER and request.form['password'] == ADMIN_PASS:
            session['logged_in'] = True
            return redirect(safe_next_url(request.args.get('next')) or url_for('index'))
        flash('用户名或密码不正确')
    return render_template_string(LOGIN_HTML)

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))


@app.errorhandler(413)
def upload_too_large(_error):
    return f'上传内容过大。投稿 PDF 上限为 {SUBMISSION_MAX_MB} MB。', 413


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
        music_data.append(item)
        add_log(change_log, 'add', f"审核通过投稿 #{submission_id}: {item['title']}")
        save_all(music_data, change_log)
        data_saved = True
        mark_approved(submission_id, new_id, item['filename'], review_note)
    except Exception:
        if data_saved:
            save_all(original_data, original_log)
        lyric_path = Path(LYRICS_DIR) / f'{new_id}.json'
        if has_lyrics and lyric_path.exists():
            lyric_path.unlink()
        if target_path.exists() and not source_path.exists():
            shutil.move(str(target_path), str(source_path))
        raise

    flash(f"投稿 #{submission_id} 已通过并发布。", 'success')
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
        music_data.append(item)
        add_log(change_log, 'add', f"添加: {item['title']}")
        try:
            save_all(music_data, change_log)
        except Exception:
            if target_path.exists():
                target_path.unlink()
            lyric_path = Path(LYRICS_DIR) / f"{new_id}.json"
            if lyric_path.exists():
                lyric_path.unlink()
            raise
        flash('成功')
        return redirect(url_for('index'))
    return render_template_string(
        HTML_TEMPLATE.replace("{% include 'category_select.html' %}", CATEGORY_SELECT_HTML),
        active_tab='upload', item=None, lyrics=None,
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
    items = data[start:start + per_page]
    page_numbers = list(range(max(1, page - 2), min(total_pages, page + 2) + 1))

    return render_template_string(
        HTML_TEMPLATE, active_tab='manage', items=items,
        keyword=keyword, composer_filter=composer_filter, category_filter=category_filter,
        page=page, per_page=per_page, total_items=total_items,
        total_pages=total_pages, page_numbers=page_numbers,
        pending_count=submission_counts()['pending'],
        deleted_count=len(load_deleted_entries()),
    )
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
        lyric_path = Path(LYRICS_DIR) / f"{item_id}.json"
        previous_lyrics = lyric_path.read_bytes() if lyric_path.exists() else None
        if category != item['category']:
            new_path = (Path(SCORES_DIR) / category / old_path.name).resolve()
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
            "filename": f"{category}/{new_path.name}"
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
        deleted_dir = Path(BACKUP_DIR) / 'deleted' / f"{timestamp}_{item.get('public_id', item_id)}"
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

if __name__ == '__main__':
    # 管理工具仅供本机使用；不要直接监听 0.0.0.0 或暴露到公网。
    app.run(host='127.0.0.1', port=5000, debug=False)
