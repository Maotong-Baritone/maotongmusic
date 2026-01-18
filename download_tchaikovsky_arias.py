import requests
import json
import os
import re
import time
import urllib.parse
from bs4 import BeautifulSoup

# === 配置 ===
TARGET_URL = "https://theoperadatabase.com/ajax_arias.php"
BASE_URL = "https://theoperadatabase.com/arias.php" # For resolving relative URLs if needed
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Referer": "https://theoperadatabase.com/arias.php",
    "X-Requested-With": "XMLHttpRequest"
}
OUTPUT_DIR = "Tchaikovsky_Arias"

def sanitize_filename(name):
    return re.sub(r'[\\/*?:",<>|]', "", name).strip().replace(" ", "_")

def clean_html(raw_html):
    if not raw_html: return ""
    return BeautifulSoup(raw_html, "html.parser").text.strip()

def extract_link(raw_html):
    if not raw_html: return None
    soup = BeautifulSoup(raw_html, "html.parser")
    a_tag = soup.find("a")
    if a_tag and a_tag.has_attr("href"):
        return a_tag["href"]
    return None

def download_tchaikovsky_v2():
    print("🚀 Starting Tchaikovsky Arias Downloader (AJAX Method)...")
    
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    # 1. Fetch All Data
    params = {
        "draw": "1",
        "start": "0",
        "length": "6000", # Fetch all
        "search[value]": "",
        "search[regex]": "false",
        "order[0][column]": "1", # Sort by Composer
        "order[0][dir]": "asc"
    }
    # Add columns (required by server)
    for i in range(7):
        params[f"columns[{i}][data]"] = str(i)
        params[f"columns[{i}][name]"] = ""
        params[f"columns[{i}][searchable]"] = "true"
        params[f"columns[{i}][orderable]"] = "true"
        params[f"columns[{i}][search][value]"] = ""
        params[f"columns[{i}][search][regex]"] = "false"

    print("📡 Fetching database index...")
    try:
        response = requests.get(TARGET_URL, params=params, headers=HEADERS)
        response.raise_for_status()
        data = response.json()
        rows = data.get("data", [])
        print(f"✅ Index fetched. Total records: {len(rows)}")
    except Exception as e:
        print(f"❌ Failed to fetch index: {e}")
        return

    # 2. Filter & Download
    target_composers = ["Tchaikovsky", "Tschaikowsky", "Peter Ilyich", "Pyotr Ilyich"]
    found_items = []

    print(f"🔍 Filtering for Tchaikovsky...")
    
    for row in rows:
        # Row format: [Aria, Composer, Opera, Character, Voice, Language, PDF]
        if len(row) < 7: continue

        aria_name = clean_html(row[0])
        composer_html = row[1]
        composer_text = clean_html(composer_html)
        opera = clean_html(row[2])
        character = clean_html(row[3])
        voice = clean_html(row[4])
        language = clean_html(row[5])
        pdf_html = row[6]

        # Check Composer
        is_target = False
        for tc in target_composers:
            if tc.lower() in composer_text.lower():
                is_target = True
                break
        
        if not is_target:
            continue

        # Check PDF
        pdf_link = extract_link(pdf_html)
        if not pdf_link:
            continue # No PDF available

        item = {
            "aria": aria_name,
            "composer": composer_text,
            "opera": opera,
            "character": character,
            "voice": voice,
            "language": language,
            "link": pdf_link
        }
        found_items.append(item)

    print(f"🎉 Found {len(found_items)} Tchaikovsky arias with PDF.")
    print("-" * 50)

    # 3. Process Downloads
    success_count = 0
    list_file_path = os.path.join(OUTPUT_DIR, "tchaikovsky_arias_list.txt")

    with open(list_file_path, "w", encoding="utf-8") as list_file:
        list_file.write("Aria | Opera | Character | Voice | Language | Filename\n")
        list_file.write("-" * 120 + "\n")

        for item in found_items:
            # Construct URL
            # The link might be relative or absolute.
            # Usually they are like "http://dme.mozarteum.at..." or "files/..."
            full_url = item["link"]
            if not full_url.startswith("http"):
                full_url = urllib.parse.urljoin("https://theoperadatabase.com/", full_url)

            # Construct Filename
            safe_opera = sanitize_filename(item["opera"])
            safe_aria = sanitize_filename(item["aria"])
            safe_voice = sanitize_filename(item["voice"])
            
            filename = f"{safe_opera}_{safe_aria}_{safe_voice}.pdf"
            if len(filename) > 200: filename = f"{safe_aria}_{safe_voice}.pdf"
            
            file_path = os.path.join(OUTPUT_DIR, filename)
            
            # Download
            downloaded = False
            if os.path.exists(file_path) and os.path.getsize(file_path) > 5120:
                print(f"✅ [Exists] {item['aria']}")
                downloaded = True
            else:
                try:
                    print(f"⬇️ [Downloading] {item['aria']}...", end="\r")
                    # Use a fresh session or requests.get
                    # Some links (mozarteum) might need Referer handling
                    current_headers = HEADERS.copy()
                    if "mozarteum" in full_url:
                        if "Referer" in current_headers: del current_headers["Referer"]
                    
                    with requests.get(full_url, headers=current_headers, timeout=30) as r:
                        r.raise_for_status()
                        content_type = r.headers.get("Content-Type", "")
                        if "pdf" in content_type or r.content.startswith(b"%PDF"):
                            with open(file_path, "wb") as f:
                                f.write(r.content)
                            print(f"🎉 [Success] {item['aria']}        ")
                            downloaded = True
                            success_count += 1
                            time.sleep(0.5)
                        else:
                            print(f"⚠️ [Not PDF] {item['aria']} ({content_type})")
                except Exception as e:
                    print(f"❌ [Error] {item['aria']}: {e}")

            if downloaded:
                # Write to list
                line = f"{item['aria']} | {item['opera']} | {item['character']} | {item['voice']} | {item['language']} | {filename}\n"
                list_file.write(line)

    print("\n" + "="*50)
    print(f"Done! Downloaded: {success_count} / Found: {len(found_items)}")
    print(f"List saved to: {list_file_path}")

if __name__ == "__main__":
    download_tchaikovsky_v2()
