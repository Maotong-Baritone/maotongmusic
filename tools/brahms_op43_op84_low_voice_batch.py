"""Bounded nine-file batch for Brahms's Op.43 and Op.84 low-voice songs."""
import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from tools import brahms_late_piano_batch as workflow
from tools.publish_brahms_op116 import PublicationBatch


IDS = ('244481', '245413', '246293', '246294',
       '38727', '38728', '346942', '38729', '346943')
BATCH = PublicationBatch(
    ids=IDS,
    batch_id='brahms-op43-op84-low-voice-nine-20260925',
    stage_rel=Path('imports/johannes_brahms/staging/op43-op84-low-voice-singles'),
    work_titles=('4 Songs, Op.43', '5 Romances and Songs, Op.84'),
    log_message='新增勃拉姆斯Op.43与Op.84低声部Peters独立歌曲谱9份；标题、速度、德语及实际声乐重唱与钢琴编制均已核对。',
    allowed_voice_types=('低声部', '圆号分谱', '低声部、钢琴', '二重唱、钢琴'),
    allowed_categories=('艺术歌曲', '器乐分谱'),
)


def source_record(file_id, root=workflow.ROOT):
    return workflow.source_record(file_id, root, batch=BATCH)


def apply_metadata_corrections(root=workflow.ROOT):
    """Correct parser errors using the live work pages and rendered scores."""
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
        raise ValueError('Op.43/84 low-voice correction scope changed')
    op43_ids = set(IDS[:4])
    for file_id in IDS:
        source_item = source_by_id[file_id]
        stage_item = stage_by_id[file_id]
        if file_id == '246293':
            expected = ('器乐分谱', '艺术歌曲', '圆号分谱', '')
        elif file_id in op43_ids:
            expected = ('艺术歌曲', '', '低声部', '英语')
        else:
            expected = ('艺术歌曲', '', '低声部', '法语')
        if tuple(source_item[k] for k in ('category', 'sub_category', 'voice_types', 'language_cn')) != expected:
            raise ValueError(f'Op.43/84 source metadata changed concurrently: {file_id}')
        if tuple(stage_item[k] for k in ('category', 'sub_category', 'voice_types', 'language')) != expected:
            raise ValueError(f'Op.43/84 staged metadata changed concurrently: {file_id}')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = root / 'backup' / 'import_metadata' / f'{BATCH.batch_id}-{stamp}'
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source_path, backup / 'manifest.json')
    shutil.copy2(stage_path, backup / 'staging-manifest.json')
    changes = []
    for file_id in IDS:
        before_voice = '圆号分谱' if file_id == '246293' else '低声部'
        after_voice = '低声部、钢琴' if file_id in op43_ids else '二重唱、钢琴'
        source_by_id[file_id]['voice_types'] = after_voice
        stage_by_id[file_id]['voice_types'] = after_voice
        changes.append({
            'imslp_id': file_id, 'field': 'voice_types', 'before': before_voice,
            'after': after_voice,
            'evidence': ('The live IMSLP page groups all four files under the Peters low-voice edition; the rendered score is voice and piano. “Horn” belongs to No.3’s German title.'
                         if file_id in op43_ids else
                         'The live IMSLP page identifies two voices with piano; the low-voice edition preserves the work’s alternating vocal roles.'),
        })
        if file_id == '246293':
            for key, after in (('category', '艺术歌曲'), ('sub_category', '')):
                before = source_by_id[file_id][key]
                source_by_id[file_id][key] = after
                stage_by_id[file_id][key] = after
                changes.append({'imslp_id': file_id, 'field': key, 'before': before, 'after': after,
                                'evidence': '“Horn” is part of the German song title; the live low-voice group and score confirm an art song.'})
        source_by_id[file_id]['language_cn'] = '德语'
        stage_by_id[file_id]['language'] = '德语'
        changes.append({
            'imslp_id': file_id, 'field': 'language',
            'before': ('' if file_id == '246293' else ('英语' if file_id in op43_ids else '法语')),
            'after': '德语',
            'evidence': 'Both live IMSLP work pages identify German and the selected Peters scores use German text.',
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
        raise ValueError('Staged Op.43/84 low-voice scope changed before inspection record')
    titles = {file_id: by_id[file_id]['title'] for file_id in IDS}
    for file_id, title in titles.items():
        version = 'Peters低声部版' if file_id in IDS[:4] else 'Peters低声部二重唱版'
        by_id[file_id].update(
            rendered_pages=by_id[file_id]['page_count'],
            visual_check='matched_title_key_and_instrumentation',
            publication_note='',
            description_summary=f'来源：IMSLP #{file_id}；版本：{version}；出版：Edition Peters；编者：Max Friedlaender',
        )
    workflow.publication.atomic_bytes(manifest_path, workflow.publication.json_bytes(manifest))
    inspection = {
        'label': 'Op.43与Op.84：Peters低声部独立歌曲',
        'checked_on': datetime.now().astimezone().date().isoformat(),
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'proposal_only': True,
        'publication_approved': False,
        'proposed_first_publication_ids': list(BATCH.ids),
        'source_notes': '实时IMSLP作品页确认两套作品均为德语、Public Domain；Op.43四份属于Peters低声部组，Op.84五份属于Peters低声部组，原作编制为二声部与钢琴。#246293标题中的Horn被解析器误判为圆号分谱。其他完整谱、中声部、手稿及改编不在本批。',
        'method': '保留原PDF字节；pypdf自动解析全部页面并校验SHA256；Poppler渲染全部页面；人工通览九份完整接触表并重点放大核对首尾、标题、速度、德语、编制和异常页。',
        'rendering_note': '九份普通清晰单曲的全部页面均已渲染；页序连续、标题和歌词可辨、末页完整结束。Op.84谱面以角色标记交替演唱。',
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
