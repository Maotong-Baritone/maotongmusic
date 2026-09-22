"""Import available aria PDFs from a saved Opera Database catalog snapshot.

The source snapshot is kept in imports/opera_database/source_arias.json. Runs are
idempotent by source URL and by a normalized composer/title/work key.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import time
import unicodedata
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "imports/opera_database/source_arias.json"
CATALOG = ROOT / "data.json"
SCORES = ROOT / "scores/歌剧咏叹调"
REPORT = ROOT / "imports/opera_database/import_report.json"
COMPOSERS = {
    "Offenbach, Jacques": "Jacques Offenbach/奥芬巴赫",
    "Thomas, Ambroise": "Ambroise Thomas/托玛",
    "Gounod, Charles": "Charles Gounod/古诺",
    "Massenet, Jules": "Jules Massenet/马斯奈",
    "Meyerbeer, Giacomo": "Giacomo Meyerbeer/梅耶贝尔",
    "Strauss, Jr., Johann": "Johann Strauss II/小约翰·施特劳斯",
    "Ponchielli, Amilcare": "Amilcare Ponchielli/庞基耶利",
    "Gomes, Antônio Carlos": "Antônio Carlos Gomes/戈梅斯",
    "Berlioz, Hector": "Hector Berlioz/柏辽兹",
    "Bizet, Georges": "Georges Bizet/比才",
    "Flotow, Friedrich": "Friedrich von Flotow/弗洛托",
    "Adam, Adolphe": "Adolphe Adam/阿道夫·亚当",
}
LANGUAGES = {"French": "法语", "German": "德语", "Italian": "意大利语", "English": "英语", "Russian": "俄语", "Czech": "捷克语", "Latin": "拉丁语"}
VOICES = {"Soprano": "女高音", "Mezzo": "女中音", "Countertenor": "假声男高音", "Contralto": "女低音", "Tenor": "男高音", "Baritone": "男中音", "Bass-Baritone": "低男中音", "Bass": "男低音"}


def plain(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]*>", "", value)).strip()


def key(value: str) -> str:
    value = value.split("/")[0]
    value = unicodedata.normalize("NFKD", value).casefold()
    return "".join(c for c in value if c.isalnum() and not unicodedata.combining(c))


def source_rows():
    rows = json.loads(SNAPSHOT.read_text(encoding="utf-8"))["data"]
    for row in rows:
        match = re.search(r"title=['\"]([^'\"]+)", row[1])
        composer = html.unescape(match.group(1)) if match else plain(row[1])
        link = re.search(r"href=['\"]([^'\"]+\.pdf)['\"]", row[6], re.I)
        if composer not in COMPOSERS or not link:
            continue
        url = html.unescape(link.group(1)).replace("http://", "https://", 1)
        language = plain(row[5]).split()[0] if plain(row[5]) else ""
        yield {"title": plain(row[0]), "composer": composer, "work": plain(row[2]),
               "character": plain(row[3]), "voice": plain(row[4]),
               "language": LANGUAGES.get(language, language), "source_url": url}


def save_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for attempt in range(5):
        try:
            os.replace(temporary, path)
            return
        except OSError:
            if attempt == 4:
                raise
            time.sleep(0.5 * (attempt + 1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--batch-id", default="opera-database-french-20260921")
    args = parser.parse_args()
    catalog = json.loads(CATALOG.read_text(encoding="utf-8-sig"))
    seen_urls = {item.get("source_url") for item in catalog}
    seen_keys = {(key(item.get("composer", "")), key(item.get("title", "")), key(item.get("work", ""))) for item in catalog}
    # Existing composers often carry a Chinese translation, so compare the English name.
    aliases = {key(v): key(v.split("/")[0]) for v in COMPOSERS.values()}
    seen_keys = {(aliases.get(c, c), t, w) for c, t, w in seen_keys}
    existing_ids = {item["id"] for item in catalog}
    report = {"source_rows": 0, "imported": [], "skipped_existing": 0, "skipped_repeated_url": 0, "failed": []}
    run_urls = set()
    today = dt.date.today().isoformat()
    for source in source_rows():
        report["source_rows"] += 1
        url = source["source_url"]
        record_key = (key(COMPOSERS[source["composer"]].split("/")[0]), key(source["title"]), key(source["work"]))
        if url in run_urls:
            report["skipped_repeated_url"] += 1
            continue
        run_urls.add(url)
        if url in seen_urls or record_key in seen_keys:
            report["skipped_existing"] += 1
            continue
        if args.limit and len(report["imported"]) >= args.limit:
            break
        public_id = str(uuid.uuid4())
        target = SCORES / f"{public_id}.pdf"
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; maotongmusic catalog importer)"})
            with urllib.request.urlopen(request, timeout=30) as response, target.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            if target.stat().st_size < 1000 or target.open("rb").read(5) != b"%PDF-":
                raise ValueError("download is not a valid PDF")
        except Exception as exc:
            target.unlink(missing_ok=True)
            report["failed"].append({"url": url, "reason": str(exc)})
            continue
        item_id = time.time_ns() // 1_000_000
        while item_id in existing_ids:
            item_id += 1
        existing_ids.add(item_id)
        voice = source["voice"]
        voice_zh = next((translation for english, translation in VOICES.items() if english.casefold() in voice.casefold()), voice)
        item = {"id": item_id, "public_id": public_id, "title": source["title"],
                "composer": COMPOSERS[source["composer"]], "work": source["work"],
                "category": "歌剧咏叹调", "sub_category": "", "voice_types": voice_zh,
                "voice_count": "", "tonality": "", "language": source["language"],
                "description": f"来源：The Opera Database；角色：{source['character']}；声部（原站）：{voice}；原站说明其所载谱件可自由再分发，并要求注明来源及遵循原文件许可。",
                "filename": f"歌剧咏叹调/{public_id}.pdf", "date": today,
                "has_lyrics": False, "import_batch_id": args.batch_id,
                "source_url": url}
        catalog.insert(0, item)
        seen_keys.add(record_key)
        seen_urls.add(url)
        report["imported"].append({"title": source["title"], "composer": source["composer"], "url": url, "file": item["filename"]})
        # Persist after each file so an interrupted batch can resume safely.
        save_json(CATALOG, catalog)
        save_json(REPORT, report)
        if len(report["imported"]) % 25 == 0:
            print(f"imported {len(report['imported'])}", flush=True)
    save_json(REPORT, report)
    print(json.dumps({k: len(v) if isinstance(v, list) else v for k, v in report.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
