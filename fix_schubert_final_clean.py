import json
import re
import os
import datetime

# === 配置 ===
DATA_FILE = 'js/data.js'
BACKUP_DIR = 'backup'

def fix_schubert_final_clean():
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
    with open(os.path.join(BACKUP_DIR, f"data_backup_schubert_final_{timestamp}.js"), 'w', encoding='utf-8') as f:
        f.write(content)

    count = 0
    print("\n🚀 开始舒伯特数据终极清洗 (清声部/清简介/修分类)...")

    for item in music_data:
        composer = item.get('composer', '')
        
        # 锁定舒伯特
        if "Schubert" in composer or "舒伯特" in composer:
            has_changed = False
            
            # 1. 清空声部 (Voice Types) -> 新增需求
            if item.get('voice_types', '') != "":
                item['voice_types'] = ""
                has_changed = True

            # 2. 修正作品名 (Work)
            current_work = item.get('work', '')
            if current_work == "Lieder/艺术歌曲":
                item['work'] = ""
                has_changed = True

            # 3. 清空简介 (Description)
            if item.get('description', '') != "":
                item['description'] = ""
                has_changed = True

            # 4. 修正分类 (Category)
            if item.get('category', '') != "艺术歌曲":
                item['category'] = "艺术歌曲"
                has_changed = True

            if has_changed:
                count += 1

    if count > 0:
        print(f"\n✅ 成功清洗了 {count} 条舒伯特数据！")
        print("   - 声部栏: 已清空")
        print("   - 作品栏: 已移除通用标记")
        print("   - 简介栏: 已清空")
        print("   - 分类栏: 已统一为 '艺术歌曲'")
        
        change_log.insert(0, {
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), 
            "type": "update", 
            "msg": f"舒伯特数据终极清洗：清空声部与简介，保留调性与套曲名 ({count} 条)。"
        })
        
        music_data.sort(key=lambda x: x['id'], reverse=True)
        new_content = f"// 最后更新于 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (Schubert Final)\n"
        new_content += f"const musicData = {json.dumps(music_data, indent=4, ensure_ascii=False)};\n"
        new_content += f"const changeLog = {json.dumps(change_log, indent=4, ensure_ascii=False)};\n"

        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("🎉 data.js 已更新。")
    else:
        print("\n⚠️ 未发现需要清洗的数据。")

if __name__ == "__main__":
    fix_schubert_final_clean()