"""Bounded seven-file batch for Brahms medium-voice songs from Opp.71 and 84."""
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import brahms_late_piano_batch as workflow
from tools.publish_brahms_op116 import PublicationBatch


IDS = ('138117', '138118', '138119', '138120', '142695', '142696', '142697')
OP84_IDS = {'142695', '142696', '142697'}
TITLE_CORRECTIONS = {
    '138117': (
        'No. 1 Es liebt sich so lieblich im Lenze! Anmuthig bewegt, Op. 71',
        'No. 1 Es liebt sich so lieblich im Lenze. Anmuthig bewegt, Op. 71',
    ),
}
BATCH = PublicationBatch(
    ids=IDS,
    batch_id='brahms-op71-op84-medium-voice-seven-20260929',
    stage_rel=Path('imports/johannes_brahms/staging/op71-op84-medium-voice-singles'),
    work_titles=('5 Songs, Op.71', '5 Romances and Songs, Op.84'),
    log_message='新增勃拉姆斯Op.71与Op.84中音声部Peters独立歌曲谱7份；标题、编号、速度、德语及实际声乐与钢琴编制均已核对。',
    allowed_voice_types=('中音声部、钢琴', '二重唱、钢琴'),
    allowed_categories=('艺术歌曲',),
)
DOWNLOAD_BATCH = PublicationBatch(
    ids=IDS,
    batch_id=BATCH.batch_id,
    stage_rel=BATCH.stage_rel,
    work_titles=BATCH.work_titles,
    log_message=BATCH.log_message,
    allowed_voice_types=('中音声部',),
    allowed_categories=('艺术歌曲',),
)


def _source(root=workflow.ROOT):
    data = workflow.publication.read_json(root / workflow.publication.REVIEW_REL)
    by_id = {
        f['imslp_id']: (w, f)
        for w in data['works']
        if w.get('title') in BATCH.work_titles
        for f in w['files']
        if f['imslp_id'] in IDS
    }
    if set(by_id) != set(IDS):
        raise ValueError('Medium-voice source scope changed')
    return data, by_id


def correct_metadata_and_complete_manifest(root=workflow.ROOT):
    stage = root / BATCH.stage_rel
    review_path = root / workflow.publication.REVIEW_REL
    trial_path = stage / 'manifest.json'
    review_before = review_path.read_bytes()
    trial_before = trial_path.read_bytes()
    review, by_id = _source(root)
    trial = workflow.publication.read_json(trial_path)
    technical = {f['imslp_id']: f for f in trial['files']}
    if set(technical) != set(IDS):
        raise ValueError('Downloaded file scope changed')
    for file_id, (_, source) in by_id.items():
        current = (source['voice_types'], source['language_cn'])
        if current != ('中音声部', '法语'):
            raise ValueError(f'Source metadata changed concurrently: {file_id}: {current!r}')
        if file_id in TITLE_CORRECTIONS and source['proposed_title'] != TITLE_CORRECTIONS[file_id][0]:
            raise ValueError(f'Source title changed concurrently: {file_id}: {source["proposed_title"]!r}')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = root / 'backup' / 'import_metadata' / f'{BATCH.batch_id}-{stamp}'
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(review_path, backup / 'manifest.json')
    shutil.copy2(trial_path, backup / 'staging-manifest.json')
    changes, completed = [], []
    for file_id in IDS:
        work, source = by_id[file_id]
        before_voice, before_language = source['voice_types'], source['language_cn']
        target_voice = '二重唱、钢琴' if file_id in OP84_IDS else '中音声部、钢琴'
        source['voice_types'] = target_voice
        source['language_cn'] = '德语'
        changes.append({'imslp_id': file_id, 'field': 'voice_types', 'before': before_voice, 'after': target_voice, 'evidence': '实时IMSLP中音声部组及谱面角色、钢琴系统所示实际编制。'})
        changes.append({'imslp_id': file_id, 'field': 'language', 'before': before_language, 'after': '德语', 'evidence': '实时IMSLP作品页及谱面歌词均为德语。'})
        if file_id in TITLE_CORRECTIONS:
            before_title, target_title = TITLE_CORRECTIONS[file_id]
            source['proposed_title'] = target_title
            changes.append({'imslp_id': file_id, 'field': 'title', 'before': before_title, 'after': target_title, 'evidence': '谱面首页标题以句点结束。'})
        item = technical[file_id]
        completed.append({
            'imslp_id': file_id,
            'public_id': source['public_id'],
            **{key: source[value] for key, value in workflow.publication.FIELD_MAP.items()},
            'movement_number': source['movement_number'],
            'title_scope': source['title_scope'],
            'source_url': work['source_url'],
            'publisher': source['publisher'],
            'editor': source['editor'],
            'source_description': source['description'],
            'copyright': source['copyright'],
            'handler_url': source['handler_url'],
            'access_method': 'wait_page',
            'local_path': item['local_path'],
            'sha256': item['sha256'],
            'bytes': (stage / item['local_path']).stat().st_size,
            'page_count': item['page_count'],
            'technical_check': 'PDF header, SHA256, pypdf page/content parsing, source-listed page count',
            'visual_check': 'pending',
            'publication_approved': False,
        })
    full_trial = {
        'batch_id': BATCH.batch_id,
        'scope': 'Opp.71 and 84 medium-voice Peters single songs',
        'authorization': 'User authorized continued reviewed Brahms batches.',
        'published': False,
        'files': completed,
    }
    review_after = workflow.publication.json_bytes(review)
    trial_after = workflow.publication.json_bytes(full_trial)
    workflow.publication.atomic_bytes(review_path, review_after)
    workflow.publication.atomic_bytes(trial_path, trial_after)
    receipt = {
        'batch_id': BATCH.batch_id,
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'source_manifest_before_sha256': hashlib.sha256(review_before).hexdigest(),
        'source_manifest_after_sha256': hashlib.sha256(review_after).hexdigest(),
        'staging_manifest_before_sha256': hashlib.sha256(trial_before).hexdigest(),
        'staging_manifest_after_sha256': hashlib.sha256(trial_after).hexdigest(),
        'backup': str(backup.relative_to(root)),
        'changes': changes,
    }
    workflow.publication.atomic_bytes(stage / 'metadata-corrections.json', workflow.publication.json_bytes(receipt))
    return receipt


def record_inspection(root=workflow.ROOT):
    stage = root / BATCH.stage_rel
    manifest = workflow.publication.read_json(stage / 'manifest.json')
    by_id = {f['imslp_id']: f for f in manifest['files']}
    if set(by_id) != set(IDS):
        raise ValueError('Inspection scope changed')
    for file_id in IDS:
        item = by_id[file_id]
        item.update(rendered_pages=item['page_count'], visual_check='matched_title_key_and_instrumentation', publication_note='',
                    description_summary=f'来源：IMSLP #{file_id}；版本：Peters中音声部版；出版：N. Simrock / Edition Peters')
    workflow.publication.atomic_bytes(stage / 'manifest.json', workflow.publication.json_bytes(manifest))
    inspection = {
        'label': 'Op.71与Op.84：Peters中音声部独立歌曲',
        'checked_on': datetime.now().astimezone().date().isoformat(),
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'proposal_only': True,
        'publication_approved': False,
        'proposed_first_publication_ids': list(IDS),
        'source_notes': '实时IMSLP作品页确认两套作品为德语、Public Domain；七份均列于中音声部组。',
        'method': '保留原PDF字节；pypdf解析全部页面并校验SHA256；Poppler渲染全部页面；人工通览七份完整接触表并放大核对首尾、标题、编号、速度、德语、编制和异常页。',
        'metadata_changes': workflow.publication.read_json(stage / 'metadata-corrections.json')['changes'],
        'files': {file_id: {'pages': by_id[file_id]['page_count'], 'key': '', 'number': by_id[file_id]['movement_number'],
                           'movement_start_pdf_pages': [1], 'titles': [by_id[file_id]['title']],
                           'notes': f'{by_id[file_id]["title"]}；共{by_id[file_id]["page_count"]}页；完整接触表及首尾页检查通过。',
                           'publication_note': ''} for file_id in IDS},
    }
    workflow.publication.atomic_bytes(stage / 'inspection.json', workflow.publication.json_bytes(inspection))
    return inspection


def publish(execute=False):
    return workflow.publication.publish(batch=BATCH) if execute else workflow.publication.prepare(batch=BATCH)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('download', 'correct-metadata', 'record-inspection', 'prepare', 'publish'))
    parser.add_argument('--id', choices=IDS)
    parser.add_argument('--url')
    parser.add_argument('--observed-at')
    args = parser.parse_args()
    if args.command == 'download':
        if not (args.id and args.url and args.observed_at):
            parser.error('download requires --id, --url, and --observed-at')
        result = workflow.download(args.id, args.url, args.observed_at, batch=DOWNLOAD_BATCH)
    elif args.command == 'correct-metadata':
        result = correct_metadata_and_complete_manifest()
    elif args.command == 'record-inspection':
        result = record_inspection()
    else:
        result = publish(args.command == 'publish')
    if args.command == 'prepare':
        result = {'count': len(result['planned']), 'already_published': result['already_published']}
    if result is not None:
        print(json.dumps(result, ensure_ascii=True, indent=2))
