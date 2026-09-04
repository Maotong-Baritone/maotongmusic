"""Four early Brahms piano works, processed in this active task, not scheduled."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.brahms_late_piano_batch import download, verify_live
from tools.publish_brahms_op116 import PublicationBatch, prepare, publish

BATCH = PublicationBatch(
    ids=('107601', '107614', '84139', '107616'),
    batch_id='brahms-opp1-2-4-5-four-20260902',
    stage_rel=Path('imports/johannes_brahms/staging/opp1-2-4-5'),
    work_titles=('Piano Sonata No.1, Op.1', 'Piano Sonata No.2, Op.2',
                 'Scherzo, Op.4', 'Piano Sonata No.3, Op.5'),
    log_message='新增勃拉姆斯早期钢琴作品 4 份：三首钢琴奏鸣曲 Op.1、2、5 与谐谑曲 Op.4，均为完整原始扫描版；保留 Op.号、调性，奏鸣曲详情附乐章目录和 PDF 页码，编制统一为钢琴独奏。',
)
STAGE = ROOT / BATCH.stage_rel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    fetch = sub.add_parser('download')
    fetch.add_argument('--id', choices=BATCH.ids, required=True)
    fetch.add_argument('--url', required=True)
    fetch.add_argument('--observed-at', required=True)
    fetch.add_argument('--direct-pdf-redirect', action='store_true')
    pub = sub.add_parser('publish')
    pub.add_argument('--execute', action='store_true')
    sub.add_parser('render')
    sub.add_parser('report')
    sub.add_parser('verify-live')
    args = parser.parse_args()
    if args.command == 'download':
        download(args.id, args.url, args.observed_at, batch=BATCH,
                 access_method='direct_pdf_redirect' if args.direct_pdf_redirect else 'wait_page')
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
