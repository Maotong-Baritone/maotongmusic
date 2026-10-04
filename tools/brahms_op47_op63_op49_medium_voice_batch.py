"""Bounded eight-file batch for Brahms medium-voice songs from Opp.47, 49, and 63."""
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import brahms_late_piano_batch as workflow
from tools.publish_brahms_op116 import PublicationBatch


IDS = ('134615', '134616', '134617', '135131', '135132', '135133', '135457', '135864')
BATCH = PublicationBatch(
    ids=IDS,
    batch_id='brahms-op47-op49-op63-medium-voice-eight-20260927',
    stage_rel=Path('imports/johannes_brahms/staging/op47-op49-op63-medium-voice-singles'),
    work_titles=('5 Lieder, Op.47', '5 Lieder, Op.49', '9 Lieder and Songs, Op.63'),
    log_message='新增勃拉姆斯Op.47、Op.49与Op.63中音声部Peters独立歌曲谱8份；标题、编号、速度、德语及声乐与钢琴编制均已核对。',
    allowed_voice_types=('中音声部、钢琴',),
    allowed_categories=('艺术歌曲',),
)

# The source manifest still contains its deliberately uncorrected parser values
# until every original PDF has been staged.  Keep the download gate just as
# narrow as the publication gate while admitting only those recorded before
# values; publication continues to require the corrected value on ``BATCH``.
DOWNLOAD_BATCH = PublicationBatch(
    ids=IDS,
    batch_id=BATCH.batch_id,
    stage_rel=BATCH.stage_rel,
    work_titles=BATCH.work_titles,
    log_message=BATCH.log_message,
    allowed_voice_types=('声乐、钢琴', '中音声部'),
    allowed_categories=('艺术歌曲',),
)


def _source(root=workflow.ROOT):
    data = workflow.publication.read_json(root / workflow.publication.REVIEW_REL)
    by_id = {f['imslp_id']:(w, f) for w in data['works'] if w.get('title') in BATCH.work_titles for f in w['files'] if f['imslp_id'] in IDS}
    if set(by_id) != set(IDS):
        raise ValueError('Medium-voice source scope changed')
    return data, by_id


def correct_metadata_and_complete_manifest(root=workflow.ROOT):
    stage = root / BATCH.stage_rel
    review_path = root / workflow.publication.REVIEW_REL
    trial_path = stage / 'manifest.json'
    review_before = review_path.read_bytes()
    trial_before = trial_path.read_bytes()
    review, by_id = _source(root)
    trial = workflow.publication.read_json(trial_path)
    technical = {f['imslp_id']:f for f in trial['files']}
    if set(technical) != set(IDS):
        raise ValueError('Downloaded file scope changed')
    expected = {
        '134615':('艺术歌曲', '', '声乐、钢琴', '法语'),
        '134616':('艺术歌曲', '', '声乐、钢琴', '法语'),
        '134617':('艺术歌曲', '', '声乐、钢琴', '法语'),
        '135131':('艺术歌曲', '', '声乐、钢琴', '法语'),
        '135132':('艺术歌曲', '', '声乐、钢琴', '法语'),
        '135133':('艺术歌曲', '', '声乐、钢琴', '法语'),
        '135457':('艺术歌曲', '', '中音声部', '德语'),
        '135864':('艺术歌曲', '', '中音声部', '德语'),
    }
    for file_id, (_, source) in by_id.items():
        current = tuple(source[k] for k in ('category','sub_category','voice_types','language_cn'))
        if current != expected[file_id]:
            raise ValueError(f'Source metadata changed concurrently: {file_id}: {current!r}')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = root / 'backup' / 'import_metadata' / f'{BATCH.batch_id}-{stamp}'
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(review_path, backup / 'manifest.json')
    shutil.copy2(trial_path, backup / 'staging-manifest.json')
    changes = []
    completed = []
    for file_id in IDS:
        work, source = by_id[file_id]
        before_voice = source['voice_types']
        before_language = source['language_cn']
        source['voice_types'] = '中音声部、钢琴'
        source['language_cn'] = '德语'
        if before_voice != source['voice_types']:
            changes.append({'imslp_id':file_id,'field':'voice_types','before':before_voice,'after':'中音声部、钢琴','evidence':'实时IMSLP中音声部组及谱面均显示独唱声部与钢琴。'})
        if before_language != '德语':
            changes.append({'imslp_id':file_id,'field':'language','before':before_language,'after':'德语','evidence':'实时IMSLP作品页标示German，谱面歌词为德语。'})
        item = technical[file_id]
        completed.append({
            'imslp_id':file_id, 'public_id':source['public_id'],
            **{key:source[value] for key,value in workflow.publication.FIELD_MAP.items()},
            'movement_number':source['movement_number'], 'title_scope':source['title_scope'],
            'source_url':work['source_url'], 'publisher':source['publisher'], 'editor':source['editor'],
            'source_description':source['description'], 'copyright':source['copyright'],
            'handler_url':source['handler_url'], 'access_method':'wait_page',
            'local_path':item['local_path'], 'sha256':item['sha256'], 'bytes':(stage/item['local_path']).stat().st_size,
            'page_count':item['page_count'], 'technical_check':'PDF header, SHA256, pypdf page/content parsing, source-listed page count',
            'visual_check':'pending', 'publication_approved':False,
        })
    full_trial = {'batch_id':BATCH.batch_id,'scope':'Opp.47, 49, and 63 medium-voice Peters single songs',
                  'authorization':'User authorized continued reviewed Brahms batches.','published':False,'files':completed}
    review_after = workflow.publication.json_bytes(review)
    trial_after = workflow.publication.json_bytes(full_trial)
    workflow.publication.atomic_bytes(review_path, review_after)
    workflow.publication.atomic_bytes(trial_path, trial_after)
    receipt = {'batch_id':BATCH.batch_id,'recorded_at':datetime.now(timezone.utc).isoformat(),
               'source_manifest_before_sha256':hashlib.sha256(review_before).hexdigest(),
               'source_manifest_after_sha256':hashlib.sha256(review_after).hexdigest(),
               'staging_manifest_before_sha256':hashlib.sha256(trial_before).hexdigest(),
               'staging_manifest_after_sha256':hashlib.sha256(trial_after).hexdigest(),
               'backup':str(backup.relative_to(root)),'changes':changes}
    workflow.publication.atomic_bytes(stage/'metadata-corrections.json', workflow.publication.json_bytes(receipt))
    return receipt


def correct_titles_after_visual_review(root=workflow.ROOT):
    title_changes = {
        '135457': ('No. 5 Junge Liebe I. Lebhaft, Op. 63', 'No. 5 Meine Liebe ist grün. Lebhaft, Op. 63'),
        '135864': ('No. 8 Heimweh II. Etwas langsam, Op. 63', "No. 8 O wüsst' ich doch den Weg zurück. Etwas langsam, Op. 63"),
    }
    source_path = root / workflow.publication.REVIEW_REL
    stage_path = root / BATCH.stage_rel / 'manifest.json'
    receipt_path = root / BATCH.stage_rel / 'metadata-corrections.json'
    source_before = source_path.read_bytes()
    stage_before = stage_path.read_bytes()
    receipt_before = receipt_path.read_bytes()
    source, source_pairs = _source(root)
    source_by_id = {file_id: pair[1] for file_id, pair in source_pairs.items()}
    stage = workflow.publication.read_json(stage_path)
    stage_by_id = {item['imslp_id']: item for item in stage['files']}
    if set(stage_by_id) != set(IDS):
        raise ValueError('Downloaded file scope changed')
    for file_id in IDS:
        source_item = source_by_id[file_id]
        stage_item = stage_by_id[file_id]
        if tuple(source_item[key] for key in ('category', 'sub_category', 'voice_types', 'language_cn')) != (
            '艺术歌曲', '', '中音声部、钢琴', '德语'
        ):
            raise ValueError(f'Source metadata changed concurrently: {file_id}')
        if tuple(stage_item[key] for key in ('category', 'sub_category', 'voice_types', 'language')) != (
            '艺术歌曲', '', '中音声部、钢琴', '德语'
        ):
            raise ValueError(f'Staged metadata changed concurrently: {file_id}')
    for file_id, (before_title, _) in title_changes.items():
        if source_by_id[file_id]['proposed_title'] != before_title or stage_by_id[file_id]['title'] != before_title:
            raise ValueError(f'Title changed concurrently: {file_id}')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = root / 'backup' / 'import_metadata' / f'{BATCH.batch_id}-titles-{stamp}'
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source_path, backup / 'manifest.json')
    shutil.copy2(stage_path, backup / 'staging-manifest.json')
    prior_receipt = workflow.publication.read_json(receipt_path)
    changes = list(prior_receipt['changes'])
    for file_id, (before_title, after_title) in title_changes.items():
        source_by_id[file_id]['proposed_title'] = after_title
        source_by_id[file_id]['review_edited'] = True
        stage_by_id[file_id]['title'] = after_title
        changes.append({
            'imslp_id': file_id,
            'field': 'proposed_title',
            'before': before_title,
            'after': after_title,
            'evidence': '首份渲染谱面印有该独立标题；与同作品已上线低声部版的谱面命名一致。',
        })
    source_after = workflow.publication.json_bytes(source)
    stage_after = workflow.publication.json_bytes(stage)
    workflow.publication.atomic_bytes(source_path, source_after)
    workflow.publication.atomic_bytes(stage_path, stage_after)
    receipt = {
        'batch_id': BATCH.batch_id,
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'prior_receipt_sha256': hashlib.sha256(receipt_before).hexdigest(),
        'source_manifest_before_sha256': hashlib.sha256(source_before).hexdigest(),
        'source_manifest_after_sha256': hashlib.sha256(source_after).hexdigest(),
        'staging_manifest_before_sha256': hashlib.sha256(stage_before).hexdigest(),
        'staging_manifest_after_sha256': hashlib.sha256(stage_after).hexdigest(),
        'backup': str(backup.relative_to(root)),
        'changes': changes,
    }
    workflow.publication.atomic_bytes(receipt_path, workflow.publication.json_bytes(receipt))
    return receipt


def record_inspection(root=workflow.ROOT):
    stage = root / BATCH.stage_rel
    manifest = workflow.publication.read_json(stage/'manifest.json')
    by_id = {f['imslp_id']:f for f in manifest['files']}
    if set(by_id) != set(IDS):
        raise ValueError('Inspection scope changed')
    for file_id in IDS:
        item = by_id[file_id]
        item.update(rendered_pages=item['page_count'], visual_check='matched_title_key_and_instrumentation',
                    publication_note='', description_summary=f'来源：IMSLP #{file_id}；版本：Peters中音声部版；出版：N. Simrock / Edition Peters；编者：Max Friedlaender')
    workflow.publication.atomic_bytes(stage/'manifest.json', workflow.publication.json_bytes(manifest))
    inspection = {
        'label':'Op.47、Op.49与Op.63：Peters中音声部独立歌曲',
        'checked_on':datetime.now().astimezone().date().isoformat(), 'recorded_at':datetime.now(timezone.utc).isoformat(),
        'proposal_only':True, 'publication_approved':False, 'proposed_first_publication_ids':list(IDS),
        'source_notes':'实时IMSLP作品页确认三套作品为德语、Public Domain；八份均列于中音声部组。',
        'method':'保留原PDF字节；pypdf解析全部页面并校验SHA256；Poppler渲染全部页面；人工通览八份完整接触表并放大核对首尾、标题、编号、速度、德语、编制和异常页。',
        'rendering_note':'八份普通清晰单曲全部页面均已渲染；页序连续，标题与歌词可辨，末页完整结束，无异常或缺页。',
        'metadata_changes':workflow.publication.read_json(stage/'metadata-corrections.json')['changes'],
        'files':{file_id:{'pages':by_id[file_id]['page_count'],'key':'','number':by_id[file_id]['movement_number'],
                 'movement_start_pdf_pages':[1],'titles':[by_id[file_id]['title']],
                 'notes':f'{by_id[file_id]["title"]}；共{by_id[file_id]["page_count"]}页；完整接触表及首尾页检查通过。','publication_note':''} for file_id in IDS},
    }
    workflow.publication.atomic_bytes(stage/'inspection.json', workflow.publication.json_bytes(inspection))
    return inspection


def publish(execute=False):
    return workflow.publication.publish(batch=BATCH) if execute else workflow.publication.prepare(batch=BATCH)


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    dl=sub.add_parser('download'); dl.add_argument('--id',required=True,choices=IDS); dl.add_argument('--url',required=True); dl.add_argument('--observed-at',required=True)
    sub.add_parser('correct-metadata'); sub.add_parser('correct-titles'); sub.add_parser('record-inspection'); sub.add_parser('prepare'); sub.add_parser('publish')
    args=parser.parse_args()
    if args.command=='download':
        result=workflow.download(args.id,args.url,args.observed_at,batch=DOWNLOAD_BATCH)
    else:
        result = correct_metadata_and_complete_manifest() if args.command=='correct-metadata' else correct_titles_after_visual_review() if args.command=='correct-titles' else record_inspection() if args.command=='record-inspection' else publish(args.command=='publish')
    if result is not None:
        print(json.dumps(result if args.command not in ('prepare','publish') else {'count':len(result['planned']),'already_published':result['already_published']},ensure_ascii=True,indent=2))
