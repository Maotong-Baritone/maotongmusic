import os
import json
import datetime
import re
import shutil
import time
from functools import wraps
from flask import Flask, render_template_string, request, redirect, url_for, flash, session
from werkzeug.utils import secure_filename

# ===⚙️ 配置区域 ===
SCORES_DIR = 'scores'
LYRICS_DIR = 'lyrics'          # 歌词存放目录
DATA_FILE = 'js/data.js'
BACKUP_DIR = 'backup'
ALLOWED_EXTENSIONS = {'pdf', 'midi', 'mp3', 'sib', 'musx'}

ADMIN_USER = 'admin'
ADMIN_PASS = 'maotong2025'

app = Flask(__name__)
app.secret_key = "maotong_secret_key_2025"

# 确保目录存在
for folder in [SCORES_DIR, BACKUP_DIR, 'js', LYRICS_DIR]:
    if not os.path.exists(folder):
        os.makedirs(folder)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def load_data_and_log():
    music_data = []
    change_log = []
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
        match_data = re.search(r'const musicData = (\[.*?\]);', content, re.DOTALL)
        if match_data:
            try: music_data = json.loads(match_data.group(1))
            except: pass
        match_log = re.search(r'const changeLog = (\[.*?\]);', content, re.DOTALL)
        if match_log:
            try: change_log = json.loads(match_log.group(1))
            except: pass
    return music_data, change_log

def save_all(music_data, change_log):
    if os.path.exists(DATA_FILE):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy(DATA_FILE, os.path.join(BACKUP_DIR, f"data_backup_{timestamp}.js"))

    music_data.sort(key=lambda x: x['id'], reverse=True)
    json_music = json.dumps(music_data, indent=4, ensure_ascii=False)
    json_log = json.dumps(change_log, indent=4, ensure_ascii=False)
    
    js_content = f"// 最后更新于 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    js_content += f"const musicData = {json_music};\n"
    js_content += f"const changeLog = {json_log};\n"
    
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        f.write(js_content)

def add_log(change_log, action_type, message):
    today = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    change_log.insert(0, {"date": today, "type": action_type, "msg": message})
    if len(change_log) > 50: change_log.pop()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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
LOGIN_HTML = """
<!doctype html>
<html lang="zh">
<head><meta charset="utf-8"><title>登录</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light d-flex align-items-center justify-content-center" style="height:100vh">
<div class="card p-4 shadow" style="width:350px">
    <h3 class="text-center mb-3">登录</h3>
    <form method="post"><input type="text" name="username" class="form-control mb-2" placeholder="User" required><input type="password" name="password" class="form-control mb-3" placeholder="Pass" required><button class="btn btn-primary w-100">Login</button></form>
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
    <div class="col-md-6"><label class="form-label small">编制 (声部/乐器)</label><input type="text" class="form-control" name="voice_types" value="{{ item.voice_types if item else '' }}" placeholder="如: Soprano, SATB"></div>
    <div class="col-md-6"><label class="form-label small">数量/类型补充</label><input type="text" class="form-control" name="voice_count" value="{{ item.voice_count if item else '' }}" placeholder="如: 二重唱"></div>
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
    <div class="d-flex justify-content-between mb-4"><h2>🎹 后台管理</h2><a href="/logout" class="btn btn-outline-danger btn-sm">退出</a></div>
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
            <input type="hidden" name="action" value="upload">
            """ + FORM_HTML + """
            <div class="mb-4 mt-3"><label class="form-label">文件 (PDF/MIDI) *</label><input type="file" class="form-control" name="file" required></div>
            <button type="submit" class="btn btn-success w-100">保存并发布</button>
        </form>
    </div></div>
    {% endif %}

    {% if active_tab == 'manage' %}
    <div class="card shadow">
        <div class="card-header bg-white">
            <form class="d-flex" action="/manage"><input class="form-control me-2" type="search" name="q" value="{{ query }}" placeholder="搜索..."><button class="btn btn-primary">搜</button></form>
        </div>
        <table class="table table-striped table-hover mb-0">
            <thead><tr><th>曲名</th><th>作曲家</th><th>分类</th><th>操作</th></tr></thead>
            <tbody>
                {% for item in items %}
                <tr>
                    <td>{{ item.title }} {% if item.has_lyrics %}<span class="badge bg-info text-dark">📖 词</span>{% endif %}</td>
                    <td>{{ item.composer }}</td>
                    <td>{{ item.category }}</td>
                    <td><a href="/edit/{{ item.id }}" class="btn btn-sm btn-outline-primary">✏️</a> <a href="/delete/{{ item.id }}" class="btn btn-sm btn-outline-danger" onclick="return confirm('删？')">🗑️</a></td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    {% endif %}

    {% if active_tab == 'edit' %}
    <div class="card shadow"><div class="card-header bg-warning"><h5>✏️ 编辑</h5></div><div class="card-body">
        <form method="post">
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
            return redirect(request.args.get('next') or url_for('index'))
        flash('错误')
    return render_template_string(LOGIN_HTML)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    if request.method == 'POST':
        file = request.files['file']
        if file and allowed_file(file.filename):
            music_data, change_log = load_data_and_log()
            new_id = 1 if not music_data else max(i['id'] for i in music_data) + 1
            
            # --- 修复核心：安全获取扩展名 ---
            # 不再依赖 safe_name 去分割，因为 safe_name 可能没有后缀
            # 既然 allowed_file 过了，说明原始 file.filename 一定有点号
            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = f"{int(time.time())}.{ext}"
            
            cat_dir = os.path.join(SCORES_DIR, request.form['category'])
            if not os.path.exists(cat_dir): os.makedirs(cat_dir)
            file.save(os.path.join(cat_dir, filename))
            
            has_lyrics = save_lyrics(new_id, request.form.get('lyrics_og', ''), request.form.get('lyrics_cn', ''))

            music_data.append({
                "id": new_id, "title": request.form['title'], "composer": request.form['composer'],
                "work": request.form.get('work',''), "language": request.form.get('language',''),
                "category": request.form['category'], "voice_count": request.form.get('voice_count',''),
                "voice_types": request.form.get('voice_types',''), "tonality": request.form.get('tonality',''),
                "description": request.form.get('description',''),
                "filename": f"{request.form['category']}/{filename}", 
                "date": datetime.date.today().strftime("%Y-%m-%d"),
                "has_lyrics": has_lyrics
            })
            add_log(change_log, 'add', f"添加: {request.form['title']}")
            save_all(music_data, change_log)
            flash('成功')
            return redirect(url_for('index'))
    return render_template_string(HTML_TEMPLATE.replace("{% include 'category_select.html' %}", CATEGORY_SELECT_HTML), active_tab='upload', item=None, lyrics=None)

@app.route('/manage')
@login_required
def manage():
    q = request.args.get('q', '').lower()
    data, _ = load_data_and_log()
    if q: data = [i for i in data if q in i['title'].lower() or q in i['composer'].lower()]
    return render_template_string(HTML_TEMPLATE, active_tab='manage', items=data, query=q)

@app.route('/edit/<int:item_id>', methods=['GET', 'POST'])
@login_required
def edit(item_id):
    data, log = load_data_and_log()
    item = next((i for i in data if i['id'] == item_id), None)
    if not item: return "404", 404
    
    if request.method == 'POST':
        item.update({
            "title": request.form['title'], "composer": request.form['composer'],
            "work": request.form.get('work',''), "language": request.form.get('language',''),
            "category": request.form['category'], "voice_count": request.form.get('voice_count',''),
            "voice_types": request.form.get('voice_types',''), "tonality": request.form.get('tonality',''),
            "description": request.form.get('description','')
        })
        has_lyrics = save_lyrics(item_id, request.form.get('lyrics_og', ''), request.form.get('lyrics_cn', ''))
        item['has_lyrics'] = has_lyrics
        
        add_log(log, 'update', f"更新: {item['title']}")
        save_all(data, log)
        flash('更新成功')
        return redirect(url_for('manage'))

    lyrics = load_lyrics(item_id)
    return render_template_string(HTML_TEMPLATE.replace("{% include 'category_select.html' %}", CATEGORY_SELECT_HTML), active_tab='edit', item=item, lyrics=lyrics)

@app.route('/delete/<int:item_id>')
@login_required
def delete(item_id):
    data, log = load_data_and_log()
    item = next((i for i in data if i['id'] == item_id), None)
    if item:
        data = [i for i in data if i['id'] != item_id]
        lyric_path = os.path.join(LYRICS_DIR, f"{item_id}.json")
        if os.path.exists(lyric_path): os.remove(lyric_path)
        
        add_log(log, 'delete', f"删除: {item['title']}")
        save_all(data, log)
        flash('已删除')
    return redirect(url_for('manage'))

if __name__ == '__main__':
    app.run(debug=True)