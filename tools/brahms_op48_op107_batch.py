"""Bounded twelve-file batch for Brahms's Op.48 and Op.107 songs."""
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from tools import brahms_late_piano_batch as workflow
from tools.publish_brahms_op116 import PublicationBatch


IDS = ('9105', '9106', '9107', '9108', '9109', '9110', '9111',
       '246589', '246590', '246591', '246592', '246593')
BATCH = PublicationBatch(
    ids=IDS,
    batch_id='brahms-op48-op107-twelve-20260909',
    stage_rel=Path('imports/johannes_brahms/staging/op48-op107-singles'),
    work_titles=('7 Lieder, Op.48', '5 Lieder, Op.107'),
    log_message='新增勃拉姆斯Op.48高声部与Op.107声乐钢琴Peters独立单曲谱12份；标题、速度、德语及编制均已核对。',
    allowed_voice_types=('高声部', '声乐、钢琴', '高声部、钢琴'),
    allowed_categories=('艺术歌曲',),
)


def source_record(file_id, root=workflow.ROOT):
    return workflow.source_record(file_id, root, batch=BATCH)


def apply_metadata_corrections(root=workflow.ROOT):
    """Correct only the seven bounded Op.48 parser errors."""
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
        raise ValueError('Op.48/107 correction scope changed')
    op48_ids = IDS[:7]
    for file_id in IDS:
        expected_voice = '高声部' if file_id in op48_ids else '声乐、钢琴'
        expected_language = '法语' if file_id in op48_ids else '德语'
        source_item = source_by_id[file_id]
        stage_item = stage_by_id[file_id]
        if (source_item['category'] != '艺术歌曲' or source_item['sub_category'] != ''
                or source_item['voice_types'] != expected_voice
                or source_item['language_cn'] != expected_language):
            raise ValueError(f'Op.48/107 source metadata changed concurrently: {file_id}')
        if (stage_item['category'] != '艺术歌曲' or stage_item['sub_category'] != ''
                or stage_item['voice_types'] != expected_voice
                or stage_item['language'] != expected_language):
            raise ValueError(f'Op.48/107 staged metadata changed concurrently: {file_id}')
    typo_title = 'No. 2 Salamander. Mit Launeor, Op. 107'
    if (source_by_id['246590']['proposed_title'] != typo_title
            or stage_by_id['246590']['title'] != typo_title):
        raise ValueError('Op.107 No.2 title changed concurrently')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = root / 'backup' / 'import_metadata' / f'{BATCH.batch_id}-{stamp}'
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source_path, backup / 'manifest.json')
    shutil.copy2(stage_path, backup / 'staging-manifest.json')
    changes = []
    for file_id in op48_ids:
        for source_key, stage_key, after in (
            ('voice_types', 'voice_types', '高声部、钢琴'),
            ('language_cn', 'language', '德语'),
        ):
            before = source_by_id[file_id][source_key]
            source_by_id[file_id][source_key] = after
            stage_by_id[file_id][stage_key] = after
            changes.append({
                'imslp_id': file_id, 'field': stage_key,
                'before': before, 'after': after,
                'evidence': 'Live IMSLP lists the file in the Peters high-voice group; the rendered score has German text and voice with piano.',
            })
    corrected_title = 'No. 2 Salamander. Mit Laune, Op. 107'
    source_by_id['246590']['proposed_title'] = corrected_title
    stage_by_id['246590']['title'] = corrected_title
    changes.append({
        'imslp_id': '246590', 'field': 'proposed_title',
        'before': typo_title, 'after': corrected_title,
        'evidence': 'The first rendered score page prints “Salamander.” and the tempo “Mit Laune.”; the trailing “or” is a source-page parsing artifact.',
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
        raise ValueError('Staged Op.48/107 scope changed before inspection record')
    titles = {
        '9105': 'No. 1 Der Gang zum Liebchen. Con grazia, Op. 48',
        '9106': 'No. 2 Der Überläufer. Andante con moto, Op. 48',
        '9107': 'No. 3 Liebesklage des Mädchens. Etwas langsam, Op. 48',
        '9108': 'No. 4 Gold überweigt die Liebe. Poco andante, Op. 48',
        '9109': 'No. 5 Trost in Thränen. Andante, Op. 48',
        '9110': 'No. 6 Vergangen ist mir Glück und Heil. Andante, Op. 48',
        '9111': 'No. 7 Herbstgefühl. Ziemlich langsam, Op. 48',
        '246589': 'No. 1 An die Stolze. Sehr lebhaft und ausdrucksvoll, Op. 107',
        '246590': 'No. 2 Salamander. Mit Laune, Op. 107',
        '246591': 'No. 3 Das Mädchen spricht. Lebhaft und Anmuthig, Op. 107',
        '246592': 'No. 4 Maienkätzchen. Grazioso, Op. 107',
        '246593': 'No. 5 Mädchenlied. Leise bewegt, Op. 107',
    }
    for file_id, title in titles.items():
        is_op48 = file_id in IDS[:7]
        publisher = ('Edition Peters No. 3201a/3961a，Plate 9312/10277'
                     if is_op48 else 'Edition Peters No. 3201a/3692a，Plate 9312/10280')
        version = 'Peters高声部版' if is_op48 else 'Peters声乐钢琴版'
        by_id[file_id].update(
            title=title,
            rendered_pages=by_id[file_id]['page_count'],
            visual_check='matched_title_key_and_instrumentation',
            publication_note='',
            description_summary=f'来源：IMSLP #{file_id}；版本：{version}；出版：{publisher}；编者：Max Friedlaender',
        )
    workflow.publication.atomic_bytes(manifest_path, workflow.publication.json_bytes(manifest))
    inspection = {
        'label': 'Op.48与Op.107：Peters独立单曲',
        'checked_on': datetime.now().astimezone().date().isoformat(),
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'proposal_only': True,
        'publication_approved': False,
        'proposed_first_publication_ids': list(BATCH.ids),
        'source_notes': '实时IMSLP作品页确认两套作品均为德语、voice/piano、Public Domain；Op.48七份列在Peters高声部组，Op.107五份为Peters声乐钢琴独立单曲。完整谱、其他声区及改编不在本批。',
        'method': '保留原PDF字节；pypdf自动解析全部页面并校验SHA256；Poppler渲染全部页面；人工通览十二份完整接触表并放大核对首尾、标题、速度、歌词、编制和异常页。',
        'rendering_note': '十二份单曲共24页，页序连续、标题和歌词可辨、末页完整结束；Op.48低分辨率扫描仍可清楚阅读。#246590谱面速度标记为Mit Laune，已纠正来源解析多出的or。',
        'metadata_changes': workflow.publication.read_json(stage / 'metadata-corrections.json')['changes'],
        'files': {
            file_id: {
                'pages': by_id[file_id]['page_count'], 'key': '',
                'number': by_id[file_id]['movement_number'],
                'movement_start_pdf_pages': [1], 'titles': [title],
                'notes': f'{title}；{("高声部" if file_id in IDS[:7] else "声乐钢琴")}Peters版，共{by_id[file_id]["page_count"]}页；首尾及完整接触表检查通过。',
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
