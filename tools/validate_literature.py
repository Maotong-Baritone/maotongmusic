"""Validate the separate literature catalog without modifying the score database."""
import argparse
import json
import re
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def validate(data,root=ROOT):
    errors=[]
    if data.get('schema_version')!=1:return ['Unsupported literature schema']
    for key in ['subjects','document_types']:
        ids=[v['id'] for v in data[key]]
        if len(ids)!=len(set(ids)):errors.append('Duplicate '+key)
    subjects={v['id'] for v in data['subjects']}
    types={v['id'] for v in data['document_types']}
    seen_ids=set();seen_hashes=set();people={}
    for doc in data['documents']:
        label=doc.get('title','<untitled>')
        try:
            id=str(uuid.UUID(doc['id']))
            assert id==doc['id'] and id not in seen_ids
            seen_ids.add(id)
            assert doc['title'] and doc['authors'] and doc['publisher'] and doc['edition']
            assert doc['document_type'] in types
            assert doc['subjects'] and set(doc['subjects'])<=subjects
            assert len(doc['subjects'])==len(set(doc['subjects']))
            assert isinstance(doc['is_translation'],bool)
            assert isinstance(doc['year'],int) and 1000<=doc['year']<=2100
            assert isinstance(doc['page_count'],int) and doc['page_count']>0
            assert isinstance(doc['file_size'],int) and doc['file_size']>0
            assert re.fullmatch(r'[0-9a-f]{64}',doc['sha256']) and doc['sha256'] not in seen_hashes
            seen_hashes.add(doc['sha256'])
            assert doc['storage_key']==f'literature/{id[:2]}/{id}.pdf'
            assert doc['cover']==f'img/literature/{id}.jpg' and (root/doc['cover']).is_file()
            assert doc['languages'] and all(isinstance(v,str) and v for v in doc['languages'])
            assert all(isinstance(v,str) and v for v in doc['tags'])
            for p in doc['authors']+doc['translators']+doc['related_composers']:
                assert p['id'] and p['name'] and re.fullmatch(r'[\w-]+',p['id'])
                assert p['id'] not in people or people[p['id']]==p['name'], 'Conflicting person labels'
                people[p['id']]=p['name']
            assert all(isinstance(c['pdf_page'],int) and 1<=c['pdf_page']<=doc['page_count'] for c in doc['contents'])
        except (KeyError,ValueError,AssertionError,TypeError) as exc:
            errors.append(label+': '+(str(exc) or 'Invalid bibliographic or storage data'))
    return errors


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--catalog',type=Path,default=ROOT/'literature.json');args=parser.parse_args()
    data=json.loads(args.catalog.read_text(encoding='utf-8'))
    errors=validate(data)
    print(json.dumps({'documents':len(data['documents']),'directions':len(data['subjects']),'errors':errors},ensure_ascii=False))
    raise SystemExit(bool(errors))


if __name__=='__main__':main()
