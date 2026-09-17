"""Build the public Cloudflare Pages directory.

The repository also contains local administration code, source PDFs, imports, and
backups.  Those files are deliberately excluded: public PDFs are served from R2.
"""

from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist"

PUBLIC_FILES = (
    "index.html",
    "contact.html",
    "resources.html",
    "data.json",
    "logs.json",
    "site-config.json",
)
PUBLIC_DIRECTORIES = ("css", "js", "img", "lyrics")
PAGES_FILE_SIZE_LIMIT = 25 * 1024 * 1024


def build() -> None:
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir()

    for relative_path in PUBLIC_FILES:
        source = ROOT / relative_path
        if not source.is_file():
            raise FileNotFoundError(f"Required public file is missing: {relative_path}")
        shutil.copy2(source, OUTPUT / relative_path)

    for relative_path in PUBLIC_DIRECTORIES:
        source = ROOT / relative_path
        if not source.is_dir():
            raise FileNotFoundError(f"Required public directory is missing: {relative_path}")
        shutil.copytree(source, OUTPUT / relative_path)

    oversized = [
        path.relative_to(OUTPUT)
        for path in OUTPUT.rglob("*")
        if path.is_file() and path.stat().st_size > PAGES_FILE_SIZE_LIMIT
    ]
    if oversized:
        names = ", ".join(str(path) for path in oversized)
        raise RuntimeError(f"Cloudflare Pages assets exceed 25 MiB: {names}")

    file_count = sum(path.is_file() for path in OUTPUT.rglob("*"))
    print(f"Built {file_count} public files in {OUTPUT}")


if __name__ == "__main__":
    build()
