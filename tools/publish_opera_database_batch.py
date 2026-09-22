"""Publish locally imported Opera Database PDFs to configured score storage."""

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from score_storage import apply_storage_metadata, manifest_entry_for, publish_entries, update_manifest_entries

CATALOG = ROOT / "data.json"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--batch-id", default="opera-database-french-20260921")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    pending = [item for item in catalog if item.get("import_batch_id") == args.batch_id and not item.get("storage_synced_at")]
    if args.limit:
        pending = pending[: args.limit]
    print(f"pending {len(pending)}", flush=True)
    for offset in range(0, len(pending), 25):
        chunk = pending[offset:offset + 25]
        entries = [manifest_entry_for(ROOT / "scores" / item["filename"], public_id=item["public_id"], catalog_filename=item["filename"]) for item in chunk]
        result = publish_entries(entries, force=True, workers=4)
        if not result.enabled:
            raise RuntimeError(result.detail)
        for item, entry in zip(chunk, result.entries):
            apply_storage_metadata(item, entry)
        update_manifest_entries(result.entries, ROOT / "storage-manifest.json")
        CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
        print(f"published {offset + len(chunk)} / {len(pending)}: {result.detail}", flush=True)


if __name__ == "__main__":
    main()
