"""Resolve known orphan files and missing languages without deleting files."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import time
import uuid
from collections import defaultdict
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data.json"
SCORES_DIR = ROOT / "scores"
BACKUP_DIR = ROOT / "backup"

LANGUAGE_BY_ID = {
    **{item_id: "德语" for item_id in range(1465, 1479)},
    83: "无歌词",
    233: "无歌词",
    234: "无歌词",
}

RESTORED_RECORDS = [
    {
        "title": "Riconosci in questo amplesso/在这拥抱中相认吧",
        "composer": "Wolfgang Amadeus Mozart/莫扎特",
        "work": "Le nozze di Figaro, K.492/费加罗的婚礼",
        "language": "意大利语",
        "category": "歌剧重唱",
        "sub_category": "",
        "voice_count": "六重唱",
        "voice_types": "Soprano/Mezzo-Soprano/Tenor/Baritone/Bass-Baritone/Bass",
        "tonality": "",
        "description": "演唱声部：六重唱（Sextet）：Susanna（女高音）、Marcellina（次女高音）、Don Curzio（男高音）、Il Conte（男中音）、Figaro（男低音/男低中音）、Bartolo（男低音）。",
        "filename": "歌剧重唱/1770429635422_Sextet_Riconosci_in_questo_amplesso_LE_NOZZE_DI_FIGARO.pdf",
        "date": "2026-02-06",
        "has_lyrics": False,
    },
    {
        "title": "Via, resti servita/您先请，不用客气",
        "composer": "Wolfgang Amadeus Mozart/莫扎特",
        "work": "Le nozze di Figaro, K.492/费加罗的婚礼",
        "language": "意大利语",
        "category": "歌剧重唱",
        "sub_category": "",
        "voice_count": "二重唱",
        "voice_types": "Soprano/Mezzo-Soprano",
        "tonality": "",
        "description": "Marcellina（次女高音）与 Susanna（女高音）的二重唱。",
        "filename": "歌剧重唱/1770429452852_Duet_Via_resti_servita_LE_NOZZE_DI_FIGARO.pdf",
        "date": "2026-02-06",
        "has_lyrics": False,
    },
    {
        "title": "Cherry Duet/樱桃二重唱（Suzel, buon dì/苏泽尔，日安）",
        "composer": "Pietro Mascagni/皮埃特罗·马斯卡尼",
        "work": "L'amico Fritz/友人弗利兹",
        "language": "意大利语",
        "category": "歌剧重唱",
        "sub_category": "",
        "voice_count": "二重唱",
        "voice_types": "Tenor/Soprano",
        "tonality": "",
        "description": "Suzel（女高音）与 Fritz（男高音）的二重唱。",
        "filename": "歌剧重唱/1770429145172_Duet_Cherry_Duet_Lamico_Fritz.pdf",
        "date": "2026-02-06",
        "has_lyrics": False,
    },
    {
        "title": "Ah guarda sorella",
        "composer": "Wolfgang Amadeus Mozart/莫扎特",
        "work": "Così fan tutte, K.588/女人心",
        "language": "意大利语",
        "category": "歌剧重唱",
        "sub_category": "",
        "voice_count": "二重唱",
        "voice_types": "Soprano/Mezzo-Soprano",
        "tonality": "",
        "description": "第一幕中 Fiordiligi（女高音）与 Dorabella（次女高音）的二重唱。",
        "filename": "歌剧重唱/1770428850247_Duet_Ah_guarda_sorella_COSI_FAN_TUTTE.pdf",
        "date": "2026-02-06",
        "has_lyrics": False,
    },
    {
        "title": "Dein ist mein ganzes Herz/你是我的一切",
        "composer": "Franz Lehár/弗朗茨·莱哈尔",
        "work": "Das Land des Lächelns/微笑王国",
        "language": "德语",
        "category": "歌剧咏叹调",
        "sub_category": "轻歌剧咏叹调",
        "voice_count": "",
        "voice_types": "Tenor/男高音",
        "tonality": "",
        "description": "轻歌剧《微笑王国》第二幕中 Sou-Chong 的男高音咏叹调。",
        "filename": "歌剧咏叹调/1765918079.pdf",
        "date": "2025-12-16",
        "has_lyrics": False,
    },
]

ALTERNATE_VERSIONS = {
    "歌剧咏叹调/1765919280.pdf": "《O ruddier than the cherry》的另一版本；目录已收录同曲目的 1765919379.pdf。",
}


def score_path(filename: str) -> Path:
    relative = PurePosixPath(filename)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"非法路径: {filename}")
    return SCORES_DIR.joinpath(*relative.parts)


def sha256(path: Path, cache: dict[Path, str]) -> str:
    if path not in cache:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        cache[path] = digest.hexdigest()
    return cache[path]


def public_id_for(filename: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://maotong.me/library/{filename}"))


def ensure_within(path: Path, parent: Path) -> None:
    resolved_path = path.resolve()
    resolved_parent = parent.resolve()
    if resolved_path != resolved_parent and resolved_parent not in resolved_path.parents:
        raise ValueError(f"路径越界，已停止移动: {path}")


def main() -> None:
    with DATA_FILE.open("r", encoding="utf-8-sig") as handle:
        data = json.load(handle)

    changes: list[str] = []
    language_updates: list[dict] = []
    for item in data:
        target_language = LANGUAGE_BY_ID.get(int(item["id"]))
        if target_language and item.get("language") != target_language:
            language_updates.append({
                "id": item["id"],
                "before": item.get("language", ""),
                "after": target_language,
            })
            item["language"] = target_language
            changes.append(f"补齐语言 id={item['id']}: {target_language}")

    existing_filenames = {item["filename"] for item in data}
    missing_records = [record.copy() for record in RESTORED_RECORDS if record["filename"] not in existing_filenames]
    next_id = max([int(item["id"]) for item in data] + [int(time.time() * 1000)]) + 1
    added_records: list[dict] = []
    for record in missing_records:
        path = score_path(record["filename"])
        if not path.is_file():
            raise FileNotFoundError(f"待恢复记录的 PDF 不存在: {record['filename']}")
        with path.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                raise ValueError(f"待恢复记录不是有效 PDF: {record['filename']}")
        record["id"] = next_id
        record["public_id"] = public_id_for(record["filename"])
        next_id += 1
        data.append(record)
        added_records.append(record)
        changes.append(f"恢复目录记录: {record['title']}")

    data.sort(key=lambda item: int(item["id"]), reverse=True)
    referenced = {item["filename"] for item in data}
    all_files = [path for path in SCORES_DIR.rglob("*") if path.is_file()]
    referenced_files = {
        path.relative_to(SCORES_DIR).as_posix(): path
        for path in all_files
        if path.relative_to(SCORES_DIR).as_posix() in referenced
    }
    orphan_files = {
        path.relative_to(SCORES_DIR).as_posix(): path
        for path in all_files
        if path.relative_to(SCORES_DIR).as_posix() not in referenced
    }

    referenced_by_size: dict[int, list[Path]] = defaultdict(list)
    for path in referenced_files.values():
        referenced_by_size[path.stat().st_size].append(path)

    hash_cache: dict[Path, str] = {}
    exact_duplicates: dict[str, str] = {}
    for relative, orphan in orphan_files.items():
        for candidate in referenced_by_size.get(orphan.stat().st_size, []):
            if sha256(orphan, hash_cache) == sha256(candidate, hash_cache):
                exact_duplicates[relative] = candidate.relative_to(SCORES_DIR).as_posix()
                break

    alternate_versions = {
        relative: reason
        for relative, reason in ALTERNATE_VERSIONS.items()
        if relative in orphan_files and relative not in exact_duplicates
    }
    unresolved = sorted(set(orphan_files) - set(exact_duplicates) - set(alternate_versions))
    if unresolved:
        raise RuntimeError(f"仍有未分类孤立文件，已停止且未修改: {unresolved}")

    if not changes and not exact_duplicates and not alternate_versions:
        print("无需清理：第二阶段已经完成。")
        return

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    BACKUP_DIR.mkdir(exist_ok=True)
    backup_path = BACKUP_DIR / f"data_backup_phase2_{timestamp}.json"
    backup_path.write_bytes(DATA_FILE.read_bytes())
    quarantine = BACKUP_DIR / "orphans" / f"phase2_{timestamp}"

    move_plan: list[tuple[Path, Path]] = []
    for relative in sorted(exact_duplicates):
        move_plan.append((orphan_files[relative], quarantine / "exact_duplicates" / Path(relative)))
    for relative in sorted(alternate_versions):
        move_plan.append((orphan_files[relative], quarantine / "alternate_versions" / Path(relative)))

    completed_moves: list[tuple[Path, Path]] = []
    temp_path = DATA_FILE.with_suffix(".json.phase2.tmp")
    try:
        for source, target in move_plan:
            ensure_within(source, SCORES_DIR)
            ensure_within(target, BACKUP_DIR)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise FileExistsError(f"隔离区已存在目标文件: {target}")
            source.replace(target)
            completed_moves.append((source, target))

        manifest = {
            "created_at": dt.datetime.now().isoformat(timespec="seconds"),
            "data_backup": backup_path.relative_to(ROOT).as_posix(),
            "language_updates": language_updates,
            "added_records": [
                {key: record[key] for key in ("id", "public_id", "title", "filename")}
                for record in added_records
            ],
            "exact_duplicates": exact_duplicates,
            "alternate_versions": alternate_versions,
        }
        quarantine.mkdir(parents=True, exist_ok=True)
        with (quarantine / "manifest.json").open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest, handle, indent=2, ensure_ascii=False)
            handle.write("\n")

        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, indent=4, ensure_ascii=False)
            handle.write("\n")
        os.replace(temp_path, DATA_FILE)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        for source, target in reversed(completed_moves):
            source.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and not source.exists():
                target.replace(source)
        raise

    print(f"数据备份：{backup_path.relative_to(ROOT)}")
    print(f"隔离区：{quarantine.relative_to(ROOT)}")
    print(f"补齐语言：{len(language_updates)} 条")
    print(f"恢复/新增目录记录：{len(added_records)} 条")
    print(f"隔离完全重复 PDF：{len(exact_duplicates)} 个")
    print(f"隔离其他版本 PDF：{len(alternate_versions)} 个")


if __name__ == "__main__":
    main()
