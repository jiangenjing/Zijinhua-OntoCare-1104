def test_feedback_requires_existing_matching_trace_and_valid_scores(app):
    client=app.test_client()
    reply=client.post('/api/chat',json={'message':'T2353 报错3212','mode':'offline'}).json
    payload={'trace_id':reply['trace_id'],'session_id':reply['session_id'],'resolved':True,'csat':5}
    assert client.post('/api/feedback',json={**payload,'csat':True}).status_code==400
    assert client.post('/api/feedback',json={**payload,'session_id':'wrong'}).status_code==404
    assert client.post('/api/feedback',json=payload).status_code==200
    client.post('/api/feedback',json={**payload,'resolved':False,'csat':2})
    summary=client.get('/api/feedback/summary').json
    assert summary['sessions_with_feedback']==1
    assert summary['resolution_responses']==1
    assert summary['demo_confirmed_resolution_rate']==0
    assert summary['demo_csat_top_two_rate']==0
    assert summary['actual_handoff_rate'] is None


def test_runtime_binding_is_shared_by_endpoint_and_actual_reply(app):
    client=app.test_client();runtime=client.get('/api/runtime').json
    reply=client.post('/api/chat',json={'message':'S1 Pro 不能用了','mode':'offline'}).json
    assert reply['runtime']==runtime
    assert runtime['agent']=='ontocare.agent.Agent'
    assert len(runtime['id'])==64
    assert 'api_key' not in str(runtime)
