"""One-time, idempotent phase-one migration for the score catalog."""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data.json"
BACKUP_DIR = ROOT / "backup"

PATH_FIXES = {
    "乐谱书/曲集/1766078857614_ABRSM_Grade8_.pdf": "乐谱书/曲集/1766078857614_ABRSM_Grade8.pdf",
    "乐谱书/曲集/1766078770162_ABRSM_Grade7_.pdf": "乐谱书/曲集/1766078770162_ABRSM_Grade7.pdf",
    "乐谱书/曲集/1766078674179_ABRSM_Grade6_.pdf": "乐谱书/曲集/1766078674179_ABRSM_Grade6.pdf",
    "乐谱书/曲集/1766078461223_ABRSM_Grade5_.pdf": "乐谱书/曲集/1766078461223_ABRSM_Grade5.pdf",
    "歌剧总谱/1768701501132_pdf": "歌剧总谱/1768701501132_pdf.pdf",
}

LANGUAGE_FIXES = {
    "German/德语": "德语",
    "Russian": "俄语",
    "French": "法语",
    "Russian\u00a0\u00a0\u00a0\u00a0/\u00a0\u00a0French": "俄语/法语",
    "Russian\u00a0\u00a0\u00a0\u00a0/\u00a0\u00a0German": "俄语/德语",
    "French\u00a0\u00a0\u00a0\u00a0/\u00a0\u00a0Russian": "法语/俄语",
}

FILE_RENAMES = {
    ROOT / "scores" / "歌剧总谱" / "1768701501132_pdf":
        ROOT / "scores" / "歌剧总谱" / "1768701501132_pdf.pdf",
}


def stable_public_id(item: dict) -> str:
    identity = f"{item['id']}|{item['title']}|{item['filename']}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://maotong.me/library/{identity}"))


def main() -> None:
    with DATA_FILE.open("r", encoding="utf-8-sig") as handle:
        data = json.load(handle)

    changes: list[str] = []
    for item in data:
        old_path = item["filename"]
        if old_path in PATH_FIXES:
            item["filename"] = PATH_FIXES[old_path]
            changes.append(f"修复文件路径 id={item['id']}: {old_path} -> {item['filename']}")

        old_language = item.get("language", "")
        if old_language in LANGUAGE_FIXES:
            item["language"] = LANGUAGE_FIXES[old_language]
            changes.append(f"规范语言 id={item['id']}: {old_language!r} -> {item['language']!r}")

        if not item.get("public_id"):
            item["public_id"] = stable_public_id(item)
            changes.append(f"新增 public_id id={item['id']}")

    public_ids = [item["public_id"] for item in data]
    if len(public_ids) != len(set(public_ids)):
        raise RuntimeError("迁移中检测到重复 public_id，已停止且未写入")

    pending_renames: list[tuple[Path, Path]] = []
    for source, target in FILE_RENAMES.items():
        if target.exists():
            if source.exists():
                raise FileExistsError(f"源文件和目标文件同时存在：{source} / {target}")
            continue
        if not source.is_file():
            raise FileNotFoundError(f"待重命名文件不存在：{source}")
        with source.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                raise ValueError(f"待重命名文件不是有效 PDF：{source}")
        pending_renames.append((source, target))

    if not changes and not pending_renames:
        print("无需迁移：数据已经是第一阶段格式。")
        return

    BACKUP_DIR.mkdir(exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"data_backup_phase1_{timestamp}.json"
    shutil.copy2(DATA_FILE, backup_path)

    completed_renames: list[tuple[Path, Path]] = []
    temp_path = DATA_FILE.with_suffix(".json.phase1.tmp")
    try:
        for source, target in pending_renames:
            source.replace(target)
            completed_renames.append((source, target))
            changes.append(f"补全 PDF 扩展名：{source.name} -> {target.name}")

        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, indent=4, ensure_ascii=False)
            handle.write("\n")
        os.replace(temp_path, DATA_FILE)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        for source, target in reversed(completed_renames):
            if target.exists() and not source.exists():
                target.replace(source)
        raise

    print(f"备份：{backup_path.relative_to(ROOT)}")
    print(f"完成 {len(changes)} 项迁移。")
    for message in changes[:20]:
        print(f"- {message}")
    if len(changes) > 20:
        print(f"- ……另有 {len(changes) - 20} 项")


if __name__ == "__main__":
    main()
