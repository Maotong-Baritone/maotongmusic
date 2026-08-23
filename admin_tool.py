import os
import json
import datetime
import re
import secrets
import shutil
import time
import uuid
from functools import wraps
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from flask import Flask, abort, render_template_string, request, redirect, url_for, flash, session
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()

# ===⚙️ 配置区域 ===
SCORES_DIR = 'scores'
LYRICS_DIR = 'lyrics'
DATA_FILE = 'data.json'      # 修改这里：指向根目录的 data.json
LOGS_FILE = 'logs.json'      # 新增这里：指向根目录的 logs.json
BACKUP_DIR = 'backup'
try:
    BACKUP_KEEP_COUNT = max(1, int(os.environ.get('BACKUP_KEEP_COUNT', '10')))
except ValueError:
    BACKUP_KEEP_COUNT = 10

AUTOMATIC_BACKUP_PATTERN = re.compile(
    r'^data_backup_\d{8}_\d{6}(?:_\d{6})?\.json$'
)
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
    MAX_CONTENT_LENGTH=100 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)

# 确保目录存在
for folder in [SCORES_DIR, BACKUP_DIR, 'js', LYRICS_DIR]:
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

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login', next=request.full_path))
        return f(*args, **kwargs)
    return decorated_function

def load_data_and_log():
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
    # 备份机制
    if os.path.exists(DATA_FILE):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        shutil.copy2(DATA_FILE, os.path.join(BACKUP_DIR, f"data_backup_{timestamp}.json"))
        prune_automatic_backups()

    # 按照 ID 倒序排列乐谱
    music_data.sort(key=lambda x: x['id'], reverse=True)
    
    data_temp = f"{DATA_FILE}.tmp"
    logs_temp = f"{LOGS_FILE}.tmp"
    with open(data_temp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(music_data, f, indent=4, ensure_ascii=False)
        f.write('\n')
    with open(logs_temp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(change_log, f, indent=4, ensure_ascii=False)
        f.write('\n')
    os.replace(data_temp, DATA_FILE)
    os.replace(logs_temp, LOGS_FILE)

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
    if not original.strip() and not translation.strip():
        path = os.path.join(LYRICS_DIR, f"{item_id}.json")
        if os.path.exists(path): os.remove(path)
        return False
    
    data = {
        "id": item_id,
        "original": original,
        "translation": translation
    }
    with open(os.path.join(LYRICS_DIR, f"{item_id}.json"), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    return True

def load_lyrics(item_id):
    path = os.path.join(LYRICS_DIR, f"{item_id}.json")
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"original": "", "translation": ""}

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
    <form method="post"><input type="hidden" name="_csrf_token" value="{{ csrf_token() }}"><input type="text" name="username" class="form-control mb-2" placeholder="User" autocomplete="username" required><input type="password" name="password" class="form-control mb-3" placeholder="Pass" autocomplete="current-password" required><button class="btn btn-primary w-100">Login</button></form>
</div>
</body></html>
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
                            <form method="post" action="/delete/{{ item.id }}" class="d-inline" onsubmit="return confirm('确定删除这条乐谱及其文件吗？')"><input type="hidden" name="_csrf_token" value="{{ csrf_token() }}"><button class="btn btn-sm btn-outline-danger" type="submit">🗑️</button></form>
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="4" class="text-center p-5 text-muted">没有找到符合条件的乐谱<br><small>请尝试调整筛选条件</small></td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
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
        flash('错误')
    return render_template_string(LOGIN_HTML)

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/', methods=['GET', 'POST'])
@login_required
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
    return render_template_string(HTML_TEMPLATE.replace("{% include 'category_select.html' %}", CATEGORY_SELECT_HTML), active_tab='upload', item=None, lyrics=None)

@app.route('/manage')
@login_required
def manage():
    # 获取筛选参数
    keyword = request.args.get('keyword', '').strip().lower()
    composer_filter = request.args.get('composer', '').strip().lower()
    category_filter = request.args.get('category', 'all')
    
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
        
    return render_template_string(HTML_TEMPLATE, active_tab='manage', items=data, 
                                  keyword=keyword, composer_filter=composer_filter, category_filter=category_filter)
@app.route('/edit/<int:item_id>', methods=['GET', 'POST'])
@login_required
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
            item['filename'] = old_filename
            raise
        flash('更新成功')
        return redirect(url_for('manage'))

    lyrics = load_lyrics(item_id)
    return render_template_string(HTML_TEMPLATE.replace("{% include 'category_select.html' %}", CATEGORY_SELECT_HTML), active_tab='edit', item=item, lyrics=lyrics)

@app.route('/delete/<int:item_id>', methods=['POST'])
@login_required
def delete(item_id):
    data, log = load_data_and_log()
    item = next((i for i in data if i['id'] == item_id), None)
    if item:
        data = [i for i in data if i['id'] != item_id]
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        deleted_dir = Path(BACKUP_DIR) / 'deleted' / f"{timestamp}_{item.get('public_id', item_id)}"
        deleted_dir.mkdir(parents=True, exist_ok=False)
        moved_files = []
        lyric_path = Path(LYRICS_DIR) / f"{item_id}.json"
        score_path = score_file_path(item['filename'])
        for source in (score_path, lyric_path):
            if source.exists():
                target = deleted_dir / source.name
                shutil.move(str(source), str(target))
                moved_files.append((source, target))
        add_log(log, 'delete', f"删除: {item['title']}")
        try:
            save_all(data, log)
        except Exception:
            for source, target in reversed(moved_files):
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(source))
            raise
        flash(f'已从目录移除，原文件保存在 {deleted_dir.as_posix()}')
    return redirect(url_for('manage'))

if __name__ == '__main__':
    # 管理工具仅供本机使用；不要直接监听 0.0.0.0 或暴露到公网。
    app.run(host='127.0.0.1', port=5000, debug=False)
