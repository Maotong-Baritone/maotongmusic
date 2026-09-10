"""Bounded ten-file batch for Brahms's Op.86 and Op.96 high-voice songs."""
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from tools import brahms_late_piano_batch as workflow
from tools.publish_brahms_op116 import PublicationBatch


IDS = ('46903', '46904', '46905', '46906', '46907', '46908',
       '246580', '246581', '246582', '246583')
BATCH = PublicationBatch(
    ids=IDS,
    batch_id='brahms-op86-op96-high-voice-ten-20260909',
    stage_rel=Path('imports/johannes_brahms/staging/op86-op96-high-voice-singles'),
    work_titles=('6 Lieder, Op.86', '4 Lieder, Op.96'),
    log_message='新增勃拉姆斯Op.86与Op.96高声部Peters独立单曲谱10份；标题、速度、德语及高声部与钢琴编制均已核对。',
    allowed_voice_types=('高声部', '声乐、钢琴', '高声部、钢琴'),
    allowed_categories=('艺术歌曲',),
)


def source_record(file_id, root=workflow.ROOT):
    return workflow.source_record(file_id, root, batch=BATCH)


def apply_metadata_corrections(root=workflow.ROOT):
    """Correct language and instrumentation only for the ten bounded files."""
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
        raise ValueError('Op.86/96 correction scope changed')
    op86_ids = set(IDS[:6])
    for file_id in IDS:
        expected_voice = '高声部' if file_id in op86_ids else '声乐、钢琴'
        source_item = source_by_id[file_id]
        stage_item = stage_by_id[file_id]
        if (source_item['category'] != '艺术歌曲' or source_item['sub_category'] != ''
                or source_item['voice_types'] != expected_voice
                or source_item['language_cn'] != '英语'):
            raise ValueError(f'Op.86/96 source metadata changed concurrently: {file_id}')
        if (stage_item['category'] != '艺术歌曲' or stage_item['sub_category'] != ''
                or stage_item['voice_types'] != expected_voice
                or stage_item['language'] != '英语'):
            raise ValueError(f'Op.86/96 staged metadata changed concurrently: {file_id}')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = root / 'backup' / 'import_metadata' / f'{BATCH.batch_id}-{stamp}'
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source_path, backup / 'manifest.json')
    shutil.copy2(stage_path, backup / 'staging-manifest.json')
    changes = []
    for file_id in IDS:
        for source_key, stage_key, after in (
            ('voice_types', 'voice_types', '高声部、钢琴'),
            ('language_cn', 'language', '德语'),
        ):
            before = source_by_id[file_id][source_key]
            source_by_id[file_id][source_key] = after
            stage_by_id[file_id][stage_key] = after
            changes.append({
                'imslp_id': file_id,
                'field': stage_key,
                'before': before,
                'after': after,
                'evidence': 'Live IMSLP identifies this Peters file as a high-voice edition; the rendered score has German text for voice and piano.',
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
        raise ValueError('Staged Op.86/96 scope changed before inspection record')
    titles = {
        '46903': 'No. 1 Therese. Etwas bewegt, Op. 86',
        '46904': 'No. 2 Feldeinsamkeit. Langsam, Op. 86',
        '46905': 'No. 3 Nachtwandler. Langsam, Op. 86',
        '46906': 'No. 4 Über die Heide. Ziemlich langsam, gehend, Op. 86',
        '46907': 'No. 5 Versunken. Sehr leidenschaftlich, doch nicht zu rasch, Op. 86',
        '46908': 'No. 6 Todessehnen. Langsam, Op. 86',
        '246580': 'No. 1 Der Tod, das ist die kühle Nacht. Sehr langsam, Op. 96',
        '246581': 'No. 2 Wir wandelten, wir zwei zusammen. Andante espressivo, Op. 96',
        '246582': 'No. 3 Es schauen die Blumen. Unruhig bewegt, Op. 96',
        '246583': 'No. 4 Meerfahrt. Andante sostenuto, Op. 96',
    }
    for file_id, title in titles.items():
        by_id[file_id].update(
            title=title,
            rendered_pages=by_id[file_id]['page_count'],
            visual_check='matched_title_key_and_instrumentation',
            publication_note='',
            description_summary=f'来源：IMSLP #{file_id}；版本：Peters高声部版；出版：Edition Peters No. 3201a/3692a，Plate 9312/10280；编者：Max Friedlaender',
        )
    workflow.publication.atomic_bytes(manifest_path, workflow.publication.json_bytes(manifest))
    inspection = {
        'label': 'Op.86与Op.96：Peters高声部独立单曲',
        'checked_on': datetime.now().astimezone().date().isoformat(),
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'proposal_only': True,
        'publication_approved': False,
        'proposed_first_publication_ids': list(BATCH.ids),
        'source_notes': '实时IMSLP作品页确认两套作品均为德语、voice/piano、Public Domain；十份均为Max Friedlaender编辑的Peters高声部独立单曲。完整谱、其他声区及改编不在本批。',
        'method': '保留原PDF字节；pypdf自动解析全部页面并校验SHA256；Poppler渲染全部页面；人工通览十份完整接触表并放大核对首尾、标题、速度、歌词、编制和异常页。',
        'rendering_note': '十份单曲共26页，页序连续、标题和歌词可辨、末页完整结束。',
        'metadata_changes': workflow.publication.read_json(stage / 'metadata-corrections.json')['changes'],
        'files': {
            file_id: {
                'pages': by_id[file_id]['page_count'],
                'key': '',
                'number': by_id[file_id]['movement_number'],
                'movement_start_pdf_pages': [1],
                'titles': [title],
                'notes': f'{title}；Peters高声部版，共{by_id[file_id]["page_count"]}页；首尾及完整接触表检查通过。',
                'publication_note': '',
            } for file_id, title in titles.items()
        },
    }
    workflow.publication.atomic_bytes(stage / 'inspection.json', workflow.publication.json_bytes(inspection))
    return inspection


def download(file_id, url, observed_at, *, access_method='wait_page'):
    workflow.download(file_id, url, observed_at, batch=BATCH, access_method=access_method)


def publish(*, execute=False):
    if execute:
        return workflow.publication.publish(batch=BATCH)
    return workflow.publication.prepare(batch=BATCH)
