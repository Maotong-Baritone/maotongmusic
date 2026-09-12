"""Bounded ten-file batch for Brahms Op.97 and Op.121 Peters high-voice songs."""
import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from tools import brahms_late_piano_batch as workflow
from tools.publish_brahms_op116 import PublicationBatch


IDS = ('232392', '232393', '232394', '232395', '232396', '232397',
       '64768', '64769', '64770', '64771')
TITLE_CHANGES = {
    '232392': ('No. 1 Nachtigall Langsam, Op. 97', 'No. 1 Nachtigall. Langsam, Op. 97'),
    '232393': ('No. 2 Auf dem Schiffe Lebhaft und rasch, Op. 97', 'No. 2 Auf dem Schiffe. Lebhaft und rasch, Op. 97'),
    '232394': ('No. 3 Entführung Schnell, Op. 97', 'No. 3 Entführung. Schnell, Op. 97'),
    '232395': ('No. 4 Dort in den Weiden steht ein Haus Lebhaft und anmuthig, Op. 97', 'No. 4 Dort in den Weiden. Lebhaft und anmuthig, Op. 97'),
    '232396': ('No. 5 Komm bald Zart bewegt, Op. 97', 'No. 5 Komm bald. Zart bewegt, Op. 97'),
    '232397': ('No. 6 Trennung Anmuthig bewegt, Op. 97', 'No. 6 Trennung. Anmuthig bewegt, Op. 97'),
    '64771': ('No. 4 Wenn ich mit Menschen und mit Engelszungen redete. Con moto ed anima, Op. 121',
              'No. 4 Wenn ich mit Menschen und mit Engelszungen redete. Andante con moto ed anima, Op. 121'),
}
BATCH = PublicationBatch(
    ids=IDS,
    batch_id='brahms-op97-op121-high-voice-ten-20260909',
    stage_rel=Path('imports/johannes_brahms/staging/op97-op121-high-voice-singles'),
    work_titles=('6 Lieder, Op.97', '4 Serious Songs, Op.121'),
    log_message='新增勃拉姆斯Op.97与Op.121的Peters高声部独立歌曲谱10份；标题、速度、德语及高声部与钢琴编制均已核对。',
    allowed_voice_types=('声乐、钢琴', '高声部', '高声部、钢琴'),
    allowed_categories=('艺术歌曲',),
)


def source_record(file_id, root=workflow.ROOT):
    return workflow.source_record(file_id, root, batch=BATCH)


def apply_metadata_corrections(root=workflow.ROOT):
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
        raise ValueError('Op.97/121 correction scope changed')
    for file_id in IDS:
        source_item = source_by_id[file_id]
        stage_item = stage_by_id[file_id]
        if (source_item['category'] != '艺术歌曲' or source_item['sub_category'] != ''
                or source_item['voice_types'] != '声乐、钢琴'
                or source_item['language_cn'] != '法语'):
            raise ValueError(f'Op.97/121 source metadata changed concurrently: {file_id}')
        if (stage_item['category'] != '艺术歌曲' or stage_item['sub_category'] != ''
                or stage_item['voice_types'] != '声乐、钢琴'
                or stage_item['language'] != '法语'):
            raise ValueError(f'Op.97/121 staged metadata changed concurrently: {file_id}')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = root / 'backup' / 'import_metadata' / f'{BATCH.batch_id}-{stamp}'
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source_path, backup / 'manifest.json')
    shutil.copy2(stage_path, backup / 'staging-manifest.json')
    changes = []
    for file_id in IDS:
        source_by_id[file_id]['voice_types'] = '高声部、钢琴'
        stage_by_id[file_id]['voice_types'] = '高声部、钢琴'
        changes.append({
            'imslp_id': file_id, 'field': 'voice_types', 'before': '声乐、钢琴',
            'after': '高声部、钢琴',
            'evidence': 'The live IMSLP page groups the selected Peters file under High Voice; the rendered score has one vocal line with piano.',
        })
        source_by_id[file_id]['language_cn'] = '德语'
        stage_by_id[file_id]['language'] = '德语'
        changes.append({
            'imslp_id': file_id, 'field': 'language', 'before': '法语', 'after': '德语',
            'evidence': 'The live IMSLP work page identifies German and the selected Peters score uses German text.',
        })
        if file_id in TITLE_CHANGES:
            before_title, after_title = TITLE_CHANGES[file_id]
            if source_by_id[file_id]['proposed_title'] != before_title or stage_by_id[file_id]['title'] != before_title:
                raise ValueError(f'Op.97/121 title changed concurrently: {file_id}')
            source_by_id[file_id]['proposed_title'] = after_title
            stage_by_id[file_id]['title'] = after_title
            changes.append({
                'imslp_id': file_id, 'field': 'title', 'before': before_title, 'after': after_title,
                'evidence': 'The rendered first page supplies the printed title and tempo; punctuation separates the independent title from its tempo.',
            })
        if file_id == '232397':
            if source_by_id[file_id]['tonality'] != '' or stage_by_id[file_id]['tonality'] != '':
                raise ValueError('Op.97 No.6 tonality changed concurrently')
            source_by_id[file_id]['tonality'] = '降A大调'
            stage_by_id[file_id]['tonality'] = '降A大调'
            changes.append({
                'imslp_id': file_id, 'field': 'tonality', 'before': '', 'after': '降A大调',
                'evidence': 'The IMSLP high-voice file is labelled A-flat major and the rendered score shows four flats; it also prints the original key as F major.',
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
        raise ValueError('Staged Op.97/121 scope changed before inspection record')
    titles = {file_id: by_id[file_id]['title'] for file_id in IDS}
    for file_id, title in titles.items():
        by_id[file_id].update(
            rendered_pages=by_id[file_id]['page_count'],
            visual_check='matched_title_key_and_instrumentation',
            publication_note='',
            description_summary=f'来源：IMSLP #{file_id}；版本：Peters高声部版；出版：Edition Peters；编者：Max Friedlaender',
        )
    workflow.publication.atomic_bytes(manifest_path, workflow.publication.json_bytes(manifest))
    inspection = {
        'label': 'Op.97与Op.121：Peters高声部独立歌曲',
        'checked_on': datetime.now().astimezone().date().isoformat(),
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'proposal_only': True,
        'publication_approved': False,
        'proposed_first_publication_ids': list(BATCH.ids),
        'source_notes': '实时IMSLP作品页确认两套作品均为德语、声乐与钢琴、Public Domain；所选十份均属于Max Friedlaender编订的Edition Peters高声部组。完整谱、低声部、中声部及改编不在本批。',
        'method': '保留原PDF字节；pypdf自动解析全部页面并校验SHA256；Poppler渲染全部页面；人工通览十份完整接触表并重点放大核对首尾、标题、速度、德语、编制和异常页。',
        'rendering_note': '十份普通清晰单曲的全部页面均已渲染；页序连续、标题和歌词可辨、末页完整结束。',
        'metadata_changes': workflow.publication.read_json(stage / 'metadata-corrections.json')['changes'],
        'files': {
            file_id: {
                'pages': by_id[file_id]['page_count'], 'key': '',
                'number': by_id[file_id]['movement_number'],
                'movement_start_pdf_pages': [1], 'titles': [title],
                'notes': f'{title}；共{by_id[file_id]["page_count"]}页；完整接触表及首尾页检查通过。',
                'publication_note': '',
            } for file_id, title in titles.items()
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
