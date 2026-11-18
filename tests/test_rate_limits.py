import hashlib
import httpx
from fastapi.testclient import TestClient
from cadence.cloud_api import create_supabase_app
from cadence.supabase import SupabaseGateway, SupabaseSettings


def test_shared_quota_rejects_before_expensive_work_and_covers_demo():
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,json={'allowed':False,'limit':20,'remaining':0,'retry_after':17})
    settings=SupabaseSettings('https://project.supabase.co','sb_publishable_test')
    with TestClient(create_supabase_app(settings,SupabaseGateway(settings,httpx.MockTransport(handler)))) as client:
        for path in ['/api/recommendations/41','/demo/api/recommendations/1','/demo/media/1']:
            response=client.get(path)
            assert response.status_code==429
            assert response.headers['Retry-After']=='17'
            assert response.headers['Cache-Control']=='no-store'
    assert all(r.url.path.endswith('cadence_rate_limit') for r in calls)


def test_limiter_fails_closed_and_local_forwarded_headers_are_not_trusted(monkeypatch):
    monkeypatch.delenv('VERCEL',raising=False)
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(503,json={})
    settings=SupabaseSettings('https://project.supabase.co','sb_publishable_test')
    with TestClient(create_supabase_app(settings,SupabaseGateway(settings,httpx.MockTransport(handler)))) as client:
        response=client.get('/demo/api/users',headers={'x-vercel-forwarded-for':'spoof'})
        assert response.status_code==503 and response.headers['Retry-After']=='5'
    import json
    assert json.loads(calls[0].content)['p_subject']==hashlib.sha256(b'testclient').hexdigest()
