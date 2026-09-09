"""Bounded nine-file batch for Brahms's 9 Lieder and Songs, Op.63."""
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from tools import brahms_late_piano_batch as workflow
from tools.publish_brahms_op116 import PublicationBatch



IDS = ('41714', '41715', '41716', '41717', '41718', '41719', '41720', '41721', '41722')
BATCH = PublicationBatch(
    ids=IDS,
    batch_id='brahms-op63-high-voice-nine-20260908',
    stage_rel=Path('imports/johannes_brahms/staging/op63-high-voice-singles'),
    work_titles=('9 Lieder and Songs, Op.63',),
    log_message='新增勃拉姆斯《9 Lieder and Songs, Op. 63》高声部Peters独立单曲谱9份；标题、速度、德语及高声部与钢琴编制均已核对。',
    allowed_voice_types=('声乐、钢琴', '高声部、钢琴'),
    allowed_categories=('艺术歌曲',),
)


def source_record(file_id, root=workflow.ROOT):
    return workflow.source_record(file_id, root, batch=BATCH)


def apply_metadata_corrections(root=workflow.ROOT):
    title_changes = {
        '41718': ('No. 5 Junge Liebe I. Lebhaft, Op. 63', 'No. 5 Meine Liebe ist grün. Lebhaft, Op. 63'),
        '41719': ('No. 6 Junge Liebe II. Zart bewegt, Op. 63', 'No. 6 Wenn um den Holunder. Zart bewegt, Op. 63'),
        '41720': ('No. 7 Heimweh I. Zart bewegt, Op. 63', 'No. 7 Heimweh. Zart bewegt, Op. 63'),
        '41721': ('No. 8 Heimweh II. Etwas langsam, Op. 63', "No. 8 O wüsst' ich doch den Weg zurück. Etwas langsam, Op. 63"),
        '41722': ('No. 9 Heimweh III. Etwas langsam, Op. 63', 'No. 9 Ich sah als Knabe Blumen blühn. Etwas langsam, Op. 63'),
    }
    source_path = root / workflow.publication.REVIEW_REL
    before = source_path.read_bytes()
    manifest = workflow.publication.read_json(source_path)
    by_id = {
        item['imslp_id']: item
        for work in manifest['works'] if work.get('title') in BATCH.work_titles
        for item in work['files'] if item['imslp_id'] in BATCH.ids
    }
    if set(by_id) != set(BATCH.ids):
        raise ValueError('Op.63 source scope changed')
    if any(item['voice_types'] != '声乐、钢琴' for item in by_id.values()):
        raise ValueError('Op.63 instrumentation changed concurrently')
    if any(by_id[file_id]['proposed_title'] != values[0] for file_id, values in title_changes.items()):
        raise ValueError('Op.63 source titles changed concurrently')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = root / 'backup' / 'import_metadata' / f'{BATCH.batch_id}-{stamp}'
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source_path, backup / 'manifest.json')
    stage_manifest_path = root / BATCH.stage_rel / 'manifest.json'
    stage_before = stage_manifest_path.read_bytes()
    stage_manifest = workflow.publication.read_json(stage_manifest_path)
    stage_by_id = {item['imslp_id']: item for item in stage_manifest['files']}
    if set(stage_by_id) != set(BATCH.ids):
        raise ValueError('Staged Op.63 scope changed')
    if any(item['voice_types'] != '声乐、钢琴' for item in stage_by_id.values()):
        raise ValueError('Staged Op.63 instrumentation changed concurrently')
    if any(stage_by_id[file_id]['title'] != values[0] for file_id, values in title_changes.items()):
        raise ValueError('Staged Op.63 titles changed concurrently')
    shutil.copy2(stage_manifest_path, backup / 'staging-manifest.json')
    for item in by_id.values():
        item['voice_types'] = '高声部、钢琴'
    for item in stage_by_id.values():
        item['voice_types'] = '高声部、钢琴'
    for file_id, (_, corrected) in title_changes.items():
        by_id[file_id]['proposed_title'] = corrected
        by_id[file_id]['review_edited'] = True
        stage_by_id[file_id]['title'] = corrected
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
            'evidence': 'Live IMSLP source identifies these nine Peters files as the edition for high voice in original keys and the work instrumentation as voice and piano.',
        } for file_id in BATCH.ids] + [{
            'imslp_id': file_id, 'field': 'proposed_title',
            'before': before_title, 'after': corrected,
            'evidence': 'The first rendered score page prints this independent title; the live IMSLP page notes that Brahms supplied the titles for Nos. 5–9.',
        } for file_id, (before_title, corrected) in title_changes.items()],
    }
    workflow.publication.atomic_bytes(root / BATCH.stage_rel / 'metadata-corrections.json', workflow.publication.json_bytes(receipt))
    return receipt


def record_inspection(root=workflow.ROOT):
    stage = root / BATCH.stage_rel
    manifest_path = stage / 'manifest.json'
    manifest = workflow.publication.read_json(manifest_path)
    by_id = {item['imslp_id']: item for item in manifest['files']}
    if set(by_id) != set(BATCH.ids):
        raise ValueError('Staged Op.63 scope changed before inspection record')
    titles = {
        '41714': 'No. 1 Frühlingstrost. Lebhaft',
        '41715': 'No. 2 Erinnerung. Innig',
        '41716': 'No. 3 An ein Bild. Etwas langsam',
        '41717': 'No. 4 An die Tauben. Sehr lebhaft',
        '41718': 'No. 5 Meine Liebe ist grün. Lebhaft',
        '41719': 'No. 6 Wenn um den Holunder. Zart bewegt',
        '41720': 'No. 7 Heimweh. Zart bewegt',
        '41721': "No. 8 O wüsst' ich doch den Weg zurück. Etwas langsam",
        '41722': 'No. 9 Ich sah als Knabe Blumen blühn. Etwas langsam',
    }
    for file_id in titles:
        by_id[file_id].update(
            rendered_pages=by_id[file_id]['page_count'],
            visual_check='matched_title_key_and_instrumentation',
            publication_note='',
            description_summary=f'来源：IMSLP #{file_id}；版本：Peters高声部原调版；出版：Edition Peters No. 3201a/3202a/3691a，Plate 9312/10190/10277；编者：Max Friedlaender',
        )
    workflow.publication.atomic_bytes(manifest_path, workflow.publication.json_bytes(manifest))
    inspection = {
        'label': '9 Lieder and Songs, Op.63：高声部单曲',
        'checked_on': datetime.now().astimezone().date().isoformat(),
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'proposal_only': True,
        'publication_approved': False,
        'proposed_first_publication_ids': list(BATCH.ids),
        'source_notes': '实时IMSLP作品页确认Op.63、九首目录、德语、voice/piano、Public Domain，并明确#41714–#41722为Peters高声部原调单曲；完整谱、低声部扫描、手稿、现代排版及中音版不在本批。',
        'method': '保留原PDF字节；pypdf逐页解析、SHA256校验；Poppler渲染全部页面；查看全部页面接触表并重点核对首尾、标题、速度、歌词、编制和完整结束。',
        'rendering_note': '九份单曲页序连续、内容清晰，标题、歌词与末页完整结束均与来源范围相符。',
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


