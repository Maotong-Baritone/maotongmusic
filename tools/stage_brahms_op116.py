"""Save only observed, released Op.116 PDF links to an isolated trial folder.

This tool has no handler/disclaimer resolver and no publication capability.
URLs must first be obtained from the visible anonymous download page after
its countdown finishes. No cookies or signed-in browser state are imported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "imports" / "johannes_brahms" / "staging" / "op116"
SOURCE = ROOT / "imports" / "johannes_brahms" / "manifest.json"
ALLOWED_IDS = {"23160", "8447", "84692", "84693", *(str(i) for i in range(1524, 1531))}
EDITION_NAMES = {
    "23160": "Simrock-1892-first-edition",
    "8447": "Peters-Sauer",
    "84692": "Breitkopf-Mandyczewski-scan",
    "84693": "Breitkopf-Mandyczewski-filter",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def validate_url(file_id, url, *, allowed_ids=ALLOWED_IDS):
    if file_id not in allowed_ids:
        raise ValueError("File is outside the explicitly bounded Op.116 trial")
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in
            {"imslp.org", "vmirror.imslp.org", "s9.imslp.org", "ks15.imslp.org"}
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("Only an observed HTTPS IMSLP PDF URL is allowed")
    name = urllib.parse.unquote(parsed.path.rsplit("/", 1)[-1])
    if not re.match(rf"IMSLP0*{re.escape(file_id)}-.*\.pdf$", name, re.I):
        raise ValueError("PDF filename does not match the requested IMSLP id")
    return name


def scoped_work():
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    matches = [w for w in source["works"] if w.get("title") == "7 Fantasien, Op.116"]
    if len(matches) != 1:
        raise ValueError("Expected exactly one Op.116 source work")
    return matches[0]


def new_manifest():
    work = scoped_work()
    return {
        "work": work["display_work_title"], "source_url": work["source_url"],
        "created_at": now(), "scope": "Op.116 local PDF trial only; not publication approval",
        "source_manifest_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "published": False, "files": [],
        "held_back": [
            {"imslp_id": f["imslp_id"], "title": f["proposed_title"],
             "copyright": f["copyright"], "reason": "特殊许可或版权附注，暂不下载"}
            for f in work["files"]
            if f.get("decision") != "excluded" and f["imslp_id"] not in ALLOWED_IDS
        ],
    }


def save_manifest(manifest):
    STAGE.mkdir(parents=True, exist_ok=True)
    target = STAGE / "manifest.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)


def local_name(file):
    file_id = file["imslp_id"]
    if file_id in EDITION_NAMES:
        title = "7 Fantasien - Op.116 - " + EDITION_NAMES[file_id]
    else:
        title = file["proposed_title"].replace("Op. 116", "Op.116")
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", title).strip(". ")
    return f"{title} - IMSLP{file_id}.pdf"


def download(file_id, url, observed_at, *, resume_validation=False):
    actual_name = validate_url(file_id, url)
    # Observation records identify the page interaction, not blanket consent.
    when = datetime.fromisoformat(observed_at)
    if when.tzinfo is None or when > datetime.now(timezone.utc):
        raise ValueError("A past timezone-aware visible-link observation is required")
    work = scoped_work()
    file = next(f for f in work["files"] if f["imslp_id"] == file_id)
    if file.get("decision") == "excluded" or file.get("copyright") != "Public Domain":
        raise ValueError("Source review/rights no longer match this trial")
    manifest_path = STAGE / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else new_manifest()
    target = STAGE / "pdfs" / local_name(file)
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = next((f for f in manifest["files"] if f["imslp_id"] == file_id), None)
    if target.exists():
        if not existing or hashlib.sha256(target.read_bytes()).hexdigest() != existing.get("sha256"):
            raise ValueError("Existing file is untracked or changed; refusing to overwrite")
        print(f"Already staged and hash verified: {file_id}")
        return
    temporary = target.with_suffix(".pdf.part")
    if temporary.exists() and not resume_validation:
        raise ValueError("Partial file exists; inspect it before retrying")
    request = urllib.request.Request(url, headers={
        "User-Agent": "MaoTongMusic-Op116-LocalReview/1.0",
        "Referer": file["handler_url"],
    })
    if not resume_validation:
        with urllib.request.urlopen(request, timeout=90) as response:
            validate_url(file_id, response.geturl())
            expected_length = response.headers.get("Content-Length")
            with temporary.open("xb") as stream:
                first = response.read(65536)
                if not first.startswith(b"%PDF-"):
                    raise ValueError("Response is not a PDF; stopping without a fallback route")
                stream.write(first)
                while chunk := response.read(1024 * 1024):
                    stream.write(chunk)
            if expected_length and temporary.stat().st_size != int(expected_length):
                raise ValueError("Truncated transfer; partial file retained for inspection")
    if not temporary.read_bytes().startswith(b"%PDF-"):
        raise ValueError("Not a PDF")
    from pypdf import PdfReader
    compatibility_note = ""
    try:
        reader = PdfReader(temporary)
        if reader.is_encrypted or not reader.pages:
            raise ValueError("Encrypted or empty PDF")
        for page in reader.pages:
            _ = page.mediabox
            content = page.get_contents()
            if content is not None:
                content.get_data()
        page_count = len(reader.pages)
        reader.close()
    except AttributeError as exc:
        if "NullObject" not in str(exc):
            raise
        # An old PDF can contain /Encrypt null: inspect, never rewrite/decrypt it.
        info = subprocess.run(["pdfinfo", str(temporary)], check=True, capture_output=True, text=True, errors="replace").stdout
        if not re.search(r"^Encrypted:\s+no\s*$", info, re.M):
            raise ValueError("Independent reader did not confirm unencrypted PDF") from exc
        page_count = int(re.search(r"^Pages:\s+(\d+)", info, re.M)[1])
        compatibility_note = "pypdf 遇到空加密字典时报错；Poppler 确认为未加密 PDF，需渲染及浏览器复核；原文件未改写"
    digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
    os.replace(temporary, target)
    manifest["files"].append({
        "imslp_id": file_id, "title": file["proposed_title"], "work": file["proposed_work"],
        "movement_number": file["movement_number"], "category": file["category"],
        "sub_category": file["sub_category"], "voice_types": file["voice_types"],
        "tonality": file["tonality"], "language": file["language_cn"],
        "publisher": file["publisher"], "editor": file["editor"],
        "copyright": file["copyright"], "source_description": file["description"],
        "handler_url": file["handler_url"], "observed_download_url": url,
        "link_visible_after_wait_at": observed_at, "downloaded_at": now(),
        "actual_source_filename": actual_name, "local_path": target.relative_to(STAGE).as_posix(),
        "bytes": target.stat().st_size, "sha256": digest, "page_count": page_count,
        "technical_check": "PDF header, SHA256; " + ("Poppler pdfinfo" if compatibility_note else "pypdf page/content parsing"),
        "compatibility_note": compatibility_note,
        "visual_check": "pending", "publication_approved": False,
    })
    manifest["updated_at"] = now()
    save_manifest(manifest)
    print(json.dumps({"id":file_id, "path":str(target), "pages":page_count, "bytes":target.stat().st_size}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", required=True, choices=sorted(ALLOWED_IDS))
    parser.add_argument("--url", required=True, help="Visible download link after anonymous countdown")
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--resume-validation", action="store_true", help="Inspect a retained .part without another network request")
    args = parser.parse_args()
    download(args.id, args.url, args.observed_at, resume_validation=args.resume_validation)
