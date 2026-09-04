"""Bounded follow-up for two Brahms piano singles; normal source waiting required."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.brahms_late_piano_batch import download, verify_live
from tools.publish_brahms_op116 import PublicationBatch, prepare, publish

BATCH = PublicationBatch(
    ids=('107644', '649836'),
    batch_id='brahms-woo5-op39-singles-two-20260903',
    stage_rel=Path('imports/johannes_brahms/staging/woo5-op39-singles'),
    work_titles=('2 Sarabandes, WoO 5', '16 Waltzes, Op.39'),
    log_message='新增勃拉姆斯钢琴单曲谱 2 份：WoO 5 第 2 首萨拉班德舞曲手稿与 Op.39 第 15 首圆舞曲（降A大调）；依据实际谱面修正来源调性误标，保留原始文件并补充版本和 PDF 页码。',
)
STAGE = ROOT / BATCH.stage_rel

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    fetch = sub.add_parser('download')
    fetch.add_argument('--id', choices=BATCH.ids, required=True)
    fetch.add_argument('--url', required=True)
    fetch.add_argument('--observed-at', required=True)
    pub = sub.add_parser('publish')
    pub.add_argument('--execute', action='store_true')
    sub.add_parser('render')
    sub.add_parser('report')
    sub.add_parser('verify-live')
    args = parser.parse_args()
    if args.command == 'download':
        download(args.id, args.url, args.observed_at, batch=BATCH)
    elif args.command == 'render':
        from tools.render_brahms_late_piano import main as render
        render(stage=STAGE)
    elif args.command == 'report':
        from tools.report_brahms_late_piano import main as report
        report(batch=BATCH)
    elif args.command == 'verify-live':
        verify_live(batch=BATCH)
    elif args.execute:
        publish(batch=BATCH)
    else:
        plan = prepare(batch=BATCH)
        print(json.dumps({'batch_id': BATCH.batch_id, 'count': len(plan['planned']),
                          'already_published': plan['already_published'],
                          'files': [p['item']['title'] for p in plan['planned']]},
                         ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
