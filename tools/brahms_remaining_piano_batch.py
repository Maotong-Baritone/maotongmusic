"""Bounded Brahms continuation; source links require normal browser release."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.brahms_late_piano_batch import download, verify_live
from tools.publish_brahms_op116 import PublicationBatch, prepare, publish

BATCH = PublicationBatch(
    ids=('57520', '103886', '103888', '84174', '57514'),
    batch_id='brahms-woo4-6-op18b-39-five-20260903',
    stage_rel=Path('imports/johannes_brahms/staging/woo4-6-op18b-39'),
    work_titles=('2 Gigues, WoO 4', '2 Sarabandes, WoO 5',
                 'Theme and Variations, Op.18b', '16 Waltzes, Op.39',
                 '51 Exercises, WoO 6'),
    log_message='新增勃拉姆斯钢琴乐谱 5 份：WoO 4 两首吉格舞曲、WoO 5 两首萨拉班德舞曲、Op.18b 主题与变奏、Op.39 十六首圆舞曲（作曲家钢琴独奏版）及 WoO 6 五十一首练习；保留作品编号与原文件，详情补充内容和实际 PDF 页码。',
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
