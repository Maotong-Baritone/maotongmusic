"""Bounded eleven-file batch for Brahms's Op.85 and Op.106 high-voice songs."""
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from tools import brahms_late_piano_batch as workflow
from tools.publish_brahms_op116 import PublicationBatch


IDS = ('44084', '44085', '44086', '44087', '44088', '44089',
       '66266', '66267', '66268', '66269', '66270')
BATCH = PublicationBatch(
    ids=IDS,
    batch_id='brahms-op85-op106-high-voice-eleven-20260908',
    stage_rel=Path('imports/johannes_brahms/staging/op85-op106-high-voice-singles'),
    work_titles=('6 Lieder, Op.85', '5 Lieder, Op.106'),
    log_message='新增勃拉姆斯Op.85与Op.106高声部Peters独立单曲谱11份；标题、速度、德语及高声部与钢琴编制均已核对。',
    allowed_voice_types=('声乐、钢琴', '高声部、钢琴'),
    allowed_categories=('艺术歌曲',),
)


def source_record(file_id, root=workflow.ROOT):
    return workflow.source_record(file_id, root, batch=BATCH)


def apply_metadata_corrections(root=workflow.ROOT):
    source_path = root / workflow.publication.REVIEW_REL
    before = source_path.read_bytes()
    manifest = workflow.publication.read_json(source_path)
    by_id = {
        item['imslp_id']: item
        for work in manifest['works'] if work.get('title') in BATCH.work_titles
        for item in work['files'] if item['imslp_id'] in BATCH.ids
    }
    if set(by_id) != set(BATCH.ids):
        raise ValueError('Op.85/106 source scope changed')
    if any(item['voice_types'] != '声乐、钢琴' for item in by_id.values()):
        raise ValueError('Op.85/106 instrumentation changed concurrently')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = root / 'backup' / 'import_metadata' / f'{BATCH.batch_id}-{stamp}'
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source_path, backup / 'manifest.json')
    stage_manifest_path = root / BATCH.stage_rel / 'manifest.json'
    stage_before = stage_manifest_path.read_bytes()
    stage_manifest = workflow.publication.read_json(stage_manifest_path)
    stage_by_id = {item['imslp_id']: item for item in stage_manifest['files']}
    if set(stage_by_id) != set(BATCH.ids):
        raise ValueError('Staged Op.85/106 scope changed')
    if any(item['voice_types'] != '声乐、钢琴' for item in stage_by_id.values()):
        raise ValueError('Staged Op.85/106 instrumentation changed concurrently')
    shutil.copy2(stage_manifest_path, backup / 'staging-manifest.json')
    for item in by_id.values():
        item['voice_types'] = '高声部、钢琴'
    for item in stage_by_id.values():
        item['voice_types'] = '高声部、钢琴'
    after = workflow.publication.json_bytes(manifest)
    stage_after = workflow.publication.json_bytes(stage_manifest)
    workflow.publication.atomic_bytes(source_path, after)
    workflow.publication.atomic_bytes(stage_manifest_path, stage_after)
    receipt = {
        'batch_id': BATCH.batch_id,
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'source_manifest_before_sha256': hashlib.sha256(before).hexdigest(),
        'source_manifest_after_sha256': hashlib.sha256(after).hexdigest(),
        'staging_manifest_before_sha256': hashlib.sha256(stage_before).hexdigest(),
        'staging_manifest_after_sha256': hashlib.sha256(stage_after).hexdigest(),
        'backup': str(backup.relative_to(root)),
        'changes': [{
            'imslp_id': file_id, 'field': 'voice_types',
            'before': '声乐、钢琴', 'after': '高声部、钢琴',
            'evidence': 'Live IMSLP sources group these Peters files as editions for high voice and identify both works as voice and piano.',
        } for file_id in BATCH.ids],
    }
    workflow.publication.atomic_bytes(root / BATCH.stage_rel / 'metadata-corrections.json', workflow.publication.json_bytes(receipt))
    return receipt


def record_inspection(root=workflow.ROOT):
    stage = root / BATCH.stage_rel
    manifest_path = stage / 'manifest.json'
    manifest = workflow.publication.read_json(manifest_path)
    by_id = {item['imslp_id']: item for item in manifest['files']}
    if set(by_id) != set(BATCH.ids):
        raise ValueError('Staged Op.85/106 scope changed before inspection record')
    titles = {
        '44084': 'No. 1 Sommerabend. Langsam, Op. 85',
        '44085': 'No. 2 Mondenschein. Langsam, Op. 85',
        '44086': 'No. 3 Mädchenlied. Gehend, Op. 85',
        '44087': 'No. 4 Ade! Bewegt, Op. 85',
        '44088': 'No. 5 Frühlingslied. Lebhaft, Op. 85',
        '44089': 'No. 6 In Waldeinsamkeit. Langsam, Op. 85',
        '66266': 'No. 1 Ständchen. Allegretto grazioso, Op. 106',
        '66267': 'No. 2 Auf dem See. Anmuthig bewegt und ausdrucksvoll, Op. 106',
        '66268': 'No. 3 Es hing der Reif im Lindenbaum. Träumerisch, Op. 106',
        '66269': 'No. 4 Meine Lieder. Bewegt und leise, Op. 106',
        '66270': 'No. 5 Ein Wanderer. In langsam gehender Bewegung, Op. 106',
    }
    for file_id in titles:
        by_id[file_id].update(
            rendered_pages=by_id[file_id]['page_count'],
            visual_check='matched_title_key_and_instrumentation',
            publication_note='',
            description_summary=f'来源：IMSLP #{file_id}；版本：Peters高声部版；出版：Edition Peters No. 3201a/3692a，Plate 9312/10280；编者：Max Friedlaender',
        )
    workflow.publication.atomic_bytes(manifest_path, workflow.publication.json_bytes(manifest))
    inspection = {
        'label': 'Op.85与Op.106：高声部单曲',
        'checked_on': datetime.now().astimezone().date().isoformat(),
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'proposal_only': True,
        'publication_approved': False,
        'proposed_first_publication_ids': list(BATCH.ids),
        'source_notes': '实时IMSLP作品页确认Op.85六首与Op.106五首均为德语、voice/piano、Public Domain，并明确本批十一份Peters文件为高声部独立单曲。完整谱、低声部、中音版、手稿和改编不在本批。',
        'method': '保留原PDF字节；pypdf自动解析每页并校验SHA256；Poppler渲染全部页面；人工通览完整接触表，并放大核对首尾、标题、速度、歌词、编制及异常页。',
        'rendering_note': '十一份单曲页序连续、内容清晰，标题、歌词与末页完整结束均与来源范围相符。',
        'metadata_changes': workflow.publication.read_json(stage / 'metadata-corrections.json')['changes'],
        'files': {
            file_id: {
                'pages': by_id[file_id]['page_count'], 'key': '',
                'number': by_id[file_id]['movement_number'],
                'movement_start_pdf_pages': [1], 'titles': [title],
                'notes': f'{title}；高声部Peters版，共{by_id[file_id]["page_count"]}页；首尾及完整接触表检查通过。',
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
