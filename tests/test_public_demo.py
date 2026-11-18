from fastapi.testclient import TestClient

from cadence.demo_api import create_demo_app


class DemoGateway:
    def __init__(self):self.calls=[]
    def rpc(self,name,token=None,payload=None):
        self.calls.append(name)
        if name=='demo_users':return [{'id':1,'display_name':'Synthetic A'},{'id':2,'display_name':'Synthetic B'}]
        if name=='catalog':return [{'id':i,'title':f'Track {i}','artist':'Demo','album_id':1,'album':'Demo album','genre_id':1,'genre':'Jazz','color':'#abcdef','duration_ms':12000} for i in [1,2,3]]
        if name=='demo_events':return [dict(id=i,user_id=1,session_id='s',track_id=i,played_at=str(i),completion=1) for i in [1,2]]
        if name=='demo_report':return [{'genre':'Jazz','tracks':3,'albums':1}]
        return {}


def test_showcase_needs_no_account_and_excludes_real_listener_ids():
    gateway=DemoGateway()
    with TestClient(create_demo_app(gateway)) as client:
        assert client.get('/api/config').json()['auth_required'] is False
        assert len(client.get('/api/users').json())==2
        assert client.get('/api/recommendations/1').status_code==200
        assert client.get('/api/recommendations/41').status_code==404
        assert client.post('/api/sql/run',json={'report_id':'top_tracks','user_id':41,'limit':20}).status_code==404


def test_guest_playback_does_not_write_to_private_database():
    gateway=DemoGateway()
    with TestClient(create_demo_app(gateway)) as client:
        session=client.post('/api/sessions',json={'user_id':1}).json()['id']
        response=client.post('/api/playback',json={'session_id':session,'track_id':1,'played_ms':5000,'event_key':'demo-test','source':'catalog'})
        assert response.status_code==201
        assert response.json()['stored'] is False
        assert client.post('/api/playback',json={'session_id':session,'track_id':1,'played_ms':13000,'event_key':'bad','source':'catalog'}).status_code==422
    assert 'record_play' not in gateway.calls and 'log_recommendations' not in gateway.calls


def test_demo_sql_is_real_report_contract_not_an_arbitrary_query():
    with TestClient(create_demo_app(DemoGateway())) as client:
        result=client.post('/api/sql/run',json={'report_id':'catalog_summary','user_id':1,'limit':20})
        assert result.json()['rows'][0]['tracks']==3
        assert client.post('/api/sql/run',json={'report_id':'SELECT secrets','user_id':1,'limit':20}).status_code==422
        audio=client.get('/media/1',headers={'Range':'bytes=0-43'})
        assert audio.status_code==206 and audio.content[:4]==b'RIFF'
