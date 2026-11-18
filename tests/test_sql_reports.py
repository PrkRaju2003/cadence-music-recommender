def test_local_sql_reports_execute_real_queries(client):
    result=client.post('/api/sql/run',json={'report_id':'catalog_summary','limit':20})
    assert result.status_code==200
    assert len(result.json()['rows'])==4
    assert sum(r['tracks'] for r in result.json()['rows'])==24
    top=client.post('/api/sql/run',json={'report_id':'top_tracks','limit':3}).json()
    assert top['row_count']==3
    assert all(r['plays']>0 for r in top['rows'])
    assert client.post('/api/sql/run',json={'report_id':'unknown','limit':3}).status_code==422
