"""Bounded review and publication helper for Brahms's WoO 35 scores."""
import argparse
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

FILE_IDS = ('102712', '108869')
DUPLICATE_ID = '102713'
SPECIAL_LICENSE_ID = '202904'
FILES = {
    '102712': {
        'name': '12 Deutsche Volkslieder, WoO 35 - Breitkopf-complete-score - IMSLP102712.pdf',
        'sha256': '5eeb94b94166dd7dc7d7c42e4ebe356bc08d506456c1de08ba4613a5beb729ae',
        'bytes': 1597022,
        'pages': 11,
    },
    '108869': {
        'name': 'No.12 Altdeutsches Kampflied, WoO 35 - first-edition - IMSLP108869.pdf',
        'sha256': 'f4ba0f4b610cc879027ad3fae9c4633f01fd4058ffbbcf533abef6a05f7f6be0',
        'bytes': 85328,
        'pages': 1,
    },
}
BATCH = PublicationBatch(
    ids=FILE_IDS,
    batch_id='brahms-woo35-complete-and-no12-first-edition-two-20260929',
    stage_rel=Path('imports/johannes_brahms/staging/woo35-complete-scan'),
    work_titles=('12 Deutsche Volkslieder, WoO 35',),
    log_message='新增勃拉姆斯《12 Deutsche Volkslieder, WoO 35》完整谱及No.12初版单曲2份；12首目录、实际PDF起始页、德语歌词、版本及无伴奏混声合唱编制均已逐页核对。',
    allowed_voice_types=('混声合唱（无伴奏）',),
    allowed_categories=('合唱作品',),
)

STARTS = [1, 2, 3, 4, 4, 5, 5, 7, 8, 9, 9, 11]
TITLES = [
    'Scheiden', 'Wach auf!', 'Erlaube mir', 'Der Fiedler', 'Da unten im Tale',
    'Des Abends', 'Wach auf! (2. Bearbeitung)', 'Dort in den Weiden',
    'Altes Volkslied', 'Der Ritter und die Feine', 'Der Zimmergesell',
    'Altdeutsches Kampflied',
]


def prepare_review(root=ROOT):
    root = Path(root)
    stage = root / BATCH.stage_rel
    for file_id, expected in FILES.items():
        content = (stage / 'pdfs' / expected['name']).read_bytes()
        if (
            not content.startswith(b'%PDF-')
            or len(content) != expected['bytes']
            or hashlib.sha256(content).hexdigest() != expected['sha256']
        ):
            raise ValueError(f'Reviewed PDF changed: #{file_id}')
    if len(STARTS) != 12 or len(TITLES) != 12:
        raise ValueError('WoO 35 directory must contain 12 items')

    review_path = root / 'imports/johannes_brahms/manifest.json'
    before = review_path.read_bytes()
    review = json.loads(before.decode('utf-8-sig'))
    matches = [w for w in review['works'] if w.get('title') == BATCH.work_titles[0]]
    if len(matches) != 1:
        raise ValueError('Source work scope changed')
    work = matches[0]
    by_id = {f.get('imslp_id'): f for f in work.get('files', [])}
    expected_ids = set(FILE_IDS + (DUPLICATE_ID, SPECIAL_LICENSE_ID))
    if expected_ids - set(by_id):
        raise ValueError('Expected source alternatives are missing')

    complete = by_id['102712']
    complete_expected = (
        complete.get('proposed_title'), complete.get('proposed_work'), complete.get('category'),
        complete.get('sub_category'), complete.get('voice_types'), complete.get('tonality'),
        complete.get('language_cn'), complete.get('copyright'), complete.get('decision'),
    )
    if complete_expected != (
        '12 Deutsche Volkslieder, WoO 35', '', '合唱作品', '艺术歌曲',
        '混声合唱', '', '德语', 'Public Domain', 'pending',
    ):
        raise ValueError(f'Complete-score metadata changed concurrently: {complete_expected!r}')

    single = by_id['108869']
    single_expected = (
        single.get('proposed_title'), single.get('proposed_work'), single.get('category'),
        single.get('sub_category'), single.get('voice_types'), single.get('tonality'),
        single.get('language_cn'), single.get('copyright'), single.get('decision'),
        single.get('movement_number'), single.get('title_scope'),
    )
    if single_expected != (
        'No. 12 Altdeutches Kapflied, WoO 35', '12 Deutsche Volkslieder, WoO 35',
        '合唱作品', '艺术歌曲', '混声合唱', '', '德语', 'Public Domain',
        'pending', 12, 'individual_movement',
    ):
        raise ValueError(f'No.12 metadata changed concurrently: {single_expected!r}')

    duplicate = by_id[DUPLICATE_ID]
    if (duplicate.get('description_en'), duplicate.get('copyright'), duplicate.get('decision')) != (
        'Complete Score (filter)', 'Public Domain', 'pending',
    ):
        raise ValueError('Filtered duplicate changed concurrently')
    special = by_id[SPECIAL_LICENSE_ID]
    if (special.get('copyright'), special.get('decision'), special.get('movement_number')) != (
        'Creative Commons Attribution Non-commercial Share Alike 3.0', 'pending', 5,
    ):
        raise ValueError('Special-license alternative changed concurrently')

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = root / 'backup/import_metadata' / f'{BATCH.batch_id}-{stamp}'
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(review_path, backup / 'manifest.json')

    complete['sub_category'] = ''
    complete['voice_types'] = '混声合唱（无伴奏）'
    complete['review_notes'] = '实时IMSLP标明German、Chorus (SATB)、For unaccompanied chorus；谱面为德语SATB无伴奏合唱。'
    complete['review_edited'] = True
    single['proposed_title'] = 'No.12 Altdeutsches Kampflied, WoO 35'
    single['sub_category'] = ''
    single['voice_types'] = '混声合唱（无伴奏）'
    single['review_notes'] = '实时IMSLP分段标题和谱面均为Altdeutsches Kampflied；作品配置为SATB无伴奏合唱。'
    single['review_edited'] = True
    duplicate.update(
        decision='excluded',
        skip_reason='与#102712为同一扫描的滤色版本；页面说明滤色可能丢失细节，保留原扫描以避免重复。',
        review_notes='同版滤色替代件，不重复发布。',
        review_edited=True,
    )
    special.update(
        decision='excluded',
        skip_reason='No.5现代排版采用CC BY-NC-SA 3.0特殊许可，且完整公版扫描已含此曲；不纳入常规公版发布。',
        review_notes='特殊许可现代排版；保留记录但不发布。',
        review_edited=True,
    )
    after = json_bytes(review)
    atomic_bytes(review_path, after)

    directory = '；'.join(
        f'No.{i} {title}（PDF第{page}页' + ('，同页起始）' if i in (5, 7, 11) else '）')
        for i, (title, page) in enumerate(zip(TITLES, STARTS), 1)
    )
    complete_note = (
        '全集第21卷连续摘页，PDF第1–11页对应印刷页18–28、全集页144–154；12首均完整。目录：'
        + directory
    )
    single_note = '单页完整乐谱；PDF第1页即乐谱起始，谱面选集编号为No.28，作品内编号为WoO 35 No.12；印刷页码33、版号9。'
    notes = {'102712': complete_note, '108869': single_note}
    summaries = {
        '102712': '来源：IMSLP #102712；版本：Breitkopf & Härtel《全集》第21卷，1926–27年，Eusebius Mandyczewski编；文件范围：印刷页18–28（全集页144–154），12首德语无伴奏混声合唱完整谱',
        '108869': '来源：IMSLP #108869；版本：Max Friedlaender编校，Verlag der Deutschen Brahms-Gesellschaft 1926年初版Urtext，版号9；文件范围：WoO 35 No.12单页完整谱',
    }
    staged_files = []
    for file_id in FILE_IDS:
        source = by_id[file_id]
        expected = FILES[file_id]
        staged_files.append({
            'imslp_id': file_id, 'public_id': source['public_id'],
            'title': source['proposed_title'], 'work': source['proposed_work'],
            'category': source['category'], 'sub_category': source['sub_category'],
            'voice_types': source['voice_types'], 'tonality': source['tonality'],
            'language': source['language_cn'], 'movement_number': source['movement_number'],
            'title_scope': source['title_scope'], 'source_url': work['source_url'],
            'publisher': source['publisher'], 'editor': source['editor'],
            'source_description': source['description'], 'copyright': source['copyright'],
            'handler_url': source['handler_url'], 'access_method': 'wait_page',
            'local_path': f"pdfs/{expected['name']}", 'sha256': expected['sha256'],
            'bytes': expected['bytes'], 'page_count': expected['pages'],
            'rendered_pages': expected['pages'],
            'technical_check': f"PDF header, SHA256, pypdf {expected['pages']}-page parsing, Poppler rendering of all pages",
            'visual_check': 'checked_with_notes', 'publication_note': notes[file_id],
            'description_summary': summaries[file_id], 'publication_approved': False,
        })
    trial = {
        'batch_id': BATCH.batch_id,
        'scope': '12 Deutsche Volkslieder, WoO 35 complete score and No.12 first-edition single',
        'authorization': 'User authorized continued reviewed Brahms batches.',
        'published': False, 'files': staged_files,
    }
    changes = [
        {'imslp_id': '102712', 'field': 'sub_category', 'before': '艺术歌曲', 'after': '', 'evidence': '作品为真正SATB无伴奏混声合唱；按现有分类归入合唱作品，不重复使用艺术歌曲子分类。'},
        {'imslp_id': '102712', 'field': 'voice_types', 'before': '混声合唱', 'after': '混声合唱（无伴奏）', 'evidence': '实时IMSLP配置为Chorus (SATB)，分类为For unaccompanied chorus；谱面仅合唱声部。'},
        {'imslp_id': '108869', 'field': 'proposed_title', 'before': 'No. 12 Altdeutches Kapflied, WoO 35', 'after': 'No.12 Altdeutsches Kampflied, WoO 35', 'evidence': '实时IMSLP分段标题及谱面标题均为Altdeutsches Kampflied。'},
        {'imslp_id': '108869', 'field': 'sub_category', 'before': '艺术歌曲', 'after': '', 'evidence': '谱面标注für Chor，为无伴奏合唱；不使用艺术歌曲子分类。'},
        {'imslp_id': '108869', 'field': 'voice_types', 'before': '混声合唱', 'after': '混声合唱（无伴奏）', 'evidence': '实时IMSLP作品配置为Chorus (SATB)，谱面无伴奏。'},
        {'imslp_id': DUPLICATE_ID, 'field': 'decision', 'before': 'pending', 'after': 'excluded', 'evidence': '与#102712为同一扫描的滤色版本；保留原扫描以避免重复。'},
        {'imslp_id': SPECIAL_LICENSE_ID, 'field': 'decision', 'before': 'pending', 'after': 'excluded', 'evidence': 'No.5现代排版采用CC BY-NC-SA 3.0特殊许可，且完整公版扫描已含此曲。'},
    ]
    inspection = {
        'label': '12 Deutsche Volkslieder, WoO 35完整谱及No.12初版单曲',
        'checked_on': datetime.now().astimezone().date().isoformat(),
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'proposal_only': True, 'publication_approved': False,
        'proposed_first_publication_ids': list(FILE_IDS),
        'source_notes': '实时IMSLP确认#102712为Public Domain、完整原扫描、11页、Breitkopf & Härtel 1926–27年全集第21卷；#102713为同一扫描的滤色重复版，排除。#108869为Public Domain、No.12单页初版Urtext，作为有用独立单曲保留。#202904为现代排版且采用CC BY-NC-SA 3.0特殊许可，排除。',
        'method': '保留两份原PDF字节；pypdf解析全部12页；Poppler渲染全部页面；人工检查完整谱全页接触表并逐页原尺寸放大11页，另逐页放大No.12初版单页，核对12首题名、实际起始页、德语歌词、SATB无伴奏编制、版本和异常。',
        'full_size_review': 'completed_all_12_pages_across_2_files',
        'metadata_changes': changes,
        'files': {
            '102712': {'pages': 11, 'key': '', 'number': None, 'movement_start_pdf_pages': STARTS,
                       'titles': [f'No.{i} {t}' for i, t in enumerate(TITLES, 1)],
                       'notes': '11页连续摘自全集第21卷；未见缺页、错序、裁切或不可读异常。No.5与No.4、No.7与No.6、No.11与No.10分别同页起始。',
                       'publication_note': complete_note},
            '108869': {'pages': 1, 'key': '', 'number': 12, 'movement_start_pdf_pages': [1],
                       'titles': ['No.12 Altdeutsches Kampflied'],
                       'notes': '初版单页扫描清晰完整；谱面选集编号为28，作品内编号为WoO 35 No.12；末注其余歌词见后记，不影响本页音乐完整性。',
                       'publication_note': single_note},
        },
    }
    receipt = {
        'batch_id': BATCH.batch_id, 'recorded_at': datetime.now(timezone.utc).isoformat(),
        'source_manifest_before_sha256': hashlib.sha256(before).hexdigest(),
        'source_manifest_after_sha256': hashlib.sha256(after).hexdigest(),
        'backup': str(backup.relative_to(root)), 'changes': changes,
    }
    atomic_bytes(stage / 'manifest.json', json_bytes(trial))
    atomic_bytes(stage / 'inspection.json', json_bytes(inspection))
    atomic_bytes(stage / 'metadata-corrections.json', json_bytes(receipt))
    return receipt


def publication(execute=False):
    from tools import publish_brahms_op116 as workflow
    return workflow.publish(batch=BATCH) if execute else workflow.prepare(batch=BATCH)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-metadata', action='store_true')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.prepare_metadata and args.execute:
        parser.error('--prepare-metadata and --execute are mutually exclusive')
    if args.prepare_metadata:
        print(json.dumps(prepare_review(), ensure_ascii=False, indent=2))
        return
    if args.execute:
        publication(execute=True)
        return
    plan = publication(execute=False)
    print(json.dumps({
        'batch_id': BATCH.batch_id,
        'count': len(plan['planned']),
        'already_published': plan['already_published'],
        'files': [
            {'id': p['id'], 'title': p['item']['title'], 'public_id': p['item']['public_id'], 'sha256': p['sha256']}
            for p in plan['planned']
        ],
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
