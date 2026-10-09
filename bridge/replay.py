#!/usr/bin/env python3
"""Offline-only replay; never starts agy. Does not overwrite original artifacts."""
import argparse
import json
from pathlib import Path
from bridge_core import Failure, adjudicate, decode, encode, make_reply, validate_request

p = argparse.ArgumentParser()
p.add_argument('run_directory')
a = p.parse_args()
d = Path(a.run_directory)
try:
    sources = validate_request(decode((d/'request.json').read_bytes()))
    verdict = decode((d/'verdict.json').read_bytes())
    if (d/'process.json').exists() and not decode((d/'process.json').read_bytes()).get('capture_complete'):
        raise Failure('INCOMPLETE_CAPTURE')
    # Partial captures from cancelled/limited processes must never be upgraded to success.
    if verdict.get('error') in ('CANCELLED', 'TIMEOUT', 'OUTPUT_LIMIT', 'CLEANUP_TIMEOUT', 'INTERNAL_ERROR'):
        raise Failure('INCOMPLETE_CAPTURE')
    result = adjudicate((d/'stdout.ndjson').read_bytes(), (d/'stderr.bin').read_bytes(), verdict['returncode'], sources)
    print(encode(make_reply(d.name, result)).decode('utf-8'))
except Failure as e:
    print(json.dumps({'ok': False, 'error': e.code}))
    raise SystemExit(1)
