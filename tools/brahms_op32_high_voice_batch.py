"""Bounded nine-file batch for Brahms's 9 Lieder and Songs, Op.32.

The batch contains the nine public-domain Peters high-voice single-song
files. Download URLs must be observed after the normal anonymous IMSLP wait.
"""
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from tools import brahms_late_piano_batch as workflow
from tools.publish_brahms_op116 import PublicationBatch


IDS = ('8990', '8991', '8992', '8993', '8994', '8995', '8996', '8997', '8998')
BATCH = PublicationBatch(
    ids=IDS,
    batch_id='brahms-op32-high-voice-nine-20260907',
    stage_rel=Path('imports/johannes_brahms/staging/op32-high-voice-singles'),
    work_titles=('9 Lieder and Songs, Op.32',),
    log_message='新增勃拉姆斯《9 Lieder and Songs, Op. 32》高声部Peters独立单曲谱9份；均保留原始PDF，并逐页核对曲名、速度、德语歌词及高声部与钢琴编制。',
    allowed_voice_types=('声乐、钢琴', '高声部、钢琴'),
    allowed_categories=('艺术歌曲',),
)


def source_record(file_id, root=workflow.ROOT):
    return workflow.source_record(file_id, root, batch=BATCH)


def apply_metadata_corrections(root=workflow.ROOT):
    """Apply the high-voice label verified on the live IMSLP source page."""
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
        raise ValueError('Op.32 source scope changed')
    if any(item['voice_types'] != '声乐、钢琴' for item in by_id.values()):
        raise ValueError('Op.32 instrumentation changed concurrently')

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = root / 'backup' / 'import_metadata' / f'{BATCH.batch_id}-{stamp}'
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source_path, backup / 'manifest.json')
    stage_manifest_path = root / BATCH.stage_rel / 'manifest.json'
    stage_before = stage_manifest_path.read_bytes()
    stage_manifest = workflow.publication.read_json(stage_manifest_path)
    stage_by_id = {item['imslp_id']: item for item in stage_manifest['files']}
    if set(stage_by_id) != set(BATCH.ids):
        raise ValueError('Staged Op.32 scope changed')
    if any(item['voice_types'] != '声乐、钢琴' for item in stage_by_id.values()):
        raise ValueError('Staged Op.32 instrumentation changed concurrently')
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
        'changes': [
            {
                'imslp_id': file_id,
                'field': 'voice_types',
                'before': '声乐、钢琴',
                'after': '高声部、钢琴',
                'evidence': 'Live IMSLP source groups all nine files under High voice; the Peters edition note explicitly identifies an edition transposed for high voice.',
            }
            for file_id in BATCH.ids
        ],
    }
    workflow.publication.atomic_bytes(
        root / BATCH.stage_rel / 'metadata-corrections.json',
        workflow.publication.json_bytes(receipt),
    )
    return receipt


def record_inspection(root=workflow.ROOT):
    stage = root / BATCH.stage_rel
    manifest_path = stage / 'manifest.json'
    manifest = workflow.publication.read_json(manifest_path)
    by_id = {item['imslp_id']: item for item in manifest['files']}
    if set(by_id) != set(BATCH.ids):
        raise ValueError('Staged Op.32 scope changed before inspection record')
    titles = {
        '8990': 'No. 1 Wie rafft ich mich auf in der Nacht. Andante',
        '8991': 'No. 2 Nicht mehr zu dir zu gehen. Langsam',
        '8992': 'No. 3 Ich schleich umher. Mässig',
        '8993': 'No. 4 Der Strom, der neben mir verrauschte. Moderato, ma agitato',
        '8994': 'No. 5 Wehe, so willst du mich wieder. Allegro',
        '8995': 'No. 6 Du sprichst, dass ich mich täuschte. Andante con moto',
        '8996': 'No. 7 Bitteres zu sagen denkst du. Con moto, espressivo ma grazioso',
        '8997': 'No. 8 So stehn wir, ich und meine Weide. In gehender Bewegung',
        '8998': 'No. 9 Wie bist du, meine Königin. Adagio',
    }
    for file_id, title in titles.items():
        item = by_id[file_id]
        item.update(
            rendered_pages=item['page_count'],
            visual_check='checked_with_notes',
            publication_note=(
                f'高声部Peters版《{title}》，PDF共{item["page_count"]}页，逐页为连续完整乐谱且末页完整结束；'
                '谱面标题、速度、德语歌词及高声部与钢琴编制均与来源相符，原PDF字节未改。'
            ),
        )
    workflow.publication.atomic_bytes(manifest_path, workflow.publication.json_bytes(manifest))
    inspection = {
        'label': '9 Lieder and Songs, Op.32：高声部单曲',
        'checked_on': datetime.now().astimezone().date().isoformat(),
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'proposal_only': True,
        'publication_approved': False,
        'proposed_first_publication_ids': list(BATCH.ids),
        'source_notes': (
            '实时IMSLP作品页确认Op.32、九首目录、德语、原作编制voice/piano及Public Domain。'
            '本批收录高声部栏目下九份互不重复的Peters独立单曲#8990–#8998；完整谱、低声部版本及选集不在本批。'
            '所有下载均来自正常匿名等待后可见链接或正常PDF跳转。'
        ),
        'method': (
            '保留原PDF字节；pypdf逐页解析、SHA256校验；Poppler以80dpi渲染全部25页；'
            '查看九份全页接触表，逐份复核标题、速度、歌词、编制和末页完整性。'
        ),
        'rendering_note': '九份高声部单曲共25页，各文件逐页连续、标题与速度一致且末页完整结束，无缺页。',
        'metadata_changes': workflow.publication.read_json(stage / 'metadata-corrections.json')['changes'],
        'files': {
            file_id: {
                'pages': by_id[file_id]['page_count'],
                'key': '',
                'number': by_id[file_id]['movement_number'],
                'movement_start_pdf_pages': [1],
                'titles': [title],
                'notes': by_id[file_id]['publication_note'],
                'publication_note': by_id[file_id]['publication_note'],
            }
            for file_id, title in titles.items()
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
