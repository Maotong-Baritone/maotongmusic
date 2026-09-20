"""Bounded nine-file batch for Brahms Op.63 low-voice songs."""
import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from tools import brahms_late_piano_batch as workflow
from tools.publish_brahms_op116 import PublicationBatch


IDS = ('311649', '311650', '311651', '311652', '44195', '311653', '311654', '44196', '311655')
BATCH = PublicationBatch(
    ids=IDS,
    batch_id='brahms-op63-low-voice-nine-20260919',
    stage_rel=Path('imports/johannes_brahms/staging/op63-low-voice-singles'),
    work_titles=('9 Lieder and Songs, Op.63',),
    log_message='新增勃拉姆斯《9 Lieder and Songs, Op. 63》低声部钢琴伴奏单曲9份；标题、速度、德语及编制均已核对。',
    allowed_voice_types=('声乐、钢琴', '低声部', '低声部、钢琴'),
    allowed_categories=('艺术歌曲',),
)


def source_record(file_id, root=workflow.ROOT):
    return workflow.source_record(file_id, root, batch=BATCH)


def apply_metadata_corrections(root=workflow.ROOT):
    title_changes = {
        '44195': ('No. 5 Junge Liebe I. Lebhaft, Op. 63', 'No. 5 Meine Liebe ist grün. Lebhaft, Op. 63'),
        '311653': ('No. 6 Junge Liebe II. Zart bewegt, Op. 63', 'No. 6 Wenn um den Holunder. Zart bewegt, Op. 63'),
        '311654': ('No. 7 Heimweh I. Zart bewegt, Op. 63', 'No. 7 Heimweh. Zart bewegt, Op. 63'),
        '44196': ('No. 8 Heimweh II. Etwas langsam, Op. 63', "No. 8 O wüsst' ich doch den Weg zurück. Etwas langsam, Op. 63"),
        '311655': ('No. 9 Heimweh III. Etwas langsam, Op. 63', 'No. 9 Ich sah als Knabe Blumen blühn. Etwas langsam, Op. 63'),
    }
    source_path = root / workflow.publication.REVIEW_REL
    stage_path = root / BATCH.stage_rel / 'manifest.json'
    source_before = source_path.read_bytes()
    stage_before = stage_path.read_bytes()
    source = workflow.publication.read_json(source_path)
    stage = workflow.publication.read_json(stage_path)
    source_by_id = {
        item['imslp_id']: item
        for work in source['works'] if work.get('title') in BATCH.work_titles
        for item in work['files'] if item['imslp_id'] in BATCH.ids
    }
    stage_by_id = {item['imslp_id']: item for item in stage['files']}
    if set(source_by_id) != set(IDS) or set(stage_by_id) != set(IDS):
        raise ValueError('Op.63 low-voice correction scope changed')
    for file_id in IDS:
        source_item = source_by_id[file_id]
        stage_item = stage_by_id[file_id]
        if (source_item['category'] != '艺术歌曲' or source_item['sub_category'] != ''
                or source_item['voice_types'] != '低声部'
                or source_item['language_cn'] != '德语'):
            raise ValueError(f'Op.63 source metadata changed concurrently: {file_id}')
        if (stage_item['category'] != '艺术歌曲' or stage_item['sub_category'] != ''
                or stage_item['voice_types'] != '低声部'
                or stage_item['language'] != '德语'):
            raise ValueError(f'Op.63 staged metadata changed concurrently: {file_id}')
    if any(source_by_id[file_id]['proposed_title'] != values[0]
           for file_id, values in title_changes.items()):
        raise ValueError('Op.63 source titles changed concurrently')
    if any(stage_by_id[file_id]['title'] != values[0]
           for file_id, values in title_changes.items()):
        raise ValueError('Staged Op.63 titles changed concurrently')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = root / 'backup' / 'import_metadata' / f'{BATCH.batch_id}-{stamp}'
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source_path, backup / 'manifest.json')
    shutil.copy2(stage_path, backup / 'staging-manifest.json')
    changes = []
    for file_id in IDS:
        source_by_id[file_id]['voice_types'] = '低声部、钢琴'
        stage_by_id[file_id]['voice_types'] = '低声部、钢琴'
        changes.append({
            'imslp_id': file_id, 'field': 'voice_types', 'before': '低声部',
            'after': '低声部、钢琴',
            'evidence': 'The live IMSLP page groups all nine selected files under Low voice; each rendered score has one vocal line with piano.',
        })
    for file_id, (before_title, corrected_title) in title_changes.items():
        source_by_id[file_id]['proposed_title'] = corrected_title
        source_by_id[file_id]['review_edited'] = True
        stage_by_id[file_id]['title'] = corrected_title
        changes.append({
            'imslp_id': file_id, 'field': 'proposed_title', 'before': before_title,
            'after': corrected_title,
            'evidence': 'The first rendered score page prints this independent title; the live IMSLP page notes that Brahms supplied the titles for Nos. 5–9.',
        })
    source_after = workflow.publication.json_bytes(source)
    stage_after = workflow.publication.json_bytes(stage)
    workflow.publication.atomic_bytes(source_path, source_after)
    workflow.publication.atomic_bytes(stage_path, stage_after)
    receipt = {
        'batch_id': BATCH.batch_id,
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'source_manifest_before_sha256': hashlib.sha256(source_before).hexdigest(),
        'source_manifest_after_sha256': hashlib.sha256(source_after).hexdigest(),
        'staging_manifest_before_sha256': hashlib.sha256(stage_before).hexdigest(),
        'staging_manifest_after_sha256': hashlib.sha256(stage_after).hexdigest(),
        'backup': str(backup.relative_to(root)),
        'changes': changes,
    }
    workflow.publication.atomic_bytes(root / BATCH.stage_rel / 'metadata-corrections.json', workflow.publication.json_bytes(receipt))
    return receipt


def record_inspection(root=workflow.ROOT):
    stage = root / BATCH.stage_rel
    manifest_path = stage / 'manifest.json'
    manifest = workflow.publication.read_json(manifest_path)
    by_id = {item['imslp_id']: item for item in manifest['files']}
    if set(by_id) != set(BATCH.ids):
        raise ValueError('Staged Op.63 low-voice scope changed before inspection record')
    titles = {file_id: by_id[file_id]['title'] for file_id in IDS}
    for file_id in IDS:
        by_id[file_id].update(
            rendered_pages=by_id[file_id]['page_count'],
            visual_check='matched_title_key_and_instrumentation',
            publication_note='',
            description_summary=f'来源：IMSLP #{file_id}；版本：低声部移调版；出版：N. Simrock（Peters再版）；编者：Max Friedlaender',
        )
    workflow.publication.atomic_bytes(manifest_path, workflow.publication.json_bytes(manifest))
    inspection = {
        'label': '9 Lieder and Songs, Op.63：低声部单曲',
        'checked_on': datetime.now().astimezone().date().isoformat(),
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'proposal_only': True,
        'publication_approved': False,
        'proposed_first_publication_ids': list(BATCH.ids),
        'source_notes': '实时IMSLP作品页确认Op.63为德语独唱与钢琴作品；所选九份均为Max Friedlaender编辑、标为Public Domain的低声部移调版，初版为N. Simrock并有Edition Peters再版。',
        'method': '保留原PDF字节；pypdf自动解析全部页面并校验SHA256；Poppler渲染全部页面；人工查看九份全页接触表并重点核对首尾、标题、速度、语言、编制和异常页。',
        'rendering_note': '九份普通清晰单曲的全部页面均已渲染；页数、内容连续性、可读性和末页收束正常。',
        'metadata_changes': workflow.publication.read_json(stage / 'metadata-corrections.json')['changes'],
        'files': {
            file_id: {
                'pages': by_id[file_id]['page_count'], 'key': '',
                'number': by_id[file_id]['movement_number'],
                'movement_start_pdf_pages': [1], 'titles': [titles[file_id]],
                'notes': f'{titles[file_id]}，共{by_id[file_id]["page_count"]}页；接触表及首尾页核对通过。',
                'publication_note': '',
            } for file_id in IDS
        },
    }
    workflow.publication.atomic_bytes(stage / 'inspection.json', workflow.publication.json_bytes(inspection))
    return inspection


def download(file_id, url, observed_at, *, access_method='wait_page'):
    workflow.download(file_id, url, observed_at, batch=BATCH, access_method=access_method)


def publish(*, execute=False):
    return workflow.publication.publish(batch=BATCH) if execute else workflow.publication.prepare(batch=BATCH)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    download_parser = sub.add_parser('download-observed')
    download_parser.add_argument('--links', default=str(workflow.ROOT / BATCH.stage_rel / 'observed-links.json'))
    sub.add_parser('correct-metadata')
    sub.add_parser('record-inspection')
    publish_parser = sub.add_parser('publish')
    publish_parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.command == 'download-observed':
        observed = workflow.publication.read_json(Path(args.links))
        if set(observed.get('links', {})) != set(IDS):
            raise ValueError('Observed-link scope differs from bounded batch')
        for file_id in IDS:
            download(file_id, observed['links'][file_id], observed['observed_at'])
    elif args.command == 'correct-metadata':
        print(json.dumps(apply_metadata_corrections(), ensure_ascii=True, indent=2))
    elif args.command == 'record-inspection':
        print(json.dumps(record_inspection(), ensure_ascii=True, indent=2))
    elif args.execute:
        publish(execute=True)
    else:
        plan = publish()
        print(json.dumps({'batch_id': BATCH.batch_id, 'count': len(plan['planned']),
                          'already_published': plan['already_published'],
                          'files': [p['item']['title'] for p in plan['planned']]},
                         ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
