"""Restore one missing score from public storage and verify its original bytes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def restore(public_id, root=ROOT, open_url=urlopen):
    def read(name):
        return json.loads((root / name).read_text(encoding='utf-8'))
    item = next(r for r in read('data.json') if r['public_id'] == public_id)
    entry = next(r for r in read('storage-manifest.json')['entries'] if r['public_id'] == public_id)
    relative = PurePosixPath(item['filename'])
    scores = (root / 'scores').resolve()
    target = (scores / relative).resolve()
    if relative.is_absolute() or '..' in relative.parts or '\\' in str(relative) or not target.is_relative_to(scores):
        raise ValueError('Score path escapes the local scores directory')
    if target.exists():
        if target.stat().st_size != entry['file_size'] or hashlib.sha256(target.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('Existing local file differs; refusing to overwrite it')
        return target
    origin = read('site-config.json')['scoreStorage']['baseUrl'].rstrip('/')
    parsed = urlsplit(origin)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError('Expected a public HTTPS storage origin')
    key = PurePosixPath(entry['storage_key'])
    if key.is_absolute() or '..' in key.parts or '\\' in str(key):
        raise ValueError('Invalid object key')
    target.parent.mkdir(parents=True, exist_ok=True)
    request = Request(origin + '/' + '/'.join(quote(part, safe='') for part in key.parts),
                      headers={'User-Agent': 'MaoTongMusic-ScoreRestore/1.0'})
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.restore-', suffix='.part', delete=False) as output:
            temporary = Path(output.name)
            h = hashlib.sha256()
            size = 0
            header = b''
            with open_url(request, timeout=60) as response:
                if response.status != 200:
                    raise ValueError('Storage did not return a complete PDF')
                for chunk in iter(lambda: response.read(1024 * 1024), b''):
                    if not header:
                        header = chunk[:5]
                    h.update(chunk)
                    size += len(chunk)
                    if size > entry['file_size']:
                        raise ValueError('Download exceeds the recorded size')
                    output.write(chunk)
            if header != b'%PDF-' or size != entry['file_size'] or h.hexdigest() != entry['sha256']:
                raise ValueError('Downloaded PDF fingerprint differs from the manifest')
        # Creating a link is atomic and fails if another process created target.
        os.link(temporary, target)
        return target
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('public_id')
    args = parser.parse_args()
    print(restore(args.public_id))
