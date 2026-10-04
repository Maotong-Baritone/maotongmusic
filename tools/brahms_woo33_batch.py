"""Bounded review and publication helper for Brahms's WoO 33 first edition."""
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

FILE_ID = '23200'
DUPLICATE_ID = '87938'
EXPECTED_SHA256 = '9597cada517ac947066cca30e7f18007e24cdbcb6a9a73efd61d395e46434b1f'
LOCAL_NAME = '49 Deutsche Volkslieder, WoO 33 - Simrock-first-edition - IMSLP23200.pdf'
BATCH = PublicationBatch(
    ids=(FILE_ID,),
    batch_id='brahms-woo33-first-edition-one-20260929',
    stage_rel=Path('imports/johannes_brahms/staging/woo33-first-edition'),
    work_titles=('49 Deutsche Volkslieder, WoO 33',),
    log_message='新增勃拉姆斯《49 Deutsche Volkslieder, WoO 33》西姆罗克初版完整谱1份；49首目录、七册结构、实际PDF起始页、德语歌词及第43–49首可选混声合唱编制均已逐页核对。',
    allowed_voice_types=('声乐、钢琴；第43–49首可加混声合唱',),
    allowed_categories=('声乐套曲',),
)

STARTS = [4,6,7,9,11,12,13,21,23,26,28,31,34,36,45,47,49,51,53,54,56,
          65,66,68,72,74,76,78,89,92,94,96,98,100,104,113,115,116,118,120,
          122,124,133,136,138,141,143,145,147]
TITLES = [
    "Sagt mir, o schönste Schäf'rin mein", "Erlaube mir, fein's Mädchen", "Gar lieblich hat sich gesellet",
    'Guten Abend', 'Die Sonne scheint nicht mehr', 'Da unten im Thale', 'Gunhilde',
    'Ach, englische Schäferin', 'Es war eine schöne Jüdin', 'Es ritt ein Ritter',
    'Jungfräulein, soll ich mit euch gehn', 'Feinsliebchen, du sollst mir nicht barfuss gehn',
    'Wach auf, mein Hort', 'Maria ging aus wandern', 'Schwesterlein', "Wach auf, mein' Herzensschöne",
    'Ach Gott, wie weh tut Scheiden', "So wünsch ich ihr ein' gute Nacht", 'Nur ein Gesicht auf Erden lebt',
    'Schönster Schatz, mein Engel', 'Es ging ein Maidlein zarte', 'Wo gehst du hin, du Stolze?',
    'Der Reiter', "Mir ist ein schön's braun's Maidelein", 'Mein Mädel hat einen Rosenmund',
    "Ach könnt' ich diesen Abend", 'Ich stand auf hohem Berge', "Es reit' ein Herr und auch sein Knecht",
    "Es war ein Markgraf über'm Rhein", "All' mein' Gedanken", 'Dort in den Weiden steht ein Haus',
    'So will ich frisch und fröhlich sein', 'Och Moder, ich well en Ding han',
    "We kumm' ich dann de Poots eren?", 'Soll sich der Mond nicht heller scheinen',
    'Es wohnet ein Fiedler', 'Du mein einzig Licht', "Des Abends kann ich nicht schlafen gehn",
    'Schöner Augen schöne Strahlen', "Ich weiss mir'n Maidlein", "Es steht ein' Lind'", 'In stiller Nacht',
    'Es stunden drei Rosen', 'Dem Himmel will ich klagen', 'Es sass ein schneeweiss Vögelein',
    'Es war einmal ein Zimmergesell', "Es ging sich uns're Fraue", 'Nachtigall, sag',
    'Verstohlen geht der Mond auf',
]


def prepare_review(root=ROOT):
    root = Path(root)
    stage = root / BATCH.stage_rel
    pdf = stage / 'pdfs' / LOCAL_NAME
    content = pdf.read_bytes()
    if not content.startswith(b'%PDF-') or hashlib.sha256(content).hexdigest() != EXPECTED_SHA256:
        raise ValueError('Reviewed PDF changed')
    if len(STARTS) != 49 or len(TITLES) != 49:
        raise ValueError('WoO 33 directory must contain 49 items')

    review_path = root / 'imports/johannes_brahms/manifest.json'
    before = review_path.read_bytes()
    review = json.loads(before.decode('utf-8-sig'))
    matches = [w for w in review['works'] if w.get('title') == BATCH.work_titles[0]]
    if len(matches) != 1:
        raise ValueError('Source work scope changed')
    work = matches[0]
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
        '49 Deutsche Volkslieder, WoO 33', '', '声乐套曲', '艺术歌曲',
        '声乐、钢琴', '', '英语', 'Public Domain', 'pending',
    ):
        raise ValueError(f'Source metadata changed concurrently: {source_expected!r}')
    duplicate_expected = (duplicate.get('description_en'), duplicate.get('copyright'), duplicate.get('decision'))
    if duplicate_expected != ('Complete Score', 'Public Domain', 'pending'):
        raise ValueError(f'Duplicate alternative changed concurrently: {duplicate_expected!r}')

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = root / 'backup/import_metadata' / f'{BATCH.batch_id}-{stamp}'
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(review_path, backup / 'manifest.json')
    source['language_cn'] = '德语'
    source['voice_types'] = '声乐、钢琴；第43–49首可加混声合唱'
    source['review_notes'] = '实时IMSLP与谱面均确认德语；第1–42首为声乐与钢琴，第43–49首可加混声合唱（SATB, ad lib）。'
    source['review_edited'] = True
    duplicate['decision'] = 'excluded'
    duplicate['skip_reason'] = '另一完整版本；本批选用西姆罗克约1894年初版完整扫描 #23200，避免重复发布。'
    duplicate['review_notes'] = '与#23200内容重复的Mandyczewski/Breitkopf后期全集版，本批不发布。'
    duplicate['review_edited'] = True
    after = json_bytes(review)
    atomic_bytes(review_path, after)

    directory = '；'.join(f'No.{i} {title}（PDF第{page}页）' for i, (title, page) in enumerate(zip(TITLES, STARTS), 1))
    page_map = (
        '七册合订：第1册PDF第1–16页（正文4–15）；第2册17–40页（正文21–37，38空白、39封底、40广告）；'
        '第3册41–60页（正文45–57，58空白、59封底、60广告）；第4册61–84页（正文65–81，82空白、83封底、84广告）；'
        '第5册85–108页（正文89–105，106空白、107封底、108广告）；第6册109–128页（正文113–125，126空白、127封底、128广告）；'
        '第7册129–152页（正文133–149，149含第43–49首歌词，150空白、151封底、152广告）。目录：' + directory
    )
    staged_file = {
        'imslp_id': FILE_ID, 'public_id': source['public_id'], 'title': source['proposed_title'],
        'work': source['proposed_work'], 'category': source['category'], 'sub_category': source['sub_category'],
        'voice_types': source['voice_types'], 'tonality': source['tonality'], 'language': source['language_cn'],
        'movement_number': source['movement_number'], 'title_scope': source['title_scope'],
        'source_url': work['source_url'], 'publisher': source['publisher'], 'editor': source['editor'],
        'source_description': source['description'], 'copyright': source['copyright'],
        'handler_url': source['handler_url'], 'access_method': 'wait_page', 'local_path': f'pdfs/{LOCAL_NAME}',
        'sha256': EXPECTED_SHA256, 'bytes': len(content), 'page_count': 152, 'rendered_pages': 152,
        'technical_check': 'PDF header, SHA256, pypdf 152-page parsing, Poppler rendering of all pages',
        'visual_check': 'checked_with_notes', 'publication_note': page_map,
        'description_summary': '来源：IMSLP #23200；版本：N. Simrock，约1894年初版，版号10206–10211、10218、10219；文件范围：49首德语民歌七册完整谱，第43–49首可加混声合唱',
        'publication_approved': False,
    }
    trial = {'batch_id': BATCH.batch_id, 'scope': '49 Deutsche Volkslieder, WoO 33 Simrock first edition complete score',
             'authorization': 'User authorized continued reviewed Brahms batches.', 'published': False, 'files': [staged_file]}
    changes = [
        {'imslp_id': FILE_ID, 'field': 'language_cn', 'before': '英语', 'after': '德语', 'evidence': '实时IMSLP标明German；谱面歌词为德语。'},
        {'imslp_id': FILE_ID, 'field': 'voice_types', 'before': '声乐、钢琴', 'after': '声乐、钢琴；第43–49首可加混声合唱', 'evidence': '实时IMSLP配置与谱面第43–49首SATB合唱声部一致。'},
        {'imslp_id': DUPLICATE_ID, 'field': 'decision', 'before': 'pending', 'after': 'excluded', 'evidence': '另一完整版本；选用#23200西姆罗克初版避免重复发布。'},
    ]
    inspection = {
        'label': '49 Deutsche Volkslieder, WoO 33 西姆罗克初版完整谱',
        'checked_on': datetime.now().astimezone().date().isoformat(), 'recorded_at': datetime.now(timezone.utc).isoformat(),
        'proposal_only': True, 'publication_approved': False, 'proposed_first_publication_ids': [FILE_ID],
        'source_notes': '实时IMSLP确认#23200为Public Domain、Complete Score、152页、西姆罗克约1894年初版；#87938为另一完整版本，排除以避免重复。',
        'method': '保留原PDF字节；pypdf解析152页；Poppler渲染全部页面；人工检查10张全页接触表并逐页原尺寸放大核对152页、49首题名与起始页、七册结构、德语歌词、编制及异常。',
        'full_size_review': 'completed_all_152_pages', 'metadata_changes': changes,
        'volume_page_ranges': [
            {'volume': 1, 'pdf_pages': '1–16', 'music_pages': '4–15'}, {'volume': 2, 'pdf_pages': '17–40', 'music_pages': '21–37'},
            {'volume': 3, 'pdf_pages': '41–60', 'music_pages': '45–57'}, {'volume': 4, 'pdf_pages': '61–84', 'music_pages': '65–81'},
            {'volume': 5, 'pdf_pages': '85–108', 'music_pages': '89–105'}, {'volume': 6, 'pdf_pages': '109–128', 'music_pages': '113–125'},
            {'volume': 7, 'pdf_pages': '129–152', 'music_pages': '133–149'},
        ],
        'files': {FILE_ID: {'pages': 152, 'key': '', 'number': None, 'movement_start_pdf_pages': STARTS,
                             'titles': [f'No.{i} {t}' for i, t in enumerate(TITLES, 1)],
                             'notes': '七册及49首连续完整；第43–49首为声乐、混声合唱（可选）与钢琴；仅见来源铅笔标记，无缺页、错序或裁切异常。',
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
