"""Bounded continuation: original scans and available singles for Opp.117–119.

Download URLs must already be visible after normal anonymous waiting. No
disclaimer resolver, credentials, CAPTCHA handling, or unbounded scraping.
Publication remains gated on complete rendering and recorded visual checks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools import publish_brahms_op116 as publication
from tools.stage_brahms_op116 import validate_url

IDS = ('84694','1515','1516','1517','84700','84747','1531','1532','1533','1534')
BATCH = publication.PublicationBatch(
    ids=IDS, batch_id='brahms-opp117-119-ten-20260902',
    stage_rel=Path('imports/johannes_brahms/staging/opp117-119'),
    work_titles=('3 Intermezzi, Op.117','6 Klavierstücke, Op.118','4 Klavierstücke, Op.119'),
    log_message='新增勃拉姆斯 Op.117、118、119 乐谱 10 份：3 份完整原始扫描版及 7 份独立单曲谱；单曲保留独立标题、Op.号、调性，编制统一为钢琴独奏。Op.118 完整谱附六首曲目目录，方便检索。',
)
STAGE = ROOT / BATCH.stage_rel


def source_record(file_id, root=ROOT, *, batch=BATCH):
    if file_id not in batch.ids:
        raise ValueError('File outside this explicitly bounded continuation batch')
    manifest = publication.read_json(root/publication.REVIEW_REL)
    matches = [(w,f) for w in manifest['works'] if w['title'] in batch.work_titles
               for f in w['files'] if f['imslp_id'] == file_id]
    if len(matches) != 1:
        raise ValueError('Source ID must identify exactly one approved-scope work')
    work, file = matches[0]
    if (file['copyright'] != 'Public Domain' or file['decision'] not in ('pending','approved')
            or file.get('warnings') or file['category'] not in batch.allowed_categories
            or file['voice_types'] not in batch.allowed_voice_types or not file.get('eligible')):
        raise ValueError('Review, rights, or instrumentation needs individual attention')
    return work, file


def download(file_id, url, observed_at, *, batch=BATCH, access_method='wait_page'):
    if access_method not in ('wait_page', 'direct_pdf_redirect'):
        raise ValueError('Unsupported source access observation')
    stage = (ROOT/batch.stage_rel).resolve()
    if not stage.is_relative_to((ROOT/'imports/johannes_brahms/staging').resolve()):
        raise ValueError('Batch staging directory outside import workspace')
    original_name = validate_url(file_id,url,allowed_ids=batch.ids)
    when = datetime.fromisoformat(observed_at)
    if when.tzinfo is None or when > datetime.now(timezone.utc):
        raise ValueError('A past timezone-aware released-link observation is required')
    work, source = source_record(file_id, batch=batch)
    manifest_path = stage/'manifest.json'
    manifest = publication.read_json(manifest_path) if manifest_path.exists() else {
        'batch_id':batch.batch_id,'scope':', '.join(batch.work_titles)+': '+', '.join(batch.allowed_voice_types)+'; original scans and available singles',
        'authorization':'User asked to continue uploading remaining Brahms works after approving the Op.116 example.',
        'published':False,'files':[],
    }
    if manifest['batch_id'] != batch.batch_id:
        raise ValueError('Staging directory belongs to a different publication batch')
    title = source['proposed_title']
    if source['title_scope'] == 'whole_work':
        title += ' - Breitkopf-Mandyczewski-scan'
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]','-',title).strip('. ') + f' - IMSLP{file_id}.pdf'
    target = stage/'pdfs'/name
    existing = next((f for f in manifest['files'] if f['imslp_id']==file_id),None)
    if existing or target.exists():
        if not existing or not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest()!=existing['sha256']:
            raise ValueError('Existing file or manifest changed; refusing overwrite')
        print(f'Already staged and verified: {file_id}')
        return
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary = target.with_suffix('.pdf.part')
    if temporary.exists():
        raise ValueError('Retained partial file requires inspection before retrying')
    request = Request(url,headers={'User-Agent':'MaoTongMusic-ReviewedBrahmsBatch/1.0','Referer':source['handler_url']})
    with urlopen(request,timeout=90) as response:
        validate_url(file_id,response.geturl(),allowed_ids=batch.ids)
        expected = response.headers.get('Content-Length')
        with temporary.open('xb') as output:
            first = response.read(65536)
            if not first.startswith(b'%PDF-'):
                raise ValueError('Not a PDF; no fallback download route will be attempted')
            output.write(first)
            while chunk := response.read(1024*1024):
                if output.tell()+len(chunk)>100*1024*1024:
                    raise ValueError('Unexpectedly large source PDF; stop for inspection')
                output.write(chunk)
        if expected and temporary.stat().st_size != int(expected):
            raise ValueError('Incomplete download; partial original retained')
    from pypdf import PdfReader
    with PdfReader(temporary) as reader:
        if reader.is_encrypted or not reader.pages:
            raise ValueError('Encrypted or empty PDF; no automatic rewriting')
        page_count = len(reader.pages)
        for page in reader.pages:
            _ = page.mediabox
            content = page.get_contents()
            if content is not None:
                content.get_data()
    expected_pages = re.search(r'(\d+)\s*(?:页|pages)',source['file_info'])
    if not expected_pages or page_count != int(expected_pages.group(1)):
        raise ValueError('Page count differs from the source listing')
    sha256 = hashlib.sha256(temporary.read_bytes()).hexdigest()
    os.replace(temporary,target)
    manifest['files'].append({
        'imslp_id':file_id,'public_id':source['public_id'],
        **{key:source[value] for key,value in publication.FIELD_MAP.items()},
        'movement_number':source['movement_number'],'title_scope':source['title_scope'],
        'source_url':work['source_url'],'publisher':source['publisher'],'editor':source['editor'],
        'source_description':source['description'],'copyright':source['copyright'],
        'handler_url':source['handler_url'],'observed_download_url':url,
        'access_method':access_method,
        **{('link_visible_after_wait_at' if access_method == 'wait_page' else 'direct_pdf_observed_at'):observed_at},
        'downloaded_at':datetime.now(timezone.utc).isoformat(),
        'actual_source_filename':original_name,'local_path':target.relative_to(stage).as_posix(),
        'sha256':sha256,'bytes':target.stat().st_size,'page_count':page_count,
        'technical_check':'PDF header, SHA256, pypdf page/content parsing, source-listed page count',
        'visual_check':'pending','publication_approved':False,
    })
    publication.atomic_bytes(manifest_path,publication.json_bytes(manifest))
    print(json.dumps({'id':file_id,'pages':page_count,'bytes':target.stat().st_size,'sha256':sha256},ensure_ascii=False),flush=True)


def verify_live(*, batch=BATCH):
    receipt = publication.read_json(ROOT/batch.stage_rel/'publication.json')
    for filename in ('data.json','logs.json'):
        request = Request('https://maotong.me/maotongmusic/'+filename,headers={
            'User-Agent':'MaoTongMusic-ReviewedPublication/1.0','Cache-Control':'no-cache'})
        with urlopen(request,timeout=45) as response:
            live = json.load(response)
        if live != publication.read_json(ROOT/filename):
            raise ValueError(f'Live {filename} differs from the locally committed publication')
    assert receipt['approved_ids'] == list(batch.ids)
    print(json.dumps({'live_verified':len(batch.ids),'batch_id':batch.batch_id,
                      'verified_at':datetime.now(timezone.utc).isoformat(timespec='seconds')},ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    download_parser = sub.add_parser('download')
    download_parser.add_argument('--id',required=True,choices=IDS)
    download_parser.add_argument('--url',required=True)
    download_parser.add_argument('--observed-at',required=True)
    publish_parser = sub.add_parser('publish')
    publish_parser.add_argument('--execute',action='store_true')
    sub.add_parser('verify-live')
    args = parser.parse_args()
    if args.command == 'download':
        download(args.id,args.url,args.observed_at)
    elif args.command == 'verify-live':
        verify_live()
    elif args.execute:
        publication.publish(batch=BATCH)
    else:
        plan = publication.prepare(batch=BATCH)
        print(json.dumps({'batch_id':BATCH.batch_id,'count':len(plan['planned']),
                          'already_published':plan['already_published'],
                          'files':[p['item']['title'] for p in plan['planned']]},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
