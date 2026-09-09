"""Bounded nine-file batch for Brahms's 8 Lieder and Romances, Op.14.

The batch contains the public-domain first-edition complete score and the
eight distinct low-voice Peters single-song files. Download URLs must be
observed after the normal anonymous IMSLP wait.
"""
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from tools import brahms_late_piano_batch as workflow
from tools.publish_brahms_op116 import PublicationBatch


IDS = ('22850', '53063', '47025', '47026', '53064', '47027', '47028', '53065', '47029')
BATCH = PublicationBatch(
    ids=IDS,
    batch_id='brahms-op14-complete-and-low-voice-nine-20260906',
    stage_rel=Path('imports/johannes_brahms/staging/op14-complete-and-singles'),
    work_titles=('8 Lieder and Romances, Op.14',),
    log_message='新增勃拉姆斯《8 Lieder and Romances, Op. 14》乐谱 9 份：首版完整谱 1 份及低声部独立单曲谱 8 份；均保留原始 PDF，并核对德语歌词、声乐与钢琴编制及各文件实际范围。',
    allowed_voice_types=('声乐、钢琴', '低声部、钢琴'),
    allowed_categories=('艺术歌曲',),
)


def source_record(file_id, root=workflow.ROOT):
    return workflow.source_record(file_id, root, batch=BATCH)


def apply_metadata_corrections(root=workflow.ROOT):
    """Apply only the page-verified Op.14 classification/instrument labels."""
    source_path = root / workflow.publication.REVIEW_REL
    before = source_path.read_bytes()
    manifest = workflow.publication.read_json(source_path)
    by_id = {
        item['imslp_id']: item
        for work in manifest['works']
        if work.get('title') in BATCH.work_titles
        for item in work['files']
        if item['imslp_id'] in BATCH.ids
    }
    if set(by_id) != set(BATCH.ids):
        raise ValueError('Op.14 source scope changed')
    complete = by_id['22850']
    if (complete['category'], complete['sub_category'], complete['voice_types']) != (
        '声乐套曲', '艺术歌曲', '声乐、钢琴'
    ):
        raise ValueError('Complete-score metadata changed concurrently')
    singles = [by_id[file_id] for file_id in BATCH.ids[1:]]
    if any(item['voice_types'] != '声乐、钢琴' for item in singles):
        raise ValueError('Single-song instrumentation changed concurrently')

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = root / 'backup' / 'import_metadata' / f'{BATCH.batch_id}-{stamp}'
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source_path, backup / 'manifest.json')
    stage_manifest_path = root / BATCH.stage_rel / 'manifest.json'
    stage_before = stage_manifest_path.read_bytes()
    stage_manifest = workflow.publication.read_json(stage_manifest_path)
    stage_by_id = {item['imslp_id']: item for item in stage_manifest['files']}
    if set(stage_by_id) != set(BATCH.ids):
        raise ValueError('Staged Op.14 scope changed')
    if (stage_by_id['22850']['category'], stage_by_id['22850']['sub_category']) != (
        '声乐套曲', '艺术歌曲'
    ) or any(stage_by_id[file_id]['voice_types'] != '声乐、钢琴' for file_id in BATCH.ids[1:]):
        raise ValueError('Staged metadata changed concurrently')
    shutil.copy2(stage_manifest_path, backup / 'staging-manifest.json')
    complete['category'] = '艺术歌曲'
    complete['sub_category'] = ''
    for item in singles:
        item['voice_types'] = '低声部、钢琴'
    stage_by_id['22850']['category'] = '艺术歌曲'
    stage_by_id['22850']['sub_category'] = ''
    for file_id in BATCH.ids[1:]:
        stage_by_id[file_id]['voice_types'] = '低声部、钢琴'
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
        'changes': [
            {'imslp_id': '22850', 'field': 'category/sub_category',
             'before': ['声乐套曲', '艺术歌曲'], 'after': ['艺术歌曲', ''],
             'evidence': 'Complete set is eight independent art songs; matches the established site treatment of complete Brahms song collections.'},
            *[
                {'imslp_id': file_id, 'field': 'voice_types',
                 'before': '声乐、钢琴', 'after': '低声部、钢琴',
                 'evidence': 'Live IMSLP source groups all eight files under Low voice; the Peters edition and filenames identify tiefe Stimme.'}
                for file_id in BATCH.ids[1:]
            ],
        ],
    }
    target = root / BATCH.stage_rel / 'metadata-corrections.json'
    workflow.publication.atomic_bytes(target, workflow.publication.json_bytes(receipt))
    return receipt


def record_inspection(root=workflow.ROOT):
    stage = root / BATCH.stage_rel
    manifest_path = stage / 'manifest.json'
    manifest = workflow.publication.read_json(manifest_path)
    by_id = {item['imslp_id']: item for item in manifest['files']}
    if set(by_id) != set(BATCH.ids):
        raise ValueError('Staged Op.14 scope changed before inspection record')
    titles = {
        '53063': 'No. 1 Vor dem Fenster. Andante',
        '47025': 'No. 2 Vom verwundeten Knaben. Andantino',
        '47026': 'No. 3 Murrays Ermordung. Con moto',
        '53064': 'No. 4 Ein Sonett. Langsam, sehr innig',
        '47027': 'No. 5 Trennung. Sehr schnell',
        '47028': 'No. 6 Gang zur Liebsten. Andante con espressione',
        '53065': 'No. 7 Ständchen. Allegretto',
        '47029': 'No. 8 Sehnsucht. Andante',
    }
    starts = [4, 9, 11, 14, 17, 20, 21, 25]
    complete_note = (
        '首版完整谱共28页：PDF第1页封面、第2页封二、第3页标题页；八首分别从PDF第4、9、11、14、17、20、21、25页开始，'
        '第26页音乐完整结束；第27页封底、第28页出版目录均按原文件保留。谱面为德语独唱与钢琴，八首跨多调，全集调性留空。'
    )
    by_id['22850'].update(
        rendered_pages=28,
        visual_check='checked_with_notes',
        publication_note=complete_note + '来源为1860/61年Rieter-Biedermann首版扫描，原PDF字节未改。',
    )
    for file_id, title in titles.items():
        item = by_id[file_id]
        item.update(
            rendered_pages=item['page_count'],
            visual_check='checked_with_notes',
            publication_note=(
                f'低声部Peters版《{title}》，PDF共{item["page_count"]}页，逐页为连续完整乐谱且末页完整结束；'
                '谱面标题、速度、德语歌词及独唱与钢琴编制均与来源相符，原PDF字节未改。'
            ),
        )
    workflow.publication.atomic_bytes(manifest_path, workflow.publication.json_bytes(manifest))
    inspection = {
        'label': '8 Lieder and Romances, Op.14：完整谱及低声部单曲',
        'checked_on': datetime.now().astimezone().date().isoformat(),
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'proposal_only': True,
        'publication_approved': False,
        'proposed_first_publication_ids': list(BATCH.ids),
        'source_notes': (
            '实时IMSLP作品页确认Op.14、八首目录、德语、原作编制voice/piano及Public Domain。'
            '本批选择#22850首版完整谱，并收录低声部栏目下八份互不重复的Peters独立单曲#53063/#47025/#47026/#53064/'
            '#47027/#47028/#53065/#47029；滤色全集#97694及高声选集#82790不在本批。所有下载均来自正常匿名等待后可见链接或正常PDF跳转。'
        ),
        'method': (
            '保留原PDF字节；pypdf逐页解析、SHA256校验；Poppler以80dpi渲染全部49页；'
            '查看九份全页接触表，并复核完整谱标题页、八首起始页、音乐末页和出版目录。'
        ),
        'rendering_note': complete_note + '八份低声部单曲共21页，各文件逐页连续、标题与速度一致且末页完整结束，无缺页。',
        'metadata_changes': workflow.publication.read_json(stage / 'metadata-corrections.json')['changes'],
        'files': {
            '22850': {
                'pages': 28, 'key': '', 'number': None,
                'movement_start_pdf_pages': starts,
                'titles': list(titles.values()),
                'notes': complete_note,
                'publication_note': by_id['22850']['publication_note'],
            },
            **{
                file_id: {
                    'pages': by_id[file_id]['page_count'], 'key': '',
                    'number': by_id[file_id]['movement_number'],
                    'movement_start_pdf_pages': [1], 'titles': [title],
                    'notes': by_id[file_id]['publication_note'],
                    'publication_note': by_id[file_id]['publication_note'],
                }
                for file_id, title in titles.items()
            },
        },
    }
    workflow.publication.atomic_bytes(stage / 'inspection.json', workflow.publication.json_bytes(inspection))
    return inspection


def download(file_id, url, observed_at, *, access_method='wait_page'):
    workflow.download(
        file_id,
        url,
        observed_at,
        batch=BATCH,
        access_method=access_method,
    )
    if file_id != '22850':
        return
    stage = workflow.ROOT / BATCH.stage_rel
    manifest_path = stage / 'manifest.json'
    manifest = workflow.publication.read_json(manifest_path)
    record = next(item for item in manifest['files'] if item['imslp_id'] == file_id)
    current = stage / record['local_path']
    target = stage / 'pdfs' / '8 Lieder and Romances, Op. 14 - First-edition - IMSLP22850.pdf'
    if current != target:
        if target.exists():
            raise ValueError('Corrected first-edition staging filename already exists')
        current.replace(target)
        record['local_path'] = target.relative_to(stage).as_posix()
        workflow.publication.atomic_bytes(manifest_path, workflow.publication.json_bytes(manifest))


def publish(*, execute=False):
    if execute:
        return workflow.publication.publish(batch=BATCH)
    return workflow.publication.prepare(batch=BATCH)
