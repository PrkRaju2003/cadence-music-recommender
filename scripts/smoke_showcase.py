"""Verify the hosted recruiter flow without creating accounts or sending email."""
import argparse
import json
from urllib.error import HTTPError
from urllib.request import Request,urlopen

parser=argparse.ArgumentParser()
parser.add_argument('--base-url',default='https://cadence-prk.vercel.app')
args=parser.parse_args()
base=args.base_url.rstrip('/')


def get(path):
    with urlopen(base+path,timeout=30) as response:return json.load(response)


assert get('/api/health')['database']=='supabase-postgresql'
assert get('/api/config')['auth_required'] is True
assert get('/demo/api/config')['auth_required'] is False
users=get('/demo/api/users')
assert len(users)==40 and all('email' not in u for u in users)
one=get('/demo/api/recommendations/1')['items']
two=get('/demo/api/recommendations/2')['items']
assert len(one)==len(two)==6 and [r['id'] for r in one]!=[r['id'] for r in two]
analytics=get('/demo/api/analytics')
assert analytics['totals']['plays']==4480
assert analytics['totals']['listeners']==40
query=Request(base+'/demo/api/sql/run',data=json.dumps({'report_id':'catalog_summary','user_id':1,'limit':20}).encode(),headers={'Content-Type':'application/json','Origin':base})
with urlopen(query,timeout=30) as response:rows=json.load(response)['rows']
assert sum(row['tracks'] for row in rows)==24
for path in ['/api/users','/api/analytics','/api/recommendations/1']:
    try:get(path)
    except HTTPError as error:assert error.code==401
    else:raise AssertionError('Private route accessible without login: '+path)
with urlopen(Request(base+'/demo/media/1',headers={'Range':'bytes=0-43'}),timeout=30) as response:
    assert response.status==206 and response.read()[:4]==b'RIFF'
print(json.dumps({'url':base+'/demo/','status':'passed','synthetic_listeners':len(users),
    'seed_plays':analytics['totals']['plays'],'catalog_tracks':24,'recommendations_per_listener':6,
    'distinct_listener_recommendations':True,'sql_report':'passed','audio_range':'passed','private_routes':'401 as expected'},indent=2))
