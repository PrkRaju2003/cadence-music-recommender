import httpx
import json
import pytest
from fastapi.testclient import TestClient

from cadence.cloud_api import create_supabase_app
from cadence.supabase import SupabaseGateway, SupabaseSettings


@pytest.fixture
def cloud():
    calls=[]
    def handle(request):
        calls.append(request)
        path=request.url.path
        if path.endswith('cadence_rate_limit'):
            return httpx.Response(200,json={'allowed':True,'limit':120,'remaining':119,'retry_after':60})
        if path=='/auth/v1/token':
            return httpx.Response(200,json={'access_token':'verified-test-token','refresh_token':'refresh-test-token','expires_in':3600})
        if path=='/auth/v1/signup':
            return httpx.Response(200,json={'user':{'id':'test-auth-id'}})
        if path=='/auth/v1/logout':
            return httpx.Response(204)
        if path=='/auth/v1/user':
            if request.headers.get('authorization')!='Bearer verified-test-token':
                return httpx.Response(401,json={'message':'Invalid token'})
            return httpx.Response(200,json={'id':'test-auth-id','email':'listener@example.test'})
        if path.endswith('cadence_profile'):
            return httpx.Response(200,json={'id':41,'display_name':'Sam','genre_ids':[1]})
        if path.endswith('cadence_start_session'):
            return httpx.Response(200,json={'id':'owned-session','user_id':41})
        if path.endswith('cadence_history'):
            return httpx.Response(200,json=[])
        if path.endswith('cadence_sql_report'):
            return httpx.Response(200,json=[{'genre':'Jazz','tracks':6,'albums':2}])
        if path.endswith('cadence_catalog'):
            return httpx.Response(200,json=[])
        return httpx.Response(200,json={})
    settings=SupabaseSettings('https://project.supabase.co','sb_publishable_test')
    gateway=SupabaseGateway(settings,httpx.MockTransport(handle))
    with TestClient(create_supabase_app(settings,gateway)) as client:
        yield client,calls


def sign_in(client):
    return client.post('/api/auth/login',json={'email':'listener@example.test','password':'test-password-only'})


def test_login_stores_tokens_only_in_httponly_cookies(cloud):
    client,calls=cloud
    response=sign_in(client)
    assert response.status_code==200
    assert response.json()=={'signed_in':True}
    cookies=response.headers.get_list('set-cookie')
    assert len(cookies)==2
    assert all('HttpOnly' in c and 'SameSite=lax' in c and 'Path=/api' in c for c in cookies)
    assert 'access_token' not in response.text
    assert client.get('/api/auth/session').json()['user']['id']==41


def test_anonymous_cannot_read_private_data(cloud):
    client,calls=cloud
    for path in ['/api/users','/api/users/41/history','/api/analytics','/api/recommendations/41','/api/sql/queries']:
        assert client.get(path).status_code==401
    assert not any('/rpc/' in str(r.url) and not r.url.path.endswith('cadence_rate_limit') for r in calls)


def test_forged_cookie_is_validated_by_supabase_auth(cloud):
    client,calls=cloud
    client.cookies.set('cadence_access','forged',path='/api')
    assert client.get('/api/users').status_code==401
    assert not any(r.url.path.endswith('cadence_profile') for r in calls)


def test_listener_id_cannot_impersonate_another_account(cloud):
    client,calls=cloud
    sign_in(client)
    assert client.get('/api/users/1/history').status_code==403
    assert client.get('/api/recommendations/1').status_code==403
    assert client.post('/api/sessions',json={'user_id':1}).status_code==403
    assert not any(r.url.path.endswith('cadence_start_session') for r in calls)
    assert client.post('/api/sessions',json={'user_id':41}).status_code==201


def test_signup_handles_email_confirmation_without_fake_login(cloud):
    client,calls=cloud
    response=client.post('/api/auth/signup',json={'email':'listener@example.test','password':'test-password-only','display_name':'Sam','genre_id':2})
    assert response.status_code==200
    assert response.json()['requires_confirmation'] is True
    assert not response.headers.get_list('set-cookie')


def test_verify_before_login_and_recover_an_account():
    settings=SupabaseSettings('https://project.supabase.co','sb_publishable_test')
    state={'confirmed':False,'password':'original-password'}

    def auth_provider(request):
        path=request.url.path
        if path.endswith('cadence_rate_limit'):
            return httpx.Response(200,json={'allowed':True,'limit':10,'remaining':9})
        body=json.loads(request.content)
        if path=='/auth/v1/signup':
            assert body['password']==state['password']
            # Even if the upstream provider returns tokens, signup never signs in.
            return httpx.Response(200,json={'access_token':'signup-token','refresh_token':'signup-refresh'})
        if path=='/auth/v1/resend':
            assert body=={'email':'listener@example.test','type':'signup'}
            return httpx.Response(200,json={})
        if path=='/auth/v1/recover':
            assert body=={'email':'listener@example.test'}
            return httpx.Response(200,json={})
        if path=='/auth/v1/user' and request.method=='PUT':
            if request.headers.get('authorization')!='Bearer recovery-test-token':
                return httpx.Response(403,json={'error_code':'bad_jwt'})
            state['password']=body['password']
            return httpx.Response(200,json={'id':'test-auth-id'})
        if path=='/auth/v1/token' and request.url.params.get('grant_type')=='password':
            if body['password']!=state['password']:
                return httpx.Response(400,json={'error_code':'invalid_credentials'})
            if not state['confirmed']:
                return httpx.Response(400,json={'error_code':'email_not_confirmed'})
            return httpx.Response(200,json={'access_token':'login-token','refresh_token':'login-refresh'})
        raise AssertionError(f'Unexpected request to {request.method} {path}')

    with TestClient(create_supabase_app(settings,SupabaseGateway(settings,httpx.MockTransport(auth_provider)))) as client:
        credentials={'email':'listener@example.test','password':'original-password'}
        signup=client.post('/api/auth/signup',json={**credentials,'display_name':'Sam'})
        assert signup.json()['requires_confirmation'] and 'set-cookie' not in signup.headers
        blocked=client.post('/api/auth/login',json=credentials)
        assert blocked.status_code==403 and blocked.json()['detail']['code']=='email_not_confirmed'
        assert 'set-cookie' not in blocked.headers
        email={'email':credentials['email']}
        assert client.post('/api/auth/resend',json=email).json()=={'accepted':True}

        state['confirmed']=True  # Supabase accepted the link in the email.
        assert client.post('/api/auth/recover',json=email).json()=={'accepted':True}
        expired=client.post('/api/auth/password',json={'recovery_token':'expired','password':'new-password'})
        assert expired.status_code==401 and expired.json()['detail']['code']=='recovery_expired'
        updated=client.post('/api/auth/password',json={'recovery_token':'recovery-test-token','password':'new-password'})
        assert updated.json()=={'updated':True} and 'set-cookie' not in updated.headers
        assert client.post('/api/auth/login',json=credentials).status_code==401
        signed_in=client.post('/api/auth/login',json={**email,'password':'new-password'})
        assert signed_in.json()=={'signed_in':True} and 'set-cookie' in signed_in.headers


def test_auth_validation_does_not_echo_passwords(cloud):
    client,_=cloud
    response=client.post('/api/auth/password',json={'recovery_token':'recovery-test-token','password':'short'})
    assert response.status_code==422
    assert 'short' not in response.text and 'recovery-test-token' not in response.text


def test_refresh_rotation_and_logout_clear_session(cloud):
    client,calls=cloud
    sign_in(client)
    assert client.post('/api/auth/refresh').status_code==200
    assert client.post('/api/auth/logout').status_code==200
    assert client.get('/api/auth/session').status_code==401


def test_cross_origin_writes_are_rejected_before_auth_call(cloud):
    client,calls=cloud
    response=client.post('/api/auth/login',headers={'Origin':'https://untrusted.example'},json={'email':'listener@example.test','password':'test-password-only'})
    assert response.status_code==403
    assert calls==[]


def test_sql_reports_are_allowlisted_and_bounded(cloud):
    client,calls=cloud
    sign_in(client)
    result=client.post('/api/sql/run',json={'report_id':'catalog_summary','limit':20})
    assert result.status_code==200
    assert result.json()['rows'][0]['genre']=='Jazz'
    assert client.post('/api/sql/run',json={'report_id':'DROP TABLE users','limit':20}).status_code==422
    assert client.post('/api/sql/run',json={'report_id':'top_tracks','limit':1000}).status_code==422


def test_https_cookies_are_secure():
    settings=SupabaseSettings('https://project.supabase.co','sb_publishable_test',True)
    transport=httpx.MockTransport(lambda req:httpx.Response(200,json={'allowed':True,'limit':120,'remaining':119,'retry_after':60} if req.url.path.endswith('cadence_rate_limit') else {'access_token':'t','refresh_token':'r','expires_in':3600}))
    with TestClient(create_supabase_app(settings,SupabaseGateway(settings,transport)),base_url='https://cadence.example') as client:
        response=sign_in(client)
        assert all('Secure' in c for c in response.headers.get_list('set-cookie'))


def test_progress_requires_verified_owner_and_uses_scoped_rpc(cloud):
    client,calls=cloud
    body={'session_id':'owned-session','track_id':1,'played_ms':5000,'event_key':'same-play','source':'catalog'}
    assert client.post('/api/playback/progress',json=body).status_code==401
    sign_in(client)
    assert client.post('/api/playback/progress',json=body).status_code==201
    request=next(r for r in calls if r.url.path.endswith('cadence_play_progress'))
    assert request.headers['authorization']=='Bearer verified-test-token'
    assert json.loads(request.content)['p_event_key']=='same-play'
