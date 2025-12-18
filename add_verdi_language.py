import json
import re
import os
import datetime

# === 配置 ===
DATA_FILE = 'js/data.js'
BACKUP_DIR = 'backup'

def add_verdi_language():
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
    with open(os.path.join(BACKUP_DIR, f"data_backup_verdi_lang_{timestamp}.js"), 'w', encoding='utf-8') as f:
        f.write(content)

    count = 0
    print("\n🚀 开始补充语言信息...")

    for item in music_data:
        composer = item.get('composer', '')
        
        # 锁定威尔第
        if 'Verdi' in composer or '威尔第' in composer:
            
            # 获取相关字段用于判断 (转小写)
            work_title = item.get('work', '').lower()
            desc = item.get('description', '').lower()
            
            # === 判定逻辑 ===
            lang = "Italian/意大利语" # 默认值
            
            # 1. 拉丁语 (安魂曲)
            if "requiem" in work_title or "requiem" in desc or "安魂曲" in work_title:
                lang = "Latin/拉丁语"
            
            # 2. 法语歌剧 (西西里晚祷, 耶路撒冷, 唐卡洛斯-法语版)
            # 检查作品名或描述中是否包含法语特征词
            elif any(x in work_title or x in desc for x in ["vêpres", "vepres", "siciliennes", "jérusalem", "jerusalem", "don carlos", "西西里晚祷", "耶路撒冷"]):
                # 注意：Don Carlo (意大利语) vs Don Carlos (法语)
                # 如果明确写了 Carlos 且没写 Italian version，暂定为法语
                if "don carlo" in work_title or "don carlo" in desc:
                    lang = "Italian/意大利语"
                elif "don carlos" in work_title or "don carlos" in desc:
                    lang = "French/法语"
                elif "vêpres" in desc or "西西里" in work_title:
                    lang = "French/法语"
            
            # 更新字段
            if item.get('language') != lang:
                item['language'] = lang
                count += 1
                # 打印特殊非意大利语的更新，确认脚本在工作
                if "Italian" not in lang:
                    print(f"  [特殊语言] 《{item['title']}》 -> {lang}")

    if count > 0:
        print(f"\n✅ 成功更新了 {count} 首威尔第作品的语言字段！")
        
        # 记录日志
        change_log.insert(0, {
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), 
            "type": "update", 
            "msg": f"批量更新威尔第作品语言：主要为意大利语，包含部分法语和拉丁语。"
        })
        
        # 保存
        music_data.sort(key=lambda x: x['id'], reverse=True)
        json_music = json.dumps(music_data, indent=4, ensure_ascii=False)
        json_log = json.dumps(change_log, indent=4, ensure_ascii=False)
        
        new_content = f"// 最后更新于 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (Verdi Language)\n"
        new_content += f"const musicData = {json_music};\n"
        new_content += f"const changeLog = {json_log};\n"

        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            f.write(new_content)
    else:
        print("\n⚠️ 没有数据发生变化。")

if __name__ == "__main__":
    add_verdi_language()