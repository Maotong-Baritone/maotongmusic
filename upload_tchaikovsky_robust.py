import os
import json
import re
import shutil
import time
import datetime

# === 配置 ===
SOURCE_DIR = 'Tchaikovsky_Arias'
LIST_FILE = os.path.join(SOURCE_DIR, 'tchaikovsky_arias_list.txt')
DEST_SCORE_DIR = 'scores/歌剧咏叹调'
DATA_FILE = 'js/data.js'
BACKUP_DIR = 'backup'

COMPOSER_NAME = "Pyotr Ilyich Tchaikovsky/柴可夫斯基"
DEFAULT_CATEGORY = "歌剧咏叹调"

def extract_json_from_js(content, var_name):
    """
    Robustly extract a JSON array/object from a JS file assignment.
    e.g. const musicData = [ ... ];
    Handles nested brackets using a counter.
    """
    pattern = f'const {var_name} = '
    start_idx = content.find(pattern)
    if start_idx == -1:
        return None, None

    # Move to the start of the value (assuming it starts with [ or {)
    value_start = start_idx + len(pattern)
    # Skip whitespace
    while value_start < len(content) and content[value_start].isspace():
        value_start += 1
    
    if value_start >= len(content):
        return None, None

    first_char = content[value_start]
    if first_char not in ('[', '{'):
        # Maybe it's not a JSON object/array?
        print(f"Warning: Variable {var_name} does not start with [ or {{.")
        return None, None

    # Bracket counting
    stack = []
    end_idx = -1
    in_string = False
    escape = False
    quote_char = None

    for i in range(value_start, len(content)):
        char = content[i]
        
        if in_string:
            if escape:
                escape = False
            elif char == '\\':
                escape = True
            elif char == quote_char:
                in_string = False
        else:
            if char in ('"', "'", '`'): # JS strings
                in_string = True
                quote_char = char
            elif char == '[' or char == '{':
                stack.append(char)
            elif char == ']' or char == '}':
                if not stack:
                    # Should not happen if we started with [ or {
                    break 
                
                last = stack.pop()
                if (char == ']' and last != '[') or (char == '}' and last != '{'):
                    print(f"Error: Mismatched brackets at index {i}")
                    return None, None
                
                if not stack:
                    # We found the matching closing bracket
                    end_idx = i + 1
                    break
    
    if end_idx != -1:
        json_str = content[value_start:end_idx]
        try:
            data = json.loads(json_str)
            return data, end_idx
        except json.JSONDecodeError as e:
            print(f"JSON Decode Error for {var_name}: {e}")
            # Fallback: maybe use simple regex if this complicated logic failed?
            return None, None
    else:
        print(f"Could not find closing bracket for {var_name}")
        return None, None

def load_data_and_log():
    music_data = []
    change_log = []
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
        
        md, _ = extract_json_from_js(content, 'musicData')
        if md is not None: music_data = md
        else: print("❌ Failed to extract musicData")

        cl, _ = extract_json_from_js(content, 'changeLog')
        if cl is not None: change_log = cl
        else: print("⚠️ Failed to extract changeLog (or empty)")
            
    return music_data, change_log

def save_all(music_data, change_log):
    # 备份
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)
    if os.path.exists(DATA_FILE):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy(DATA_FILE, os.path.join(BACKUP_DIR, f"data_backup_tchaikovsky_{timestamp}.js"))

    # 排序
    music_data.sort(key=lambda x: x['id'], reverse=True)
    
    # 序列化
    json_music = json.dumps(music_data, indent=4, ensure_ascii=False)
    json_log = json.dumps(change_log, indent=4, ensure_ascii=False)
    
    js_content = f"// 最后更新于 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (Tchaikovsky Batch)\n"
    js_content += f"const musicData = {json_music};\n"
    js_content += f"const changeLog = {json_log};\n"
    
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        f.write(js_content)

def process_upload():
    print("🚀 开始处理柴可夫斯基乐谱导入...")
    
    if not os.path.exists(LIST_FILE):
        print(f"❌ 清单文件不存在: {LIST_FILE}")
        return

    if not os.path.exists(DEST_SCORE_DIR):
        os.makedirs(DEST_SCORE_DIR)

    music_data, change_log = load_data_and_log()
    
    if not music_data and os.path.exists(DATA_FILE) and os.path.getsize(DATA_FILE) > 1000:
        print("❌ 严重错误: 无法读取现有数据，中止操作以防数据丢失。")
        return
    
    print(f"📚 现有乐谱数量: {len(music_data)}")

    # 获取当前最大ID
    current_max_id = 0
    if music_data:
        current_max_id = max(item['id'] for item in music_data)
    
    new_count = 0
    
    with open(LIST_FILE, 'r', encoding='utf-8') as f:
        # 跳过前两行表头
        lines = f.readlines()[2:]
        
        for line in lines:
            parts = [p.strip() for p in line.split('|')]
            if len(parts) < 6: continue
            
            # Aria | Opera | Character | Voice | Language | Filename
            aria = parts[0]
            opera = parts[1]
            character = parts[2]
            voice = parts[3]
            language = parts[4]
            original_filename = parts[5]
            
            source_path = os.path.join(SOURCE_DIR, original_filename)
            if not os.path.exists(source_path):
                print(f"⚠️ 文件未找到: {original_filename}")
                continue
                
            # 检查是否重复
            is_duplicate = False
            for item in music_data:
                # 宽松匹配: 同名且同作品
                if item.get('title') == aria and item.get('work') == opera:
                    is_duplicate = True
                    break
            
            if is_duplicate:
                # print(f"⏭️ 跳过已存在: {aria}")
                continue

            # 复制文件
            safe_filename = os.path.basename(original_filename)
            dest_filename = f"{int(time.time())}_{new_count}_{safe_filename}"
            dest_path = os.path.join(DEST_SCORE_DIR, dest_filename)
            
            shutil.copy2(source_path, dest_path)
            
            current_max_id += 1
            new_item = {
                "id": current_max_id,
                "title": aria,
                "composer": COMPOSER_NAME,
                "work": opera,
                "language": language,
                "category": DEFAULT_CATEGORY,
                "sub_category": "",
                "voice_count": "", 
                "voice_types": voice, 
                "tonality": "",
                "description": f"角色: {character}",
                "filename": f"{DEFAULT_CATEGORY}/{dest_filename}", 
                "date": datetime.date.today().strftime("%Y-%m-%d"),
                "has_lyrics": False
            }
            
            music_data.append(new_item)
            new_count += 1
            print(f"✅ [新增] {aria}")

    if new_count > 0:
        # 更新日志
        today = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        change_log.insert(0, {"date": today, "type": "add", "msg": f"批量添加柴可夫斯基咏叹调 ({new_count} 首)"})
        if len(change_log) > 50: change_log.pop()
        
        save_all(music_data, change_log)
        print(f"\n🎉 成功导入 {new_count} 首乐谱！数据已保存。")
        print(f"📊 新乐谱总数: {len(music_data)}")
    else:
        print("\n⚠️ 没有新乐谱被导入 (可能全部重复)。")

if __name__ == "__main__":
    process_upload()
