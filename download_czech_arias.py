import requests
import json
import os
import re
import time
import urllib.parse
from bs4 import BeautifulSoup

# === Configuration ===
TARGET_URL = "https://theoperadatabase.com/ajax_arias.php"
BASE_URL = "https://theoperadatabase.com/arias.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Referer": "https://theoperadatabase.com/arias.php",
    "X-Requested-With": "XMLHttpRequest"
}
OUTPUT_DIR = "Czech_Arias"

def sanitize_filename(name):
    # Remove invalid chars and replace spaces
    cleaned = re.sub(r'[\\/*?:",<>|]', "", name).strip()
    return cleaned.replace(" ", "_")

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

def download_czech_arias():
    print("🚀 Starting Czech Arias Downloader...")
    
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    # 1. Fetch All Data
    # The database returns all rows if length is high enough.
    params = {
        "draw": "1",
        "start": "0",
        "length": "10000", # Increase limit to ensure we get everything
        "search[value]": "",
        "search[regex]": "false",
        "order[0][column]": "1", # Sort by Composer
        "order[0][dir]": "asc"
    }
    
    # Add columns params required by the server (0-6)
    for i in range(7):
        params[f"columns[{i}][data]"] = str(i)
        params[f"columns[{i}][name]"] = ""
        params[f"columns[{i}][searchable]"] = "true"
        params[f"columns[{i}][orderable]"] = "true"
        params[f"columns[{i}][search][value]"] = ""
        params[f"columns[{i}][search][regex]"] = "false"

    print("📡 Fetching database index from theoperadatabase.com...")
    try:
        response = requests.get(TARGET_URL, params=params, headers=HEADERS)
        response.raise_for_status()
        data = response.json()
        rows = data.get("data", [])
        print(f"✅ Index fetched. Total records: {len(rows)}")
    except Exception as e:
        print(f"❌ Failed to fetch index: {e}")
        return

    # 2. Filter for Czech Language
    target_language = "Czech"
    found_items = []

    print(f"🔍 Filtering for Language: {target_language}...")
    
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

        # Check Language (Case-insensitive)
        if target_language.lower() not in language.lower():
            continue

        # Check PDF Availability
        pdf_link = extract_link(pdf_html)
        if not pdf_link:
            continue 

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

    print(f"🎉 Found {len(found_items)} Czech arias with PDF.")
    print("-" * 50)

    # 3. Process Downloads
    success_count = 0
    metadata_list = []
    
    for item in found_items:
        # Construct URL
        full_url = item["link"]
        if not full_url.startswith("http"):
            full_url = urllib.parse.urljoin("https://theoperadatabase.com/", full_url)

        # Construct Filename: Composer_Opera_Aria_Voice.pdf to be descriptive
        safe_composer = sanitize_filename(item["composer"])
        safe_opera = sanitize_filename(item["opera"])
        safe_aria = sanitize_filename(item["aria"])
        safe_voice = sanitize_filename(item["voice"])
        
        # Limit filename length
        filename = f"{safe_composer}_{safe_opera}_{safe_aria}_{safe_voice}.pdf"
        if len(filename) > 200:
             filename = f"{safe_composer}_{safe_aria}.pdf"

        file_path = os.path.join(OUTPUT_DIR, filename)
        
        # Download
        downloaded = False
        if os.path.exists(file_path) and os.path.getsize(file_path) > 1024:
            print(f"✅ [Exists] {filename}")
            downloaded = True
        else:
            try:
                print(f"⬇️ [Downloading] {filename}...", end="\r")
                current_headers = HEADERS.copy()
                # Mozarteum specific handling if needed (though unlikely for Czech arias, mostly Dvorak/Smetana)
                if "mozarteum" in full_url:
                    if "Referer" in current_headers: del current_headers["Referer"]
                
                with requests.get(full_url, headers=current_headers, timeout=30) as r:
                    r.raise_for_status()
                    content_type = r.headers.get("Content-Type", "")
                    # Simple check for PDF content
                    if "pdf" in content_type.lower() or r.content.startswith(b"%PDF"):
                        with open(file_path, "wb") as f:
                            f.write(r.content)
                        print(f"🎉 [Success] {filename}        ")
                        downloaded = True
                        success_count += 1
                        time.sleep(0.5) # Be polite
                    else:
                        print(f"⚠️ [Not PDF] {filename} (Type: {content_type})")
            except Exception as e:
                print(f"❌ [Error] {filename}: {e}")

        if downloaded:
            # Add to metadata
            item["local_filename"] = filename
            metadata_list.append(item)

    # 4. Save Metadata
    json_path = os.path.join(OUTPUT_DIR, "czech_arias_metadata.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(metadata_list, f, indent=4, ensure_ascii=False)

    print("\n" + "="*50)
    print(f"Done! Downloaded: {success_count} / Found: {len(found_items)}")
    print(f"Metadata saved to: {json_path}")

if __name__ == "__main__":
    download_czech_arias()
