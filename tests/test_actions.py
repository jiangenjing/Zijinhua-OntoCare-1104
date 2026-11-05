from concurrent.futures import ThreadPoolExecutor
import copy
import json
import shutil
import sqlite3

from flask import Flask
import pytest

from ontocare.actions import DEFAULT_ACTOR, connect, execute, register
from ontocare.data import ROOT, rows
from ontocare.manager import snapshot


@pytest.fixture
def action_app(tmp_path):
    for name in ['actions', 'ontology', 'data']:
        shutil.copytree(ROOT / name, tmp_path / name)
    (tmp_path / 'local').mkdir()
    with sqlite3.connect(tmp_path / 'local/service.sqlite') as conn:
        for name in ['tickets', 'products', 'documents', 'orders', 'order_items', 'dealers']:
            conn.execute(f'CREATE TABLE {name} (id TEXT PRIMARY KEY, payload TEXT)')
            conn.executemany(f'INSERT INTO {name} VALUES (?,?)', [(str(i), json.dumps(r)) for i, r in enumerate(rows(name))])
    app = Flask(__name__)
    register(app, tmp_path)
    return app, tmp_path


def payload(key='request-001', ticket='ticket-003'):
    return {'actionType': 'submitForReview', 'idempotency_key': key,
            'parameters': {'ticket': {'objectType': 'SupportTicket', 'id': ticket}, 'reason': '核对主机与配件的物流记录'}}


def counts(root):
    with connect(root) as conn:
        return {name: conn.execute('SELECT count(*) FROM ' + name).fetchone()[0] for name in ['ticket_state', 'review_tasks', 'action_links', 'action_events', 'action_audit', 'action_receipts']}


def test_action_commits_real_edits_links_event_and_audit(action_app):
    app, root = action_app
    before = snapshot(root, 'candidate-1')
    original = rows('tickets', root)
    result = app.test_client().post('/api/actions/submit', json=payload())
    assert result.status_code == 200 and result.json['committed']
    assert result.json['before']['workflow_status'] == 'OPEN'
    assert result.json['after']['workflow_status'] == 'PENDING_REVIEW'
    assert result.json['event']['delivery'] == 'local_outbox'
    assert all(c['passed'] for c in result.json['checks'])
    assert set(counts(root).values()) == {1}
    assert rows('tickets', root) == original
    after = snapshot(root, 'candidate-1')
    assert len(after['nodes']) == len(before['nodes']) + 1
    assert any(l['source'] == 'ticket:ticket-003' and l['target'] == result.json['review_task']['id'] and l['relation'] == 'needs_review' for l in after['links'])
    ticket = next(n for n in after['nodes'] if n['id'] == 'ticket:ticket-003')
    assert ticket['properties']['workflow_status'] == 'PENDING_REVIEW'


def test_idempotent_replay_and_conflicting_key(action_app):
    app, root = action_app
    client = app.test_client()
    one = client.post('/api/actions/submit', json=payload()).json
    two = client.post('/api/actions/submit', json=payload()).json
    assert two['action_id'] == one['action_id'] and two['replayed']
    assert counts(root)['review_tasks'] == counts(root)['action_events'] == 1
    different = payload(); different['parameters']['reason'] = '另一个完全不同的复核理由'
    assert client.post('/api/actions/submit', json=different).status_code == 409
    assert counts(root)['review_tasks'] == 1


@pytest.mark.parametrize('actor', [dict(id='reader', roles=['Viewer'], purposes=['customer-service-review']), dict(id='agent', roles=['CustomerServiceAgent'], purposes=['other-purpose'])])
def test_permissions_use_server_identity_and_purpose(action_app, actor):
    app, root = action_app
    app.config['ONTOCARE_ACTION_ACTOR'] = actor
    result = app.test_client().post('/api/actions/submit', json=payload())
    assert result.status_code == 403 and result.json['error'] == 'permission_denied'
    assert counts(root)['review_tasks'] == counts(root)['ticket_state'] == 0
    assert counts(root)['action_audit'] == 1


def test_bad_reference_and_client_role_injection_rejected(action_app):
    app, root = action_app
    client = app.test_client()
    assert client.post('/api/actions/submit', json=payload(ticket='ticket-999')).status_code == 404
    forged = payload(); forged['roles'] = ['CustomerServiceSupervisor']
    assert client.post('/api/actions/submit', json=forged).status_code == 400
    wrong_type = payload(); wrong_type['parameters']['ticket']['objectType'] = 'Order'
    assert client.post('/api/actions/submit', json=wrong_type).status_code == 400
    assert counts(root)['ticket_state'] == 0


def test_mid_transaction_failure_rolls_back_every_business_change(action_app):
    app, root = action_app
    with connect(root) as conn:
        conn.execute("CREATE TRIGGER fail_event BEFORE INSERT ON action_events BEGIN SELECT RAISE(ABORT,'test event failure'); END")
    result = app.test_client().post('/api/actions/submit', json=payload())
    assert result.status_code == 503 and result.json['committed'] is False
    actual = counts(root)
    assert actual['action_audit'] == 1
    assert all(n == 0 for key, n in actual.items() if key != 'action_audit')


def test_concurrent_submissions_do_not_create_duplicate_open_tasks(action_app):
    _, root = action_app
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda key: execute(payload(key=key), copy.deepcopy(DEFAULT_ACTOR), root), ['parallel-001', 'parallel-002']))
    assert sorted(status for _, status in results) == [200, 409]
    assert counts(root)['review_tasks'] == counts(root)['action_events'] == 1


def test_cross_origin_and_external_requests_denied(action_app):
    app, root = action_app
    client = app.test_client()
    assert client.post('/api/actions/submit', json=payload(), headers={'Origin': 'https://example.com'}).status_code == 403
    assert client.post('/api/actions/submit', json=payload(), environ_base={'REMOTE_ADDR': '192.0.2.1'}).status_code == 403
    assert counts(root)['review_tasks'] == 0
