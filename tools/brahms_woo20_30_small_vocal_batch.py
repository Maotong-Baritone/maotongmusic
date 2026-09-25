"""Bounded nine-file batch for Brahms's small WoO vocal works."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from tools import brahms_late_piano_batch as workflow
from tools.publish_brahms_op116 import PublicationBatch


IDS = ('102714', '85498', '85506', '102768', '102763', '102770',
       '102716', '102772', '102718')
WORK_TITLES = (
    'Dem dunkeln Schoß der heilgen Erde, WoO 20',
    'Mondnacht, WoO 21',
    'Regenlied, WoO 23',
    'Grausam erweiset sich Amor, WoO 24',
    'Mir lächelt kein Frühling, WoO 25',
    'O wie sanft!, WoO 26',
    'Töne, lindernder Klang, WoO 28',
    'Wann?, WoO 29',
    'Zu Rauch, WoO 30',
)
BATCH = PublicationBatch(
    ids=IDS,
    batch_id='brahms-woo20-30-small-vocal-nine-20260925',
    stage_rel=Path('imports/johannes_brahms/staging/woo20-30-small-vocal'),
    work_titles=WORK_TITLES,
    log_message='新增勃拉姆斯WoO 20、21、23–26、28–30短小声乐作品谱9份；七份无伴奏合唱/卡农与两份艺术歌曲的题名、调性、德语及实际编制均已核对。',
    allowed_voice_types=('混声合唱', '女声合唱', '声乐、钢琴'),
    allowed_categories=('合唱作品', '艺术歌曲'),
)

VOICE_CORRECTIONS = {
    '102768': ('四重唱', '女声合唱'),
    '102763': ('四重唱', '女声合唱'),
    '102770': ('四重唱', '女声合唱'),
    '102716': ('四重唱', '混声合唱'),
    '102772': ('二重唱', '女声合唱'),
    '102718': ('四重唱', '混声合唱'),
}


def apply_source_metadata_corrections(root=workflow.ROOT):
    """Apply only the live-page-supported instrumentation corrections."""
    source_path = root / workflow.publication.REVIEW_REL
    before_bytes = source_path.read_bytes()
    source = workflow.publication.read_json(source_path)
    by_id = {
        item['imslp_id']: item
        for work in source['works'] if work.get('title') in BATCH.work_titles
        for item in work['files'] if item['imslp_id'] in BATCH.ids
    }
    if set(by_id) != set(IDS):
        raise ValueError('WoO small-vocal correction scope changed')
    for file_id, item in by_id.items():
        if (item['copyright'] != 'Public Domain' or not item.get('eligible')
                or item.get('warnings') or item['decision'] != 'pending'):
            raise ValueError(f'Review state changed for #{file_id}')
        if item['category'] not in BATCH.allowed_categories:
            raise ValueError(f'Category changed for #{file_id}')
    for file_id, (expected, _) in VOICE_CORRECTIONS.items():
        if by_id[file_id]['voice_types'] != expected:
            raise ValueError(f'Instrumentation changed concurrently for #{file_id}')
    if by_id['102714']['voice_types'] != '混声合唱':
        raise ValueError('WoO 20 instrumentation changed concurrently')
    for file_id in ('85498', '85506'):
        if by_id[file_id]['voice_types'] != '声乐、钢琴':
            raise ValueError(f'Art-song instrumentation changed for #{file_id}')

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = root / 'backup' / 'import_metadata' / f'{BATCH.batch_id}-{stamp}'
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source_path, backup / 'manifest.json')
    changes = []
    evidence = {
        '102768': 'Live IMSLP instrumentation: female chorus.',
        '102763': 'Live IMSLP instrumentation: female chorus.',
        '102770': 'Live IMSLP instrumentation: female chorus (SSAA).',
        '102716': 'Live IMSLP instrumentation: mixed chorus (SATB).',
        '102772': 'Live IMSLP instrumentation: female chorus.',
        '102718': 'Live IMSLP instrumentation: mixed chorus (SATB).',
    }
    for file_id, (old, new) in VOICE_CORRECTIONS.items():
        by_id[file_id]['voice_types'] = new
        changes.append({'imslp_id': file_id, 'field': 'voice_types',
                        'before': old, 'after': new, 'evidence': evidence[file_id]})
    after_bytes = workflow.publication.json_bytes(source)
    workflow.publication.atomic_bytes(source_path, after_bytes)
    receipt = {
        'batch_id': BATCH.batch_id,
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'source_manifest_before_sha256': hashlib.sha256(before_bytes).hexdigest(),
        'source_manifest_after_sha256': hashlib.sha256(after_bytes).hexdigest(),
        'backup': str(backup.relative_to(root)),
        'changes': changes,
    }
    workflow.publication.atomic_bytes(
        root / BATCH.stage_rel / 'metadata-corrections.json',
        workflow.publication.json_bytes(receipt),
    )
    return receipt


def download_observed(root=workflow.ROOT):
    observed = workflow.publication.read_json(root / BATCH.stage_rel / 'observed-links.json')
    records = {item['imslp_id']: item for item in observed.get('files', [])}
    if set(records) != set(IDS):
        raise ValueError('Observed-link scope differs from bounded batch')
    observed_at = observed['observed_at']
    for file_id in IDS:
        workflow.download(file_id, records[file_id]['download_url'], observed_at,
                          batch=BATCH, access_method='wait_page')


def record_inspection(root=workflow.ROOT):
    """Record the completed all-page visual inspection for this exact batch."""
    stage = root / BATCH.stage_rel
    manifest_path = stage / 'manifest.json'
    manifest = workflow.publication.read_json(manifest_path)
    by_id = {item['imslp_id']: item for item in manifest['files']}
    if tuple(by_id) != IDS:
        raise ValueError('Staging scope changed before inspection receipt')
    notes = {
        '102714': ('正文始于PDF第1页；作品在第2页上半结束，同页下半接《Töne, lindernder Klang》。',
                   '来源：IMSLP #102714；Breitkopf & Härtel《Sämtliche Werke》第21卷，Mandyczewski编；正文始于PDF第1页，第2页同页接后续作品。'),
        '85498': ('正文始于PDF第1页并在第2页完整结束。',
                  '来源：IMSLP #85498；Breitkopf & Härtel《Sämtliche Werke》第26卷，Mandyczewski编。'),
        '85506': ('正文始于PDF第1页并在第2页完整结束。',
                  '来源：IMSLP #85506；Breitkopf & Härtel《Sämtliche Werke》第26卷，Mandyczewski编。'),
        '102768': ('PDF第1页上半为《Mir lächelt kein Frühling》结尾；本作始于同页下半，按原版卡农排印完整收录。',
                   '来源：IMSLP #102768；Breitkopf & Härtel《Sämtliche Werke》第21卷，Mandyczewski编；本作始于PDF第1页下半。'),
        '102763': ('正文始于PDF第1页；作品在第2页上半结束，同页下半接《Grausam erweiset sich Amor》。',
                   '来源：IMSLP #102763；Breitkopf & Härtel《Sämtliche Werke》第21卷，Mandyczewski编；正文始于PDF第1页，第2页同页接后续作品。'),
        '102770': ('正文始于PDF第1页，按原版一页卡农排印完整收录。',
                   '来源：IMSLP #102770；Breitkopf & Härtel《Sämtliche Werke》第21卷，Mandyczewski编。'),
        '102716': ('PDF第1页上半为《Dem dunkeln Schoß der heilgen Erde》结尾；本作始于同页下半，在第2页上半结束，同页下半接《Zu Rauch》。',
                   '来源：IMSLP #102716；Breitkopf & Härtel《Sämtliche Werke》第21卷，Mandyczewski编；本作始于PDF第1页下半，第2页同页接后续作品。'),
        '102772': ('本作位于PDF第1页上半；同页下半另收《Spruch, WoO 27》。',
                   '来源：IMSLP #102772；Breitkopf & Härtel《Sämtliche Werke》第21卷，Mandyczewski编；本作位于PDF第1页上半。'),
        '102718': ('PDF第1页上半为《Töne, lindernder Klang》结尾；本作始于同页下半，按原版卡农排印完整收录。',
                   '来源：IMSLP #102718；Breitkopf & Härtel《Sämtliche Werke》第21卷，Mandyczewski编；本作始于PDF第1页下半。'),
    }
    files = {}
    for file_id in IDS:
        item = by_id[file_id]
        item['rendered_pages'] = item['page_count']
        item['visual_check'] = 'checked_with_notes'
        item['publication_note'] = notes[file_id][0]
        item['description_summary'] = notes[file_id][1]
        item['publication_approved'] = False
        files[file_id] = {
            'pages': item['page_count'], 'key': item['tonality'],
            'movement_start_pdf_pages': [1], 'titles': [item['title']],
            'notes': notes[file_id][0], 'publication_note': notes[file_id][0],
        }
    workflow.publication.atomic_bytes(manifest_path, workflow.publication.json_bytes(manifest))
    receipt = {
        'label': 'WoO 20、21、23–26、28–30：短小声乐作品',
        'checked_on': datetime.now().astimezone().date().isoformat(),
        'recorded_at': datetime.now(timezone.utc).isoformat(),
        'proposal_only': True, 'publication_approved': False,
        'proposed_first_publication_ids': list(IDS),
        'source_notes': '实时IMSLP作品页确认九份均为Public Domain；七份无伴奏合唱或卡农、两份德语声乐与钢琴艺术歌曲。',
        'method': '保留原PDF字节；pypdf解析全部14页并校验SHA256；Poppler渲染全部页面；人工逐页放大核对题名、调性、德语、编制、页序及同页相邻作品。',
        'rendering_note': '九份清晰原扫描共14页，文字与谱面可读；短卡农依原版跨作品同页排印，实际起始位置和相邻内容已逐份记录。',
        'metadata_changes': workflow.publication.read_json(stage/'metadata-corrections.json')['changes'],
        'files': files,
    }
    workflow.publication.atomic_bytes(stage/'inspection.json', workflow.publication.json_bytes(receipt))
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('correct-source-metadata')
    sub.add_parser('download-observed')
    sub.add_parser('record-inspection')
    args = parser.parse_args()
    if args.command == 'correct-source-metadata':
        print(json.dumps(apply_source_metadata_corrections(), ensure_ascii=False, indent=2))
    elif args.command == 'download-observed':
        download_observed()
    else:
        print(json.dumps(record_inspection(), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
