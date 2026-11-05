"""Voluntary demo feedback, separate from production customer outcomes."""
import json
import time

from flask import jsonify, request
from .data import connect


def register(app, root):
    with connect(root) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS service_feedback (trace_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, resolved INTEGER, csat INTEGER, updated_at REAL NOT NULL)')

    @app.post('/api/feedback')
    def save_feedback():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {'trace_id', 'session_id', 'resolved', 'csat'}:
            return jsonify({'error': '需要 trace_id、session_id、resolved、csat 四个字段'}), 400
        if not all(isinstance(body[k], str) and 1 <= len(body[k]) <= 80 for k in ['trace_id', 'session_id']):
            return jsonify({'error': '无效的会话或回复标识'}), 400
        if body['resolved'] is not None and type(body['resolved']) is not bool:
            return jsonify({'error': '解决状态须为 true、false 或 null'}), 400
        if body['csat'] is not None and (type(body['csat']) is not int or not 1 <= body['csat'] <= 5):
            return jsonify({'error': '满意度须为 1 至 5 分或 null'}), 400
        if body['resolved'] is None and body['csat'] is None:
            return jsonify({'error': '请至少选择解决状态或满意度'}), 400
        with connect(root) as conn:
            trace = conn.execute('SELECT payload FROM traces WHERE id=?', (body['trace_id'],)).fetchone()
            if not trace or json.loads(trace['payload']).get('session_id') != body['session_id']:
                return jsonify({'error': '回复与会话不匹配'}), 404
            conn.execute('INSERT OR REPLACE INTO service_feedback VALUES (?,?,?,?,?)',
                         (body['trace_id'], body['session_id'], body['resolved'], body['csat'], time.time()))
        return jsonify({'saved': True, 'scope': 'voluntary local-demo feedback, not production resolution'})

    @app.get('/api/feedback/summary')
    def feedback_summary():
        with connect(root) as conn:
            rows = conn.execute('SELECT resolved,csat FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY updated_at DESC,trace_id DESC) AS rn FROM service_feedback) WHERE rn=1').fetchall()
        resolution = [r['resolved'] for r in rows if r['resolved'] is not None]
        satisfaction = [r['csat'] for r in rows if r['csat'] is not None]
        return jsonify({'scope': '本机演示的自愿反馈；每会话最新一次反馈。不是生产客服指标。',
                        'sessions_with_feedback': len(rows), 'resolution_responses': len(resolution),
                        'demo_confirmed_resolution_rate': sum(resolution) / len(resolution) if resolution else None,
                        'csat_responses': len(satisfaction),
                        'demo_csat_top_two_rate': sum(v >= 4 for v in satisfaction) / len(satisfaction) if satisfaction else None,
                        'actual_handoff_rate': None, 'repeat_contact_rate': None,
                        'limitations': '自愿反馈存在选择偏差；缺少真实转接回执、跨会话客户标识与观察窗口。'})
