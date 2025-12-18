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
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def is_pdf_content(content):
    """检查文件头是否为PDF"""
    return content.startswith(b'%PDF')

def download_by_composer():
    print("正在连接数据库获取乐谱列表...")
    
    try:
        response = requests.get(TARGET_URL, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        table = soup.find("table", id="ariadatatable")
        
        if not table:
            print("❌ 未找到数据表格")
            return

        rows = table.find_all("tr")[1:] # 跳过表头
        
        # === 交互式询问 ===
        print(f"\n✅ 数据库连接成功！共加载 {len(rows)} 条乐谱数据。")
        print("=" * 40)
        target_composer = input("请输入你想下载的作曲家名字 (支持模糊搜索，如 Verdi, Puccini, Bach): ").strip()
        
        if not target_composer:
            print("输入为空，程序退出。")
            return

        # 创建对应的目录
        clean_name = sanitize_filename(target_composer.replace(" ", "_"))
        output_dir = f"{clean_name}_Arias"
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        list_file = os.path.join(output_dir, f"{clean_name}_upload_list.txt")
        
        print(f"\n📂 目标目录: {output_dir}")
        print(f"📝 清单文件: {list_file}")
        print("-" * 50)

        found_count = 0
        success_count = 0
        fail_count = 0

        with open(list_file, "w", encoding="utf-8") as f:
            # 写入表头
            f.write("Aria | Composer | Opera | Voice | Filename\n")
            f.write("-" * 100 + "\n")

            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 7: continue

                aria_name = cols[0].text.strip()
                composer = cols[1].text.strip()
                opera = cols[2].text.strip()
                voice = cols[3].text.strip()

                # === 核心筛选逻辑 ===
                # 忽略大小写进行匹配
                if target_composer.lower() not in composer.lower():
                    continue

                found_count += 1
                
                # 寻找链接
                pdf_link_tag = cols[6].find("a")
                if not pdf_link_tag: pdf_link_tag = row.find("a", class_="pdfbutton")
                
                if not pdf_link_tag or not pdf_link_tag.has_attr('href'):
                    continue

                raw_url = pdf_link_tag['href']
                pdf_url = urllib.parse.urljoin(TARGET_URL, raw_url)
                
                safe_name = sanitize_filename(aria_name)
                filename = f"{safe_name}.pdf"
                file_path = os.path.join(output_dir, filename)

                download_success = False

                # 检查是否已存在
                if os.path.exists(file_path) and os.path.getsize(file_path) > 5120:
                    print(f"✅ [已存在] {aria_name}")
                    download_success = True
                else:
                    try:
                        print(f"⬇️ [下载中] {aria_name} ...", end="\r")
                        current_headers = HEADERS.copy()
                        if "mozarteum.at" in pdf_url:
                            del current_headers["Referer"]
                        with requests.get(pdf_url, headers=current_headers, timeout=20) as r:
                            r.raise_for_status()
                            
                            # 严格检查是否为真PDF
                            if is_pdf_content(r.content):
                                with open(file_path, 'wb') as pdf_file:
                                    pdf_file.write(r.content)
                                print(f"🎉 [成功] {aria_name}        ")
                                success_count += 1
                                download_success = True
                                time.sleep(0.5) 
                            else:
                                print(f"⏭️ [跳过] {aria_name} (非PDF/外链)")
                                fail_count += 1
                    except Exception as e:
                        print(f"❌ [失败] {aria_name}: {e}")
                        fail_count += 1

                # 只有下载成功（或文件存在）才写入清单，方便后续上传
                if download_success:
                    line = f"{aria_name} | {composer} | {opera} | {voice} | {filename}\n"
                    f.write(line)

        print("\n" + "="*40)
        print(f"🎯 作曲家: {target_composer}")
        print(f"🔍 扫描到: {found_count} 首")
        print(f"📥 成功获取: {success_count} (含新下载)")
        print(f"⚠️ 跳过/失败: {fail_count}")
        print(f"📄 上传清单已生成: {list_file}")

    except Exception as e:
        print(f"程序运行出错: {e}")

if __name__ == "__main__":
    download_by_composer()