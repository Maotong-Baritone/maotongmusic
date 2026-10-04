"""Bounded single-manuscript batch for Brahms's Albumblatt for Clara Schumann."""
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.publish_brahms_op116 import PublicationBatch, atomic_bytes, json_bytes, read_json

FILE_ID = '374716'
BATCH = PublicationBatch(
    ids=(FILE_ID,),
    batch_id='brahms-albumblatt-clara-manuscript-one-20260929',
    stage_rel=Path('imports/johannes_brahms/staging/albumblatt-clara-schumann-manuscript'),
    work_titles=('Albumblatt für Clara Schumann',),
    log_message='新增勃拉姆斯《Albumblatt für Clara Schumann》无伴奏独唱手稿1份；题名、德语歌词、C大调、日期及手稿正反面均已核对。',
    allowed_voice_types=('独唱（无伴奏）',),
    allowed_categories=('艺术歌曲',),
)


def prepare_review(root=ROOT):
    stage = root / BATCH.stage_rel
    source_pdf = stage / 'IMSLP374716-PMLP604863-AlbumblattfuerClaraSchumann.pdf'
    if not source_pdf.exists():
        raise FileNotFoundError(source_pdf)
    content = source_pdf.read_bytes()
    if not content.startswith(b'%PDF-'):
        raise ValueError('Downloaded file is not a PDF')
    digest = hashlib.sha256(content).hexdigest()
    if digest != '70eb0176904582d48a4d9bd21169c677bfc458fa588077ba3322a9fd8536e704':
        raise ValueError('Downloaded manuscript hash changed')
    pdf_dir = stage / 'pdfs'
    pdf_dir.mkdir(exist_ok=True)
    local_name = 'IMSLP374716-PMLP604863-AlbumblattfuerClaraSchumann.pdf'
    target_pdf = pdf_dir / local_name
    if target_pdf.exists() and target_pdf.read_bytes() != content:
        raise ValueError('Staging PDF conflict')
    target_pdf.write_bytes(content)

    review_path = root / 'imports/johannes_brahms/manifest.json'
    before = review_path.read_bytes()
    review = json.loads(before.decode('utf-8-sig'))
    matches = [(w, f) for w in review['works'] for f in w.get('files', []) if f.get('imslp_id') == FILE_ID]
    if len(matches) != 1:
        raise ValueError('Source scope changed')
    work, source = matches[0]
    expected = (work.get('title'), source.get('voice_types'), source.get('language_cn'), source.get('tonality'), source.get('category'), source.get('decision'))
    if expected != ('Albumblatt für Clara Schumann', '声乐', '', 'C大调', '艺术歌曲', 'pending'):
        raise ValueError(f'Source metadata changed concurrently: {expected!r}')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = root / 'backup/import_metadata' / f'{BATCH.batch_id}-{stamp}'
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(review_path, backup / 'manifest.json')
    source['voice_types'] = '独唱（无伴奏）'
    source['language_cn'] = '德语'
    source['review_notes'] = '实时IMSLP作品页标为voice、For 1 voice、For unaccompanied voices；两页手稿正面含德语题词与单旋律，背面为空白五线纸。'
    source['review_edited'] = True
    after = json_bytes(review)
    atomic_bytes(review_path, after)

    trial = {
        'batch_id': BATCH.batch_id,
        'scope': 'Albumblatt für Clara Schumann complete holograph manuscript',
        'authorization': 'User authorized continued reviewed Brahms batches.',
        'published': False,
        'files': [{
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
            'page_count': 2,
            'rendered_pages': 2,
            'technical_check': 'PDF header, SHA256, pypdf two-page parsing, Poppler rendering of both pages',
            'visual_check': 'checked_with_notes',
            'publication_note': 'PDF第1页为手稿正面，含题名、德语题词、Adagio单旋律及1868年9月12日日期；第2页为无音乐内容的背面空白五线纸。',
            'description_summary': '来源：IMSLP #374716；版本：勃拉姆斯1868年手稿（Mus.ms.autogr. Brahms, J. 10）；文件范围：PDF第1页为手稿正面，第2页为空白背面',
            'publication_approved': False,
        }],
    }
    inspection = {
        'label': 'Albumblatt für Clara Schumann 无伴奏独唱手稿',
        'checked_on': datetime.now().astimezone().date().isoformat(),
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'proposal_only': True,
        'publication_approved': False,
        'proposed_first_publication_ids': [FILE_ID],
        'source_notes': '实时IMSLP作品页确认Public Domain、Holograph manuscript, 1868、C major、voice及For unaccompanied voices。',
        'method': '保留原PDF字节；pypdf解析两页；Poppler以180dpi渲染两页；人工逐页放大核对题名、题词、旋律、日期、馆藏号及空白背面。',
        'metadata_changes': [
            {'imslp_id': FILE_ID, 'field': 'voice_types', 'before': '声乐', 'after': '独唱（无伴奏）', 'evidence': '实时IMSLP标注For 1 voice、For unaccompanied voices；谱面仅有单旋律与歌词，无伴奏。'},
            {'imslp_id': FILE_ID, 'field': 'language', 'before': '', 'after': '德语', 'evidence': '手稿正面歌词为“Hoch auf’m Berg, tief im Tal, grüß’ ich dich vieltausendmal”。'},
        ],
        'files': {FILE_ID: {'pages': 2, 'key': 'C大调', 'number': None, 'movement_start_pdf_pages': [1], 'titles': ['Albumblatt für Clara Schumann'], 'notes': '第1页完整手稿正面；第2页空白背面；无缺页或裁切异常。', 'publication_note': trial['files'][0]['publication_note']}},
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
