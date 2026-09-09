"""Bounded nine-file batch for Brahms's Op.70 and Op.71 high-voice songs."""
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from tools import brahms_late_piano_batch as workflow
from tools.publish_brahms_op116 import PublicationBatch


IDS = ('42125', '42126', '42127', '42128', '42132', '42133', '42134', '42135', '42136')
BATCH = PublicationBatch(
    ids=IDS,
    batch_id='brahms-op70-op71-high-voice-nine-20260908',
    stage_rel=Path('imports/johannes_brahms/staging/op70-op71-high-voice-singles'),
    work_titles=('4 Gesänge, Op.70', '5 Songs, Op.71'),
    log_message='新增勃拉姆斯Op.70与Op.71高声部Peters独立单曲谱9份；标题、速度、德语及高声部与钢琴编制均已核对。',
    allowed_voice_types=('声乐、钢琴', '高声部', '高声部、钢琴'),
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
        raise ValueError('Op.70/71 source scope changed')
    expected = {file_id: ('声乐、钢琴' if file_id in IDS[:4] else '高声部') for file_id in IDS}
    if any(by_id[file_id]['voice_types'] != expected[file_id] for file_id in IDS):
        raise ValueError('Op.70/71 instrumentation changed concurrently')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = root / 'backup' / 'import_metadata' / f'{BATCH.batch_id}-{stamp}'
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source_path, backup / 'manifest.json')
    stage_manifest_path = root / BATCH.stage_rel / 'manifest.json'
    stage_before = stage_manifest_path.read_bytes()
    stage_manifest = workflow.publication.read_json(stage_manifest_path)
    stage_by_id = {item['imslp_id']: item for item in stage_manifest['files']}
    if set(stage_by_id) != set(BATCH.ids):
        raise ValueError('Staged Op.70/71 scope changed')
    if any(stage_by_id[file_id]['voice_types'] != expected[file_id] for file_id in IDS):
        raise ValueError('Staged Op.70/71 instrumentation changed concurrently')
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
            'before': expected[file_id], 'after': '高声部、钢琴',
            'evidence': 'Live IMSLP sources identify these nine Peters files as editions for high voice and the works as voice and piano.',
        } for file_id in BATCH.ids],
    }
    workflow.publication.atomic_bytes(root / BATCH.stage_rel / 'metadata-corrections.json', workflow.publication.json_bytes(receipt))
    return receipt


def apply_language_corrections(root=workflow.ROOT):
    """Correct source parser language bleed-through before deployment."""
    source_path = root / workflow.publication.REVIEW_REL
    stage_path = root / BATCH.stage_rel / 'manifest.json'
    data_path = root / 'data.json'
    expected = {file_id: ('英语' if file_id in IDS[:4] else '法语') for file_id in IDS}
    source_before = source_path.read_bytes()
    stage_before = stage_path.read_bytes()
    data_before = data_path.read_bytes()
    source = workflow.publication.read_json(source_path)
    stage = workflow.publication.read_json(stage_path)
    data = workflow.publication.read_json(data_path)
    source_by_id = {
        item['imslp_id']: item
        for work in source['works'] if work.get('title') in BATCH.work_titles
        for item in work['files'] if item['imslp_id'] in BATCH.ids
    }
    stage_by_id = {item['imslp_id']: item for item in stage['files']}
    public_by_id = {
        item['source_imslp_id']: item for item in data
        if item.get('import_batch_id') == BATCH.batch_id
    }
    if set(source_by_id) != set(IDS) or set(stage_by_id) != set(IDS) or set(public_by_id) != set(IDS):
        raise ValueError('Op.70/71 language correction scope changed')
    for file_id in IDS:
        if source_by_id[file_id]['language_cn'] != expected[file_id]:
            raise ValueError(f'Op.70/71 source language changed concurrently: {file_id}')
        if stage_by_id[file_id]['language'] != expected[file_id]:
            raise ValueError(f'Op.70/71 staged language changed concurrently: {file_id}')
        if public_by_id[file_id]['language'] != expected[file_id]:
            raise ValueError(f'Op.70/71 catalog language changed concurrently: {file_id}')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = root / 'backup' / 'import_metadata' / f'{BATCH.batch_id}-language-{stamp}'
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source_path, backup / 'manifest.json')
    shutil.copy2(stage_path, backup / 'staging-manifest.json')
    shutil.copy2(data_path, backup / 'data.json')
    for file_id in IDS:
        source_by_id[file_id]['language_cn'] = '德语'
        stage_by_id[file_id]['language'] = '德语'
        public_by_id[file_id]['language'] = '德语'
    source_after = workflow.publication.json_bytes(source)
    stage_after = workflow.publication.json_bytes(stage)
    data_after = workflow.publication.json_bytes(data)
    workflow.publication.atomic_bytes(source_path, source_after)
    workflow.publication.atomic_bytes(stage_path, stage_after)
    workflow.publication.atomic_bytes(data_path, data_after)
    changes = [{
        'imslp_id': file_id, 'field': 'language',
        'before': expected[file_id], 'after': '德语',
        'evidence': 'The live IMSLP work page and every rendered score show German titles and German text; the inherited English/French labels belong to adjacent editions.',
    } for file_id in IDS]
    receipt = {
        'batch_id': BATCH.batch_id,
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'source_manifest_before_sha256': hashlib.sha256(source_before).hexdigest(),
        'source_manifest_after_sha256': hashlib.sha256(source_after).hexdigest(),
        'staging_manifest_before_sha256': hashlib.sha256(stage_before).hexdigest(),
        'staging_manifest_after_sha256': hashlib.sha256(stage_after).hexdigest(),
        'data_before_sha256': hashlib.sha256(data_before).hexdigest(),
        'data_after_sha256': hashlib.sha256(data_after).hexdigest(),
        'backup': str(backup.relative_to(root)),
        'changes': changes,
    }
    workflow.publication.atomic_bytes(root / BATCH.stage_rel / 'language-corrections.json', workflow.publication.json_bytes(receipt))
    return receipt


def record_inspection(root=workflow.ROOT):
    stage = root / BATCH.stage_rel
    manifest_path = stage / 'manifest.json'
    manifest = workflow.publication.read_json(manifest_path)
    by_id = {item['imslp_id']: item for item in manifest['files']}
    if set(by_id) != set(BATCH.ids):
        raise ValueError('Staged Op.70/71 scope changed before inspection record')
    titles = {
        '42125': 'No. 1 Im Garten am Seegestade. Traurig, doch nicht zu langsam, Op. 70',
        '42126': 'No. 2 Lerchengesang. Andante espressivo, Op. 70',
        '42127': 'No. 3 Serenade. Grazioso, Op. 70',
        '42128': 'No. 4 Abendregen. Ruhig, Op. 70',
        '42132': 'No. 1 Es liebt sich so lieblich im Lenze! Anmuthig bewegt, Op. 71',
        '42133': 'No. 2 An den Mond. Nicht zu langsam und mit Anmuth, Op. 71',
        '42134': 'No. 3 Geheimnis. Belebt und heimlich, Op. 71',
        "42135": "No. 4 Willst du, dass ich geh'? Sehr lebhaft, Op. 71",
        '42136': 'No. 5 Minnelied. Sehr innig, doch nicht zu langsam, Op. 71',
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
        'label': 'Op.70与Op.71：高声部单曲',
        'checked_on': datetime.now().astimezone().date().isoformat(),
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'proposal_only': True,
        'publication_approved': False,
        'proposed_first_publication_ids': list(BATCH.ids),
        'source_notes': '实时IMSLP作品页确认Op.70与Op.71共九首、德语、voice/piano、Public Domain，并明确#42125–#42128及#42132–#42136为Peters高声部单曲；Op.70四首及Op.71 Nos.1–4为原调。完整谱、低声部、中音版、外语版和改编不在本批。',
        'method': '保留原PDF字节；pypdf逐页解析、SHA256校验；Poppler渲染全部页面；查看全部页面接触表并重点核对首尾、标题、速度、歌词、编制和完整结束。',
        'rendering_note': '九份单曲页序连续、内容清晰，标题、歌词与末页完整结束均与来源范围相符。',
        'metadata_changes': (
            workflow.publication.read_json(stage / 'metadata-corrections.json')['changes']
            + workflow.publication.read_json(stage / 'language-corrections.json')['changes']
        ),
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
