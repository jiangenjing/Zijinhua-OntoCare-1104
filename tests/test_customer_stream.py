import json

from ontocare.customer_stream import stream_reply
from ontocare.prompting import contract


def frames(response):
    return [(part.splitlines()[0][7:], json.loads(part.splitlines()[1][6:]))
            for part in response.get_data(as_text=True).strip().split('\n\n')]


def test_stream_sends_only_validated_answer_and_evidence(app):
    class Service:
        def run(self, payload, on_event=None):
            assert payload['_customer_experience'] is True
            return {'zh': '已核验的答复。' * 8, 'session_id': 's1', 'trace_id': 't1', 'citations': []}
    with app.test_request_context():
        response = stream_reply(Service(), {'message': '测试'}, {'id': 'test'})
        events = frames(response)
    assert events[0][0] == 'status'
    assert [k for k, _ in events].index('evidence') < [k for k, _ in events].index('delta')
    assert ''.join(v['text'] for k, v in events if k == 'delta') == '已核验的答复。' * 8
    assert events[-1][0] == 'done'


def test_stream_failure_never_exposes_internal_exception(app):
    class Service:
        def run(self, payload, on_event=None):
            raise ValueError('private configuration')
    with app.test_request_context():
        events = frames(stream_reply(Service(), {}, {}))
    assert events[-1][0] == 'error'
    assert 'private configuration' not in str(events)
    assert not any(k in {'delta', 'done'} for k, _ in events)


def test_stream_uses_existing_input_validation(app):
    client = app.test_client()
    for payload in [{'message': ''}, {'message': 'test', 'context': {'unknown': 'x'}}, {'message': 'test', 'session_id': '../../x'}]:
        assert client.post('/api/chat/stream', json=payload).status_code == 400
    for language in ['fr', [], {}]:
        assert client.post('/api/chat/stream', json={'message': 'test', 'response_language': language}).status_code == 400


def test_real_progress_and_graph_arrive_before_validated_english_answer(app):
    class Service:
        def run(self, payload, on_event=None):
            on_event('identified', {'pn': 'T2353'})
            on_event('tool_completed', {'name': 'search_evidence'})
            on_event('context_ready', {'trace_id': 't2', 'retrieval': {
                'nodes': [{'id': 'pn:T2353', 'type': 'product_model', 'name': 'T2353'}], 'edges': []}})
            return {'zh': '中文答复', 'en': 'Verified answer.', 'session_id': 's2', 'trace_id': 't2'}
    with app.test_request_context():
        events = frames(stream_reply(Service(), {'response_language': 'en'}, {}))
    kinds = [kind for kind, _ in events]
    assert kinds.index('graph') < kinds.index('evidence') < kinds.index('delta')
    preview = next(data for kind, data in events if kind == 'graph')
    assert preview['graph']['nodes'][0]['id'] == 'pn:T2353'
    assert ''.join(data['text'] for kind, data in events if kind == 'delta') == 'Verified answer.'
    assert any(data.get('stage') == 'search_evidence' for kind, data in events if kind == 'status')


def test_customer_profile_is_separate_and_hashes_both_policies(test_root):
    original = contract('shipping', test_root)
    customer = contract('shipping', test_root, customer_experience=True)
    assert original['id'] == 'customer-service-v2'
    assert customer['id'] == 'customer-experience-v1'
    assert customer['system'].startswith(original['system'])
    assert customer['skill_text'].startswith(original['skill_text'])
    assert customer['system_sha256'] != original['system_sha256']
    assert customer['skill_sha256'] != original['skill_sha256']
