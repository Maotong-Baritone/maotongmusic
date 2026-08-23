"""Validate the score catalog without modifying any project files."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import uuid
from collections import Counter
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data.json"
SCORES_DIR = ROOT / "scores"
LYRICS_DIR = ROOT / "lyrics"

REQUIRED_FIELDS = ("id", "public_id", "title", "composer", "category", "filename", "date")
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
    "室内乐",
    "歌剧总谱",
    "管弦乐/交响曲",
    "协奏曲总谱",
    "宗教声乐作品总谱",
    "其他",
}
CANONICAL_LANGUAGES = {
    "意大利语",
    "德语",
    "法语",
    "英语",
    "俄语",
    "拉丁语",
    "捷克语",
    "汉语",
    "俄语/法语",
    "俄语/德语",
    "法语/俄语",
    "无歌词",
}


def load_json(path: Path):
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def catalog_path(filename: str) -> Path | None:
    relative = PurePosixPath(filename)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    return SCORES_DIR.joinpath(*relative.parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="检查乐谱目录、PDF 与歌词文件的一致性")
    parser.add_argument("--strict", action="store_true", help="将警告也视为失败")
    parser.add_argument("--limit", type=int, default=25, help="每类问题最多显示多少条")
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []

    try:
        data = load_json(DATA_FILE)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"错误：无法读取 {DATA_FILE.name}: {exc}")
        return 1

    if not isinstance(data, list):
        print("错误：data.json 的顶层必须是数组")
        return 1

    ids: list[object] = []
    public_ids: list[str] = []
    referenced_files: set[str] = set()
    flagged_lyrics: set[str] = set()

    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            errors.append(f"记录 #{index} 不是对象")
            continue

        label = f"记录 #{index} (id={item.get('id', '?')})"
        for field in REQUIRED_FIELDS:
            if item.get(field) in (None, ""):
                errors.append(f"{label} 缺少字段 {field}")

        item_id = item.get("id")
        ids.append(item_id)

        public_id = str(item.get("public_id", ""))
        public_ids.append(public_id)
        try:
            uuid.UUID(public_id)
        except (ValueError, AttributeError):
            errors.append(f"{label} 的 public_id 不是有效 UUID: {public_id!r}")

        category = str(item.get("category", ""))
        if category not in ALLOWED_CATEGORIES:
            errors.append(f"{label} 使用未知分类: {category!r}")

        language = str(item.get("language", "")).strip()
        if not language:
            warnings.append(f"{label} 未填写语言")
        elif language not in CANONICAL_LANGUAGES:
            warnings.append(f"{label} 使用未规范语言: {language!r}")

        date_value = str(item.get("date", ""))
        try:
            dt.date.fromisoformat(date_value)
        except ValueError:
            errors.append(f"{label} 的日期格式无效: {date_value!r}")

        filename = str(item.get("filename", ""))
        normalized_filename = PurePosixPath(filename).as_posix()
        referenced_files.add(normalized_filename)
        file_path = catalog_path(filename)
        if file_path is None:
            errors.append(f"{label} 的文件路径越出 scores 目录: {filename!r}")
        elif not file_path.is_file():
            errors.append(f"{label} 引用的文件不存在: {filename}")
        else:
            if file_path.suffix.lower() != ".pdf":
                errors.append(f"{label} 的文件不是 .pdf: {filename}")
            try:
                with file_path.open("rb") as handle:
                    if handle.read(5) != b"%PDF-":
                        errors.append(f"{label} 的文件头不是有效 PDF: {filename}")
            except OSError as exc:
                errors.append(f"{label} 的文件无法读取: {filename} ({exc})")

        if item.get("has_lyrics"):
            flagged_lyrics.add(str(item_id))

    for duplicate, count in Counter(ids).items():
        if count > 1:
            errors.append(f"数字 ID 重复 {count} 次: {duplicate!r}")
    for duplicate, count in Counter(public_ids).items():
        if count > 1:
            errors.append(f"public_id 重复 {count} 次: {duplicate!r}")

    actual_files = {
        path.relative_to(SCORES_DIR).as_posix()
        for path in SCORES_DIR.rglob("*")
        if path.is_file()
    }
    for filename in sorted(actual_files - referenced_files):
        warnings.append(f"未被 data.json 引用的文件: {filename}")

    lyric_files = {path.stem: path for path in LYRICS_DIR.glob("*.json") if path.is_file()}
    for lyric_id in sorted(flagged_lyrics - set(lyric_files)):
        errors.append(f"记录标记了歌词，但文件不存在: lyrics/{lyric_id}.json")
    for lyric_id in sorted(set(lyric_files) - flagged_lyrics):
        warnings.append(f"歌词文件存在，但目录记录未标记歌词: lyrics/{lyric_id}.json")
    for lyric_id, lyric_path in lyric_files.items():
        try:
            lyric_data = load_json(lyric_path)
            if not isinstance(lyric_data, dict):
                raise ValueError("顶层不是对象")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"歌词文件无效 lyrics/{lyric_id}.json: {exc}")

    print("乐谱库完整性检查")
    print(f"- 目录记录：{len(data)}")
    print(f"- 实际文件：{len(actual_files)}")
    print(f"- 歌词文件：{len(lyric_files)}")
    print(f"- 错误：{len(errors)}")
    print(f"- 警告：{len(warnings)}")

    if errors:
        print("\n错误明细：")
        for message in errors[: args.limit]:
            print(f"  [错误] {message}")
        if len(errors) > args.limit:
            print(f"  ……另有 {len(errors) - args.limit} 条")

    if warnings:
        print("\n警告明细：")
        for message in warnings[: args.limit]:
            print(f"  [警告] {message}")
        if len(warnings) > args.limit:
            print(f"  ……另有 {len(warnings) - args.limit} 条")

    if errors or (args.strict and warnings):
        return 1
    print("\n检查通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
