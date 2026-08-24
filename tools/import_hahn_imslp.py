"""Resumable IMSLP importer for Reynaldo Hahn works C-Z.

The downloader follows IMSLP's ordinary anonymous flow: it accepts the
copyright disclaimer, waits through the published 15-second delay for every
file, and then downloads the exposed PDF URL. It never handles CAPTCHA pages
or attempts to bypass membership restrictions.
"""

from __future__ import annotations

import argparse
import csv
import http.cookiejar
import json
import os
import re
import shutil
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from lxml import html


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data.json"
SCORES_DIR = ROOT / "scores"
IMPORT_DIR = ROOT / "imports" / "reynaldo_hahn"
MANIFEST_FILE = IMPORT_DIR / "manifest.json"
REPORT_FILE = IMPORT_DIR / "catalog.csv"
GAP_REPORT_FILE = IMPORT_DIR / "category_gaps.md"
DOWNLOAD_GAP_REPORT_FILE = IMPORT_DIR / "anonymous_download_gaps.md"
BACKUP_FILE = IMPORT_DIR / "data_before_hahn_import.json"
BROWSER_SCRAPE_FILE = IMPORT_DIR / "browser_scrape.json"
CHINESE_METADATA_BACKUP_FILE = IMPORT_DIR / "data_before_chinese_instrumentation.json"

CATEGORY_URL = "https://imslp.org/wiki/Category:Hahn,_Reynaldo"
COMPOSER = "Reynaldo Hahn/哈恩"
ANONYMOUS_WAIT_SECONDS = 15.5
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0 Safari/537.36 MaoTongMusicImporter/1.0"
)

ALLOWED_CATEGORIES = {
    "歌剧咏叹调",
    "歌剧重唱",
    "宗教声乐作品",
    "艺术歌曲",
    "音乐剧选段",
    "合唱作品",
    "音乐会咏叹调/世俗康塔塔",
    "声乐套曲",
    "乐谱书/曲集",
    "器乐独奏",
    "器乐分谱",
    "室内乐",
    "歌剧总谱",
    "管弦乐/交响曲",
    "协奏曲总谱",
    "宗教声乐作品总谱",
    "其他",
}
def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_title(value: str) -> str:
    value = value.split("/", 1)[0]
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def class_has(element, class_name: str) -> bool:
    return class_name in clean(element.get("class")).split()


def text_content(element) -> str:
    return clean(element.text_content()) if element is not None else ""


def first(elements):
    return elements[0] if elements else None


def first_value(rows: dict[str, str], *labels: str) -> str:
    for label in labels:
        if rows.get(label):
            return rows[label]
    return ""


def direct_row_map(root) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in root.xpath(".//tr"):
        headers = row.xpath("./th[1]")
        cells = row.xpath("./td[1]")
        if not headers or not cells:
            continue
        label = text_content(headers[0])
        value = text_content(cells[0])
        if label and value and label not in result:
            result[label] = value
    return result


class IMSLPSession:
    def __init__(self) -> None:
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )

    def open(self, url: str, *, referer: str = "", timeout: int = 60):
        url = urllib.parse.quote(url, safe=":/?&=#%")
        headers = {
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        if referer:
            headers["Referer"] = referer
        request = urllib.request.Request(url, headers=headers)
        return self.opener.open(request, timeout=timeout)

    def get_text(self, url: str, *, referer: str = "") -> tuple[str, str]:
        with self.open(url, referer=referer) as response:
            payload = response.read()
            try:
                decoded = payload.decode("utf-8")
            except UnicodeDecodeError:
                charset = response.headers.get_content_charset() or "utf-8"
                decoded = payload.decode(charset, errors="replace")
            return decoded, response.geturl()


def parse_html(payload: str, base_url: str):
    document = html.fromstring(payload, base_url=base_url)
    document.make_links_absolute(base_url)
    return document


def category_entries(session: IMSLPSession) -> list[dict[str, str]]:
    payload, final_url = session.get_text(CATEGORY_URL)
    document = parse_html(payload, final_url)
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in document.xpath('//a[contains(@href, "Hahn")]'):
        href = clean(anchor.get("href"))
        decoded = urllib.parse.unquote(href)
        if "_(Hahn," not in decoded and "_(Hahn%2C" not in href:
            continue
        headings = anchor.xpath("preceding::h3[1]")
        heading = text_content(headings[0]) if headings else ""
        match = re.match(r"([A-Z])(?:\b|\s)", heading)
        if not match:
            continue
        letter = match.group(1)
        title = re.sub(r"\s*\(Hahn,\s*Reynaldo\)\s*$", "", text_content(anchor))
        if not title or href in seen:
            continue
        seen.add(href)
        entries.append({"letter": letter, "title": title, "href": href})
    return entries


def nearest_parent_with_class(element, class_name: str):
    current = element
    while current is not None:
        if class_has(current, class_name):
            return current
        current = current.getparent()
    return None


def nearest_tab_id(element) -> str:
    current = element
    while current is not None:
        element_id = clean(current.get("id"))
        if element_id.startswith("tab"):
            return element_id
        current = current.getparent()
    return ""


def parse_work_page(session: IMSLPSession, entry: dict[str, str]) -> dict:
    payload, final_url = session.get_text(entry["href"], referer=CATEGORY_URL)
    document = parse_html(payload, final_url)
    rows = direct_row_map(document)
    files: list[dict] = []

    for block in document.xpath('//*[@id and starts-with(@id, "IMSLP")]'):
        block_id = clean(block.get("id"))
        id_match = re.fullmatch(r"IMSLP(\d+)", block_id)
        if not id_match:
            continue
        download_link = first(
            block.xpath('.//a[contains(@href, "Special:ImagefromIndex")]')
        )
        if download_link is None:
            continue
        internal_link = first(
            block.xpath('.//a[contains(concat(" ", normalize-space(@class), " "), " internal ") and contains(@href, "/images/")]')
        )
        original_filename = ""
        if internal_link is not None:
            original_filename = clean(internal_link.get("title"))
            if not original_filename:
                original_filename = urllib.parse.unquote(
                    urllib.parse.urlparse(internal_link.get("href", "")).path.rsplit("/", 1)[-1]
                )

        file_info_node = first(block.xpath('.//*[contains(concat(" ", normalize-space(@class), " "), " we_file_info2 ")]'))
        file_format_node = first(block.xpath('.//*[contains(concat(" ", normalize-space(@class), " "), " we_file_info ")]'))
        download_title_node = first(download_link.xpath('.//*[@title][1]'))
        description_en = clean(download_title_node.get("title")) if download_title_node is not None else ""
        description_en = re.sub(r"^.*?\((.*)\)$", r"\1", description_en)

        edition = nearest_parent_with_class(block, "we")
        edition_rows = direct_row_map(edition) if edition is not None else {}
        file_format = text_content(file_format_node).split(" ", 1)[0] if file_format_node is not None else ""
        if not (original_filename.lower().endswith(".pdf") or file_format.upper() == "PDF"):
            continue

        files.append(
            {
                "imslp_id": id_match.group(1),
                "description": text_content(download_link),
                "description_en": description_en,
                "handler_url": clean(download_link.get("href")),
                "original_filename": original_filename,
                "file_info": text_content(file_info_node),
                "section": nearest_tab_id(block),
                "copyright": re.sub(
                    r"\s*\[(?:tag|del|mrg).*?$",
                    "",
                    first_value(edition_rows, "版权", "Copyright"),
                    flags=re.I,
                ),
                "publisher": first_value(edition_rows, "出版者资料", "Publisher Info."),
            }
        )

    return {
        **entry,
        "source_url": final_url,
        "work_title": first_value(rows, "作品名称", "Work Title") or entry["title"],
        "alternative_title": first_value(rows, "副题名", "Alternative. Title"),
        "key": first_value(rows, "调", "Key"),
        "instrumentation": first_value(rows, "配置", "Instrumentation"),
        "genre_categories": first_value(rows, "音乐类型分类", "Genre Categories"),
        "language": first_value(rows, "语言", "Language"),
        "internal_reference": first_value(rows, "内部参考编号", "Internal Reference Number"),
        "files": files,
    }


KEY_ACCIDENTALS = {
    "C-flat": "降C",
    "G-flat": "降G",
    "D-flat": "降D",
    "A-flat": "降A",
    "E-flat": "降E",
    "B-flat": "降B",
    "F-flat": "降F",
    "C-sharp": "升C",
    "G-sharp": "升G",
    "D-sharp": "升D",
    "A-sharp": "升A",
    "E-sharp": "升E",
    "B-sharp": "升B",
    "F-sharp": "升F",
}


def translate_key(value: str) -> str:
    value = clean(value)
    if not value:
        return ""
    result = value
    for source, target in KEY_ACCIDENTALS.items():
        result = re.sub(rf"\b{re.escape(source)}\b", target, result, flags=re.I)
    result = re.sub(r"\b([A-G]) major\b", r"\1大调", result, flags=re.I)
    result = re.sub(r"\b([A-G]) minor\b", lambda m: m.group(1).lower() + "小调", result, flags=re.I)
    result = re.sub(r"(降|升)([A-G]) major\b", r"\1\2大调", result, flags=re.I)
    result = re.sub(
        r"(降|升)([A-G]) minor\b",
        lambda m: m.group(1) + m.group(2).lower() + "小调",
        result,
        flags=re.I,
    )
    result = re.sub(r"\bDorian mode\b", "多利亚调式", result, flags=re.I)
    result = re.sub(r"\bPhrygian mode\b", "弗里几亚调式", result, flags=re.I)
    return result


def language_for(work: dict) -> str:
    blob = f"{work.get('language', '')}; {work.get('genre_categories', '')}".casefold()
    labels = []
    for source, target in (
        ("french", "法语"),
        ("latin", "拉丁语"),
        ("english", "英语"),
        ("italian", "意大利语"),
        ("german", "德语"),
    ):
        if source in blob:
            labels.append(target)
    return "/".join(labels)


def translate_instrumentation(value: str) -> str:
    """Translate IMSLP instrumentation and part labels into concise Chinese."""
    result = clean(value)
    if not result:
        return ""
    if result == "下载这个文件":
        return ""
    result = result.replace("（改编版：下载这个文件）", "（改编版）")

    exact = {
        "1 piano": "钢琴",
        "2 pianos": "双钢琴",
        "Piano": "钢琴",
        "Piano solo": "钢琴独奏",
        "piano 2 hands": "钢琴独奏",
        "piano 4-hands": "钢琴四手联弹",
        "2 pianos (Nos.1-12); voice, piano (No.13)": "双钢琴（第1–12首）；声乐、钢琴（第13首）",
        "2 Violins, Viola, Cello, and Piano": "2把小提琴、中提琴、大提琴、钢琴",
        "low voice and piano": "低声部、钢琴",
        "mixed chorus (SATB)": "混声四部合唱（SATB）",
        "soprano, female chorus (SA), piano": "女高音、女声二部合唱（SA）、钢琴",
        "tenor, male chorus (TB), piano": "男高音、男声二部合唱（TB）、钢琴",
        "SATB soloists (in combinations of 3 and 4 voices), piano": "女高音、女低音、男高音、男低音独唱（3或4声部组合）、钢琴",
    }
    if result in exact:
        return exact[result]

    result = re.sub(r"violinOrchestra", "violin; Orchestra", result, flags=re.I)
    result = re.sub(r"bassoons(?=\d)", "bassoons, ", result, flags=re.I)
    for instrument, label, counter in (
        ("flutes?", "长笛", "支"),
        ("oboes?", "双簧管", "支"),
        ("clarinets?", "单簧管", "支"),
        ("bassoons?", "巴松", "支"),
        ("horns?", "圆号", "支"),
        ("trumpets?", "小号", "支"),
        ("trombones?", "长号", "支"),
        ("violins?", "小提琴", "把"),
        ("violas?", "中提琴", "把"),
        ("cellos?", "大提琴", "把"),
    ):
        result = re.sub(
            rf"\b(\d+)\s+{instrument}\b",
            lambda match, label=label, counter=counter: f"{match.group(1)}{counter}{label}",
            result,
            flags=re.I,
        )
    replacements = (
        (r"\bPiano Conductor\b", "指挥用钢琴谱"),
        (r"\bComplete Score\b", "总谱"),
        (r"\bPiano Score\b", "钢琴谱"),
        (r"\bViolin Part\b", "小提琴分谱"),
        (r"\bVocal soloists\b", "独唱"),
        (r"\bvocal soloists\b", "独唱"),
        (r"\bSoloists\b", "独唱"),
        (r"\bsoli\b", "独唱"),
        (r"\bSolo\s*:", "独奏："),
        (r"\bOrchestra\s*:", "管弦乐队："),
        (r"\bfemale chorus\b", "女声合唱"),
        (r"\bmale chorus\b", "男声合唱"),
        (r"\bmixed chorus\b", "混声合唱"),
        (r"\bchorus\b", "合唱"),
        (r"\bchoir\b", "合唱"),
        (r"\bspeaker\b", "朗诵"),
        (r"\bsoprano\b", "女高音"),
        (r"\bcontralto\b", "女低音"),
        (r"\btenor\b", "男高音"),
        (r"\blow voice\b", "低声部"),
        (r"\bvoices\b", "声乐"),
        (r"\bvoice\b", "声乐"),
        (r"\bOrchestra\b", "管弦乐队"),
        (r"\bPiano solo\b", "钢琴独奏"),
        (r"\bpiano 4[- ]hands\b", "钢琴四手联弹"),
        (r"\bpiano 2 hands\b", "钢琴独奏"),
        (r"\b2 pianos\b", "双钢琴"),
        (r"\b1 piano\b", "钢琴"),
        (r"\bpiano\b", "钢琴"),
        (r"\bharpsichord\b", "羽管键琴"),
        (r"\bdouble basses\b", "低音提琴"),
        (r"\bbasses\b", "低音提琴"),
        (r"\bbassoons?\b", "巴松"),
        (r"\bcellos?\b", "大提琴"),
        (r"\bclarinets?\b", "单簧管"),
        (r"\bcornets?\b", "短号"),
        (r"\bflutes?\b", "长笛"),
        (r"\bpiccolo\b", "短笛"),
        (r"\bhorns?\b", "圆号"),
        (r"\boboes?\b", "双簧管"),
        (r"\bpercussion\b", "打击乐"),
        (r"\btimpani\b", "定音鼓"),
        (r"\btrombones?\b", "长号"),
        (r"\btrumpets?\b", "小号"),
        (r"\bviolas?\b", "中提琴"),
        (r"\bviolins?\b", "小提琴"),
        (r"\bharp\b", "竖琴"),
        (r"\bstrings\b", "弦乐"),
        (r"\borgan\b", "管风琴"),
        (r"\balso\b", "兼"),
        (r"\bsolo\b", "独奏"),
    )
    for pattern, replacement in replacements:
        result = re.sub(pattern, replacement, result, flags=re.I)

    result = re.sub(r"\(A,\s*B♭\)", "（A、B♭调）", result)
    result = re.sub(
        r"\(([A-G](?:♭|♯)?(?:/[A-G](?:♭|♯)?)?)\)",
        r"（\1调）",
        result,
    )
    result = re.sub(r"\s+(?:and|&)\s+", "、", result, flags=re.I)
    result = re.sub(r"\s+or\s+", "或", result, flags=re.I)
    result = re.sub(r"\s*,\s*", "、", result)
    result = re.sub(r"\s*;\s*", "；", result)
    result = re.sub(r"、+", "、", result)
    result = re.sub(r"\s+", "", result)
    result = result.replace("(", "（").replace(")", "）")
    return result.strip("、；")


SUBCATEGORY_RULES = (
    ("comic operas", "喜歌剧"),
    ("operas comiques", "喜歌剧"),
    ("lyric operas", "抒情歌剧"),
    ("operettas", "轻歌剧"),
    ("operas", "歌剧"),
    ("musicals", "音乐剧"),
    ("ballets", "芭蕾舞剧"),
    ("incidental music", "戏剧配乐"),
    ("pantomimes", "哑剧配乐"),
    ("sacred oratorios", "宗教清唱剧"),
    ("secular oratorios", "世俗清唱剧"),
    ("oratorios", "清唱剧"),
    ("motets", "经文歌"),
    ("canticles", "圣歌"),
    ("sacred songs", "宗教歌曲"),
    ("madrigals", "牧歌"),
    ("chansons", "香颂"),
    ("songs", "艺术歌曲"),
    ("concertos", "协奏曲"),
    ("quartets", "四重奏"),
    ("quintets", "五重奏"),
    ("sonatinas", "小奏鸣曲"),
    ("sonatas", "奏鸣曲"),
    ("variations", "变奏曲"),
    ("preludes", "前奏曲"),
    ("nocturnes", "夜曲"),
    ("waltzes", "圆舞曲"),
    ("dances", "舞曲"),
    ("caprices", "随想曲"),
    ("canons", "卡农"),
    ("studies", "练习曲"),
    ("improvisations", "即兴曲"),
    ("vocalises", "练声曲"),
    ("suites", "组曲"),
    ("pieces", "小品"),
)


def subcategory_for(work: dict) -> str:
    genres = work.get("genre_categories", "").casefold()
    for marker, label in SUBCATEGORY_RULES:
        if marker in genres:
            return label
    return ""


def is_vocal_collection(work: dict) -> bool:
    title = work.get("work_title", "")
    genres = work.get("genre_categories", "").casefold()
    return bool(
        re.match(r"^\d+\s", title)
        or any(
            marker in normalize_title(title)
            for marker in (
                "chansons et madrigaux",
                "les feuilles blessees",
                "le ruban denoue",
                "les bretonnes",
                "juvenilia",
            )
        )
        or "song cycles" in genres
    )


def category_for(work: dict, score_file: dict) -> str:
    genres = work.get("genre_categories", "").casefold()
    instrumentation = work.get("instrumentation", "").casefold()
    title = work.get("work_title", "").casefold()
    section = score_file.get("section", "")
    blob = f"{genres}; {instrumentation}; {title}"

    if section == "tabScore2":
        return "器乐分谱"
    if any(marker in genres for marker in ("operas", "operettas", "musicals")):
        return "歌剧总谱"
    if "concertos" in genres or " concerto" in f" {title}":
        return "协奏曲总谱"
    if "sacred oratorios" in genres:
        return "宗教声乐作品总谱"
    if "secular oratorios" in genres:
        return "音乐会咏叹调/世俗康塔塔"
    if any(marker in genres for marker in ("religious works", "sacred songs", "motets", "canticles")):
        if any(marker in blob for marker in ("chorus", "orchestra", "oratorio")):
            return "宗教声乐作品总谱"
        return "宗教声乐作品"
    if any(marker in genres for marker in ("choruses", "madrigals")) or " chorus" in instrumentation:
        return "合唱作品"
    if any(marker in genres for marker in ("songs", "chansons", "melodies", "vocalises")):
        return "声乐套曲" if is_vocal_collection(work) else "艺术歌曲"
    if "arias" in genres and "voice" in instrumentation:
        return "音乐会咏叹调/世俗康塔塔"
    if any(marker in genres for marker in ("ballets", "incidental music", "pantomimes")):
        return "管弦乐/交响曲"
    if "for orchestra" in genres or "orchestra" in instrumentation:
        return "管弦乐/交响曲"
    if any(marker in genres for marker in ("quartets", "quintets", "sonatas")):
        return "室内乐" if any(marker in blob for marker in ("violin", "cello", "viola", "flute", "clarinet")) else "器乐独奏"
    if any(marker in instrumentation for marker in ("violin", "cello", "viola", "flute", "clarinet", "harp")) and "," in instrumentation:
        return "室内乐"
    if "2 piano" in blob or "piano 4 hands" in blob or "for 2 players" in genres:
        return "室内乐"
    if "piano" in instrumentation or "for piano" in genres:
        return "器乐独奏"
    return "其他"


def voice_types_for(work: dict, score_file: dict) -> str:
    instrumentation = translate_instrumentation(work.get("instrumentation", ""))
    description = clean(score_file.get("description_en") or score_file.get("description"))
    if description == "下载这个文件":
        description = ""
    else:
        description = translate_instrumentation(description)
    section = score_file.get("section", "")
    if section == "tabScore2":
        return f"{description}（分谱）" if description else "器乐分谱"
    if section == "tabArrTrans":
        return f"{instrumentation}（改编版：{description}）" if description else f"{instrumentation}（改编版）"
    if section == "tabScore3":
        return f"{instrumentation}（声乐谱）" if instrumentation else "声乐谱"
    return instrumentation


def eligible_in_us(score_file: dict) -> tuple[bool, str]:
    copyright_text = clean(score_file.get("copyright"))
    if "Non-PD US" in copyright_text:
        return False, "IMSLP 标记为 Non-PD US"
    if copyright_text.startswith("Public Domain") or copyright_text.startswith("Creative Commons"):
        return True, ""
    return False, f"未识别的版权状态：{copyright_text or '空白'}"


def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def replace_with_retry(source: Path, target: Path, attempts: int = 10) -> None:
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt + 1 >= attempts:
                raise
            time.sleep(0.25 * (attempt + 1))


def write_json_atomic(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    replace_with_retry(temporary, path)


def prepend_records_preserving_format(
    base_path: Path, target_path: Path, records: list[dict]
) -> None:
    """Prepend JSON-array records without reformatting the existing catalog."""
    if not records:
        return
    original = base_path.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in original else "\n"
    stripped = original.strip()
    rendered = json.dumps(records, ensure_ascii=False, indent=4).replace("\n", newline)
    if stripped == "[]":
        updated = rendered + newline
    else:
        first_newline = original.find("\n")
        if first_newline < 0 or not stripped.startswith("["):
            raise RuntimeError("data.json 不是预期的格式化 JSON 数组")
        interior = rendered[len("[" + newline) : -len(newline + "]")]
        updated = (
            original[: first_newline + 1]
            + interior
            + ","
            + newline
            + original[first_newline + 1 :]
        )
    temporary = target_path.with_suffix(target_path.suffix + ".tmp")
    temporary.write_bytes(updated.encode("utf-8"))
    replace_with_retry(temporary, target_path)


def build_manifest(session: IMSLPSession) -> dict:
    existing_data = load_json(DATA_FILE, [])
    existing_titles = {
        normalize_title(item.get("title", ""))
        for item in existing_data
        if clean(item.get("composer")).startswith("Reynaldo Hahn")
    }
    old_manifest = load_json(MANIFEST_FILE, {})
    old_files = {
        score_file.get("imslp_id"): score_file
        for work in old_manifest.get("works", [])
        for score_file in work.get("files", [])
        if score_file.get("imslp_id")
    }

    all_entries = category_entries(session)
    targets = [entry for entry in all_entries if entry["letter"] not in {"A", "B"}]
    works = []
    for index, entry in enumerate(targets, start=1):
        print(f"[metadata {index}/{len(targets)}] {entry['title']}", flush=True)
        work = parse_work_page(session, entry)
        work_exists = normalize_title(work["work_title"]) in existing_titles
        for score_file in work["files"]:
            eligible, reason = eligible_in_us(score_file)
            if work_exists:
                eligible = False
                reason = "本地目录已有同名 Hahn 作品"
            score_file["eligible"] = eligible
            score_file["skip_reason"] = reason
            score_file["category"] = category_for(work, score_file)
            score_file["sub_category"] = subcategory_for(work)
            score_file["tonality"] = translate_key(work.get("key", ""))
            score_file["language_cn"] = language_for(work)
            score_file["voice_types"] = voice_types_for(work, score_file)
            previous = old_files.get(score_file["imslp_id"], {})
            score_file["public_id"] = previous.get("public_id") or str(uuid.uuid4())
            score_file["local_filename"] = previous.get("local_filename") or (
                f"{score_file['category']}/{score_file['public_id']}.pdf"
            )
            local_path = SCORES_DIR / Path(score_file["local_filename"])
            score_file["status"] = "downloaded" if local_path.exists() else "pending"
            score_file["error"] = ""
            if score_file["category"] not in ALLOWED_CATEGORIES:
                raise RuntimeError(f"未知分类：{score_file['category']}")
        works.append(work)
        time.sleep(0.35)

    return {
        "composer": COMPOSER,
        "source_url": CATEGORY_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": {
            "skipped_letters": ["A", "B"],
            "excluded_in_current_location": "Non-PD US",
            "anonymous_wait_seconds_per_file": ANONYMOUS_WAIT_SECONDS,
        },
        "works": works,
    }


def merge_browser_confirmed_links(manifest: dict) -> int:
    """Merge the full handler URLs observed through IMSLP's browser UI."""
    browser_scrape = load_json(BROWSER_SCRAPE_FILE, {})
    browser_files_by_id = {
        score_file.get("imslp_id"): score_file
        for work in browser_scrape.get("works", [])
        for score_file in work.get("files", [])
        if score_file.get("imslp_id")
    }
    merged = 0
    for work in manifest.get("works", []):
        for score_file in work.get("files", []):
            browser_file = browser_files_by_id.get(score_file.get("imslp_id"), {})
            confirmed = browser_file.get("handler_url", "")
            if confirmed and confirmed != score_file.get("handler_url"):
                score_file["handler_url"] = confirmed
                merged += 1
            direct_url = browser_file.get("direct_url", "")
            if direct_url and direct_url != score_file.get("direct_url"):
                score_file["direct_url"] = direct_url
                score_file["direct_url_waited_at"] = browser_file.get("direct_url_waited_at", "")
                merged += 1
            resolve_blocked = browser_file.get("resolve_blocked") is True
            if resolve_blocked and score_file.get("status") != "downloaded" and not direct_url:
                blocked_error = clean(
                    browser_file.get("resolve_error") or "匿名下载页没有提供 PDF 直链"
                )
                if (
                    score_file.get("status") != "blocked"
                    or score_file.get("error") != blocked_error
                ):
                    score_file["status"] = "blocked"
                    score_file["error"] = blocked_error
                    merged += 1
            if score_file.get("status") == "error" and (
                "没有出现 PDF 地址" in score_file.get("error", "")
                or "friendlyredirect" in score_file.get("error", "")
            ):
                score_file["status"] = "pending"
                score_file["error"] = ""
    return merged


def apply_manifest_defaults(manifest: dict) -> int:
    """Normalize display metadata while preserving the original IMSLP fields."""
    updated = 0
    for work in manifest.get("works", []):
        for score_file in work.get("files", []):
            if score_file.get("language_cn") == "无歌词":
                score_file["language_cn"] = ""
                updated += 1
            voice_types = voice_types_for(work, score_file)
            if score_file.get("voice_types") != voice_types:
                score_file["voice_types"] = voice_types
                updated += 1
    return updated


def handler_document(session: IMSLPSession, handler_url: str):
    payload, final_url = session.get_text(handler_url)
    document = parse_html(payload, final_url)
    accept_links = document.xpath('//a[contains(@href, "Special:IMSLPDisclaimerAccept")]/@href')
    if accept_links:
        payload, final_url = session.get_text(accept_links[0], referer=handler_url)
        document = parse_html(payload, final_url)
    return document, final_url


def resolve_pdf_url(session: IMSLPSession, handler_url: str) -> str:
    started = time.monotonic()
    document, final_url = handler_document(session, handler_url)
    captcha_text = text_content(document).casefold()
    if "captcha" in captcha_text or "验证码" in captcha_text:
        raise RuntimeError("IMSLP 显示 CAPTCHA；脚本按策略停止，不自动处理")
    wait_nodes = document.xpath('//*[@id="sm_dl_wait"]')
    direct_url = clean(wait_nodes[0].get("data-id")) if wait_nodes else ""
    if not direct_url:
        pdf_links = document.xpath('//a[contains(translate(@href, "PDF", "pdf"), ".pdf")]/@href')
        direct_url = clean(pdf_links[0]) if pdf_links else ""
    if not direct_url:
        raise RuntimeError(f"下载页面没有出现 PDF 地址：{final_url}")
    remaining = ANONYMOUS_WAIT_SECONDS - (time.monotonic() - started)
    if remaining > 0:
        time.sleep(remaining)
    return direct_url


def download_pdf(session: IMSLPSession, score_file: dict) -> None:
    target = SCORES_DIR / Path(score_file["local_filename"])
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        score_file["status"] = "downloaded"
        score_file["error"] = ""
        return

    direct_url = score_file.get("direct_url") or resolve_pdf_url(
        session, score_file["handler_url"]
    )
    temporary = target.with_suffix(target.suffix + ".part")
    try:
        with session.open(direct_url, referer=score_file["handler_url"], timeout=180) as response:
            with temporary.open("wb") as output:
                first_chunk = response.read(65536)
                if not first_chunk.startswith(b"%PDF-"):
                    raise RuntimeError("响应不是 PDF 文件")
                output.write(first_chunk)
                shutil.copyfileobj(response, output, length=1024 * 1024)
        os.replace(temporary, target)
        score_file["status"] = "downloaded"
        score_file["error"] = ""
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def iter_eligible_files(manifest: dict):
    for work in manifest.get("works", []):
        for score_file in work.get("files", []):
            if score_file.get("eligible"):
                yield work, score_file


def download_pending(
    session: IMSLPSession, manifest: dict, limit: int, *, direct_only: bool = False
) -> None:
    pending = [
        (work, score_file)
        for work, score_file in iter_eligible_files(manifest)
        if (
            score_file.get("status") == "pending"
            if direct_only
            else score_file.get("status") != "downloaded"
        )
        and (not direct_only or score_file.get("direct_url"))
    ]
    if limit > 0:
        pending = pending[:limit]
    for index, (work, score_file) in enumerate(pending, start=1):
        label = f"{work['work_title']} / IMSLP #{score_file['imslp_id']}"
        print(f"[download {index}/{len(pending)}] {label}", flush=True)
        try:
            download_pdf(session, score_file)
            print(f"  saved: scores/{score_file['local_filename']}", flush=True)
        except (OSError, RuntimeError, urllib.error.URLError) as exc:
            score_file["status"] = "error"
            score_file["error"] = clean(exc)
            write_json_atomic(MANIFEST_FILE, manifest)
            print(f"  ERROR: {exc}", file=sys.stderr, flush=True)
            if "CAPTCHA" in str(exc):
                break
        write_json_atomic(MANIFEST_FILE, manifest)
        write_reports(manifest)


def description_for(work: dict, score_file: dict) -> str:
    parts = [
        f"来源：IMSLP #{score_file['imslp_id']}",
        f"作品页：{work['source_url']}",
        f"版本：{score_file.get('description_en') or score_file.get('description')}",
        f"版权：{score_file.get('copyright')}",
    ]
    if score_file.get("publisher"):
        parts.append(f"出版信息：{score_file['publisher']}")
    if score_file.get("original_filename"):
        parts.append(f"IMSLP 原文件：{score_file['original_filename']}")
    return "；".join(clean(part) for part in parts if clean(part).split("：", 1)[-1])


def publish_downloaded(manifest: dict) -> int:
    data = load_json(DATA_FILE, [])
    known_imslp_ids = {
        match.group(1)
        for item in data
        for match in [re.search(r"IMSLP\s*#(\d+)", clean(item.get("description")))]
        if match
    }
    existing_public_ids = {clean(item.get("public_id")) for item in data}
    next_id = max((int(item.get("id", 0)) for item in data), default=0) + 1
    additions = []

    for work, score_file in iter_eligible_files(manifest):
        if score_file.get("status") != "downloaded":
            continue
        if score_file["imslp_id"] in known_imslp_ids:
            continue
        public_id = score_file["public_id"]
        if public_id in existing_public_ids:
            continue
        additions.append(
            {
                "id": next_id,
                "public_id": public_id,
                "title": work["work_title"],
                "composer": COMPOSER,
                "work": "",
                "language": score_file.get("language_cn", ""),
                "category": score_file["category"],
                "sub_category": score_file.get("sub_category", ""),
                "voice_count": "",
                "voice_types": score_file.get("voice_types", ""),
                "tonality": score_file.get("tonality", ""),
                "description": description_for(work, score_file),
                "filename": score_file["local_filename"],
                "date": date.today().isoformat(),
                "has_lyrics": False,
            }
        )
        next_id += 1
        existing_public_ids.add(public_id)
        known_imslp_ids.add(score_file["imslp_id"])

    if not additions:
        return 0
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    if not BACKUP_FILE.exists():
        shutil.copy2(DATA_FILE, BACKUP_FILE)
    additions.sort(key=lambda item: (normalize_title(item["title"]), item["public_id"]))
    prepend_records_preserving_format(DATA_FILE, DATA_FILE, additions)
    return len(additions)


def sync_imported_defaults(manifest: dict) -> int:
    """Synchronize display metadata only on records created by this import."""
    if not BACKUP_FILE.exists():
        return 0
    current = load_json(DATA_FILE, [])
    backup = load_json(BACKUP_FILE, [])
    original_public_ids = {clean(item.get("public_id")) for item in backup}
    manifest_files = {
        score_file.get("imslp_id"): score_file
        for work in manifest.get("works", [])
        for score_file in work.get("files", [])
        if score_file.get("imslp_id")
    }
    additions = [
        item
        for item in current
        if clean(item.get("public_id")) not in original_public_ids
    ]
    updated = 0
    for item in additions:
        match = re.search(r"IMSLP\s*#(\d+)", clean(item.get("description")))
        score_file = manifest_files.get(match.group(1), {}) if match else {}
        language = clean(score_file.get("language_cn"))
        if item.get("language") == "无歌词":
            item["language"] = ""
            updated += 1
        elif not clean(item.get("language")) and language:
            item["language"] = language
            updated += 1
        voice_types = clean(score_file.get("voice_types"))
        if voice_types and item.get("voice_types") != voice_types:
            item["voice_types"] = voice_types
            updated += 1
    if updated:
        prepend_records_preserving_format(BACKUP_FILE, DATA_FILE, additions)
    return updated


def write_catalog_preserving_format(value: list[dict]) -> None:
    original = DATA_FILE.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in original else "\n"
    rendered = json.dumps(value, ensure_ascii=False, indent=4).replace("\n", newline) + newline
    temporary = DATA_FILE.with_suffix(DATA_FILE.suffix + ".tmp")
    temporary.write_bytes(rendered.encode("utf-8"))
    replace_with_retry(temporary, DATA_FILE)


def normalize_hahn_catalog_metadata() -> tuple[int, int, int]:
    """Translate Hahn instrumentation and remove explicit no-lyrics labels."""
    data = load_json(DATA_FILE, [])
    changed_records = 0
    changed_instrumentation = 0
    cleared_languages = 0
    if not CHINESE_METADATA_BACKUP_FILE.exists():
        shutil.copy2(DATA_FILE, CHINESE_METADATA_BACKUP_FILE)
    for item in data:
        if clean(item.get("composer")) != COMPOSER:
            continue
        changed = False
        translated = translate_instrumentation(item.get("voice_types", ""))
        if item.get("voice_types", "") != translated:
            item["voice_types"] = translated
            changed_instrumentation += 1
            changed = True
        if item.get("language") == "无歌词":
            item["language"] = ""
            cleared_languages += 1
            changed = True
        if changed:
            changed_records += 1
    if changed_records:
        write_catalog_preserving_format(data)
    return changed_records, changed_instrumentation, cleared_languages


def restore_catalog_format_from_backup() -> int:
    """Restore the original bytes and reapply records added after the backup."""
    if not BACKUP_FILE.exists():
        raise RuntimeError(f"缺少导入前备份：{BACKUP_FILE}")
    current = load_json(DATA_FILE, [])
    backup = load_json(BACKUP_FILE, [])
    backup_by_public_id = {clean(item.get("public_id")): item for item in backup}
    current_by_public_id = {clean(item.get("public_id")): item for item in current}
    changed_common = [
        public_id
        for public_id, backup_item in backup_by_public_id.items()
        if current_by_public_id.get(public_id) != backup_item
    ]
    if changed_common:
        raise RuntimeError(
            "备份后已有旧记录被修改，拒绝自动恢复格式："
            + ", ".join(changed_common[:5])
        )
    additions = [
        item
        for item in current
        if clean(item.get("public_id")) not in backup_by_public_id
    ]
    prepend_records_preserving_format(BACKUP_FILE, DATA_FILE, additions)
    return len(additions)


def write_reports(manifest: dict) -> None:
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "letter",
        "work_title",
        "key_original",
        "tonality",
        "genre_categories",
        "category",
        "sub_category",
        "instrumentation",
        "instrumentation_cn",
        "voice_types",
        "language",
        "imslp_id",
        "file_description",
        "section",
        "copyright",
        "publisher",
        "eligible",
        "status",
        "error",
        "skip_reason",
        "local_filename",
        "source_url",
        "handler_url",
    ]
    with REPORT_FILE.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for work in manifest.get("works", []):
            for score_file in work.get("files", []):
                writer.writerow(
                    {
                        "letter": work.get("letter", ""),
                        "work_title": work.get("work_title", ""),
                        "key_original": work.get("key", ""),
                        "tonality": score_file.get("tonality", ""),
                        "genre_categories": work.get("genre_categories", ""),
                        "category": score_file.get("category", ""),
                        "sub_category": score_file.get("sub_category", ""),
                        "instrumentation": work.get("instrumentation", ""),
                        "instrumentation_cn": translate_instrumentation(
                            work.get("instrumentation", "")
                        ),
                        "voice_types": score_file.get("voice_types", ""),
                        "language": score_file.get("language_cn", ""),
                        "imslp_id": score_file.get("imslp_id", ""),
                        "file_description": score_file.get("description_en") or score_file.get("description", ""),
                        "section": score_file.get("section", ""),
                        "copyright": score_file.get("copyright", ""),
                        "publisher": score_file.get("publisher", ""),
                        "eligible": score_file.get("eligible", False),
                        "status": score_file.get("status", ""),
                        "error": score_file.get("error", ""),
                        "skip_reason": score_file.get("skip_reason", ""),
                        "local_filename": score_file.get("local_filename", ""),
                        "source_url": work.get("source_url", ""),
                        "handler_url": score_file.get("handler_url", ""),
                    }
                )

    genre_counts = Counter()
    for work in manifest.get("works", []):
        genres = {clean(value) for value in work.get("genre_categories", "").split(";")}
        for genre in genres:
            if genre:
                genre_counts[genre] += 1
    gaps = [
        ("轻歌剧／喜歌剧总谱", ("Operettas", "Comic operas", "Operas comiques"), "暂归入“歌剧总谱”"),
        ("音乐剧总谱", ("Musicals",), "暂归入“歌剧总谱”"),
        ("芭蕾舞剧总谱", ("Ballets",), "暂归入“管弦乐/交响曲”"),
        ("戏剧／哑剧配乐", ("Incidental music", "Pantomimes"), "暂归入“管弦乐/交响曲”"),
    ]
    lines = [
        "# Reynaldo Hahn：网站分类缺口",
        "",
        "本报告只列出本次 C–Z IMSLP 作品中出现、但当前网站没有独立一级分类的体裁。",
        "",
        "| 建议分类 | IMSLP 体裁 | 涉及作品页数 | 当前临时归类 |",
        "|---|---|---:|---|",
    ]
    for proposed, markers, fallback in gaps:
        count = sum(genre_counts.get(marker, 0) for marker in markers)
        if count:
            lines.append(f"| {proposed} | {', '.join(markers)} | {count} | {fallback} |")
    lines.extend(
        [
            "",
            "## 当前网站一级分类",
            "",
            "、".join(sorted(ALLOWED_CATEGORIES)),
            "",
            "CSV 中同时保留 IMSLP 原始体裁、本站一级分类和中文子分类，后续新增分类时可批量迁移。",
            "",
        ]
    )
    GAP_REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")

    blocked_rows = [
        (work, score_file)
        for work in manifest.get("works", [])
        for score_file in work.get("files", [])
        if score_file.get("eligible") and score_file.get("status") == "blocked"
    ]
    blocked_works = {work.get("work_title", "") for work, _ in blocked_rows}
    download_gap_lines = [
        "# Reynaldo Hahn：匿名下载缺口",
        "",
        f"共 {len(blocked_rows)} 份文件（{len(blocked_works)} 部作品）在正常匿名流程中没有出现 PDF 直链，未尝试绕过 IMSLP 限制。",
        "",
        "| 作品 | IMSLP 文件号 | 版权标记 | 下载页面 |",
        "|---|---:|---|---|",
    ]
    for work, score_file in sorted(
        blocked_rows,
        key=lambda row: (normalize_title(row[0].get("work_title", "")), row[1].get("imslp_id", "")),
    ):
        title = work.get("work_title", "").replace("|", "\\|")
        copyright_text = clean(score_file.get("copyright", "")).replace("|", "\\|")
        handler_url = score_file.get("handler_url", "")
        download_gap_lines.append(
            f"| {title} | {score_file.get('imslp_id', '')} | {copyright_text} | [IMSLP]({handler_url}) |"
        )
    download_gap_lines.extend(
        [
            "",
            "这些项目仍保留在 manifest 与 CSV 中，状态为 `blocked`，以后可在登录账户或 IMSLP 页面规则变化后重试。",
            "",
        ]
    )
    DOWNLOAD_GAP_REPORT_FILE.write_text("\n".join(download_gap_lines), encoding="utf-8")


def print_summary(manifest: dict) -> None:
    works = manifest.get("works", [])
    files = [score_file for work in works for score_file in work.get("files", [])]
    eligible = [score_file for score_file in files if score_file.get("eligible")]
    statuses = Counter(score_file.get("status", "") for score_file in eligible)
    skipped = Counter(score_file.get("skip_reason", "") for score_file in files if not score_file.get("eligible"))
    categories = Counter(score_file.get("category", "") for score_file in eligible)
    print(f"works={len(works)} files={len(files)} eligible={len(eligible)}", flush=True)
    print(f"eligible_statuses={dict(statuses)}", flush=True)
    print(f"skipped={dict(skipped)}", flush=True)
    print(f"categories={dict(categories)}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scrape", action="store_true", help="重新抓取 C–Z 元数据并生成清单")
    parser.add_argument("--download", action="store_true", help="下载清单中的待处理 PDF")
    parser.add_argument("--download-limit", type=int, default=0, help="本次最多下载多少份；0 表示全部")
    parser.add_argument(
        "--direct-only",
        action="store_true",
        help="只下载已通过浏览器倒计时确认了直接地址的文件",
    )
    parser.add_argument("--publish", action="store_true", help="把已下载项目写入 data.json")
    parser.add_argument(
        "--normalize-hahn-metadata",
        action="store_true",
        help="把全部 Hahn 记录的声部／乐器改为中文，并清除“无歌词”标记",
    )
    parser.add_argument(
        "--restore-catalog-format",
        action="store_true",
        help="从导入前备份恢复 data.json 原格式，并重新插入新增记录",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    session = IMSLPSession()
    if args.scrape:
        manifest = build_manifest(session)
        write_json_atomic(MANIFEST_FILE, manifest)
        write_reports(manifest)
    else:
        manifest = load_json(MANIFEST_FILE, None)
        if manifest is None:
            print("缺少 manifest.json；请先使用 --scrape。", file=sys.stderr)
            return 2
    merged_links = merge_browser_confirmed_links(manifest)
    if merged_links:
        print(f"merged_browser_links={merged_links}", flush=True)
    applied_defaults = apply_manifest_defaults(manifest)
    if applied_defaults:
        print(f"manifest_defaults={applied_defaults}", flush=True)
    if args.download:
        download_pending(
            session,
            manifest,
            max(0, args.download_limit),
            direct_only=args.direct_only,
        )
    if args.publish:
        count = publish_downloaded(manifest)
        print(f"published={count}", flush=True)
        synced = sync_imported_defaults(manifest)
        if synced:
            print(f"metadata_synced={synced}", flush=True)
    if args.normalize_hahn_metadata:
        records, instrumentation, languages = normalize_hahn_catalog_metadata()
        print(
            "hahn_metadata_normalized="
            f"records:{records},instrumentation:{instrumentation},languages:{languages}",
            flush=True,
        )
    if args.restore_catalog_format:
        count = restore_catalog_format_from_backup()
        print(f"format_restored_with_additions={count}", flush=True)
    write_json_atomic(MANIFEST_FILE, manifest)
    write_reports(manifest)
    print_summary(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
