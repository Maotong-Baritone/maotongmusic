"""Build a review-only IMSLP manifest for Johannes Brahms.

This command deliberately stops before downloading or publishing anything.
It scrapes the 161 pages in IMSLP's ``Compositions`` section, proposes the
catalog metadata that would eventually be published, and writes a manifest
plus a CSV for human review.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import uuid
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.import_hahn_imslp import (  # noqa: E402
    ALLOWED_CATEGORIES,
    IMSLPSession,
    clean,
    concise_file_label,
    concise_instrumentation,
    direct_row_map,
    eligible_in_us,
    first,
    first_value,
    language_for,
    nearest_parent_with_class,
    nearest_tab_id,
    parse_html,
    text_content,
    translate_key,
)


DATA_FILE = ROOT / "data.json"
IMPORT_DIR = ROOT / "imports" / "johannes_brahms"
MANIFEST_FILE = IMPORT_DIR / "manifest.json"
REPORT_FILE = IMPORT_DIR / "review_catalog.csv"
GAP_REPORT_FILE = IMPORT_DIR / "category_gaps.md"

CATEGORY_URL = "https://imslp.org/wiki/Category:Brahms,_Johannes"
COMPOSER = "Johannes Brahms/勃拉姆斯"
COMPOSER_PAGE_SUFFIX = "_(Brahms,_Johannes)"
SCRAPE_PAUSE_SECONDS = 0.25
REVIEW_DECISIONS = {"pending", "approved", "excluded", "deferred"}
SOURCE_CACHE_DIR = ROOT / "tmp" / "brahms_metadata_cache"


class CachedMetadataSession(IMSLPSession):
    """Cache public HTML only, so parser fixes can be checked offline."""

    def get_text(self, url: str, *, referer: str = "") -> tuple[str, str]:
        parsed = urllib.parse.urlparse(url)
        if parsed.hostname != "imslp.org" or "Special:" in urllib.parse.unquote(parsed.path):
            raise ValueError("元数据阶段只允许读取 IMSLP 作品页，不读取下载处理器")
        cache_file = SOURCE_CACHE_DIR / (hashlib.sha256(url.encode()).hexdigest() + ".json")
        cached = load_json(cache_file, None)
        self.last_from_cache = bool(cached)
        if cached:
            return cached["html"], cached["url"]
        payload, final_url = super().get_text(url, referer=referer)
        write_json_atomic(cache_file, {"url": final_url, "html": payload})
        return payload, final_url


def normalize_search_text(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", clean(value))
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", normalized.casefold()).strip()


def normalize_work_identity(value: object) -> str:
    normalized = normalize_search_text(value)
    return re.sub(r"\b(?:op|woo|anh)\b.*$", "", normalized).strip()


def write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(path)


def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def richer_row_map(root) -> dict[str, str]:
    """Keep the richest repeated IMSLP table value (not the short page header)."""
    result: dict[str, str] = {}
    for row in root.xpath(".//tr"):
        headers = row.xpath("./th[1]")
        cells = row.xpath("./td[1]")
        if not headers or not cells:
            continue
        label = text_content(headers[0])
        value = text_content(cells[0])
        if label and value and len(value) > len(result.get(label, "")):
            result[label] = value
    return result


def value_for_label_fragment(rows: dict[str, str], *fragments: str) -> str:
    """Handle IMSLP labels whose visible and abbreviated spans concatenate."""
    folded_fragments = [
        re.sub(r"[\s/]+", "", clean(fragment).casefold()) for fragment in fragments
    ]
    for label, value in rows.items():
        folded_label = re.sub(r"[\s/]+", "", clean(label).casefold())
        if any(fragment in folded_label for fragment in folded_fragments):
            return value
    return ""


def movements_from_document(document, rows: dict[str, str]) -> tuple[str, list[dict[str, object]]]:
    """Preserve list numbering that IMSLP renders with CSS rather than text."""
    best_items: list[str] = []
    best_title_items: list[str] = []
    best_prefix = ""
    for row in document.xpath(".//tr"):
        headers = row.xpath("./th[1]")
        cells = row.xpath("./td[1]")
        if not headers or not cells:
            continue
        label = re.sub(r"[\s/]+", "", text_content(headers[0]).casefold())
        if "乐章" not in label and "movements" not in label and "mov'ts" not in label:
            continue
        nodes = [node for node in cells[0].xpath(".//li[not(ancestor::li)]") if text_content(node)]
        items = [text_content(node) for node in nodes]
        if len(items) > len(best_items):
            best_items = items
            best_title_items = []
            for node in nodes:
                title_node = deepcopy(node)
                for nested in title_node.xpath('.//ol | .//ul'):
                    if nested.getparent() is not None:
                        nested.getparent().remove(nested)
                best_title_items.append(text_content(title_node))
            direct_text = clean(" ".join(cells[0].xpath("./text()")))
            best_prefix = direct_text.rstrip(":：")

    if best_items:
        movements = []
        numbered = []
        for number, raw_item in enumerate(best_items, start=1):
            raw_item = re.sub(rf"^\s*{number}\.\s*", "", raw_item)
            title_item = re.sub(rf"^\s*{number}\.\s*", "", best_title_items[number - 1])
            label, key = split_trailing_key(title_item)
            movements.append({"number": number, "title": label, "key": key, "has_subsections": title_item != raw_item})
            numbered.append(f"{number}. {raw_item}")
        prefix = f"{best_prefix}: " if best_prefix else ""
        return prefix + " ".join(numbered), movements

    fallback = value_for_label_fragment(
        rows, "乐章/部分", "乐章/段落", "Movements/Sections", "Mov'ts/Sec's"
    )
    return fallback, parse_movements(fallback)


def category_entries(session: IMSLPSession) -> list[dict[str, str]]:
    """Return only IMSLP's Compositions section, excluding collected works."""
    payload, final_url = session.get_text(CATEGORY_URL)
    document = parse_html(payload, final_url)
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in document.xpath("//a[@href]"):
        href = clean(anchor.get("href"))
        decoded_path = urllib.parse.unquote(urllib.parse.urlparse(href).path)
        if COMPOSER_PAGE_SUFFIX not in decoded_path:
            continue
        section_headings = anchor.xpath("preceding::h2[1]")
        section = text_content(section_headings[0]) if section_headings else ""
        if "Compositions by:" not in section:
            continue
        title = re.sub(
            r"\s*\(Brahms,\s*Johannes\)\s*$", "", text_content(anchor)
        )
        if not title or href in seen:
            continue
        letter_headings = anchor.xpath("preceding::h3[1]")
        letter_heading = text_content(letter_headings[0]) if letter_headings else ""
        letter_match = re.match(r"([A-Z])(?:\b|\s)", letter_heading)
        seen.add(href)
        entries.append(
            {
                "letter": letter_match.group(1) if letter_match else "",
                "title": title,
                "href": href,
            }
        )
    return entries


def normalize_catalogue_text(value: object) -> str:
    value = clean(value)
    if not value:
        return ""
    value = re.sub(r"\bOpp?\.\s*", lambda m: "Opp. " if m.group(0).casefold().startswith("opp") else "Op. ", value, flags=re.I)
    value = re.sub(r"\bWoO\s*", "WoO ", value, flags=re.I)
    value = re.sub(r"\bAnh\.?\s*", "Anh. ", value, flags=re.I)
    value = re.sub(r"\bNo\.\s*", "No. ", value, flags=re.I)
    value = re.sub(r"\s*/\s*", "/", value)
    return re.sub(r"\s+", " ", value).strip(" ,;")


def normalize_catalogue_in_title(value: object) -> str:
    title = clean(value)
    title = re.sub(r"\bOp\.\s*([0-9]+[a-z]?)", r"Op. \1", title, flags=re.I)
    title = re.sub(r"\bOpp\.\s*([0-9]+)", r"Opp. \1", title, flags=re.I)
    title = re.sub(r"\bWoO\s*([0-9]+)", r"WoO \1", title, flags=re.I)
    title = re.sub(r"\bAnh\.?\s*([0-9]+(?:[a-z])?(?:/[0-9]+)?)", r"Anh. \1", title, flags=re.I)
    title = re.sub(r"\bNo\.\s*([0-9]+)", r"No. \1", title, flags=re.I)
    return re.sub(r"\s+", " ", title).strip()


def catalogue_from_title(value: object) -> str:
    title = normalize_catalogue_in_title(value)
    match = re.search(
        r"(?:^|,\s*)((?:Op\.\s*\d+[a-z]?(?:\s+No\.\s*\d+)?|WoO\s*\d+|Anh\.\s*\d+[a-z]?(?:/\d+)?))\s*$",
        title,
        flags=re.I,
    )
    return normalize_catalogue_text(match.group(1)) if match else ""


def title_with_catalogue(title: object, catalogue: object) -> str:
    title = normalize_catalogue_in_title(title)
    catalogue = normalize_catalogue_text(catalogue)
    if not catalogue:
        return title
    catalogue_tokens = normalize_search_text(re.sub(r'\([^)]*\)', '', catalogue))
    if catalogue_tokens and re.search(r'(?:^|\s)' + re.escape(catalogue_tokens) + r'(?:\s|$)', normalize_search_text(title)):
        return title
    return f"{title}, {catalogue}" if title else catalogue


def split_trailing_key(value: str) -> tuple[str, str]:
    value = re.sub(r"\s*\(\d+ bars\)", "", value, flags=re.I)
    value = re.sub(r"(?<=[a-zÀ-ž])\.(?=[A-ZÀ-Þ])", ". ", value)
    match = re.search(
        r"\s*\(((?:[A-G](?:-flat|-sharp|[♭♯])?\s+)?(?:major|minor)(?:\s*/\s*[A-G](?:-flat|-sharp|[♭♯])?\s+(?:major|minor))*|see below)(?:,\s*\d+ bars)?\)\s*$",
        value,
        flags=re.I,
    )
    if not match:
        return clean(value), ""
    return clean(value[: match.start()]), clean(match.group(1))


def chinese_tonality(value: str) -> str:
    value = value.replace('♭', '-flat').replace('♯', '-sharp')
    return '/'.join(translate_key(part.strip()) for part in value.split('/'))


def parse_movements(value: object) -> list[dict[str, object]]:
    """Parse IMSLP's flattened numeric movement/piece list."""
    source = clean(value)
    if not source:
        return []
    parts = re.split(r"(?<![A-Za-z0-9])(\d{1,3})\.\s+", source)
    if len(parts) < 3:
        return []
    movements: list[dict[str, object]] = []
    for index in range(1, len(parts) - 1, 2):
        number = int(parts[index])
        label, key = split_trailing_key(parts[index + 1])
        label = re.sub(r"\s+(?:[IVXLCDM]+\.)?$", "", label).strip()
        if label:
            movements.append({"number": number, "title": label, "key": key})
    return movements


def heading_context(block) -> dict[str, str]:
    context = {f"h{level}": "" for level in (3, 4, 5, 6)}
    # Walk up the current heading hierarchy; do not carry a previous section's
    # h5/h6 across a newer h3/h4 (e.g. a movement name from an earlier edition).
    nearest_level = 7
    for heading in reversed(block.xpath("preceding::*[self::h2 or self::h3 or self::h4 or self::h5 or self::h6]")):
        level = int(heading.tag[1])
        if level < nearest_level:
            if level in (3, 4, 5, 6):
                context[f"h{level}"] = text_content(heading)
            nearest_level = level
        if level <= 3:
            break
    return context


def parse_work_page(session: IMSLPSession, entry: dict[str, str]) -> dict:
    payload, final_url = session.get_text(entry["href"], referer=CATEGORY_URL)
    document = parse_html(payload, final_url)
    rows = richer_row_map(document)
    files: list[dict] = []

    for block in document.xpath('//*[@id and starts-with(@id, "IMSLP")]'):
        id_match = re.fullmatch(r"IMSLP(\d+)", clean(block.get("id")))
        if not id_match:
            continue
        download_link = first(
            block.xpath('.//a[contains(@href, "Special:ImagefromIndex")]')
        )
        if download_link is None:
            continue

        internal_link = first(
            block.xpath(
                './/a[contains(concat(" ", normalize-space(@class), " "), " internal ") and contains(@href, "/images/")]'
            )
        )
        original_filename = ""
        if internal_link is not None:
            original_filename = clean(internal_link.get("title"))
            if not original_filename:
                original_filename = urllib.parse.unquote(
                    urllib.parse.urlparse(internal_link.get("href", "")).path.rsplit("/", 1)[-1]
                )

        file_info_node = first(
            block.xpath(
                './/*[contains(concat(" ", normalize-space(@class), " "), " we_file_info2 ")]'
            )
        )
        file_format_node = first(
            block.xpath(
                './/*[contains(concat(" ", normalize-space(@class), " "), " we_file_info ")]'
            )
        )
        download_title_node = first(download_link.xpath('.//*[@title][1]'))
        description_en = (
            clean(download_title_node.get("title"))
            if download_title_node is not None
            else ""
        )
        description_en = re.sub(r"^.*?\((.*)\)$", r"\1", description_en)
        description = text_content(download_link)
        if description_en == "下载这个文件":
            description_en = ""

        file_format = (
            text_content(file_format_node).split(" ", 1)[0]
            if file_format_node is not None
            else ""
        )
        if not (
            original_filename.casefold().endswith(".pdf")
            or file_format.upper() == "PDF"
        ):
            continue

        edition = nearest_parent_with_class(block, "we")
        edition_rows = direct_row_map(edition) if edition is not None else {}
        context = heading_context(block)
        files.append(
            {
                "imslp_id": str(int(id_match.group(1))),
                "description": description,
                "description_en": description_en,
                "handler_url": clean(download_link.get("href")),
                "original_filename": original_filename,
                "file_info": text_content(file_info_node),
                "section": nearest_tab_id(block),
                "heading_context": context,
                "copyright": re.sub(
                    r"\s*\[(?:tag|del|mrg).*?$",
                    "",
                    first_value(edition_rows, "版权", "Copyright"),
                    flags=re.I,
                ),
                "publisher": first_value(
                    edition_rows, "出版者资料", "Publisher Info.", "Publisher. Info."
                ),
                "arranger": first_value(edition_rows, "编曲者", "改编", "Arranger"),
                "editor": first_value(edition_rows, "编者", "编辑", "Editor"),
            }
        )

    movements_text, movements = movements_from_document(document, rows)
    catalogue = value_for_label_fragment(
        rows, "作品号", "目录编号", "目录号", "Opus/Catalogue Number", "Op./Cat. No."
    ) or catalogue_from_title(entry["title"])
    return {
        **entry,
        "source_url": final_url,
        "work_title_original": first_value(rows, "作品名称", "Work Title") or entry["title"],
        "display_work_title": title_with_catalogue(entry["title"], catalogue),
        "alternative_title": first_value(rows, "副题名", "Alternative. Title"),
        "catalogue_number": normalize_catalogue_text(catalogue),
        "key": first_value(rows, "调", "Key"),
        "movements_text": movements_text,
        "movements": movements,
        "instrumentation": first_value(rows, "配置", "Instrumentation"),
        "genre_categories": first_value(rows, "音乐类型分类", "Genre Categories"),
        "language": first_value(rows, "语言", "Language"),
        "files": files,
    }


def is_individual_part(score_file: dict) -> bool:
    label = concise_file_label(
        score_file.get("description_en") or score_file.get("description"),
        allow_bare_instrument=True,
    )
    return score_file.get("section") == "tabScore2" or (
        "分谱" in label and "总谱" not in label
    )


def is_vocal_collection(work: dict) -> bool:
    title = normalize_search_text(work.get("display_work_title"))
    genres = work.get("genre_categories", "").casefold()
    return bool(
        re.match(r"^\d+\s", title)
        or "song cycles" in genres
        or any(marker in title for marker in ("lieder", "songs", "volkslieder", "romanzen"))
    )


def original_genres(work: dict) -> str:
    return "; ".join(
        tag.strip().casefold() for tag in work.get("genre_categories", "").split(";")
        if "(arr)" not in tag.casefold()
    )


def original_scoring(work: dict) -> str:
    for tag in original_genres(work).split(";"):
        tag = tag.strip()
        if tag.startswith("for ") and not re.fullmatch(r"for \d+ players?", tag):
            return tag[4:]
    return work.get("instrumentation", "").casefold()


def is_art_song_ensemble(work: dict) -> bool:
    scoring, genres = original_scoring(work), original_genres(work)
    if not re.search(r"\b[2-9]\s+voices\b", scoring):
        return False
    return not any(marker in scoring + ';' + genres for marker in (
        'chorus', 'choir', 'choruses', 'motets', 'sacred', 'religious',
        'requiems', 'cantatas', 'oratorios', 'operas', 'canons',
    ))


def category_for(work: dict, score_file: dict) -> str:
    genres = original_genres(work)
    instrumentation = original_scoring(work)
    title = work.get("display_work_title", "").casefold()
    blob = f"{genres}; {instrumentation}; {title}"

    if is_individual_part(score_file):
        return "器乐分谱"
    arrangement = arrangement_instrumentation(score_file).casefold()
    if arrangement:
        if any(marker in arrangement for marker in ("voice", "chorus", "choir", "声", "合唱")):
            pass
        elif "orchestra" in arrangement or "管弦" in arrangement:
            return "管弦乐/交响曲"
        elif re.fullmatch(r"(?:piano|organ|钢琴|管风琴)(?: solo|独奏)?", arrangement):
            return "器乐独奏"
        elif any(marker in arrangement for marker in ("piano", "violin", "cello", "钢琴", "小提琴", "大提琴", "长笛", "clarinet")):
            return "室内乐"
    if "concertos" in genres or " concerto" in f" {title}":
        return "协奏曲总谱"
    if any(marker in genres for marker in ("requiems", "sacred cantatas", "sacred oratorios")):
        return "宗教声乐作品总谱"
    if any(marker in genres for marker in ("motets", "sacred choruses", "sacred songs", "religious works")):
        return "宗教声乐作品"
    if any(marker in genres for marker in ("secular cantatas", "oratorios")):
        return "音乐会咏叹调/世俗康塔塔"
    if any(marker in arrangement for marker in ("chorus", "choir", "合唱")):
        return "合唱作品"
    if is_art_song_ensemble(work):
        return "艺术歌曲"
    if any(marker in genres for marker in ("choruses", "part songs", "quartets for voices")):
        return "合唱作品"
    if "canons" in genres and "voice" in genres:
        return "合唱作品"
    if re.search(r"\b[2-9]\s+voices\b", instrumentation):
        return "合唱作品"
    if "chorus" in instrumentation or "choir" in instrumentation:
        return "合唱作品"
    if any(marker in genres for marker in ("songs", "lieder", "romances", "vocalises")):
        if movement_for_file(work, score_file):
            return "艺术歌曲"
        return "声乐套曲" if is_vocal_collection(work) else "艺术歌曲"
    if "for 1 voice" in genres:
        return "艺术歌曲"
    if any(marker in genres for marker in ("collections", "collected works")):
        return "乐谱书/曲集"
    if "orchestra" in instrumentation:
        return "管弦乐/交响曲"
    if any(marker in instrumentation for marker in ("4 hands", "4-hands", "2 pianos")):
        return "室内乐"
    chamber_markers = (
        "trios",
        "quartets",
        "quintets",
        "sextets",
        "chamber music",
        "for violin, piano",
        "for cello, piano",
        "for clarinet, piano",
    )
    if any(marker in genres for marker in chamber_markers):
        return "室内乐"
    if any(marker in blob for marker in ("violin", "viola", "cello", "clarinet", "horn")) and "," in instrumentation:
        return "室内乐"
    if any(marker in genres for marker in ("for piano", "for organ", "keyboard")):
        return "器乐独奏"
    if any(marker in instrumentation for marker in ("piano", "organ")) and "," not in instrumentation:
        return "器乐独奏"
    return "其他"


SUBCATEGORY_RULES = (
    ("symphonies", "交响曲"),
    ("overtures", "序曲"),
    ("serenades", "小夜曲"),
    ("concertos", "协奏曲"),
    ("requiems", "安魂曲"),
    ("motets", "经文歌"),
    ("cantatas", "康塔塔"),
    ("chorale preludes", "众赞歌前奏曲"),
    ("chorales", "众赞歌"),
    ("piano trios", "钢琴三重奏"),
    ("trios", "三重奏"),
    ("quartets", "四重奏"),
    ("quintets", "五重奏"),
    ("sextets", "六重奏"),
    ("sonatas", "奏鸣曲"),
    ("variations", "变奏曲"),
    ("fantasias", "幻想曲"),
    ("rhapsodies", "狂想曲"),
    ("ballades", "叙事曲"),
    ("intermezzos", "间奏曲"),
    ("caprices", "随想曲"),
    ("waltzes", "圆舞曲"),
    ("dances", "舞曲"),
    ("studies", "练习曲"),
    ("fugues", "赋格"),
    ("canons", "卡农"),
    ("songs", "艺术歌曲"),
)


def subcategory_for(work: dict, category: str, score_file: dict | None = None) -> str:
    if category == "艺术歌曲" and is_art_song_ensemble(work):
        return ""
    movement = movement_for_file(work, score_file) if score_file else None
    if movement and category == "器乐独奏":
        movement_title = clean(movement.get("title")).casefold()
        for marker, label in (("capriccio", "随想曲"), ("intermezzo", "间奏曲"), ("rhapsod", "狂想曲"), ("ballad", "叙事曲")):
            if movement_title.startswith(marker):
                return label
    genres = original_genres(work)
    for marker, label in SUBCATEGORY_RULES:
        if marker in genres:
            if category == "艺术歌曲" and label == "艺术歌曲":
                return ""
            return label
    return ""


def movement_number_from_file(work: dict, score_file: dict) -> int | None:
    context = score_file.get("heading_context", {})
    sources = (
        score_file.get("description_en"), score_file.get("description"),
        context.get("h4"), context.get("h5"), context.get("h6"),
    )
    for source in (clean(value) for value in sources if clean(value)):
        if re.search(r"\bNos\.\s*\d", source, flags=re.I):
            continue
        no_match = re.search(
            r"\bNo\.\s*(\d{1,3})(?!\d)(?!\s*(?:[,;&]\s*\d|[-–—]\s*\d|and\s+\d|to\s+\d))",
            source,
            flags=re.I,
        )
        if no_match:
            return int(no_match.group(1))
        numbered_match = re.search(r"(?:^|[;: ])(\d{1,3})\.\s+[\[\"'“‘]?[A-Za-zÀ-ž\u4e00-\u9fff]", source)
        if numbered_match:
            return int(numbered_match.group(1))

    # Filename suffixes are also work numbers, book numbers, scan versions or
    # instrument parts. Never infer a movement from a filename alone.
    return None


def movement_label_from_file(number: int, score_file: dict) -> tuple[str, str]:
    context = score_file.get("heading_context", {})
    sources = (
        score_file.get("description_en"), score_file.get("description"),
        context.get("h4"), context.get("h5"), context.get("h6"),
    )
    for source in (clean(value) for value in sources if clean(value)):
        numbered = re.match(rf"^(?:No\.\s*)?{number}\.?(?:\s*[-–—:]\s*|\s+)(.+)$", source, flags=re.I)
        if numbered:
            label = numbered.group(1)
        elif re.search(rf"\(No\.\s*{number}\)\s*$", source, flags=re.I):
            label = re.sub(rf"\s*\(No\.\s*{number}\)\s*$", "", source, flags=re.I)
        else:
            continue
        label = re.sub(
            r"\s*\((?:scan|filter|medium quality|low quality|high quality|complete)\)\s*$",
            "", label, flags=re.I,
        )
        label, key = split_trailing_key(label)
        if label and not re.match(
            r"^(?:piccolo|flute|oboe|clarinet|bassoon|horn|trumpet|trombone|violin|viola|cello|bass|timpani|harp|percussion)\b",
            label,
            flags=re.I,
        ):
            return label, key
    return "", ""


def movement_for_file(work: dict, score_file: dict) -> dict | None:
    number = movement_number_from_file(work, score_file)
    if number is None:
        return None
    known = next(
        (movement for movement in work.get("movements", []) if movement["number"] == number),
        None,
    )
    if known:
        return known
    title, key = movement_label_from_file(number, score_file)
    return {"number": number, "title": title, "key": key}


def selection_label_for_file(score_file: dict) -> str:
    context = score_file.get("heading_context", {})
    sources = (
        score_file.get("description_en"), context.get("h4"),
        context.get("h5"), context.get("h6"),
    )
    for source in (clean(value) for value in sources if clean(value)):
        match = re.search(
            r"\b(No(?:s)?\.\s*\d{1,3}(?:\s*(?:[,;&]|[-–—]|and\b|to\b)\s*\d{1,3})+)",
            source,
            flags=re.I,
        )
        if not match:
            continue
        label = match.group(1)
        if label.casefold().startswith("no."):
            label = "Nos." + label[3:]
        label = re.sub(r"\bNos\.\s*", "Nos. ", label, flags=re.I)
        label = re.sub(r"\s*[-–—]\s*", "–", label)
        label = re.sub(r"\s*,\s*", ", ", label)
        label = re.sub(r"\s+", " ", label)
        return label.strip()
    return ""


def proposed_title_for(work: dict, score_file: dict) -> tuple[str, str, str]:
    parent_title = work["display_work_title"]
    movement = movement_for_file(work, score_file)
    if not movement:
        selection = selection_label_for_file(score_file)
        if selection:
            return (
                title_with_catalogue(selection, work.get("catalogue_number")),
                parent_title,
                "selection",
            )
        return parent_title, "", "whole_work"
    number = movement["number"]
    movement_title = clean(movement.get("title"))
    if movement_title:
        for plural, singular in (("Intermezzi", "Intermezzo"), ("Rhapsodies", "Rhapsody"), ("Ballades", "Ballade"), ("Waltzes", "Waltz")):
            if re.match(rf"^\d+ {plural}\b", parent_title, flags=re.I) and not movement_title.casefold().startswith(singular.casefold()):
                movement_title = singular + '. ' + movement_title
                break
    base = f"No. {number} {movement_title}".strip()
    segment = re.search(r"\((?:segment|段)\s*(\d+)\)", score_file.get("description_en") or score_file.get("description", ""), flags=re.I)
    if segment:
        base += f"（片段 {segment.group(1)}）"
    return (
        title_with_catalogue(base, work.get("catalogue_number")),
        parent_title,
        "individual_movement",
    )


def arrangement_instrumentation(score_file: dict) -> str:
    context = score_file.get("heading_context", {})
    for level in ("h6", "h5", "h4"):
        heading = clean(context.get(level))
        match = re.match(r"(?:For\s+|给)(.+?)(?:\s+\([^()]+\))?$", heading, flags=re.I)
        if match:
            return match.group(1)
    return ""


def compact_instrumentation(value: str) -> str:
    source = clean(value).casefold()
    if source in {"piano left hand", "piano lefthand", "piano (left hand)"}:
        return "钢琴左手"
    if source in {"piano", "piano solo", "钢琴", "钢琴独奏"}:
        return "钢琴独奏"
    if source in {"organ", "organ solo", "管风琴"}:
        return "管风琴独奏"
    if source in {"piano 4 hands", "piano 4-hands", "钢琴四手联弹", "钢琴4手联弹"}:
        return "钢琴四手联弹"
    if source in {"2 pianos", "2钢琴", "双钢琴"}:
        return "双钢琴"
    if source in {"orchestra", "管弦乐团", "管弦乐队"}:
        return "管弦乐总谱"
    if "chorus" in source or "choir" in source:
        label = "混声合唱" if "mixed" in source else "合唱"
        if "female" in source or "women" in source:
            label = "女声合唱"
        elif "male" in source or "men" in source:
            label = "男声合唱"
        if "voice" in source:
            label = "独唱、" + label
        if "orchestra" in source:
            return label + "、管弦乐队"
        if "piano" in source:
            return label + "、钢琴"
        return label
    if "voice" in source:
        number = re.search(r"\b([2-9]) voices\b", source)
        label = {"2": "二重唱", "3": "三重唱", "4": "四重唱", "5": "五重唱", "6": "六重唱", "7": "七重唱", "8": "八重唱", "9": "九重唱"}.get(number.group(1), "重唱") if number else "声乐"
        if "piano" in source:
            label += "、钢琴四手联弹" if "4 hands" in source else "、钢琴"
        if "viola" in source:
            label += "、中提琴"
        if "orchestra" in source:
            label += "、管弦乐队"
        return label
    translated = concise_instrumentation(value)
    for before, after in (("Tuba", "大号"), ("tuba", "大号"), ("contrabassoon", "低音巴松"), ("baritone", "男中音"), ("bass声乐", "男低音")):
        translated = translated.replace(before, after)
    translated = translated.replace("和", "、").replace("管弦乐团", "管弦乐队")
    # Detailed orchestration belongs in source metadata, not the compact badge.
    return translated if len(translated) <= 80 else ""


def voice_types_for(work: dict, score_file: dict, category: str) -> str:
    description = score_file.get("description_en") or score_file.get("description", "")
    label = concise_file_label(description, allow_bare_instrument=True)
    if is_individual_part(score_file):
        if label == "" or label == "器乐分谱":
            for marker, name in (("tuba", "大号分谱"), ("triangle", "三角铁分谱"), ("harp", "竖琴分谱"), ("organ", "管风琴分谱"), ("complete parts", "全套分谱")):
                if marker in description.casefold():
                    return name
        return label or "器乐分谱"
    if label in {"钢琴谱", "声乐谱", "指挥用钢琴谱"}:
        return label
    arrangement = arrangement_instrumentation(score_file)
    if arrangement:
        translated = compact_instrumentation(arrangement)
        voice_number = re.search(r"\b([2-9])\s+voices\b", original_scoring(work))
        if translated.startswith('各声部') and voice_number:
            translated = compact_instrumentation(voice_number.group(1) + ' voices') + translated[len('各声部'):]
        if translated:
            return translated
    instrumentation = compact_instrumentation(original_scoring(work))
    if category == "管弦乐/交响曲":
        return "管弦乐总谱"
    if category == "协奏曲总谱":
        solo_match = re.search(
            r"\b(piano|violin|cello|clarinet|horn)\b", original_scoring(work), flags=re.I
        )
        if solo_match:
            instrument = {"piano": "钢琴", "violin": "小提琴", "cello": "大提琴", "clarinet": "单簧管", "horn": "圆号"}[solo_match.group(1).casefold()]
            return instrument + "独奏"
    return instrumentation or label


def default_decision(score_file: dict, eligible: bool) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if not eligible:
        warnings.append("当前版权状态不适合匿名下载")
        return "excluded", warnings
    arranger = clean(score_file.get("arranger"))
    if arranger or score_file.get("section") == "tabArrTrans":
        is_composer = bool(re.fullmatch(r"(?:Johannes\s+)?Brahms(?:\s*\(1833[–-]1897\))?", arranger, flags=re.I)) or arranger.casefold() in {"composer", "the composer", "作曲家"}
        if not is_composer:
            if not arranger:
                warnings.append("改编者未确认（暂不收录）")
                return "excluded", warnings
            warnings.append("第三方改编（按约定默认排除）")
            return "excluded", warnings
    return "pending", warnings


def apply_review_defaults(work: dict, score_file: dict, previous: dict) -> None:
    eligible, reason = eligible_in_us(score_file)
    category = category_for(work, score_file)
    subcategory = subcategory_for(work, category, score_file)
    title, parent_work, title_scope = proposed_title_for(work, score_file)
    movement = movement_for_file(work, score_file)
    tonality_source = clean(movement.get("key")) if movement else clean(work.get("key"))
    if tonality_source.casefold() == "see below":
        tonality_source = ""
    decision, warnings = default_decision(score_file, eligible)
    copyright_label = clean(score_file.get("copyright")).casefold()
    if copyright_label.startswith("creative commons"):
        warnings.append("许可版本：发布前需逐项核对署名、非商业及相同方式共享等条件")
    elif "see notes" in copyright_label:
        warnings.append("版权标注含附注，发布前需人工核对")
    if len(score_file.get("source_references", [])) > 1:
        warnings.append("同一 IMSLP 文件出现在多个来源位置，已合并为一条")
    if len(title) > 200:
        warnings.append("标题超过 200 字符，需要精简")
    if category == "其他":
        warnings.append("未匹配网站现有分类")
    voice_types = voice_types_for(work, score_file, category)
    if not voice_types or re.search(r"[A-Za-z]{3,}", voice_types):
        warnings.append("编制中文简写仍需确认")
    if movement and not clean(movement.get("title")):
        warnings.append("已识别乐章编号，但乐章名称仍需人工确认")
    if movement and movement.get("has_subsections"):
        warnings.append("该曲含子乐章，文件覆盖范围需对照谱面确认")
    if re.search(r"cover page|title page|封面页|标题页", score_file.get("description_en") or score_file.get("description", ""), flags=re.I):
        decision = "excluded"
        warnings.append("仅封面或标题页，不作为乐谱收录")
    source_context = " ".join([score_file.get("description_en", ""), score_file.get("description", ""), *score_file.get("heading_context", {}).values()]).casefold()
    if tonality_source and any(marker in source_context for marker in ("high voice", "low voice", "medium voice", "高声部", "低声部", "中音声部", "transpos", "移调")):
        warnings.append("调性取自作品页，移调版本需对照谱面确认")
    if title_scope == "whole_work":
        description_blob = " ".join(
            clean(value)
            for value in (
                score_file.get("description_en"),
                score_file.get("description"),
                score_file.get("heading_context", {}).get("h4"),
            )
        ).casefold()
        if any(marker in description_blob for marker in ("selection", "选集", "excerpt", " no.")):
            warnings.append("可能是单乐章/选段，但尚未可靠识别标题")

    score_file.update(
        {
            "eligible": eligible,
            "skip_reason": reason,
            "proposed_title": title,
            "proposed_work": parent_work,
            "title_scope": title_scope,
            "movement_number": movement.get("number") if movement else None,
            "category": category,
            "sub_category": subcategory,
            "voice_types": voice_types,
            "tonality": chinese_tonality(tonality_source),
            "language_cn": language_for(work) if category not in {"器乐独奏", "器乐分谱", "室内乐", "管弦乐/交响曲", "协奏曲总谱"} else "",
            "warnings": warnings,
            "decision": decision,
            "review_notes": "",
            "review_edited": False,
            "public_id": str(uuid.uuid4()),
        }
    )

    if previous:
        score_file["public_id"] = previous.get("public_id") or score_file["public_id"]
        if previous.get("review_edited"):
            for field in (
                "proposed_title",
                "proposed_work",
                "category",
                "sub_category",
                "voice_types",
                "tonality",
                "language_cn",
                "decision",
                "review_notes",
                "review_edited",
                "reviewed_at",
            ):
                if field in previous:
                    score_file[field] = previous[field]
    if score_file.get("decision") == "approved" and not eligible:
        score_file["decision"] = "excluded"
        score_file["warnings"].append("来源版权状态已变化，原批准状态已撤回")


def existing_catalog_context() -> tuple[set[str], set[str]]:
    data = load_json(DATA_FILE, [])
    titles = {
        normalize_work_identity(item.get("title"))
        for item in data
        if "Brahms" in clean(item.get("composer")) or "勃拉姆斯" in clean(item.get("composer"))
    }
    imslp_ids = {
        match.group(1)
        for item in data
        for match in [re.search(r"IMSLP\s*#(\d+)", clean(item.get("description")))]
        if match
    }
    return titles, imslp_ids


def annotate_catalog_duplicates(manifest: dict) -> None:
    existing_titles, existing_imslp_ids = existing_catalog_context()
    for work in manifest.get("works", []):
        work_exists = normalize_work_identity(work.get("display_work_title")) in existing_titles
        for score_file in work.get("files", []):
            warnings = score_file.setdefault("warnings", [])
            if work_exists and "网站已有同名勃拉姆斯作品" not in warnings:
                warnings.append("网站已有同名勃拉姆斯作品")
            if score_file.get("imslp_id") in existing_imslp_ids:
                warnings.append("网站已有相同 IMSLP 文件号")
                score_file["decision"] = "excluded"


def deduplicate_manifest_files(manifest: dict) -> None:
    """One review/publish candidate per IMSLP file, retaining every source."""
    by_id: dict[str, tuple[dict, dict]] = {}
    for work in manifest.get("works", []):
        for item in work.get("files", []):
            identity = str(int(item["imslp_id"]))
            item["imslp_id"] = identity
            reference = {"work_title": work["display_work_title"], "source_url": work["source_url"], "description": item.get("description", "")}
            if identity not in by_id:
                item["source_references"] = [reference]
                by_id[identity] = (work, item)
                continue
            previous_work, previous = by_id[identity]
            references = previous["source_references"] + [reference]
            # Prefer an original/eligible placement to a third-party arrangement
            # placement, unless an administrator already edited the first one.
            prefer_new = not previous.get("review_edited") and (
                item.get("review_edited") or (previous.get("decision") == "excluded" and item.get("decision") != "excluded")
            )
            if prefer_new:
                item["source_references"] = references
                by_id[identity] = (work, item)
            else:
                previous["source_references"] = references
    for work in manifest.get("works", []):
        work["files"] = [item for item in work.get("files", []) if by_id[item["imslp_id"]][1] is item]
        for item in work["files"]:
            if len(item["source_references"]) > 1:
                item["warnings"].append("同一 IMSLP 文件出现在多个来源位置，已合并为一条")


def build_manifest(session: IMSLPSession) -> dict:
    old_bytes = MANIFEST_FILE.read_bytes() if MANIFEST_FILE.exists() else None
    old_manifest = load_json(MANIFEST_FILE, {})
    old_files = {
        str(int(score_file["imslp_id"])): score_file
        for work in old_manifest.get("works", [])
        for score_file in work.get("files", [])
        if score_file.get("imslp_id")
    }
    entries = category_entries(session)
    manifest = {
        "composer": COMPOSER,
        "source_url": CATEGORY_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "review_only",
        "review_workflow": old_manifest.get("review_workflow", {}),
        "policy": {
            "source_section": "Compositions",
            "collected_works_included": False,
            "third_party_arrangements_default": "excluded",
            "pdf_downloaded": False,
            "published": False,
        },
        "works": [],
    }
    for index, entry in enumerate(entries, start=1):
        print(f"[metadata {index}/{len(entries)}] {entry['title']}", flush=True)
        work = parse_work_page(session, entry)
        for score_file in work.get("files", []):
            apply_review_defaults(work, score_file, old_files.get(score_file["imslp_id"], {}))
        manifest["works"].append(work)
        if index % 5 == 0:
            write_json_atomic(SOURCE_CACHE_DIR / "scrape_checkpoint.json", manifest)
        if not getattr(session, "last_from_cache", False):
            time.sleep(SCRAPE_PAUSE_SECONDS)
    manifest["discovered_file_references"] = sum(len(work["files"]) for work in manifest["works"])
    deduplicate_manifest_files(manifest)
    annotate_catalog_duplicates(manifest)
    current_bytes = MANIFEST_FILE.read_bytes() if MANIFEST_FILE.exists() else None
    if current_bytes != old_bytes:
        raise RuntimeError("抓取期间审核清单被修改；已保留你的修改。请暂停审核后重新运行，已抓取网页可从缓存复用。")
    write_json_atomic(MANIFEST_FILE, manifest)
    return manifest


def rebuild_proposals(manifest: dict) -> dict:
    """Recalculate proposed metadata locally while preserving manual review edits."""
    for work in manifest.get("works", []):
        if work.get('title'):
            work['display_work_title'] = title_with_catalogue(work['title'], work.get('catalogue_number'))
        for score_file in work.get("files", []):
            previous = dict(score_file)
            apply_review_defaults(work, score_file, previous)
    annotate_catalog_duplicates(manifest)
    manifest["proposals_rebuilt_at"] = datetime.now(timezone.utc).isoformat()
    write_json_atomic(MANIFEST_FILE, manifest)
    return manifest


def write_reports(manifest: dict) -> None:
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "decision",
        "warnings",
        "proposed_title",
        "proposed_work",
        "catalogue_number",
        "movement_number",
        "title_scope",
        "category",
        "sub_category",
        "voice_types",
        "tonality",
        "language",
        "imslp_id",
        "file_description",
        "section",
        "arranger",
        "editor",
        "copyright",
        "eligible",
        "skip_reason",
        "publisher",
        "original_filename",
        "source_url",
        "handler_url",
        "review_notes",
    ]
    with REPORT_FILE.open("w", encoding="utf-8-sig", newline="") as handle:
        class SafeCSVWriter(csv.DictWriter):
            def writerow(self, rowdict):
                # Exported source titles/review notes are text, never formulas.
                return super().writerow({
                    key: "'" + value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else value
                    for key, value in rowdict.items()
                })
        writer = SafeCSVWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for work in manifest.get("works", []):
            for score_file in work.get("files", []):
                writer.writerow(
                    {
                        "decision": score_file.get("decision", "pending"),
                        "warnings": "；".join(score_file.get("warnings", [])),
                        "proposed_title": score_file.get("proposed_title", ""),
                        "proposed_work": score_file.get("proposed_work", ""),
                        "catalogue_number": work.get("catalogue_number", ""),
                        "movement_number": score_file.get("movement_number") or "",
                        "title_scope": score_file.get("title_scope", ""),
                        "category": score_file.get("category", ""),
                        "sub_category": score_file.get("sub_category", ""),
                        "voice_types": score_file.get("voice_types", ""),
                        "tonality": score_file.get("tonality", ""),
                        "language": score_file.get("language_cn", ""),
                        "imslp_id": score_file.get("imslp_id", ""),
                        "file_description": score_file.get("description_en") or score_file.get("description", ""),
                        "section": score_file.get("section", ""),
                        "arranger": score_file.get("arranger", ""),
                        "editor": score_file.get("editor", ""),
                        "copyright": score_file.get("copyright", ""),
                        "eligible": score_file.get("eligible", False),
                        "skip_reason": score_file.get("skip_reason", ""),
                        "publisher": score_file.get("publisher", ""),
                        "original_filename": score_file.get("original_filename", ""),
                        "source_url": work.get("source_url", ""),
                        "handler_url": score_file.get("handler_url", ""),
                        "review_notes": score_file.get("review_notes", ""),
                    }
                )

    unmatched = [
        (work, score_file)
        for work in manifest.get("works", [])
        for score_file in work.get("files", [])
        if score_file.get("category") == "其他" or any("分类待确认" in warning for warning in score_file.get("warnings", []))
    ]
    unmatched_works = {}
    for work, _score_file in unmatched:
        unmatched_works[work.get("source_url", "")] = work
    lines = [
        "# Johannes Brahms：分类待确认",
        "",
        "本报告列出未匹配或只能暂时归入现有分类的作品。所有条目仍停留在审核清单中，未下载、未发布。",
        "",
        f"分类待确认文件：{len(unmatched)}；涉及作品：{len(unmatched_works)}。",
        "",
        "已确认规则：艺术歌曲的二重唱、四重唱等归入“艺术歌曲”，通过中文编制标记几重唱；不新增分类。合唱、宗教声乐等保留原有分类。",
        "",
        "| 作品 | IMSLP 体裁 | 建议操作 |",
        "|---|---|---|",
    ]
    for work in sorted(unmatched_works.values(), key=lambda item: normalize_search_text(item.get("display_work_title"))):
        title = clean(work.get("display_work_title")).replace("|", "\\|")
        genres = clean(work.get("genre_categories")).replace("|", "\\|")
        source_url = work.get("source_url", "")
        lines.append(f"| [{title}]({source_url}) | {genres} | 审核后选择现有分类或新增分类 |")
    lines.extend(["", "当前网站一级分类：", "", "、".join(sorted(ALLOWED_CATEGORIES)), ""])
    GAP_REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")


def print_summary(manifest: dict) -> None:
    works = manifest.get("works", [])
    files = [score_file for work in works for score_file in work.get("files", [])]
    print(f"works={len(works)} files={len(files)}", flush=True)
    print(f"decisions={dict(Counter(item.get('decision', '') for item in files))}", flush=True)
    print(f"categories={dict(Counter(item.get('category', '') for item in files))}", flush=True)
    print(f"individual_movements={sum(item.get('title_scope') == 'individual_movement' for item in files)}", flush=True)
    print(f"warning_files={sum(bool(item.get('warnings')) for item in files)}", flush=True)
    print("this_command_pdf_downloaded=0 this_command_published=0", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scrape", action="store_true", help="抓取 IMSLP 元数据并重建待审核清单")
    parser.add_argument("--refresh-reports", action="store_true", help="根据现有清单重新生成 CSV 与分类报告")
    parser.add_argument("--rebuild-proposals", action="store_true", help="不联网，仅根据现有清单重算标题和分类建议")
    parser.add_argument("--inspect-url", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.inspect_url:
        payload, final_url = CachedMetadataSession().get_text(args.inspect_url)
        document = parse_html(payload, final_url)
        rows = richer_row_map(document)
        for label, value in rows.items():
            print(f"{label!r} => {value!r}")
        movements_text, movements = movements_from_document(document, rows)
        print(f"movements_text={movements_text!r}")
        print(f"movements={movements!r}")
        return 0
    if args.scrape:
        manifest = build_manifest(CachedMetadataSession())
    else:
        manifest = load_json(MANIFEST_FILE, None)
        if manifest is None:
            print("缺少 manifest.json；请先使用 --scrape。", file=sys.stderr)
            return 2
    if args.rebuild_proposals:
        manifest = rebuild_proposals(manifest)
    if args.scrape or args.refresh_reports or args.rebuild_proposals:
        write_reports(manifest)
    print_summary(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
