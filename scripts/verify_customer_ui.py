"""Exercise the actual customer SSE route; retain only public smoke-test metadata."""
import json
from pathlib import Path
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:5112'


def request(message, session=None):
    payload = {'message': message, 'mode': 'live'}
    if session:
        payload['session_id'] = session
    req = urllib.request.Request(BASE + '/api/chat/stream', data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'})
    start = time.perf_counter(); events = []; result = None; parts = []
    with urllib.request.urlopen(req, timeout=240) as response:
        event = None
        for raw in response:
            line = raw.decode().rstrip('\n')
            if line.startswith('event: '): event = line[7:]
            if not line.startswith('data: '): continue
            data = json.loads(line[6:]); events.append({'event': event, 'seconds': round(time.perf_counter() - start, 3)})
            if event == 'error': raise RuntimeError(data['error'])
            if event == 'evidence': result = data
            if event == 'delta': parts.append(data['text'])
    assert result is not None and events[-1]['event'] == 'done'
    assert ''.join(parts) == result['zh']
    kinds = [e['event'] for e in events]
    assert kinds.index('graph') < kinds.index('evidence') < kinds.index('delta')
    (ROOT / 'local' / ('customer-ui-' + result['trace_id'] + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    summary = {'question': message, 'trace_id': result['trace_id'], 'model_status': result['model_status'],
               'checks': result['checks'], 'decision': result['decision'], 'latency_ms': result['latency_ms'],
               'citation_count': len(result['citations']), 'graph_nodes': len(result['conversation_graph']['nodes']),
               'graph_edges': len(result['conversation_graph']['edges']), 'state': result['state'],
               'events': events, 'stream_matches_validated_answer': True}
    return summary, result['session_id']


if __name__ == '__main__':
    results = []
    first, session = request('我的 E25 报错误码3212，应该先检查什么？')
    results.append(first)
    followup, _ = request('滚筒缠绕的异物已经清理过了，但仍然报3212，下一步应该怎么做？', session)
    results.append(followup)
    report = {'scope': '2 live customer-interface smoke requests; not an independent quality evaluation',
              'delivery': 'real progress and retrieved graph, then validated answer chunks; not upstream token streaming',
              'results': results}
    destination = ROOT / 'reports/customer-ui-live-check.json'
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({'report': str(destination), 'results': [{k: r[k] for k in ['trace_id', 'model_status', 'latency_ms', 'citation_count', 'graph_nodes']} for r in results]}, ensure_ascii=False))
