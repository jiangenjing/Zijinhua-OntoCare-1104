"""One registered local ActionType, with atomic edits and an event outbox."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid

from flask import Blueprint, current_app, jsonify, request
import jsonschema

from .data import digest, load_json, rows


SCHEMA = {
    'type': 'object', 'required': ['actionType', 'parameters', 'idempotency_key'], 'additionalProperties': False,
    'properties': {
        'actionType': {'const': 'submitForReview'},
        'idempotency_key': {'type': 'string', 'pattern': '^[A-Za-z0-9_-]{8,100}$'},
        'parameters': {'type': 'object', 'required': ['ticket', 'reason'], 'additionalProperties': False,
                       'properties': {'ticket': {'type': 'object', 'required': ['objectType', 'id'], 'additionalProperties': False,
                                                 'properties': {'objectType': {'const': 'SupportTicket'}, 'id': {'type': 'string', 'pattern': '^ticket-[0-9]{3}$'}}},
                                      'reason': {'type': 'string', 'minLength': 6, 'maxLength': 1000}}},
    },
}
DEFAULT_ACTOR = {'id': 'local-operator', 'roles': ['CustomerServiceAgent'], 'purposes': ['customer-service-review']}


class ActionError(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status


def connect(root):
    conn = sqlite3.connect(Path(root) / 'local/actions.sqlite', timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def initialize(root):
    with connect(root) as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS ticket_state (ticket_id TEXT PRIMARY KEY, workflow_status TEXT NOT NULL, revision INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS review_tasks (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS action_links (id TEXT PRIMARY KEY, source TEXT NOT NULL, target TEXT NOT NULL, relation TEXT NOT NULL, action_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS action_events (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS action_audit (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS action_receipts (actor_id TEXT, request_key TEXT, request_hash TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(actor_id,request_key));
        ''')


def runtime(root):
    if not (Path(root) / 'local/actions.sqlite').exists():
        return {'states': [], 'tasks': [], 'links': []}
    with connect(root) as conn:
        conn.execute('BEGIN')
        return {'states': [dict(r) for r in conn.execute('SELECT * FROM ticket_state')],
                'tasks': [json.loads(r[0]) for r in conn.execute('SELECT payload FROM review_tasks')],
                'links': [dict(r) for r in conn.execute('SELECT * FROM action_links')]}


def execute(payload, actor, root):
    specification = load_json(Path(root) / 'actions/submit-review.json')
    now = datetime.now(timezone.utc).isoformat()
    action_id = 'action-' + uuid.uuid4().hex
    checks, before = [], None
    conn = connect(root)
    try:
        conn.execute('BEGIN IMMEDIATE')
        try:
            jsonschema.validate(payload, SCHEMA)
        except jsonschema.ValidationError:
            raise ActionError('invalid_parameters', '参数不符合动作定义：请提供工单引用、至少 6 字的复核理由和幂等键。') from None
        if len(payload['parameters']['reason'].strip()) < 6:
            raise ActionError('invalid_reason', '请填写至少 6 个非空白字符的复核理由。')
        # Identity and purpose are supplied by the server, never by request roles.
        allowed = bool(set(actor.get('roles', [])) & set(specification['permissions']['roles'])) and specification['permissions']['purpose'] in actor.get('purposes', [])
        if not allowed:
            raise ActionError('permission_denied', '当前服务端操作员没有此角色或用途权限。', 403)
        request_hash = digest(payload)
        existing = conn.execute('SELECT request_hash,payload FROM action_receipts WHERE actor_id=? AND request_key=?', (actor['id'], payload['idempotency_key'])).fetchone()
        if existing:
            if existing['request_hash'] != request_hash:
                raise ActionError('idempotency_conflict', '同一个幂等键不能用于不同参数。', 409)
            conn.rollback()
            return {**json.loads(existing['payload']), 'replayed': True}, 200
        ticket_id = payload['parameters']['ticket']['id']
        if not any(t['id'] == ticket_id for t in rows('tickets', root)):
            raise ActionError('ticket_not_found', '工单不存在。', 404)
        checks.append({'rule': 'ticket_exists', 'passed': True, 'reason': '工单引用命中本地原始工单记录。'})
        state = conn.execute('SELECT * FROM ticket_state WHERE ticket_id=?', (ticket_id,)).fetchone()
        before = dict(state) if state else {'ticket_id': ticket_id, 'workflow_status': 'OPEN', 'revision': 0}
        if before['workflow_status'] not in specification['validation'][1]['allowed']:
            raise ActionError('invalid_state', '工单当前状态不允许重复提交复核。', 409)
        checks.append({'rule': 'ticket_status_allowed', 'passed': True, 'reason': '当前本地处理状态为 ' + before['workflow_status'] + '，允许提交。'})
        tasks = [json.loads(r[0]) for r in conn.execute('SELECT payload FROM review_tasks')]
        if any(t['ticket_id'] == ticket_id and t['status'] == 'OPEN' for t in tasks):
            raise ActionError('review_already_open', '工单已有待处理复核任务。', 409)
        checks.append({'rule': 'no_open_review', 'passed': True, 'reason': '没有重复的待处理复核任务。'})
        task = {'id': 'review-' + uuid.uuid4().hex, 'ticket_id': ticket_id, 'reason': payload['parameters']['reason'].strip(),
                'status': 'OPEN', 'created_at': now, 'created_by': actor['id'], 'action_id': action_id}
        after = {'ticket_id': ticket_id, 'workflow_status': 'PENDING_REVIEW', 'revision': before['revision'] + 1}
        link = {'id': 'link-' + uuid.uuid4().hex, 'source': 'ticket:' + ticket_id, 'target': task['id'], 'relation': 'needs_review', 'action_id': action_id}
        event = {'id': 'event-' + uuid.uuid4().hex, 'eventType': 'REVIEW_REQUESTED', 'created_at': now, 'delivery': 'local_outbox',
                 'payload': {'ticket_id': ticket_id, 'review_id': task['id'], 'action_id': action_id}}
        result = {'action_id': action_id, 'actionType': specification['ActionType'], 'definition_sha256': digest(specification),
                  'committed': True, 'replayed': False, 'actor': actor['id'], 'created_at': now, 'scope': 'local_demo',
                  'checks': checks, 'before': before, 'after': after, 'review_task': task, 'link': link, 'event': event,
                  'message': '已创建本地复核任务；未向外部系统转接或发送消息。'}
        conn.execute('INSERT OR REPLACE INTO ticket_state VALUES (?,?,?)', tuple(after[k] for k in ['ticket_id', 'workflow_status', 'revision']))
        conn.execute('INSERT INTO review_tasks VALUES (?,?)', (task['id'], json.dumps(task, ensure_ascii=False)))
        conn.execute('INSERT INTO action_links VALUES (?,?,?,?,?)', tuple(link[k] for k in ['id', 'source', 'target', 'relation', 'action_id']))
        conn.execute('INSERT INTO action_events VALUES (?,?)', (event['id'], json.dumps(event, ensure_ascii=False)))
        conn.execute('INSERT INTO action_audit VALUES (?,?,?)', (action_id, now, json.dumps(result, ensure_ascii=False)))
        conn.execute('INSERT INTO action_receipts VALUES (?,?,?,?)', (actor['id'], payload['idempotency_key'], request_hash, json.dumps(result, ensure_ascii=False)))
        conn.commit()
        return result, 200
    except (ActionError, sqlite3.Error) as exc:
        conn.rollback()
        if isinstance(exc, ActionError):
            code, message, status = exc.code, exc.message, exc.status
        else:
            code, message, status = 'transaction_failed', '动作事务失败，业务变更已回滚。', 503
        result = {'action_id': action_id, 'actionType': 'submitForReview', 'committed': False, 'actor': actor.get('id'),
                  'error': code, 'message': message, 'checks': checks, 'created_at': now}
        conn.execute('INSERT INTO action_audit VALUES (?,?,?)', (action_id, now, json.dumps(result, ensure_ascii=False)))
        conn.commit()
        return result, status
    finally:
        conn.close()


def register(app, root):
    initialize(root)
    app.config.setdefault('ONTOCARE_ACTION_ACTOR', DEFAULT_ACTOR.copy())
    bp = Blueprint('action_types', __name__)

    @bp.get('/ontology/actions')
    def page():
        from flask import send_file
        return send_file(Path(root) / 'web/actions.html')

    @bp.get('/api/action-types')
    def definitions():
        return jsonify({'types': [load_json(Path(root) / 'actions/submit-review.json')],
                        'actor': current_app.config['ONTOCARE_ACTION_ACTOR'], 'identity_mode': 'local_demo_server_identity'})

    @bp.get('/api/actions/history')
    def history():
        with connect(root) as conn:
            audit = [json.loads(r[0]) for r in conn.execute('SELECT payload FROM action_audit ORDER BY rowid DESC LIMIT 20')]
        return jsonify({'records': audit, 'scope': 'local_demo'})

    @bp.post('/api/actions/submit')
    def submit():
        if request.remote_addr not in {'127.0.0.1', '::1'} or request.headers.get('Origin', request.host_url.rstrip('/')) != request.host_url.rstrip('/'):
            return jsonify({'committed': False, 'error': 'origin_denied', 'message': '只允许本机同源提交本地动作。'}), 403
        result, status = execute(request.get_json(silent=True), current_app.config['ONTOCARE_ACTION_ACTOR'], root)
        return jsonify(result), status

    app.register_blueprint(bp)
