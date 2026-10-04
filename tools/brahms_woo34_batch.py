"""Bounded review and publication helper for Brahms's WoO 34 first edition."""
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.publish_brahms_op116 import PublicationBatch, atomic_bytes, json_bytes

FILE_ID = '23201'
DUPLICATE_IDS = ('102709', '102710')
EXPECTED_SHA256 = 'ac943fa0e4bab6b4a7864316fc373e40b9e4c467eaf69b50914619978c1c2306'
LOCAL_NAME = '14 Deutsche Volkslieder, WoO 34 - Rieter-Biedermann-first-edition - IMSLP23201.pdf'
BATCH = PublicationBatch(
    ids=(FILE_ID,),
    batch_id='brahms-woo34-first-edition-one-20260929',
    stage_rel=Path('imports/johannes_brahms/staging/woo34-first-edition'),
    work_titles=('14 Deutsche Volkslieder, WoO 34',),
    log_message='新增勃拉姆斯《14 Deutsche Volkslieder, WoO 34》1864年初版完整谱1份；14首目录、两册结构、实际PDF起始页、德语歌词及无伴奏混声合唱编制均已逐页核对。',
    allowed_voice_types=('混声合唱（无伴奏）',),
    allowed_categories=('合唱作品',),
)

STARTS = [5, 7, 9, 11, 13, 17, 19, 25, 27, 29, 31, 33, 37, 39]
TITLES = [
    'Von edler Art', 'Mit Lust tät ich ausreiten', 'Bei nächtlicher Weil',
    'Vom heiligen Märtyrer Emmerano', 'Täublein weiss', 'Ach lieber Herre Jesu Christ',
    'Sankt Raphael', 'In stiller Nacht', 'Abschiedslied', 'Der tote Knabe',
    'Die Wollust in den Maien', 'Morgengesang', 'Schnitter Tod', 'Der englische Jäger',
]


def prepare_review(root=ROOT):
    root = Path(root)
    stage = root / BATCH.stage_rel
    pdf = stage / 'pdfs' / LOCAL_NAME
    content = pdf.read_bytes()
    if not content.startswith(b'%PDF-') or hashlib.sha256(content).hexdigest() != EXPECTED_SHA256:
        raise ValueError('Reviewed PDF changed')
    if len(STARTS) != 14 or len(TITLES) != 14:
        raise ValueError('WoO 34 directory must contain 14 items')

    review_path = root / 'imports/johannes_brahms/manifest.json'
    before = review_path.read_bytes()
    review = json.loads(before.decode('utf-8-sig'))
    matches = [w for w in review['works'] if w.get('title') == BATCH.work_titles[0]]
    if len(matches) != 1:
        raise ValueError('Source work scope changed')
    work = matches[0]
    by_id = {f.get('imslp_id'): f for f in work.get('files', [])}
    if set((FILE_ID,) + DUPLICATE_IDS) - set(by_id):
        raise ValueError('Expected source alternatives are missing')
    source = by_id[FILE_ID]
    source_expected = (
        source.get('proposed_title'), source.get('proposed_work'), source.get('category'),
        source.get('sub_category'), source.get('voice_types'), source.get('tonality'),
        source.get('language_cn'), source.get('copyright'), source.get('decision'),
    )
    if source_expected != (
        '14 Deutsche Volkslieder, WoO 34', '', '合唱作品', '艺术歌曲',
        '混声合唱', '', '英语', 'Public Domain', 'pending',
    ):
        raise ValueError(f'Source metadata changed concurrently: {source_expected!r}')
    for duplicate_id in DUPLICATE_IDS:
        duplicate = by_id[duplicate_id]
        expected_description = 'Complete Score (scan)' if duplicate_id == '102709' else 'Complete Score (filter)'
        duplicate_expected = (duplicate.get('description_en'), duplicate.get('copyright'), duplicate.get('decision'))
        if duplicate_expected != (expected_description, 'Public Domain', 'pending'):
            raise ValueError(f'Duplicate alternative changed concurrently: #{duplicate_id} {duplicate_expected!r}')

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = root / 'backup/import_metadata' / f'{BATCH.batch_id}-{stamp}'
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(review_path, backup / 'manifest.json')
    source['language_cn'] = '德语'
    source['sub_category'] = ''
    source['voice_types'] = '混声合唱（无伴奏）'
    source['review_notes'] = '实时IMSLP标明German、mixed chorus (SATB)、For unaccompanied chorus；谱面为德语SATB无伴奏合唱。'
    source['review_edited'] = True
    for duplicate_id in DUPLICATE_IDS:
        duplicate = by_id[duplicate_id]
        duplicate['decision'] = 'excluded'
        duplicate['skip_reason'] = '1926–27年全集版替代扫描；本批选用1864年Rieter-Biedermann初版完整扫描#23201，避免重复发布。'
        duplicate['review_notes'] = '与#23201同曲完整版本；原扫描和滤色件均不重复发布。'
        duplicate['review_edited'] = True
    after = json_bytes(review)
    atomic_bytes(review_path, after)

    directory = '；'.join(f'No.{i} {title}（PDF第{page}页）' for i, (title, page) in enumerate(zip(TITLES, STARTS), 1))
    page_map = (
        '两册合订：第1册PDF第1–21页（封面1、题名2、空白3、题献4、正文5–20、21空白）；'
        '第2册PDF第22–41页（题名22、空白23、题献24、正文25–40、41空白）。目录：' + directory
    )
    staged_file = {
        'imslp_id': FILE_ID, 'public_id': source['public_id'], 'title': source['proposed_title'],
        'work': source['proposed_work'], 'category': source['category'], 'sub_category': source['sub_category'],
        'voice_types': source['voice_types'], 'tonality': source['tonality'], 'language': source['language_cn'],
        'movement_number': source['movement_number'], 'title_scope': source['title_scope'],
        'source_url': work['source_url'], 'publisher': source['publisher'], 'editor': source['editor'],
        'source_description': source['description'], 'copyright': source['copyright'],
        'handler_url': source['handler_url'], 'access_method': 'wait_page', 'local_path': f'pdfs/{LOCAL_NAME}',
        'sha256': EXPECTED_SHA256, 'bytes': len(content), 'page_count': 41, 'rendered_pages': 41,
        'technical_check': 'PDF header, SHA256, pypdf 41-page parsing, Poppler rendering of all pages',
        'visual_check': 'checked_with_notes', 'publication_note': page_map,
        'description_summary': '来源：IMSLP #23201；版本：J. Rieter-Biedermann，1864年初版，版号395a、395b；文件范围：14首德语无伴奏混声合唱民歌两册完整谱',
        'publication_approved': False,
    }
    trial = {'batch_id': BATCH.batch_id, 'scope': '14 Deutsche Volkslieder, WoO 34 Rieter-Biedermann first edition complete score',
             'authorization': 'User authorized continued reviewed Brahms batches.', 'published': False, 'files': [staged_file]}
    changes = [
        {'imslp_id': FILE_ID, 'field': 'language_cn', 'before': '英语', 'after': '德语', 'evidence': '实时IMSLP一般信息标明German；谱面歌词为德语。'},
        {'imslp_id': FILE_ID, 'field': 'sub_category', 'before': '艺术歌曲', 'after': '', 'evidence': '作品为真正SATB无伴奏混声合唱；按现有分类归入合唱作品，不重复使用艺术歌曲子分类。'},
        {'imslp_id': FILE_ID, 'field': 'voice_types', 'before': '混声合唱', 'after': '混声合唱（无伴奏）', 'evidence': '实时IMSLP配置为mixed chorus (SATB)，分类为For unaccompanied chorus；谱面仅SATB四声部。'},
        *[{'imslp_id': i, 'field': 'decision', 'before': 'pending', 'after': 'excluded', 'evidence': '1926–27年全集版替代扫描；选用#23201初版以避免重复发布。'} for i in DUPLICATE_IDS],
    ]
    inspection = {
        'label': '14 Deutsche Volkslieder, WoO 34 Rieter-Biedermann初版完整谱',
        'checked_on': datetime.now().astimezone().date().isoformat(), 'recorded_at': datetime.now(timezone.utc).isoformat(),
        'proposal_only': True, 'publication_approved': False, 'proposed_first_publication_ids': [FILE_ID],
        'source_notes': '实时IMSLP确认#23201为Public Domain、Complete Score、41页、J. Rieter-Biedermann 1864年初版；#102709与#102710为1926–27全集版原扫描和滤色替代版，排除以避免重复版本。',
        'method': '保留原PDF字节；pypdf解析41页；Poppler渲染全部页面；人工检查4张全页接触表并逐页原尺寸放大核对41页、14首题名与起始页、两册结构、德语歌词、SATB无伴奏编制及异常。',
        'full_size_review': 'completed_all_41_pages', 'metadata_changes': changes,
        'volume_page_ranges': [{'volume': 1, 'pdf_pages': '1–21', 'music_pages': '5–20'}, {'volume': 2, 'pdf_pages': '22–41', 'music_pages': '25–40'}],
        'files': {FILE_ID: {'pages': 41, 'key': '', 'number': None, 'movement_start_pdf_pages': STARTS,
                             'titles': [f'No.{i} {t}' for i, t in enumerate(TITLES, 1)],
                             'notes': '两册及14首连续完整；SATB无伴奏混声合唱。全页有来源数字水印及少量铅笔馆藏标记，未见缺页、错序、裁切或不可读异常。',
                             'publication_note': page_map}},
    }
    receipt = {'batch_id': BATCH.batch_id, 'recorded_at': datetime.now(timezone.utc).isoformat(),
               'source_manifest_before_sha256': hashlib.sha256(before).hexdigest(),
               'source_manifest_after_sha256': hashlib.sha256(after).hexdigest(),
               'backup': str(backup.relative_to(root)), 'changes': changes}
    atomic_bytes(stage / 'manifest.json', json_bytes(trial))
    atomic_bytes(stage / 'inspection.json', json_bytes(inspection))
    atomic_bytes(stage / 'metadata-corrections.json', json_bytes(receipt))
    return receipt


if __name__ == '__main__':
    print(json.dumps(prepare_review(), ensure_ascii=False, indent=2))
