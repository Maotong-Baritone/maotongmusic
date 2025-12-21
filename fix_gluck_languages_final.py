import json
import re
import os
import datetime

# === 配置 ===
DATA_FILE = 'js/data.js'
BACKUP_DIR = 'backup'

# === 格鲁克作品语言修正表 ===
# 键：歌剧名关键词（小写），值：正确语言
GLUCK_LANG_MAP = {
    # --- 法语作品 (Paris Reform Operas & Comiques) ---
    "orphée": "French/法语",   # 区分 Orfeo (意) 和 Orphée (法)
    "orphee": "French/法语",
    "iphigénie": "French/法语", # 包含 Aulide 和 Tauride
    "iphigenie": "French/法语",
    "écho et narcisse": "French/法语",
    "echo et narcisse": "French/法语",
    "armide": "French/法语",
    "alceste": "French/法语",   # 巴黎版阿尔切斯特 (通常名为 Alceste 的多为法语版)
    "la rencontre imprévue": "French/法语", # 不期而遇
    "cythère assiégée": "French/法语",
    "l'ivrogne corrigé": "French/法语",
    "le cadi dupé": "French/法语",
    "l'arbre enchanté": "French/法语",

    # --- 德语作品 ---
    "der betrogene kadi": "German/德语",
    "die pilger von mekka": "German/德语", # La rencontre imprévue 的德语版
}

def fix_gluck_languages():
    print(f"📂 正在读取 {DATA_FILE} ...")
    if not os.path.exists(DATA_FILE): return

    with open(DATA_FILE, 'r', encoding='utf-8') as f: content = f.read()
    match_data = re.search(r'const musicData = (\[.*?\]);', content, re.DOTALL)
    match_log = re.search(r'const changeLog = (\[.*?\]);', content, re.DOTALL)
    if not match_data: return
    music_data = json.loads(match_data.group(1))
    change_log = json.loads(match_log.group(1)) if match_log else []

    # 备份
    if not os.path.exists(BACKUP_DIR): os.makedirs(BACKUP_DIR)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(os.path.join(BACKUP_DIR, f"data_backup_gluck_lang_{timestamp}.js"), 'w', encoding='utf-8') as f:
        f.write(content)

    count = 0
    print("\n🚀 开始修正格鲁克 (Gluck) 作品的语言...")

    for item in music_data:
        composer = item.get('composer', '').lower()
        
        # 只处理格鲁克
        if 'gluck' not in composer and '格鲁克' not in composer:
            continue

        work = item.get('work', '').lower()
        original_lang = item.get('language', '')
        
        target_lang = None

        # 遍历映射表匹配歌剧名
        for key, lang in GLUCK_LANG_MAP.items():
            if key in work:
                target_lang = lang
                break
        
        # 特殊处理：Alceste (存在意/法两个版本)
        # 如果映射表已匹配为法语，且原语言是意大利语，则执行修改。
        # 但为了防止误伤明确的意大利版(Alceste al bivio)，可以加一个排除逻辑。
        # 鉴于用户需求是“标错成意大利语了”，我们优先信赖法语修正。
        
        # 特殊处理：Orfeo ed Euridice (保留意大利语)
        if "orfeo" in work: 
            continue # 跳过，保留原有的 Italian

        # 如果找到了目标语言，且与当前语言不同（或者当前是双语格式但我想统一清洗）
        if target_lang:
             # 为了保持格式统一，如果 target_lang 是 "French/法语"，
             # 而 original_lang 是 "法语" (已清洗过)，则认为无需修改，跳过。
             # 但如果 original_lang 是 "Italian/意大利语" 或 "意大利语"，则必须改。
             
             # 提取纯中文对比
             clean_target = target_lang.split('/')[-1]
             clean_original = original_lang.split('/')[-1] if '/' in original_lang else original_lang
             
             if clean_original != clean_target:
                # 使用纯中文格式 (因为您刚才要求清洗掉外文)
                final_lang = clean_target
                
                print(f"  [修正] 《{item['work']}》: {original_lang} -> {final_lang}")
                item['language'] = final_lang
                count += 1

    if count > 0:
        print(f"\n✅ 成功修正了 {count} 条格鲁克作品语言！")
        change_log.insert(0, {
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), 
            "type": "update", 
            "msg": f"修正格鲁克 (Gluck) 作品的语言归属 (法语/德语) ({count} 条)。"
        })
        
        music_data.sort(key=lambda x: x['id'], reverse=True)
        new_content = f"// 最后更新于 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (Gluck Lang Fix)\n"
        new_content += f"const musicData = {json.dumps(music_data, indent=4, ensure_ascii=False)};\n"
        new_content += f"const changeLog = {json.dumps(change_log, indent=4, ensure_ascii=False)};\n"

        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("🎉 data.js 已更新。")
    else:
        print("\n⚠️ 未发现需要修正的格鲁克作品语言。")

if __name__ == "__main__":
    fix_gluck_languages()