# -*- coding: utf-8 -*-
import os
import json
import datetime
import shutil

# 配置路径
DB_FILE = 'database.json'
FRONTEND_DATA_FILE = 'data.json'
FRONTEND_LOG_FILE = 'logs.json'
BACKUP_DIR = 'backup'

def load_db():
    """ 加载主数据库 """
    if not os.path.exists(DB_FILE):
        print(f"Error: {DB_FILE} not found.")
        return None
    
    with open(DB_FILE, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON: {e}")
            return None

def save_db(db):
    """ 保存主数据库并导出前端文件 """
    # 1. 备份
    if os.path.exists(DB_FILE):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        if not os.path.exists(BACKUP_DIR):
            os.makedirs(BACKUP_DIR)
        backup_path = os.path.join(BACKUP_DIR, f"database_backup_{timestamp}.json")
        shutil.copy(DB_FILE, backup_path)
        print(f"Database backed up to {backup_path}")

    # 2. 排序 (ID 倒序)
    db['musicData'].sort(key=lambda x: x.get('id', 0), reverse=True)
    
    # 3. 限制日志长度 (保留最近 200 条)
    if len(db.get('changeLog', [])) > 200:
        db['changeLog'] = db['changeLog'][:200]

    # 4. 保存主数据库 (格式化，易读)
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db, f, indent=4, ensure_ascii=False)
    
    # 5. 导出前端数据 (压缩，无缩进，减小体积)
    with open(FRONTEND_DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(db['musicData'], f, ensure_ascii=False)
        
    with open(FRONTEND_LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(db['changeLog'], f, ensure_ascii=False)

    print(f"Saved: {DB_FILE} (Master), {FRONTEND_DATA_FILE} (Frontend), {FRONTEND_LOG_FILE} (Frontend)")

def contains_chinese(text):
    for char in text:
        if '\u4e00' <= char <= '\u9fff':
            return True
    return False

def main():
    db = load_db()
    if not db:
        return

    music_data = db.get('musicData', [])
    change_log = db.get('changeLog', [])

    # --- 逻辑 1: 清理莫扎特声部 (Mozart Voice Types) ---
    character_to_voice_type = {
        "Count Almaviva": "Baritone", "The Countess Almaviva": "Soprano", "Susanna": "Soprano",
        "Figaro": "Bass-baritone", "Cherubino": "Mezzo-soprano", "Marcellina": "Mezzo-soprano",
        "Doctor Bartolo": "Bass", "Don Basilio": "Tenor", "Barbarina": "Soprano",
        "Don Giovanni": "Baritone", "Leporello": "Bass", "Donna Anna": "Soprano",
        "Don Ottavio": "Tenor", "Donna Elvira": "Soprano", "Zerlina": "Soprano",
        "Masetto": "Bass", "Commendatore": "Bass", "Tamino": "Tenor", "Pamina": "Soprano",
        "Papageno": "Baritone", "Papagena": "Soprano", "Sarastro": "Bass", 
        "The Queen of the Night": "Soprano", "Monostatos": "Tenor", "Fiordiligi": "Soprano",
        "Dorabella": "Mezzo-soprano", "Guglielmo": "Baritone", "Ferrando": "Tenor",
        "Despina": "Soprano", "Don Alfonso": "Bass-baritone", "Idomeneo": "Tenor",
        "Idamantes": "Mezzo-soprano", "Ilia": "Soprano", "Electra": "Soprano", "Arbaces": "Tenor",
        "Konstanze": "Soprano", "Belmonte": "Tenor", "Blondchen": "Soprano",
        "Pedrillo": "Tenor", "Osmin": "Bass", "Tito": "Tenor", "Vitellia": "Soprano",
        "Sextus": "Mezzo-soprano", "Annius": "Mezzo-soprano", "Servilia": "Soprano",
        "Publius": "Bass-baritone", "Zaide": "Soprano", "Gomatz": "Tenor", "Allazim": "Bass",
        "Sultan Soliman": "Tenor", "Zaram": "Tenor", "Alonso": "Tenor", "Juan": "Tenor",
        "Bastien": "Tenor", "Bastienne": "Soprano", "Colas": "Bass",
        "Madame Herz": "Soprano", "Madame Silberklang": "Soprano"
    }
    
    cleaned_count = 0
    for item in music_data:
        if "mozart" in item.get("composer", "").lower():
            current_voice = item.get("voice_types", "").strip()
            if current_voice in character_to_voice_type:
                new_voice = character_to_voice_type[current_voice]
                if item["voice_types"] != new_voice:
                    item["voice_types"] = new_voice
                    cleaned_count += 1
    
    if cleaned_count > 0:
        print(f"Cleaned {cleaned_count} Mozart voice type entries.")

    # --- 逻辑 2: 汉化声部 (Localize Voice Types) ---
    voice_translation_map = {
        "soprano": "Soprano/女高音", "mezzo-soprano": "Mezzo-soprano/次女高音",
        "alto": "Alto/女低音", "tenor": "Tenor/男高音", "baritone": "Baritone/男中音",
        "bass-baritone": "Bass-baritone/低男中音", "bass": "Bass/男低音",
    }

    localized_count = 0
    for item in music_data:
        original_voice_type = item.get("voice_types")
        if not original_voice_type or contains_chinese(original_voice_type) or "/" in original_voice_type:
            continue

        normalized_voice = original_voice_type.lower().strip()
        if normalized_voice in voice_translation_map:
            new_voice_type = voice_translation_map[normalized_voice]
            if original_voice_type != new_voice_type:
                item["voice_types"] = new_voice_type
                localized_count += 1

    if localized_count > 0:
        print(f"Localized {localized_count} voice type entries.")

    # --- 保存 ---
    if cleaned_count > 0 or localized_count > 0:
        today = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        change_log.insert(0, {"date": today, "type": "update", "msg": f"批量处理数据：清理 {cleaned_count} 条声部，汉化 {localized_count} 条声部。"})
        save_db(db)
    else:
        # 即使没有修改逻辑，我们也重新生成一下前端文件，确保最新
        print("No logic changes needed, ensuring frontend files are up to date...")
        save_db(db)

if __name__ == '__main__':
    main()