import os
import requests
from bs4 import BeautifulSoup
import time
import re
import urllib.parse

# === 配置 ===
TARGET_URLS = [
    "https://theoperadatabase.com/songs.php",
    "https://theoperadatabase.com/songs.html"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Referer": "https://theoperadatabase.com/"
}

def sanitize_filename(name):
    # 移除非法字符，将逗号和空格转换为下划线
    name = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    return name.replace(" ", "_").replace(",", "")

def is_pdf_content(content):
    return content.startswith(b'%PDF')

def parse_voice_and_key(raw_text):
    text = raw_text.strip()
    key_match = re.search(r'\((.*?)\)', text)
    tonality = "Original"
    if key_match:
        tonality = key_match.group(1).strip()
        voice_part = text.replace(f"({key_match.group(1)})", "").strip()
    else:
        voice_part = text
    
    voice_lower = voice_part.lower()
    if "high" in voice_lower: voice_std = "High"
    elif "medium" in voice_lower: voice_std = "Medium"
    elif "low" in voice_lower: voice_std = "Low"
    else: voice_std = "Voice"
    
    return voice_std, tonality

def download_art_songs_universal():
    print("🚀 [Universal Art Songs] 启动通用下载脚本...")
    print("   (将自动扫描页面所有歌曲，并按作曲家自动分文件夹)")
    
    found_table = None
    final_url = ""

    # 1. 寻找有效页面
    for url in TARGET_URLS:
        try:
            print(f"\n🌐 尝试连接: {url} ...")
            response = requests.get(url, headers=HEADERS, timeout=15)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                tables = soup.find_all("table")
                for tbl in tables:
                    txt = tbl.text.lower()[:500] 
                    if "composer" in txt and ("title" in txt or "song" in txt):
                        found_table = tbl
                        final_url = url
                        print("   ✅ 成功锁定数据表格！")
                        break
                if found_table: break
        except Exception as e:
            print(f"   ❌ 连接错误: {e}")
    
    if not found_table:
        print("\n❌ 错误：未找到歌曲表格。")
        return

    # 2. 分析列
    rows = found_table.find_all("tr")
    header_row = rows[0]
    headers = [col.text.strip().lower() for col in header_row.find_all(['th', 'td'])]
    
    col_map = {"title": -1, "composer": -1, "voice": -1}
    for i, h in enumerate(headers):
        if "title" in h or "song" in h: col_map["title"] = i
        elif "composer" in h: col_map["composer"] = i
        elif "voice" in h or "key" in h: col_map["voice"] = i
        
    if col_map["title"] == -1: col_map["title"] = 0
    if col_map["composer"] == -1: col_map["composer"] = 1
    if col_map["voice"] == -1: col_map["voice"] = 2
    
    # 3. 开始遍历所有行
    data_rows = rows[1:] if "composer" in rows[0].text.lower() else rows
    
    print(f"\n📥 开始扫描 {len(data_rows)} 首歌曲...")

    # 用一个字典记录每个作曲家的统计数据，避免重复打印表头
    composer_stats = {} 

    for row in data_rows:
        cols = row.find_all("td")
        if not cols: continue

        try:
            # === 自动提取信息 ===
            song_title = cols[col_map["title"]].text.strip() if len(cols) > col_map["title"] else "Unknown"
            raw_composer = cols[col_map["composer"]].text.strip() if len(cols) > col_map["composer"] else "Unknown_Composer"
            
            if not song_title or not raw_composer: continue

            # === 自动创建作曲家文件夹 ===
            # 将 "Schubert, Franz" 转换为 "Schubert_Franz" 这种文件名友好的格式
            clean_comp_name = sanitize_filename(raw_composer)
            if len(clean_comp_name) > 30: clean_comp_name = clean_comp_name[:30] # 防止文件夹名过长
            
            output_dir = f"{clean_comp_name}_ArtSongs"
            if not os.path.exists(output_dir): os.makedirs(output_dir)
            
            # 对应的清单文件
            list_file_path = os.path.join(output_dir, f"{clean_comp_name}_song_list.txt")
            
            # 如果是第一次遇到这个作曲家，初始化清单文件
            if clean_comp_name not in composer_stats:
                composer_stats[clean_comp_name] = {"success": 0, "exist": 0}
                if not os.path.exists(list_file_path): # 只有文件不存在时才写表头，防止覆盖追加
                    with open(list_file_path, "w", encoding="utf-8") as f:
                        f.write("Song Title | Composer | Voice Type | Tonality | Filename\n")
                        f.write("-" * 100 + "\n")

            # === 解析声部与调性 ===
            raw_voice_info = ""
            if col_map["voice"] != -1 and len(cols) > col_map["voice"]:
                raw_voice_info = cols[col_map["voice"]].text.strip()
            if not raw_voice_info and len(cols) > col_map["voice"] + 1:
                    raw_voice_info = cols[col_map["voice"] + 1].text.strip()

            voice_type, tonality = parse_voice_and_key(raw_voice_info)
            
            # === 获取链接 ===
            pdf_link_tag = row.find("a", href=re.compile(r'\.pdf$', re.IGNORECASE))
            if not pdf_link_tag: pdf_link_tag = row.find("a", class_="pdfbutton")
            if not pdf_link_tag or not pdf_link_tag.has_attr('href'): continue

            raw_url = pdf_link_tag['href']
            pdf_url = urllib.parse.urljoin(final_url, raw_url)
            
            # === 下载逻辑 ===
            safe_title = sanitize_filename(song_title)
            safe_key = sanitize_filename(tonality)
            safe_voice = sanitize_filename(voice_type)
            filename = f"{safe_title}_{safe_voice}_{safe_key}.pdf"
            if len(filename) > 200: filename = filename[:200] + ".pdf"
            
            file_path = os.path.join(output_dir, filename)
            download_success = False

            if os.path.exists(file_path) and os.path.getsize(file_path) > 1024:
                composer_stats[clean_comp_name]["exist"] += 1
                download_success = True
                # print(f"   [已存在] {clean_comp_name}: {song_title}")
            else:
                try:
                    print(f"⬇️ 下载 [{clean_comp_name}]: {song_title} ({voice_type})...")
                    with requests.get(pdf_url, headers=HEADERS, timeout=20) as r:
                        r.raise_for_status()
                        if is_pdf_content(r.content):
                            with open(file_path, 'wb') as pdf_file:
                                pdf_file.write(r.content)
                            composer_stats[clean_comp_name]["success"] += 1
                            download_success = True
                            time.sleep(0.1) # 稍微慢点，防止被封IP
                        else:
                            print("   ❌ 非PDF内容")
                except Exception as e:
                    print(f"   ❌ 下载失败: {e}")

            if download_success:
                with open(list_file_path, "a", encoding="utf-8") as f:
                    line = f"{song_title} | {raw_composer} | {voice_type} | {tonality} | {filename}\n"
                    f.write(line)

        except Exception as e:
            continue

    print("\n✅ 所有下载任务完成！统计如下：")
    for comp, stat in composer_stats.items():
        if stat['success'] > 0 or stat['exist'] > 0:
            print(f"   - {comp}: 新下载 {stat['success']} / 已有 {stat['exist']}")

if __name__ == "__main__":
    download_art_songs_universal()