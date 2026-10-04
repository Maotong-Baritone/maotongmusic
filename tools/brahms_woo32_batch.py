"""Bounded publication helper for Brahms's 28 Deutsche Volkslieder, WoO 32."""
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

FILE_ID = '88084'
DUPLICATE_ID = '88085'
EXPECTED_SHA256 = '5ebeb415e7ccf348635f1c789207bf2b3a22a434f444129165dee352f4260319'
BATCH = PublicationBatch(
    ids=(FILE_ID,),
    batch_id='brahms-woo32-complete-scan-one-20260929',
    stage_rel=Path('imports/johannes_brahms/staging/woo32-complete-scan'),
    work_titles=('28 Deutsche Volkslieder, WoO 32',),
    log_message='新增勃拉姆斯《28 Deutsche Volkslieder, WoO 32》声乐与钢琴完整谱1份；28首目录、实际PDF起始页、德语歌词及出版版本均已核对。',
    allowed_voice_types=('声乐、钢琴',),
    allowed_categories=('声乐套曲',),
)


def prepare_review(root=ROOT):
    root = Path(root)
    stage = root / BATCH.stage_rel
    source_pdf = stage / 'source/IMSLP88084.pdf'
    content = source_pdf.read_bytes()
    if not content.startswith(b'%PDF-'):
        raise ValueError('Downloaded file is not a PDF')
    digest = hashlib.sha256(content).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError('Downloaded score hash changed')
    pdf_dir = stage / 'pdfs'
    pdf_dir.mkdir(exist_ok=True)
    local_name = 'IMSLP88084-PMLP180155-Brahms_Werke_Band_26_WoO_32_scan.pdf'
    target_pdf = pdf_dir / local_name
    if target_pdf.exists() and target_pdf.read_bytes() != content:
        raise ValueError('Staging PDF conflict')
    target_pdf.write_bytes(content)

    review_path = root / 'imports/johannes_brahms/manifest.json'
    before = review_path.read_bytes()
    review = json.loads(before.decode('utf-8-sig'))
    work_matches = [w for w in review['works'] if w.get('title') == BATCH.work_titles[0]]
    if len(work_matches) != 1:
        raise ValueError('Source work scope changed')
    work = work_matches[0]
    by_id = {f.get('imslp_id'): f for f in work.get('files', [])}
    if set((FILE_ID, DUPLICATE_ID)) - set(by_id):
        raise ValueError('Expected source alternatives are missing')
    source, duplicate = by_id[FILE_ID], by_id[DUPLICATE_ID]
    source_expected = (
        source.get('proposed_title'), source.get('proposed_work'), source.get('category'),
        source.get('sub_category'), source.get('voice_types'), source.get('tonality'),
        source.get('language_cn'), source.get('copyright'), source.get('decision'),
    )
    if source_expected != (
        '28 Deutsche Volkslieder, WoO 32', '', '声乐套曲', '艺术歌曲',
        '声乐、钢琴', '', '德语', 'Public Domain', 'pending',
    ):
        raise ValueError(f'Source metadata changed concurrently: {source_expected!r}')
    duplicate_expected = (duplicate.get('description_en'), duplicate.get('copyright'), duplicate.get('decision'))
    if duplicate_expected != ('Complete Score (filter)', 'Public Domain', 'pending'):
        raise ValueError(f'Duplicate alternative changed concurrently: {duplicate_expected!r}')

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = root / 'backup/import_metadata' / f'{BATCH.batch_id}-{stamp}'
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(review_path, backup / 'manifest.json')
    duplicate['decision'] = 'excluded'
    duplicate['skip_reason'] = '同版滤色替代件；选用分辨率更高且未滤色的完整扫描 #88084，避免重复发布。'
    duplicate['review_notes'] = '实时IMSLP说明滤色版可能损失细小内容；本批保留原扫描 #88084。'
    duplicate['review_edited'] = True
    after = json_bytes(review)
    atomic_bytes(review_path, after)

    page_map = (
        'PDF第1页：No.1 Die Schnürbrust、No.2 Der Jäger；第2页：No.3 Drei Vögelein、No.4 Auf, gebet uns das Pfingstei；'
        '第3页：No.5 Des Markgrafen Töchterlein、No.6 Der Reiter；第4页：No.7 Die heilige Elisabeth；'
        '第5页：No.8 Der englische Gruß、No.9 Ich stund an einem Morgen；第6页：No.10 Gunhilde、No.11 Der tote Gast；'
        '第7页：No.12 Tageweis von einer schönen Frauen、No.13 Schifferlied；第8页：No.14 Nachtgesang；'
        '第9页：No.15 Die beiden Königskinder、No.16 Scheiden；第10页：No.17 Altes Minnelied、No.18 Der getreue Eckart（续至第11页）；'
        '第11页：No.19 Die Versuchung；第12页：No.20 Der Tochter Wunsch；第13页：No.21 Schnitter Tod、No.22 Marias Wallfahrt；'
        '第14页：No.23 Das Mädchen und der Tod、No.24 Es ritt ein Ritter；第15页：No.25 Liebeslied、No.26 Guten Abend；'
        '第16页：No.27 Die Wollust in den Maien、No.28 Es reit ein Herr und auch sein Knecht；第17页为出版社作品目录。'
    )
    staged_file = {
        'imslp_id': FILE_ID,
        'public_id': source['public_id'],
        'title': source['proposed_title'],
        'work': source['proposed_work'],
        'category': source['category'],
        'sub_category': source['sub_category'],
        'voice_types': source['voice_types'],
        'tonality': source['tonality'],
        'language': source['language_cn'],
        'movement_number': source['movement_number'],
        'title_scope': source['title_scope'],
        'source_url': work['source_url'],
        'publisher': source['publisher'],
        'editor': source['editor'],
        'source_description': source['description'],
        'copyright': source['copyright'],
        'handler_url': source['handler_url'],
        'access_method': 'wait_page',
        'local_path': f'pdfs/{local_name}',
        'sha256': digest,
        'bytes': len(content),
        'page_count': 17,
        'rendered_pages': 17,
        'technical_check': 'PDF header, SHA256, pypdf 17-page parsing, Poppler rendering of all pages',
        'visual_check': 'checked_with_notes',
        'publication_note': page_map,
        'description_summary': '来源：IMSLP #88084；版本：Sämtliche Werke, Band 26，Breitkopf & Härtel，1926–27，版号J.B.174；编者：Eusebius Mandyczewski；文件范围：28首声乐与钢琴完整谱，PDF第17页为出版社目录',
        'publication_approved': False,
    }
    trial = {
        'batch_id': BATCH.batch_id,
        'scope': '28 Deutsche Volkslieder, WoO 32 complete original scan',
        'authorization': 'User authorized continued reviewed Brahms batches.',
        'published': False,
        'files': [staged_file],
    }
    inspection = {
        'label': '28 Deutsche Volkslieder, WoO 32 原扫描完整谱',
        'checked_on': datetime.now().astimezone().date().isoformat(),
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'proposal_only': True,
        'publication_approved': False,
        'proposed_first_publication_ids': [FILE_ID],
        'source_notes': '实时IMSLP作品页确认Public Domain、Complete Score (scan)、17页、声乐与钢琴、德语及Mandyczewski/Breitkopf版本；滤色替代件#88085未采用。',
        'method': '保留原PDF字节；pypdf解析17页；Poppler渲染全部页面；人工查看全页接触表并逐页原尺寸放大核对28首题名、页序、声乐与钢琴编制、德语歌词、版本及末页出版社目录。',
        'metadata_changes': [{
            'imslp_id': DUPLICATE_ID,
            'field': 'decision',
            'before': 'pending',
            'after': 'excluded',
            'evidence': '同版滤色替代件；实时IMSLP提示可能损失细小内容，已选用较高分辨率原扫描#88084。',
        }],
        'files': {FILE_ID: {
            'pages': 17,
            'key': '',
            'number': None,
            'movement_start_pdf_pages': list(range(1, 17)),
            'titles': ['No.1–28'],
            'notes': 'PDF第1–16页为28首完整乐谱；第17页为出版社作品目录；无缺页、错序或裁切异常。',
            'publication_note': page_map,
        }},
    }
    receipt = {
        'batch_id': BATCH.batch_id,
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'source_manifest_before_sha256': hashlib.sha256(before).hexdigest(),
        'source_manifest_after_sha256': hashlib.sha256(after).hexdigest(),
        'backup': str(backup.relative_to(root)),
        'changes': inspection['metadata_changes'],
    }
    atomic_bytes(stage / 'manifest.json', json_bytes(trial))
    atomic_bytes(stage / 'inspection.json', json_bytes(inspection))
    atomic_bytes(stage / 'metadata-corrections.json', json_bytes(receipt))
    return receipt


if __name__ == '__main__':
    print(json.dumps(prepare_review(), ensure_ascii=False, indent=2))
