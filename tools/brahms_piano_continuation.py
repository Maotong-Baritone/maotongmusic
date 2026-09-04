"""Bounded third batch; no automatic scheduling and no hidden URL resolution."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.brahms_late_piano_batch import download, verify_live
from tools.publish_brahms_op116 import PublicationBatch, prepare, publish
from tools.publish_brahms_op116 import REVIEW_REL, atomic_bytes, json_bytes, read_json

BATCH = PublicationBatch(
    ids=('84162','16646','16647','16648','16649','1033090','110908','110909','84690','16650','16651'),
    batch_id='brahms-opp10-76-79-eleven-20260902',
    stage_rel=Path('imports/johannes_brahms/staging/opp10-76-79'),
    work_titles=('4 Ballades, Op.10','8 Klavierstücke, Op.76','2 Rhapsodies, Op.79'),
    log_message='新增勃拉姆斯 Op.10、76、79 乐谱 11 份：3 份完整原始扫描及 8 份独立单曲谱；单曲保留独立标题、Op.号、调性，编制统一为钢琴独奏。Op.76 的其余曲目可在完整谱中查阅。',
)
STAGE = ROOT/BATCH.stage_rel


def apply_recorded_corrections(root=ROOT):
    """Apply exactly three recorded review corrections, without approving files."""
    root = Path(root)
    stage = root/BATCH.stage_rel
    inspection = read_json(stage/'inspection.json')
    corrections = inspection['metadata_changes']
    if set(corrections) != {'16646','16650','16651'}:
        raise ValueError('Unexpected correction scope')
    paths = [root/REVIEW_REL, stage/'manifest.json']
    before = {p:p.read_bytes() for p in paths}
    review, trial = [json.loads(before[p].decode('utf-8-sig')) for p in paths]
    sources = {f['imslp_id']:f for w in review['works'] for f in w['files']}
    staged = {f['imslp_id']:f for f in trial['files']}
    changed = []
    for file_id, correction in corrections.items():
        source, file = sources[file_id], staged[file_id]
        for label, source_key, staged_key in [('key','tonality','tonality'),('title','proposed_title','title')]:
            if 'after_'+label not in correction:
                continue
            old, new = correction['before_'+label], correction['after_'+label]
            if source[source_key] == new and file[staged_key] == new:
                continue
            if source[source_key] != old or file[staged_key] != old or source['decision'] != 'pending':
                raise ValueError('Metadata changed concurrently or already published')
            source[source_key] = file[staged_key] = new
            source['review_edited'] = True
            source['review_notes'] = '2026-09-02 原谱核对：'+inspection['files'][file_id]['notes']
            changed.append(file_id+':'+source_key)
    if not changed:
        print('Recorded corrections already applied; no changes')
        return
    backup = root/'backup/import_publications'/('opp10-76-79-metadata-'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    backup.mkdir(parents=True)
    for n, path in enumerate(paths):
        (backup/f'{n}-{path.name}').write_bytes(before[path])
    if any(p.read_bytes()!=before[p] for p in paths):
        raise ValueError('Concurrent review edit')
    written = {}
    try:
        for path, value in zip(paths, (review,trial)):
            content = json_bytes(value)
            atomic_bytes(path, content)
            written[path] = content
    except Exception:
        for path, content in written.items():
            if path.read_bytes() == content:
                atomic_bytes(path,before[path])
        raise
    print('Applied recorded corrections: '+', '.join(changed))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    fetch = sub.add_parser('download')
    fetch.add_argument('--id', choices=BATCH.ids, required=True)
    fetch.add_argument('--url', required=True)
    fetch.add_argument('--observed-at', required=True)
    fetch.add_argument('--direct-pdf-redirect', action='store_true', help='Record a normal handler redirect observed in the browser; not an alternate download route')
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
        print(json.dumps({'batch_id':BATCH.batch_id,'count':len(plan['planned']),
                          'already_published':plan['already_published'],
                          'files':[p['item']['title'] for p in plan['planned']]},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
