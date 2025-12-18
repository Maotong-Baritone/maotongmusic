import json
import re
import os
import datetime

# === 配置 ===
DATA_FILE = 'js/data.js'
BACKUP_DIR = 'backup'

# === 威尔第角色与声部对照表 (包含主要歌剧) ===
# 格式：角色名 (小写) -> 标准声部
ROLE_TO_VOICE = {
    # --- Soprano / 女高音 ---
    "violetta": "Soprano/女高音", "valery": "Soprano/女高音",
    "gilda": "Soprano/女高音",
    "leonora": "Soprano/女高音", # Trovatore & Forza
    "aida": "Soprano/女高音",
    "desdemona": "Soprano/女高音",
    "lady macbeth": "Soprano/女高音", "lady": "Soprano/女高音",
    "amelia": "Soprano/女高音", # Ballo & Boccanegra
    "abigaille": "Soprano/女高音",
    "elvira": "Soprano/女高音", # Ernani
    "nannetta": "Soprano/女高音",
    "oscar": "Soprano/女高音", # 裤装角色
    "luisa": "Soprano/女高音", "luisa miller": "Soprano/女高音",
    "elisabetta": "Soprano/女高音",
    "lucrezia": "Soprano/女高音",
    "odabella": "Soprano/女高音",
    "giselda": "Soprano/女高音",
    "alice": "Soprano/女高音", "alice ford": "Soprano/女高音",
    "lina": "Soprano/女高音",
    "gulnara": "Soprano/女高音",
    "medora": "Soprano/女高音",
    "giovanna": "Soprano/女高音", "giovanna d'arco": "Soprano/女高音",
    "alzira": "Soprano/女高音",
    "amalia": "Soprano/女高音", # I masnadieri

    # --- Mezzo-Soprano / 次女高音 ---
    "azucena": "Mezzo-soprano/次女高音",
    "amneris": "Mezzo-soprano/次女高音",
    "eboli": "Mezzo-soprano/次女高音", "princess eboli": "Mezzo-soprano/次女高音",
    "fenena": "Mezzo-soprano/次女高音",
    "ulrica": "Mezzo-soprano/次女高音", # Contralto role usually
    "maddalena": "Mezzo-soprano/次女高音",
    "meg": "Mezzo-soprano/次女高音", "meg page": "Mezzo-soprano/次女高音",
    "preziosilla": "Mezzo-soprano/次女高音",
    "federica": "Mezzo-soprano/次女高音",
    "cuniza": "Mezzo-soprano/次女高音",

    # --- Tenor / 男高音 ---
    "alfredo": "Tenor/男高音", "alfredo germont": "Tenor/男高音",
    "duca": "Tenor/男高音", "duke": "Tenor/男高音", "mantua": "Tenor/男高音",
    "manrico": "Tenor/男高音",
    "radames": "Tenor/男高音",
    "otello": "Tenor/男高音",
    "riccardo": "Tenor/男高音",
    "ernani": "Tenor/男高音",
    "don carlo": "Tenor/男高音", "don carlos": "Tenor/男高音",
    "fenton": "Tenor/男高音",
    "rodolfo": "Tenor/男高音",
    "macduff": "Tenor/男高音",
    "ismaele": "Tenor/男高音",
    "foresto": "Tenor/男高音",
    "jacopo": "Tenor/男高音", "foscari": "Tenor/男高音",
    "carlo": "Tenor/男高音", # I masnadieri
    "arrigo": "Tenor/男高音",
    "gabriele": "Tenor/男高音", "adorno": "Tenor/男高音",
    "oronte": "Tenor/男高音",
    "corrado": "Tenor/男高音",
    "zamoro": "Tenor/男高音",
    "stidell": "Tenor/男高音",

    # --- Baritone / 男中音 ---
    "rigoletto": "Baritone/男中音",
    "germont": "Baritone/男中音", "giorgio germont": "Baritone/男中音",
    "conte": "Baritone/男中音", "conte di luna": "Baritone/男中音", "luna": "Baritone/男中音",
    "amonasro": "Baritone/男中音",
    "iago": "Baritone/男中音", "jago": "Baritone/男中音",
    "macbeth": "Baritone/男中音",
    "renato": "Baritone/男中音",
    "carlo": "Baritone/男中音", "don carlo": "Baritone/男中音", # Ernani & Forza (confusing, handled by context usually but defaulting to baritone for these keywords in typical aria lists)
    "rodrigo": "Baritone/男中音", "posa": "Baritone/男中音", "marquis of posa": "Baritone/男中音",
    "nabucco": "Baritone/男中音",
    "simon": "Baritone/男中音", "boccanegra": "Baritone/男中音",
    "falstaff": "Baritone/男中音",
    "miller": "Baritone/男中音",
    "francesco": "Baritone/男中音", # I masnadieri
    "ezio": "Baritone/男中音",
    "rolando": "Baritone/男中音",
    "gusmano": "Baritone/男中音",
    "seid": "Baritone/男中音",
    "monforte": "Baritone/男中音",
    "ford": "Baritone/男中音",

    # --- Bass / 男低音 ---
    "zaccaria": "Bass/男低音",
    "fiesco": "Bass/男低音",
    "filippo": "Bass/男低音", "philip": "Bass/男低音", "king philip": "Bass/男低音",
    "banquo": "Bass/男低音", "banco": "Bass/男低音",
    "silva": "Bass/男低音",
    "ramfis": "Bass/男低音",
    "sparafucile": "Bass/男低音",
    "procida": "Bass/男低音",
    "attila": "Bass/男低音",
    "pagano": "Bass/男低音",
    "walter": "Bass/男低音",
    "wurms": "Bass/男低音",
    "ferrando": "Bass/男低音"
}

def fix_verdi_data():
    print(f"📂 正在读取 {DATA_FILE} ...")
    
    if not os.path.exists(DATA_FILE):
        print("❌ 错误：找不到数据文件！")
        return

    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. 提取数据
    match_data = re.search(r'const musicData = (\[.*?\]);', content, re.DOTALL)
    match_log = re.search(r'const changeLog = (\[.*?\]);', content, re.DOTALL)

    if not match_data:
        print("❌ 错误：无法解析 musicData。")
        return

    music_data = json.loads(match_data.group(1))
    change_log = json.loads(match_log.group(1)) if match_log else []

    # 2. 自动备份
    if not os.path.exists(BACKUP_DIR): os.makedirs(BACKUP_DIR)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"data_backup_verdi_fix_{timestamp}.js")
    with open(backup_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"📦 已备份原数据到: {backup_path}")

    # 3. 开始修复
    count_composer = 0
    count_voice = 0
    
    print("\n🚀 开始修复威尔第数据...")

    for item in music_data:
        composer = item.get('composer', '')
        
        # 只要是 Verdi (不管之前写的是什么 AI Upload 还是 Giuseppe)
        if 'Verdi' in composer or '威尔第' in composer:
            
            # --- 修复 1: 作曲家名字标准化 ---
            target_composer_name = "Giuseppe Verdi/威尔第"
            if item['composer'] != target_composer_name:
                item['composer'] = target_composer_name
                count_composer += 1

            # --- 修复 2: 角色名 -> 标准声部 ---
            original_voice = item.get('voice_types', '').strip()
            voice_lower = original_voice.lower()
            
            # 移除可能存在的括号内容以便匹配 (例如 "Rigoletto (role)" -> "rigoletto")
            clean_voice_lower = re.sub(r'\s*\(.*?\)', '', voice_lower).strip()

            # 查找匹配
            matched_voice = None
            
            # 直接匹配字典
            if clean_voice_lower in ROLE_TO_VOICE:
                matched_voice = ROLE_TO_VOICE[clean_voice_lower]
            # 模糊匹配 (比如 data 里写的是 "Role: Violetta")
            else:
                for role, v_type in ROLE_TO_VOICE.items():
                    if role == clean_voice_lower or f" {role} " in f" {clean_voice_lower} ":
                        matched_voice = v_type
                        break
            
            # 如果匹配到了，并且跟现在填的不一样，就更新
            if matched_voice and item['voice_types'] != matched_voice:
                print(f"  [声部修正] {item['title']}: '{original_voice}' -> '{matched_voice}'")
                item['voice_types'] = matched_voice
                count_voice += 1
            
            # 额外检查：如果是英文标准声部，也顺便汉化一下
            elif original_voice.lower() == "soprano": item['voice_types'] = "Soprano/女高音"; count_voice += 1
            elif original_voice.lower() == "tenor": item['voice_types'] = "Tenor/男高音"; count_voice += 1
            elif original_voice.lower() == "baritone": item['voice_types'] = "Baritone/男中音"; count_voice += 1
            elif original_voice.lower() == "bass": item['voice_types'] = "Bass/男低音"; count_voice += 1
            elif "mezzo" in original_voice.lower() and "soprano" in original_voice.lower() and "次" not in original_voice: 
                item['voice_types'] = "Mezzo-soprano/次女高音"; count_voice += 1

    # 4. 保存结果
    if count_composer > 0 or count_voice > 0:
        print(f"\n✅ 修复完成！")
        print(f"   - 修正作曲家名: {count_composer} 条")
        print(f"   - 修正角色声部: {count_voice} 条")
        
        # 添加日志
        change_log.insert(0, {
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), 
            "type": "update", 
            "msg": f"批量标准化威尔第数据：修正 {count_voice} 个声部及 {count_composer} 个作曲家名。"
        })
        
        # 写入文件
        music_data.sort(key=lambda x: x['id'], reverse=True)
        json_music = json.dumps(music_data, indent=4, ensure_ascii=False)
        json_log = json.dumps(change_log, indent=4, ensure_ascii=False)
        
        new_content = f"// 最后更新于 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (Verdi Fix)\n"
        new_content += f"const musicData = {json_music};\n"
        new_content += f"const changeLog = {json_log};\n"

        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            f.write(new_content)
            
        print("🎉 data.js 已更新，请刷新网页查看效果。")
    else:
        print("\n⚠️ 未发现需要修复的数据。可能已经修复过了？")

if __name__ == "__main__":
    fix_verdi_data()