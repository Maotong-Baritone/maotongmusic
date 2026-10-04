"""Bounded review helper for Brahms's 15 Volkskinderlieder, WoO 31."""
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

GERMAN_ID = '23199'
ENGLISH_ID = '836460'
DUPLICATE_IDS = ('88080', '88081')
EXPECTED_SHA256 = {
    GERMAN_ID: 'd3d5ffb2cd6d8d174e4f1be98f0842265b24b2d58ce0506e8c8664c526b0e3c2',
    ENGLISH_ID: '85582dd922437b24c9bcf23b463d64cb42447c3ca087a1bc88431eee53eb334b',
}
BATCH = PublicationBatch(
    ids=(GERMAN_ID, ENGLISH_ID),
    batch_id='brahms-woo31-two-editions-20260929',
    stage_rel=Path('imports/johannes_brahms/staging/woo31-first-edition'),
    work_titles=('15 Volkskinderlieder, WoO 31',),
    log_message='新增勃拉姆斯《15 Volkskinderlieder, WoO 31》德语初版及英文版完整谱2份；曲目、实际PDF起始页、语言、编制及出版版本均已核对。',
    allowed_voice_types=('声乐、钢琴',),
    allowed_categories=('声乐套曲',),
)


def _stage_file(source, local_name, content, digest, page_count, starts, title, work_title, language, summary, note):
    return {
        'imslp_id': source['imslp_id'],
        'public_id': source['public_id'],
        'title': title,
        'work': work_title,
        'category': '声乐套曲',
        'sub_category': '艺术歌曲',
        'voice_types': '声乐、钢琴',
        'tonality': '',
        'language': language,
        'movement_number': None,
        'title_scope': source['title_scope'],
        'source_url': 'https://imslp.org/wiki/15_Volkskinderlieder%2C_WoO_31_%28Brahms%2C_Johannes%29',
        'publisher': source['publisher'],
        'editor': source['editor'],
        'source_description': source['description'],
        'copyright': source['copyright'],
        'handler_url': source['handler_url'],
        'access_method': 'wait_page',
        'local_path': f'pdfs/{local_name}',
        'sha256': digest,
        'bytes': len(content),
        'page_count': page_count,
        'rendered_pages': page_count,
        'technical_check': f'PDF header, SHA256, pypdf {page_count}-page parsing, Poppler rendering of all pages',
        'visual_check': 'checked_with_notes',
        'movement_start_pdf_pages': starts,
        'publication_note': note,
        'description_summary': summary,
        'publication_approved': False,
    }


def prepare_review(root=ROOT):
    root = Path(root)
    stage = root / BATCH.stage_rel
    pdf_dir = stage / 'pdfs'
    pdf_dir.mkdir(exist_ok=True)
    source_specs = {
        GERMAN_ID: ('source/IMSLP23199.pdf', 'IMSLP23199-PMLP52990-BraWV_S_582f.pdf', 24),
        ENGLISH_ID: ('source/IMSLP836460.pdf', 'IMSLP836460-PMLP52990-Popular_Nursery_Songs.pdf', 19),
    }
    contents = {}
    digests = {}
    for file_id, (source_rel, local_name, _) in source_specs.items():
        content = (stage / source_rel).read_bytes()
        if not content.startswith(b'%PDF-'):
            raise ValueError(f'{file_id}: downloaded file is not a PDF')
        digest = hashlib.sha256(content).hexdigest()
        if digest != EXPECTED_SHA256[file_id]:
            raise ValueError(f'{file_id}: downloaded score hash changed')
        target = pdf_dir / local_name
        if target.exists() and target.read_bytes() != content:
            raise ValueError(f'{file_id}: staging PDF conflict')
        target.write_bytes(content)
        contents[file_id], digests[file_id] = content, digest

    review_path = root / 'imports/johannes_brahms/manifest.json'
    before = review_path.read_bytes()
    review = json.loads(before.decode('utf-8-sig'))
    matches = [w for w in review['works'] if w.get('title') == BATCH.work_titles[0]]
    if len(matches) != 1:
        raise ValueError('Source work scope changed')
    work = matches[0]
    by_id = {f.get('imslp_id'): f for f in work.get('files', [])}
    expected_ids = set(BATCH.ids + DUPLICATE_IDS)
    if expected_ids - set(by_id):
        raise ValueError('Expected source editions are missing')

    german, english = by_id[GERMAN_ID], by_id[ENGLISH_ID]
    common_expected = ('声乐套曲', '艺术歌曲', '声乐、钢琴', '', 'Public Domain', 'pending')
    for file_id in BATCH.ids + DUPLICATE_IDS:
        item = by_id[file_id]
        actual = (item.get('category'), item.get('sub_category'), item.get('voice_types'), item.get('tonality'), item.get('copyright'), item.get('decision'))
        if actual != common_expected:
            raise ValueError(f'{file_id}: source metadata changed concurrently: {actual!r}')
    if (german.get('proposed_title'), german.get('proposed_work'), german.get('language_cn')) != ('15 Volkskinderlieder, WoO 31', '', '英语'):
        raise ValueError('German first-edition metadata changed concurrently')
    if (english.get('proposed_title'), english.get('proposed_work'), english.get('language_cn')) != ('15 Volkskinderlieder, WoO 31', '', '英语'):
        raise ValueError('English edition metadata changed concurrently')

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = root / 'backup/import_metadata' / f'{BATCH.batch_id}-{stamp}'
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(review_path, backup / 'manifest.json')

    changes = []
    def change(item, field, value, evidence):
        old = item.get(field)
        if old != value:
            item[field] = value
            item['review_edited'] = True
            changes.append({'imslp_id': item['imslp_id'], 'field': field, 'before': old, 'after': value, 'evidence': evidence})

    change(german, 'language_cn', '德语', '谱面标题及全部歌词为德语；实时IMSLP一般信息亦标为German。')
    change(english, 'proposed_title', 'Popular Nursery Songs, WoO 31', '英文版封面实际题名为Popular Nursery Songs。')
    change(english, 'proposed_work', '15 Volkskinderlieder, WoO 31', '该文件为WoO 31的英文翻译完整版本，所属作品另列。')
    for file_id in DUPLICATE_IDS:
        item = by_id[file_id]
        change(item, 'decision', 'excluded', '已保留德语初版#23199；该后出全集版为同曲完整替代扫描，避免重复发布。')
        item['skip_reason'] = '同曲完整替代扫描；本批选用德语初版#23199，避免重复发布。'
        item['review_notes'] = '全集版#88080及其滤色件#88081均不发布；实时IMSLP另提示滤色件可能损失细小内容。'
        item['review_edited'] = True

    after = json_bytes(review)
    atomic_bytes(review_path, after)

    german_note = ('PDF第1页封面、第2页空白内封、第3页题名页；曲目起始页：No.1第4页、No.2第5页、No.3第6页、'
                   'No.4第8页、No.5第10页、No.6第11页、No.7第12页、No.8第一版第13页、No.8第二版第14页、'
                   'No.9第15页、No.10第16页、No.11第18页、No.12第19页、No.13第20页、No.14第21页；'
                   '第22–23页为空白封底，第24页为出版社目录。')
    english_note = ('PDF第1页封面、第2页空白；英文曲目起始页：No.1第3页、No.2第4页、No.3第6页、No.4第8页、'
                    'No.5第9页、No.6第10页、No.7第11页、No.8第12页、No.9第13页、No.10第14页、'
                    'No.11第16页、No.12第17页、No.13第18页、No.14第19页；此英文版收14首编号歌曲，未收入德语初版No.8的第二版本。')
    files = [
        _stage_file(german, source_specs[GERMAN_ID][1], contents[GERMAN_ID], digests[GERMAN_ID], 24,
                    [4,5,6,8,10,11,12,13,14,15,16,18,19,20,21], '15 Volkskinderlieder, WoO 31', '', '德语',
                    '来源：IMSLP #23199；版本：J. Rieter-Biedermann，1858年初版，版号60；文件范围：15首声乐与钢琴曲（含No.8两个版本），末页为出版社目录', german_note),
        _stage_file(english, source_specs[ENGLISH_ID][1], contents[ENGLISH_ID], digests[ENGLISH_ID], 19,
                    [3,4,6,8,9,10,11,12,13,14,16,17,18,19], 'Popular Nursery Songs, WoO 31', '15 Volkskinderlieder, WoO 31', '英语',
                    '来源：IMSLP #836460；版本：J. Rieter-Biedermann，版号771，伦敦Stanley Lucas, Weber & Co.发行；译者未署名；文件范围：14首英文版声乐与钢琴曲', english_note),
    ]
    trial = {'batch_id': BATCH.batch_id, 'scope': 'WoO 31 German first edition and distinct English edition',
             'authorization': 'User authorized continued reviewed Brahms batches.', 'published': False, 'files': files}
    inspection = {
        'label': '15 Volkskinderlieder, WoO 31 德语初版及英文版',
        'checked_on': datetime.now().astimezone().date().isoformat(),
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'proposal_only': True,
        'publication_approved': False,
        'proposed_first_publication_ids': list(BATCH.ids),
        'source_notes': '实时IMSLP作品页确认两份Public Domain完整谱、页数、语言、声乐与钢琴编制及出版信息；全集替代扫描#88080/#88081不采用。',
        'method': '保留原PDF字节；pypdf解析；Poppler渲染全部页面；人工查看两份全页接触表，并放大核对封面、首尾页、曲目页序、语言、编制和版本。',
        'metadata_changes': changes,
        'files': {
            GERMAN_ID: {'pages': 24, 'movement_start_pdf_pages': files[0]['movement_start_pdf_pages'], 'notes': german_note},
            ENGLISH_ID: {'pages': 19, 'movement_start_pdf_pages': files[1]['movement_start_pdf_pages'], 'notes': english_note},
        },
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
