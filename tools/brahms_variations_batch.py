"""Six reviewed Brahms piano-variation scans for the next bounded batch."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.brahms_late_piano_batch import download, verify_live
from tools.publish_brahms_op116 import (PublicationBatch, REVIEW_REL, atomic_bytes,
                                        json_bytes, prepare, publish, read_json)

BATCH = PublicationBatch(
    ids=('107618', '107692', '107694', '107697', '107699', '107701'),
    batch_id='brahms-variations-six-20260903',
    stage_rel=Path('imports/johannes_brahms/staging/variations-op9-21-24-35'),
    work_titles=(
        'Variations on a Theme by Robert Schumann, Op.9',
        'Variations on an Original Theme, Op.21 No.1',
        'Variations on a Hungarian Song, Op.21 No.2',
        'Variations and Fugue on a Theme by Handel, Op.24',
        'Variations on a Theme by Paganini, Op.35',
    ),
    log_message='新增勃拉姆斯钢琴变奏曲乐谱 6 份：Op.9、Op.21 No.1、Op.21 No.2、Op.24，以及 Op.35 第一、第二册；均保留 Op.号与调性，Op.35 两册分别标明 Book I / Book II，编制统一为钢琴独奏。',
)
STAGE = ROOT / BATCH.stage_rel

OP35_CORRECTIONS = {
    '107699': {
        'before': ('Variations on a Theme by Paganini, Op. 35', '', 'whole_work'),
        'after': ('Variations on a Theme by Paganini, Op. 35, Book I',
                  'Variations on a Theme by Paganini, Op. 35', 'selection'),
    },
    '107701': {
        'before': ('Variations on a Theme by Paganini, Op. 35', '', 'whole_work'),
        'after': ('Variations on a Theme by Paganini, Op. 35, Book II',
                  'Variations on a Theme by Paganini, Op. 35', 'selection'),
    },
}


def apply_recorded_corrections(root=ROOT):
    """Record only the two source-confirmed Op.35 book-scope corrections."""
    root = Path(root)
    path = root / REVIEW_REL
    before_bytes = path.read_bytes()
    review = json.loads(before_bytes.decode('utf-8-sig'))
    sources = {f['imslp_id']: f for w in review['works'] for f in w['files']}
    changed = []
    for file_id, correction in OP35_CORRECTIONS.items():
        source = sources[file_id]
        before = correction['before']
        after = correction['after']
        current = (source['proposed_title'], source['proposed_work'], source['title_scope'])
        if current == after:
            continue
        if current != before or source['decision'] != 'pending':
            raise ValueError('Metadata changed concurrently or source is no longer pending')
        source['proposed_title'], source['proposed_work'], source['title_scope'] = after
        source['review_edited'] = True
        source['review_notes'] = ('2026-09-03 IMSLP 来源页核对：该文件仅为 Op.35 的 '
                                  + ('Book I。' if file_id == '107699' else 'Book II。'))
        changed.append(file_id)
    if not changed:
        print('Recorded Op.35 book corrections already applied; no changes')
        return
    backup = root / 'backup/import_publications' / (
        'op35-book-metadata-' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    backup.mkdir(parents=True)
    (backup / path.name).write_bytes(before_bytes)
    if path.read_bytes() != before_bytes:
        raise ValueError('Concurrent review edit')
    atomic_bytes(path, json_bytes(review))
    print('Applied recorded Op.35 book corrections: ' + ', '.join(changed))


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
    sub.add_parser('apply-recorded-corrections')
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
    elif args.command == 'apply-recorded-corrections':
        apply_recorded_corrections()
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
