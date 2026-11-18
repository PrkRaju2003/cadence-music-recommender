"""Validate PBIR files against Microsoft's official JSON schemas.

Requires network on the first run; cached schemas are reused afterward.
This checks report JSON structure, not Desktop rendering or DAX execution.
"""
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

from jsonschema import Draft7Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / '.cache/pbi-schemas'
CACHE.mkdir(parents=True, exist_ok=True)


def retrieve(uri):
    if not uri.startswith('https://developer.microsoft.com/json-schemas/'):
        raise ValueError('Unexpected schema host: ' + uri)
    key = hashlib.sha256(uri.encode()).hexdigest() + '.json'
    path = CACHE / key
    if not path.exists():
        url = uri.replace('https://developer.microsoft.com/json-schemas/',
                          'https://raw.githubusercontent.com/microsoft/json-schemas/main/')
        path.write_bytes(urlopen(url, timeout=30).read())
    contents = json.loads(path.read_text())
    return Resource.from_contents(contents, default_specification=DRAFT7)


registry = Registry(retrieve=retrieve)
count = 0
for path in sorted((ROOT / 'powerbi').rglob('*')):
    if not path.is_file() or path.suffix not in {'.json','.pbip','.pbir','.pbism'}:
        continue
    document = json.loads(path.read_text())
    uri = document.get('$schema')
    if not uri:
        continue
    schema = retrieve(uri).contents
    validator = Draft7Validator(schema, registry=registry)
    errors = list(validator.iter_errors(document))
    if errors:
        raise SystemExit(str(path.relative_to(ROOT)) + '\n' + '\n'.join(str(e) for e in errors))
    count += 1
print(f'Validated {count} Power BI JSON files against Microsoft schemas.')
