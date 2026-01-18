import os
import json
import requests
import time
import shutil
import datetime
import re

# === 配置区域 ===
API_KEY = "sk-8b158d13c0a64d97ac903bc0a8a975e3"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

METADATA_FILE = os.path.join("Czech_Arias", "czech_arias_metadata.json")
SOURCE_DIR = "Czech_Arias"
DEST_SCORE_DIR = os.path.join("scores", "歌剧咏叹调")
DATA_FILE = os.path.join("js", "data.js")
BACKUP_DIR = "backup"

# 缓存翻译结果
translation_cache = {}

def translate_text(text, type="aria"):
    if not text: return ""
    if text in translation_cache: return translation_cache[text]
    
    role_prompt = "你是一个专业的古典音乐翻译助手。"
    if type == "composer":
        prompt = f"将这位作曲家的名字翻译成中文。格式严格为：原文(英文或原名)/中文译名。例如：'Mozart/莫扎特'。名称：{text}"
    else:
        prompt = f"将这个古典音乐{'咏叹调' if type=='aria' else '歌剧'}名称翻译成中文。格式严格为：原文/中文译名。不要解释，不要额外标点。名称：{text}"

    print(f"   🤖 [AI翻译] 正在翻译 '{text}' ...", end="\r")
    
    try:
        resp = requests.post(DEEPSEEK_URL, headers={"Authorization": f"Bearer {API_KEY}"}, json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": role_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1
        }, timeout=15)
        
        if resp.status_code == 200:
            res = resp.json()['choices'][0]['message']['content'].strip()
            res = res.replace("**", "").replace("`", "").strip()
            translation_cache[text] = res
            print(f"   ✨ [翻译完成] {res}                               ")
            return res
    except Exception as e:
        print(f"   ⚠️ 翻译API出错: {e}")
    
    return text

# === JS数据处理辅助函数 (复用自 upload_tchaikovsky_robust.py) ===
def extract_json_from_js(content, var_name):
    pattern = f'const {var_name} = '
    start_idx = content.find(pattern)
    if start_idx == -1: return None, None
    value_start = start_idx + len(pattern)
    while value_start < len(content) and content[value_start].isspace(): value_start += 1
    if value_start >= len(content): return None, None
    
    stack = []
    end_idx = -1
    in_string = False
    quote_char = None
    escape = False

    for i in range(value_start, len(content)):
        char = content[i]
        if in_string:
            if escape: escape = False
            elif char == '\\': escape = True
            elif char == quote_char: in_string = False
        else:
            if char in ('"', "'", '`'): in_string = True; quote_char = char
            elif char in ('[', '{'): stack.append(char)
            elif char in (']', '}'):
                if not stack: break
                stack.pop()
                if not stack:
                    end_idx = i + 1
                    break
    
    if end_idx != -1:
        try:
            return json.loads(content[value_start:end_idx]), end_idx
        except: return None, None
    return None, None

def load_data_and_log():
    music_data = []
    change_log = []
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
        md, _ = extract_json_from_js(content, 'musicData')
        if md: music_data = md
        cl, _ = extract_json_from_js(content, 'changeLog')
        if cl: change_log = cl
    return music_data, change_log

def save_all(music_data, change_log):
    if not os.path.exists(BACKUP_DIR): os.makedirs(BACKUP_DIR)
    if os.path.exists(DATA_FILE):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy(DATA_FILE, os.path.join(BACKUP_DIR, f"data_backup_czech_{timestamp}.js"))

    music_data.sort(key=lambda x: x['id'], reverse=True)
    
    js_content = f"// 最后更新于 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (Czech Batch)\n"
    js_content += f"const musicData = {json.dumps(music_data, indent=4, ensure_ascii=False)};\n"
    js_content += f"const changeLog = {json.dumps(change_log, indent=4, ensure_ascii=False)};\n"
    
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        f.write(js_content)

def process_upload_direct():
    if not os.path.exists(METADATA_FILE):
        print(f"❌ 元数据文件未找到: {METADATA_FILE}")
        return

    if not os.path.exists(DEST_SCORE_DIR):
        os.makedirs(DEST_SCORE_DIR)

    # 1. 加载现有数据
    music_data, change_log = load_data_and_log()
    current_max_id = max([item['id'] for item in music_data]) if music_data else 0
    print(f"📚 现有乐谱: {len(music_data)} (Max ID: {current_max_id})")

    # 2. 读取新数据
    with open(METADATA_FILE, 'r', encoding='utf-8') as f:
        items = json.load(f)

    print(f"🚀 开始处理 {len(items)} 首捷克语作品 (直接写入模式)...")
    
    success_count = 0
    new_items_added = []

    for i, item in enumerate(items):
        original_aria = item.get('aria', '')
        original_opera = item.get('opera', '')
        original_composer = item.get('composer', '')
        filename = item.get('local_filename', '')
        voice = item.get('voice', '')
        character = item.get('character', '')

        if not filename: continue
        
        source_path = os.path.join(SOURCE_DIR, filename)
        if not os.path.exists(source_path):
            print(f"⚠️ 文件缺失: {filename}")
            continue

        # 查重 (宽松匹配)
        is_duplicate = False
        for m in music_data:
            # 如果标题包含原文且作品包含原文
            if original_aria in m.get('title', '') and original_opera in m.get('work', ''):
                is_duplicate = True
                break
        
        if is_duplicate:
            print(f"⏭️ [跳过] 已存在: {original_aria}")
            continue

        print(f"\n[{i+1}/{len(items)}] 处理: {original_aria}")

        # === 翻译 ===
        title_cn = translate_text(original_aria, "aria")
        work_cn = translate_text(original_opera, "opera")
        composer_cn = translate_text(original_composer, "composer")
        
        # === 复制文件 ===
        # 生成唯一文件名防止冲突
        safe_filename = os.path.basename(filename)
        dest_filename = f"{int(time.time())}_{success_count}_{safe_filename}"
        dest_path = os.path.join(DEST_SCORE_DIR, dest_filename)
        
        try:
            shutil.copy2(source_path, dest_path)
        except Exception as e:
            print(f"   ❌ 文件复制失败: {e}")
            continue

        # === 构造数据 ===
        current_max_id += 1
        clean_voice = voice.replace("_", " ").strip()
        
        new_entry = {
            "id": current_max_id,
            "title": title_cn,
            "composer": composer_cn,
            "work": work_cn,
            "language": "捷克语",
            "category": "歌剧咏叹调",
            "sub_category": "",
            "voice_count": "",
            "voice_types": clean_voice,
            "tonality": "",
            "description": f"角色: {character}\n原文: {original_aria}\n出处: {original_opera}",
            "filename": f"歌剧咏叹调/{dest_filename}",
            "date": datetime.date.today().strftime("%Y-%m-%d"),
            "has_lyrics": False
        }
        
        music_data.append(new_entry)
        new_items_added.append(title_cn)
        success_count += 1
        print(f"   ✅ 添加成功 -> {title_cn}")
        
        time.sleep(1) # 避免翻译太快

    # 3. 保存所有变更
    if success_count > 0:
        log_msg = f"批量添加 {success_count} 首捷克语咏叹调 (Smetana等)"
        change_log.insert(0, {"date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "type": "add", "msg": log_msg})
        if len(change_log) > 100: change_log = change_log[:100]
        
        save_all(music_data, change_log)
        print("\n" + "="*50)
        print(f"🎉 处理完成！已保存到 data.js")
    else:
        print("\n⚠️ 没有新增条目。")

if __name__ == "__main__":
    process_upload_direct()