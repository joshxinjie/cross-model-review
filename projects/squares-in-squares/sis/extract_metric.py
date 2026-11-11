"""Extract the pinned code from an already downloaded public Kaggle kernel JSON."""
import argparse
import hashlib
import json
from pathlib import Path

from .metric import LOCK


def extract(path):
    payload = json.loads(Path(path).read_text())
    meta = payload['metadata']
    if meta['id'] != LOCK['kernel_id'] or meta['currentVersionNumber'] != LOCK['notebook_version']:
        raise ValueError('not the pinned official notebook version')
    notebook = json.loads(payload['blob']['sourceNullable'])
    code = '\n\n'.join(''.join(c['source']) for c in notebook['cells'] if c['cell_type'] == 'code')+'\n'
    if hashlib.sha256(code.encode()).hexdigest() != LOCK['source_sha256']:
        raise ValueError('source hash mismatch; do not silently update the pin')
    return code


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('download', type=Path)
    p.add_argument('output', type=Path)
    args = p.parse_args()
    source = extract(args.download)
    with args.output.open('x') as out:
        out.write(source)


if __name__ == '__main__':
    main()
