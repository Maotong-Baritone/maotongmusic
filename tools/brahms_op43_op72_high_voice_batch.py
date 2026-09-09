"""Bounded nine-file batch for Brahms's Op.43 and Op.72 high-voice songs."""
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from tools import brahms_late_piano_batch as workflow
from tools.publish_brahms_op116 import PublicationBatch


IDS = ('9112', '9113', '9114', '9115', '42188', '42189', '42190', '42191', '42192')
BATCH = PublicationBatch(
    ids=IDS,
    batch_id='brahms-op43-op72-high-voice-nine-20260909',
    stage_rel=Path('imports/johannes_brahms/staging/op43-op72-high-voice-singles'),
    work_titles=('4 Songs, Op.43', '5 Songs, Op.72'),
    log_message='新增勃拉姆斯Op.43与Op.72高声部Peters独立单曲谱9份；标题、速度、德语及高声部与钢琴编制均已核对。',
    allowed_voice_types=('高声部', '圆号分谱', '高声部、钢琴'),
    allowed_categories=('艺术歌曲', '器乐分谱'),
)


def source_record(file_id, root=workflow.ROOT):
    return workflow.source_record(file_id, root, batch=BATCH)


def apply_metadata_corrections(root=workflow.ROOT):
    """Correct the bounded parser errors in source and staged manifests."""
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
        raise ValueError('Op.43/72 correction scope changed')
    expected = {
        file_id: {
            'category': ('器乐分谱' if file_id == '9114' else '艺术歌曲'),
            'sub_category': ('艺术歌曲' if file_id == '9114' else ''),
            'voice_types': ('圆号分谱' if file_id == '9114' else '高声部'),
            'language_cn': ('英语' if file_id in IDS[:4] and file_id != '9114' else ('' if file_id == '9114' else '德语')),
        } for file_id in IDS
    }
    for file_id in IDS:
        staged_expected = {
            'category': expected[file_id]['category'],
            'sub_category': expected[file_id]['sub_category'],
            'voice_types': expected[file_id]['voice_types'],
            'language': expected[file_id]['language_cn'],
        }
        if any(source_by_id[file_id][key] != value for key, value in expected[file_id].items()):
            raise ValueError(f'Op.43/72 source metadata changed concurrently: {file_id}')
        if any(stage_by_id[file_id][key] != value for key, value in staged_expected.items()):
            raise ValueError(f'Op.43/72 staged metadata changed concurrently: {file_id}')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = root / 'backup' / 'import_metadata' / f'{BATCH.batch_id}-{stamp}'
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source_path, backup / 'manifest.json')
    shutil.copy2(stage_path, backup / 'staging-manifest.json')
    changes = []
    for file_id in IDS:
        for key, public_key, after in (
            ('voice_types', 'voice_types', '高声部、钢琴'),
            ('language_cn', 'language', '德语'),
        ):
            before = source_by_id[file_id][key]
            source_by_id[file_id][key] = after
            stage_by_id[file_id][public_key] = after
            if before != after:
                changes.append({'imslp_id': file_id, 'field': public_key, 'before': before, 'after': after,
                                'evidence': 'Live IMSLP groups the file under the Peters high-voice edition; the work and rendered score are German voice and piano.'})
    item = source_by_id['9114']
    staged = stage_by_id['9114']
    for key, after in (('category', '艺术歌曲'), ('sub_category', '')):
        before = item[key]
        item[key] = after
        staged[key] = after
        changes.append({'imslp_id': '9114', 'field': key, 'before': before, 'after': after,
                        'evidence': '“Horn” is part of the German song title; live IMSLP and the rendered one-page score confirm a voice-and-piano art song.'})
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
        raise ValueError('Staged Op.43/72 scope changed before inspection record')
    titles = {
        '9112': 'No. 1 Von ewiger Liebe. Mässig — Ziemlich langsam, Op. 43',
        '9113': 'No. 2 Die Mainacht. Sehr langsam und ausdrucksvwoll, Op. 43',
        '9114': 'No. 3 Ich schell mein Horn ins Jammerthal. Durchaus nicht zu langsam und ziemlich frei vorzutragen, Op. 43',
        '9115': 'No. 4 Das Lied vom Herrn von Falkenstein. Allegro, Op. 43',
        '42188': 'No. 1 Alte Liebe. Bewegt, doch nicht zu sehr, Op. 72',
        '42189': 'No. 2 Sommerfäden. Andante con moto, Op. 72',
        '42190': 'No. 3 O Kühler Wald. Langsam, Op. 72',
        '42191': 'No. 4 Verzagen. Bewegt, Op. 72',
        '42192': 'No. 5 Unüberwindlich. Vivace, Op. 72',
    }
    for file_id in titles:
        publisher = ('Edition Peters No. 3202a/3691a，Plate 10190/10277' if file_id in IDS[:4]
                     else 'Edition Peters No. 3201a/3692a，Plate 9312/10280')
        by_id[file_id].update(
            rendered_pages=by_id[file_id]['page_count'],
            visual_check='matched_title_key_and_instrumentation',
            publication_note='',
            description_summary=f'来源：IMSLP #{file_id}；版本：Peters高声部版；出版：{publisher}；编者：Max Friedlaender',
        )
    workflow.publication.atomic_bytes(manifest_path, workflow.publication.json_bytes(manifest))
    inspection = {
        'label': 'Op.43与Op.72：高声部单曲',
        'checked_on': datetime.now().astimezone().date().isoformat(),
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'proposal_only': True,
        'publication_approved': False,
        'proposed_first_publication_ids': list(BATCH.ids),
        'source_notes': '实时IMSLP作品页确认Op.43四首与Op.72五首均为德语、voice/piano、Public Domain；本批九份Peters文件均列在高声部组。#9114标题中的Horn被解析器误判为圆号分谱，来源分组与谱面均确认其为声乐与钢琴艺术歌曲。',
        'method': '保留原PDF字节；pypdf自动解析全部页面并校验SHA256；Poppler渲染全部页面；人工通览九份完整接触表并放大核对首尾、标题、速度、歌词、编制和异常页。',
        'rendering_note': '九份单曲共35页，页序连续、标题和歌词可辨、末页完整结束；Op.43扫描分辨率偏低但实际阅读清楚。',
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
