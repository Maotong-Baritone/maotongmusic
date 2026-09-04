"""Bounded batch for the reviewed 5 Studies, Anh.1a/1 sources."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.brahms_late_piano_batch import download, verify_live
from tools.publish_brahms_op116 import PublicationBatch, prepare, publish

BATCH = PublicationBatch(
    ids=("57515", "454876", "454879", "64516"),
    batch_id="brahms-studies-anh1a1-four-20260904",
    stage_rel=Path("imports/johannes_brahms/staging/studies-anh1a1"),
    work_titles=("5 Studies, Anh.1a/1",),
    log_message=(
        "新增勃拉姆斯《5 Studies, Anh.1a/1》钢琴乐谱 4 份："
        "1 份完整 Breitkopf-Mandyczewski 版及第 1、2、5 首独立谱；"
        "第 1、2 首为双手钢琴，第 5 首为钢琴左手，保留原始文件并补充实际 PDF 页码。"
    ),
    allowed_voice_types=("钢琴独奏", "钢琴左手"),
)
STAGE = ROOT / BATCH.stage_rel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("download")
    fetch.add_argument("--id", choices=BATCH.ids, required=True)
    fetch.add_argument("--url", required=True)
    fetch.add_argument("--observed-at", required=True)
    pub = sub.add_parser("publish")
    pub.add_argument("--execute", action="store_true")
    sub.add_parser("render")
    sub.add_parser("report")
    sub.add_parser("verify-live")
    args = parser.parse_args()

    if args.command == "download":
        download(args.id, args.url, args.observed_at, batch=BATCH)
    elif args.command == "render":
        from tools.render_brahms_late_piano import main as render
        render(stage=STAGE)
    elif args.command == "report":
        from tools.report_brahms_late_piano import main as report
        report(batch=BATCH)
    elif args.command == "verify-live":
        verify_live(batch=BATCH)
    elif args.execute:
        publish(batch=BATCH)
    else:
        plan = prepare(batch=BATCH)
        print(json.dumps({
            "batch_id": BATCH.batch_id,
            "count": len(plan["planned"]),
            "already_published": plan["already_published"],
            "files": [p["item"]["title"] for p in plan["planned"]],
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
