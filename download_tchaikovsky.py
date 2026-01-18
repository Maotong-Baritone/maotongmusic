import os
import requests
from bs4 import BeautifulSoup
import time
import re
import urllib.parse

# === 配置 ===
TARGET_URL = "https://theoperadatabase.com/arias.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Referer": "https://theoperadatabase.com/"
}

def sanitize_filename(name):
    """清洗文件名"""
    return re.sub(r'[\\/*?:\"<>|]', "", name).strip()

def is_pdf_content(content):
    """检查文件头是否为PDF"""
    return content.startswith(b'%PDF')

def clean_voice_text(text):
    """
    清洗声部文本，去掉可能混入的角色名
    """
    valid_voices = ["Soprano", "Mezzo", "Alto", "Tenor", "Baritone", "Bass", "Contralto"]
    for v in valid_voices:
        if v.lower() in text.lower():
            if "mezzo" in text.lower(): return "Mezzo-soprano"
            return v 
    return text

def download_tchaikovsky():
    print("正在连接数据库获取柴可夫斯基 (Tchaikovsky) 的咏叹调...")
    
    try:
        response = requests.get(TARGET_URL, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        table = soup.find("table", id="ariadatatable")
        
        if not table:
            print("❌ 未找到数据表格")
            return

        # 尝试获取表头以确认列的含义（辅助调试）
        header_row = table.find("tr")
        headers = [th.text.strip() for th in header_row.find_all("th")] if header_row else []
        # print(f"DEBUG: 表头 -> {headers}") 
        # 假设 headers 类似于: Aria, Composer, Opera, Voice, Key?, Range?, Link? 

        rows = table.find_all("tr")[1:] 
        
        target_composers = ["Tchaikovsky", "Tschaikowsky", "Peter Ilyich"]
        output_dir = "Tchaikovsky_Arias"
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        list_file = os.path.join(output_dir, "tchaikovsky_arias_list.txt")
        
        print(f"📂 目标目录: {output_dir}")
        print("-" * 50)

        found_count = 0
        success_count = 0

        with open(list_file, "w", encoding="utf-8") as f:
            # 写入表头 - 假设 Col 4/5 是语言或其他信息，我们先全部抓取
            f.write("Aria | Opera | Voice | Extra_Info_1 | Extra_Info_2 | Filename\n")
            f.write("-" * 120 + "\n")

            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 7: continue

                aria_name = cols[0].text.strip()
                composer = cols[1].text.strip()
                opera = cols[2].text.strip()
                raw_voice = cols[3].text.strip()
                
                # 提取额外信息，可能是语言或调性
                extra_1 = cols[4].text.strip() 
                extra_2 = cols[5].text.strip()

                # 筛选柴可夫斯基
                is_target = False
                for tc in target_composers:
                    if tc.lower() in composer.lower():
                        is_target = True
                        break
                
                if not is_target:
                    continue

                found_count += 1
                voice = clean_voice_text(raw_voice)

                # 寻找链接
                pdf_link_tag = cols[6].find("a")
                if not pdf_link_tag: pdf_link_tag = row.find("a", class_="pdfbutton")
                
                if not pdf_link_tag or not pdf_link_tag.has_attr('href'):
                    continue

                raw_url = pdf_link_tag['href']
                pdf_url = urllib.parse.urljoin(TARGET_URL, raw_url)
                
                # 构建文件名：歌剧_咏叹调_声部.pdf
                safe_opera = sanitize_filename(opera)
                safe_aria = sanitize_filename(aria_name)
                safe_voice = sanitize_filename(voice)
                
                filename = f"{safe_opera}_{safe_aria}_{safe_voice}.pdf"
                # 避免文件名过长
                if len(filename) > 200:
                    filename = f"{safe_aria}_{safe_voice}.pdf"

                file_path = os.path.join(output_dir, filename)

                download_success = False

                if os.path.exists(file_path) and os.path.getsize(file_path) > 5120:
                    print(f"✅ [已存在] {aria_name}")
                    download_success = True
                else:
                    try:
                        print(f"⬇️ [下载中] {aria_name} ...", end="\r")
                        with requests.get(pdf_url, headers=HEADERS, timeout=20) as r:
                            r.raise_for_status()
                            if is_pdf_content(r.content):
                                with open(file_path, 'wb') as pdf_file:
                                    pdf_file.write(r.content)
                                print(f"🎉 [成功] {aria_name}        ")
                                success_count += 1
                                download_success = True
                                time.sleep(0.5) 
                            else:
                                print(f"⏭️ [跳过] {aria_name} (非PDF)")
                    except Exception as e:
                        print(f"❌ [失败] {aria_name}: {e}")

                if download_success:
                    # 写入清单：作品名字、歌剧出处、声部、语言(推测在 extra_1 或 extra_2)、文件名
                    line = f"{aria_name} | {opera} | {voice} | {extra_1} | {extra_2} | {filename}\n"
                    f.write(line)

        print("\n" + "="*40)
        print(f"处理完成！")
        print(f"🔍 找到: {found_count} 首")
        print(f"📥 成功: {success_count} (含新下载)")
        print(f"📄 清单: {list_file}")
        print("注意：清单中的 'Extra_Info' 列可能包含语言或音域信息，请检查文件确认。")

    except Exception as e:
        print(f"程序出错: {e}")

if __name__ == "__main__":
    download_tchaikovsky()
