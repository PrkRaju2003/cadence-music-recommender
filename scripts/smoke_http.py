"""Exercise a real server (including range audio) without test-only clients."""
import argparse
import json
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser()
parser.add_argument('--base-url', default='http://127.0.0.1:8000')
args = parser.parse_args()
base = args.base_url.rstrip('/')
for attempt in range(30):
    try:
        with urlopen(base + '/api/health', timeout=2) as response:
            assert json.load(response)['status'] == 'ok'
        break
    except (URLError, TimeoutError):
        if attempt == 29:
            raise
        time.sleep(1)
for path in ['/api/catalog','/api/recommendations/1','/api/analytics','/api/evaluation']:
    with urlopen(base + path, timeout=10) as response:
        data = json.load(response)
        assert data
with urlopen(Request(base + '/media/1', headers={'Range':'bytes=0-43'}), timeout=5) as response:
    assert response.status == 206
    assert response.read()[:4] == b'RIFF'
print('HTTP smoke passed: health, catalog, recommendations, analytics, evaluation, range audio.')
