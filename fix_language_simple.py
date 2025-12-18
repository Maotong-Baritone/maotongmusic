import json
import re
import os
import datetime

# === 配置 ===
DATA_FILE = 'js/data.js'
BACKUP_DIR = 'backup'

def fix_language_simple():
    print(f"📂 正在读取 {DATA_FILE} ...")
    
    if not os.path.exists(DATA_FILE):
        print("❌ 错误：找不到数据文件！")
        return

    with open(DATA_FILE, 'r', encoding='utf-8') as f: content = f.read()

    match_data = re.search(r'const musicData = (\[.*?\]);', content, re.DOTALL)
    match_log = re.search(r'const changeLog = (\[.*?\]);', content, re.DOTALL)

    if not match_data: return
    music_data = json.loads(match_data.group(1))
    change_log = json.loads(match_log.group(1)) if match_log else []

    # 备份
    if not os.path.exists(BACKUP_DIR): os.makedirs(BACKUP_DIR)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(os.path.join(BACKUP_DIR, f"data_backup_lang_clean_{timestamp}.js"), 'w', encoding='utf-8') as f:
        f.write(content)

    count = 0
    print("\n🚀 开始简化语言标签 (只保留中文)...")

    for item in music_data:
        lang = item.get('language', '').strip()
        
        # 核心逻辑：如果检测到 "/"，就只取后面那部分
        if '/' in lang:
            # 例如 "Italian/意大利语" -> 分割成 ["Italian", "意大利语"] -> 取最后一个
            new_lang = lang.split('/')[-1].strip()
            
            # 只有当新旧不一样时才更新
            if new_lang != lang:
                # print(f"  [修改] {lang} -> {new_lang}") # 调试时可以打开
                item['language'] = new_lang
                count += 1
        
        # 额外保险：如果你之前的脚本写成了 "Italian" (没中文)，这里可以顺手补救一下
        elif lang == "Italian": item['language'] = "意大利语"; count += 1
        elif lang == "French": item['language'] = "法语"; count += 1
        elif lang == "German": item['language'] = "德语"; count += 1
        elif lang == "Latin": item['language'] = "拉丁语"; count += 1

    if count > 0:
        print(f"\n✅ 成功简化了 {count} 条数据的语言标签！")
        
        # 记录日志
        change_log.insert(0, {
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), 
            "type": "update", 
            "msg": f"批量简化语言标签：移除原文，仅保留中文显示。"
        })
        
        # 保存
        music_data.sort(key=lambda x: x['id'], reverse=True)
        json_music = json.dumps(music_data, indent=4, ensure_ascii=False)
        json_log = json.dumps(change_log, indent=4, ensure_ascii=False)
        
        new_content = f"// 最后更新于 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (Lang Clean)\n"
        new_content += f"const musicData = {json_music};\n"
        new_content += f"const changeLog = {json_log};\n"

        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            f.write(new_content)
    else:
        print("\n⚠️ 没有发现带有斜杠 '/' 的语言标签，数据可能已经是纯中文了。")

if __name__ == "__main__":
    fix_language_simple()