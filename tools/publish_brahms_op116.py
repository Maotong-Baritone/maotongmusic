"""Publish only the eight explicitly confirmed Op.116 files.

Dry-run by default. R2 upload/public-byte verification precedes catalog writes.
Never deletes remote objects, edits original PDFs, or invokes git/deployment.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import score_storage as storage
from tools.sync_object_storage import S3Target

IDS = ('84692', '1524', '1525', '1526', '1527', '1528', '1529', '1530')
BATCH_ID = 'brahms-op116-reviewed-eight-20260902'
STAGE_REL = Path('imports/johannes_brahms/staging/op116')
REVIEW_REL = Path('imports/johannes_brahms/manifest.json')
FIELD_MAP = {'title':'proposed_title', 'work':'proposed_work', 'category':'category',
             'sub_category':'sub_category', 'voice_types':'voice_types',
             'tonality':'tonality', 'language':'language_cn'}


@dataclass(frozen=True)
class PublicationBatch:
    ids: tuple[str, ...]
    batch_id: str
    stage_rel: Path
    work_titles: tuple[str, ...]
    log_message: str
    allowed_voice_types: tuple[str, ...] = ('钢琴独奏',)
    allowed_categories: tuple[str, ...] = ('器乐独奏',)


OP116_BATCH = PublicationBatch(
    IDS, BATCH_ID, STAGE_REL, ('7 Fantasien, Op.116',),
    '新增勃拉姆斯《7 Fantasien, Op.116》乐谱 8 份：7 首独立单曲谱＋1 份完整原始扫描版；已核对单曲标题、调性与钢琴独奏编制。',
)


def digest(content):
    return hashlib.sha256(content).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def json_bytes(value, indent=2):
    return (json.dumps(value, ensure_ascii=False, indent=indent) + '\n').encode('utf-8')


def atomic_bytes(path, content):
    temp = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    with temp.open('xb') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def prepend_json(original, additions):
    """Keep all pre-existing catalog/log bytes after the opening bracket."""
    previous = json.loads(original.decode('utf-8-sig'))
    if not previous:
        return json_bytes(additions, 4)
    text = original.decode('utf-8')
    newline = '\r\n' if '\r\n' in text else '\n'
    opening = text.index('[') + 1
    block = json.dumps(additions, ensure_ascii=False, indent=4)[1:-1].strip('\n').replace('\n', newline)
    result = (text[:opening] + newline + block + ',' + text[opening:]).encode('utf-8')
    if json.loads(result) != additions + previous:
        raise ValueError('Prepending would change existing records')
    return result


def prepare(root=ROOT, *, batch=OP116_BATCH):
    root = Path(root)
    stage = root / batch.stage_rel
    if not stage.resolve().is_relative_to((root/'imports/johannes_brahms/staging').resolve()):
        raise ValueError('Batch staging path is outside the import staging directory')
    if not batch.ids or len(set(batch.ids)) != len(batch.ids):
        raise ValueError('Batch must contain unique source IDs')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*',batch.batch_id):
        raise ValueError('Unsafe publication batch identifier')
    review = read_json(root / REVIEW_REL)
    trial = read_json(stage / 'manifest.json')
    inspection = read_json(stage / 'inspection.json')
    if tuple(inspection.get('proposed_first_publication_ids', ())) != batch.ids:
        raise ValueError('The proposed publication scope changed; stop for review')
    works = [w for w in review['works'] if w.get('title') in batch.work_titles]
    if {w['title'] for w in works} != set(batch.work_titles):
        raise ValueError('Confirmed source work is missing')
    source_by_id = {f['imslp_id']:(w,f) for w in works for f in w['files']}
    trial_by_id = {f['imslp_id']:f for f in trial['files']}
    catalog = read_json(root / 'data.json')
    logs = read_json(root / 'logs.json')
    catalog_by_pid = {f['public_id']:f for f in catalog}
    hashes = {f['sha256']:f['public_id'] for f in read_json(root/'storage-manifest.json')['entries']}
    imslp_ids = {match.group(1) for f in catalog for match in re.finditer(r'IMSLP\s*#(\d+)', f.get('description',''))}
    next_id = max((int(f['id']) for f in catalog), default=0) + len(batch.ids)
    stamp = datetime.now().astimezone()
    planned = []
    seen_pids, seen_hashes = set(), set()
    for index, file_id in enumerate(batch.ids):
        work, source = source_by_id[file_id]
        staged = trial_by_id[file_id]
        if source['copyright'] != 'Public Domain' or staged['copyright'] != 'Public Domain':
            raise ValueError(f'Rights changed: #{file_id}')
        if source['decision'] not in ('pending','approved'):
            raise ValueError(f'Review decision excludes #{file_id}')
        if staged['category'] not in batch.allowed_categories:
            raise ValueError('Category outside the explicitly bounded batch')
        if staged['voice_types'] not in batch.allowed_voice_types:
            raise ValueError('Instrumentation outside the explicitly bounded batch')
        if staged['visual_check'] not in ('checked_with_notes','matched_title_key_and_instrumentation'):
            raise ValueError(f'PDF visual inspection missing: #{file_id}')
        if staged.get('rendered_pages') != staged['page_count']:
            raise ValueError(f'PDF rendering incomplete: #{file_id}')
        if any(staged[k] != source[v] for k,v in FIELD_MAP.items()):
            raise ValueError(f'Metadata changed after PDF review: #{file_id}')
        pid = str(uuid.UUID(source['public_id']))
        source_path = (stage / staged['local_path']).resolve()
        if not source_path.is_relative_to((stage/'pdfs').resolve()):
            raise ValueError('PDF path outside staging')
        content = source_path.read_bytes()
        if not content.startswith(b'%PDF-') or len(content) != staged['bytes'] or digest(content) != staged['sha256']:
            raise ValueError(f'PDF changed: #{file_id}')
        if pid in seen_pids or staged['sha256'] in seen_hashes:
            raise ValueError('Duplicate file within confirmed batch')
        seen_pids.add(pid)
        seen_hashes.add(staged['sha256'])
        existing = catalog_by_pid.get(pid)
        if existing:
            if existing.get('import_batch_id') != batch.batch_id or any(existing.get(k) != staged[k] for k in FIELD_MAP):
                raise ValueError(f'Existing public identifier conflicts: #{file_id}')
        elif file_id in imslp_ids or staged['sha256'] in hashes:
            raise ValueError(f'Existing source/content duplicate needs review: #{file_id}')
        filename = f"{staged['category']}/{pid}.pdf"
        target = root/'scores'/filename
        if target.exists() and (not existing or digest(target.read_bytes()) != staged['sha256']):
            raise ValueError(f'Refusing to overwrite local score: #{file_id}')
        description = f"来源：IMSLP #{file_id}；作品页：{work['source_url']}；版本：{source.get('description_en') or source['description']}；版权：Public Domain；出版信息：{source['publisher']}；编者：{source.get('editor','')}"
        if file_id == '84692':
            description += '；谱面核对：实际印刷页码 105–128（来源页写 pp.105–38），版号 J.B.64'
        elif staged.get('publication_note'):
            description += '；谱面核对：' + staged['publication_note']
        item = existing or {
            'id':next_id-index, 'public_id':pid,
            **{k:staged[k] for k in FIELD_MAP},
            'composer':review['composer'], 'voice_count':'',
            'description':description, 'filename':filename,
            'date':stamp.date().isoformat(), 'has_lyrics':False,
            'import_batch_id':batch.batch_id, 'source_imslp_id':file_id,
        }
        planned.append({'id':file_id,'item':copy.deepcopy(item),'source':source_path,
                        'target':target,'sha256':staged['sha256'],'exists':bool(existing)})
    present = sum(p['exists'] for p in planned)
    if present not in (0,len(batch.ids)):
        raise ValueError('Partial catalog publication detected; do not duplicate or guess recovery')
    batch_logs = [log for log in logs if log.get('batch_id') == batch.batch_id]
    if len(batch_logs) != (1 if present else 0):
        raise ValueError('Batch log/catalog mismatch requires recovery')
    return {'root':root,'stage':stage,'review':review,'trial':trial,'inspection':inspection,
            'catalog':catalog,'logs':logs,'planned':planned,'already_published':bool(present)}


def publish(root=ROOT, *, verify_public=True, batch=OP116_BATCH):
    root = Path(root)
    from dotenv import load_dotenv
    load_dotenv(root/'.env')
    from submission_store import init_database, sync_catalog
    plan = prepare(root, batch=batch)
    count = len(batch.ids)
    if plan['already_published']:
        print(f'Already published: {count} catalog records and one batch log; no changes')
        return
    backup = root/'backup/import_publications'/f'{batch.batch_id}-{datetime.now():%Y%m%d_%H%M%S_%f}'
    backup.mkdir(parents=True)
    relative_paths = [Path('data.json'),Path('logs.json'),Path('storage-manifest.json'),REVIEW_REL,
                      batch.stage_rel/'manifest.json',batch.stage_rel/'inspection.json']
    snapshots = {path:(root/path).read_bytes() for path in relative_paths}
    for path, content in snapshots.items():
        target = backup/path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    db_path = (root/os.environ.get('SUBMISSIONS_DB','submissions.db')).resolve()
    if not db_path.is_relative_to(root.resolve()):
        raise ValueError('Database is outside the current project')
    if db_path.exists():
        with sqlite3.connect(str(db_path)) as source_db, sqlite3.connect(str(backup/'submissions.db')) as backup_db:
            source_db.backup(backup_db)
    entries = [storage.manifest_entry_for(p['source'],public_id=p['item']['public_id'],
               catalog_filename=p['item']['filename'],sha256=p['sha256']) for p in plan['planned']]
    configuration = storage._configuration(force=True)
    target = S3Target(**vars(configuration))
    for entry in entries:
        if target.inspect(entry).status == 'different':
            raise ValueError(f'Refusing to overwrite conflicting remote object: {entry.storage_key}')
    print(f'Uploading the {count} confirmed PDFs and verifying storage metadata...',flush=True)
    result = storage.publish_entries(entries,force=True,workers=4)
    print(result.detail,flush=True)
    base_url = read_json(root/'site-config.json')['scoreStorage']['baseUrl'].rstrip('/')
    if base_url != 'https://scores.maotong.me':
        raise ValueError('Public download origin changed; verify before publishing')
    for p,entry in zip(plan['planned'],entries):
        if verify_public:
            request = Request(base_url+'/'+entry.storage_key, headers={
                'User-Agent':'MaoTongMusic-ReviewedPublication/1.0',
                'Accept':'application/pdf',
            })
            with urlopen(request,timeout=45) as response:
                content = response.read()
            if len(content) != entry.file_size or digest(content) != entry.sha256:
                raise ValueError('Public download does not match staged PDF')
        storage.apply_storage_metadata(p['item'],entry)
        print(f"Verified public PDF: IMSLP #{p['id']}",flush=True)
    for path,content in snapshots.items():
        if (root/path).read_bytes() != content:
            raise ValueError('Local metadata changed during upload; stop before catalog write')
    if any(p['target'].exists() for p in plan['planned']):
        raise ValueError('Local score target appeared during upload')
    timestamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    items = [p['item'] for p in plan['planned']]
    log = {'date':datetime.now().astimezone().strftime('%Y-%m-%d %H:%M'),'type':'add',
           'msg':batch.log_message,
           'batch_id':batch.batch_id,'count':count}
    for work in plan['review']['works']:
        for file in work['files']:
            if file['imslp_id'] in batch.ids:
                file.update(decision='approved',review_edited=True,published_at=timestamp,
                            publication_batch_id=batch.batch_id,publication_status='catalog_and_storage_published')
    for file in plan['trial']['files']:
        if file['imslp_id'] in batch.ids:
            file.update(publication_approved=True,published_at=timestamp,publication_batch_id=batch.batch_id)
    plan['trial'].update(published=True,published_count=count,publication_batch_id=batch.batch_id)
    plan['inspection'].update(proposal_only=False,publication_approved=True,
                              approved_at=timestamp,approved_publication_ids=list(batch.ids))
    candidate_manifest = backup/'storage-manifest.candidate.json'
    candidate_manifest.write_bytes(snapshots[Path('storage-manifest.json')])
    storage.update_manifest_entries(entries,candidate_manifest)
    outputs = {
        Path('data.json'):prepend_json(snapshots[Path('data.json')],items),
        Path('logs.json'):prepend_json(snapshots[Path('logs.json')],[log]),
        Path('storage-manifest.json'):candidate_manifest.read_bytes(),
        REVIEW_REL:json_bytes(plan['review']), batch.stage_rel/'manifest.json':json_bytes(plan['trial']),
        batch.stage_rel/'inspection.json':json_bytes(plan['inspection']),
    }
    written, copied = {}, []
    try:
        for p in plan['planned']:
            p['target'].parent.mkdir(parents=True,exist_ok=True)
            with p['target'].open('xb') as output, p['source'].open('rb') as source:
                shutil.copyfileobj(source,output)
            copied.append(p)
            if digest(p['target'].read_bytes()) != p['sha256']:
                raise ValueError('Local copy mismatch')
        for path,content in outputs.items():
            if (root/path).read_bytes() != snapshots[path]:
                raise ValueError('Concurrent local edit detected; refusing overwrite')
            atomic_bytes(root/path,content)
            written[path] = content
        init_database(db_path)
        sync_catalog(items+plan['catalog'],db_path)
    except Exception:
        for path,content in written.items():
            if (root/path).read_bytes() != content:
                raise RuntimeError(f'Concurrent edit during rollback: {path}; use backup {backup}')
            atomic_bytes(root/path,snapshots[path])
        for p in copied:
            if p['target'].exists() and digest(p['target'].read_bytes()) == p['sha256']:
                recovery = backup/'recovered_scores'/p['target'].name
                recovery.parent.mkdir(exist_ok=True)
                p['target'].rename(recovery)
        raise
    receipt = {
        'batch_id':batch.batch_id,'approved_ids':list(batch.ids),'approved_count':count,
        'storage_verified_count':count,'local_catalog_count':count,'website_published_count':0,
        'catalog_updated_at':timestamp,'website_status':'awaiting_deployment',
        'website_url':'https://maotong.me/maotongmusic/',
        'backup_directory':str(backup.relative_to(root)),
        'files':[{'imslp_id':p['id'],'public_id':p['item']['public_id'],
                  'filename':p['item']['filename'],'storage_key':entry.storage_key,
                  'sha256':entry.sha256} for p,entry in zip(plan['planned'],entries)],
    }
    atomic_bytes(plan['stage']/'publication.json',json_bytes(receipt))
    print(json.dumps({'published_locally':count,'storage_verified':count,'catalog_total':len(plan['catalog'])+count,
                      'homepage_log_added':1,'website_status':'awaiting_deployment'},ensure_ascii=False),flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args = parser.parse_args()
    if args.execute:
        publish()
    else:
        plan = prepare()
        print(json.dumps({'batch_id':BATCH_ID,'count':len(plan['planned']),
                          'already_published':plan['already_published'],
                          'files':[{'id':p['id'],'title':p['item']['title'],'public_id':p['item']['public_id'],
                                    'sha256':p['sha256']} for p in plan['planned']]},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
