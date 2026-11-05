"""Paired 78-request ontology-cache benchmark; synthetic data only."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import random
import sys
import time
import urllib.request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ontocare.agent import Agent
from ontocare.app import create_app
from ontocare.data import ROOT, digest
from ontocare.evaluation import http_server
from ontocare.retrieval import Retriever

SCENARIOS = [
    ('e25_roller', ['我的 E25 报错误码3212，还没检查，先做什么？', '滚筒异物已经检查并清理了，还是报3212错误。', '现有资料是否还有其他支持的检查步骤？']),
    ('e28_roller', ['My E28 shows error 3212. What should I inspect first?', 'I already checked and cleaned the roller and removed all debris, but 3212 persists.', 'Which evidence supports the next step?']),
    ('parts_warranty', ['T8D04 可清洗配件的保修期限多久？', '我问的是鸭嘴阀，需要提供哪些保修资料？', '请再说明还缺哪些核验条件。']),
    ('hub_warranty', ['What is the warranty period for the T8D04 pump hub?', 'For the pump hub warranty, what proof of purchase is needed?', 'Does knowing the policy period mean eligibility is already verified?']),
    ('refund', ['T8D04 用了一周，包装还在，可以退款吗？', '原包装还在能改变未使用这个退款条件吗？', '请简要说明你能确认什么、还不能确认什么。']),
    ('solar', ['My T8170 camera is not charging from its solar panel. What can I inspect?', 'Please summarize the checks supported by the source.', 'What details should I collect if it still will not charge?']),
    ('wifi', ['我的 E28 T2352 经常 Wi-Fi 离线，可以怎么检查？', '如果按资料检查后仍然离线，需要提供哪些信息？', '用英文简要说明还需确认的信息。']),
    ('map', ['T2352 Omni E28 的地图经常丢失，有适用的说明吗？', 'Should I provide a screenshot and describe when the map disappears?', '请确认引用的资料适用哪个型号。']),
    ('base_station', ['我的 E25 T2353 基站不执行集尘、烘干或洗拖布任务，怎么办？', '请按引用资料整理需要检查的事项。', '如果问题仍存在，需要提交什么信息供核查？']),
    ('unsupported_error', ['T8170 报错误码3212，怎么处理？', '如果没有适用的错误码资料，你会怎么处理？', '请列出我需要补充的信息。']),
    ('unknown_product', ['我的 S1 Pro 不工作，怎么办？', '我还没有找到准确型号。', '缺少准确型号时，可以直接套用相似产品的排障说明吗？']),
    ('product_switch', ['我的 E25 报错误码3212，应该怎么查？', '现在换成另一台 E28，它也报错误码3212。', '这台 E28 已检查并清理滚筒异物，还是报3212。']),
    ('version_switch', ['T2353 error 3212, what should I check?', 'T2353 error 3212. I already checked and cleaned the roller.', 'Should I repeat the roller check or provide the result for review?']),
]


def workload():
    sessions = []
    for repeat in range(2):
        for name, messages in SCENARIOS:
            sessions.append({'id': f'{name}-{repeat+1}', 'turns': [{'id': f'{name}-{repeat+1}-{i+1}', 'message': ('你好，' if repeat else '') + message, 'version': 'v0' if name == 'version_switch' and i == 0 else 'candidate-1'} for i, message in enumerate(messages)]})
    random.Random(20261029).shuffle(sessions)
    return {'provenance': '78 synthetic requests in 26 three-turn sessions; not the 78 engineering tests or the 63 original tickets', 'sessions': sessions, 'sha256': digest(sessions)}


def request(base, payload):
    started = time.perf_counter()
    req = urllib.request.Request(base + '/api/chat', data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=210) as response:
            reply = json.load(response)
        return {'http_complete_ms': round((time.perf_counter()-started)*1000, 3), 'reply': {k: reply.get(k) for k in ['mode','model_status','decision','next_action','citation_ids','zh','en','sections','state','prompt','model_calls','checks','ontology_cache','timings','latency_ms','trace_id','bundle_sha256']}}
    except Exception as error:
        return {'http_complete_ms': round((time.perf_counter()-started)*1000, 3), 'error_type': type(error).__name__}


def session_pair(case, bases, mode):
    ids = {arm: uuid.uuid4().hex for arm in bases}
    rng = random.Random(case['id'])
    results = []
    for turn in case['turns']:
        arms = list(bases); rng.shuffle(arms)
        pair = {'id': turn['id'], 'session': case['id'], 'message': turn['message'], 'version': turn['version'], 'order': arms, 'arms': {}}
        for arm in arms:
            payload = {'message': turn['message'], 'session_id': ids[arm], 'version': turn['version'], 'mode': mode}
            pair['arms'][arm] = request(bases[arm], payload)
        results.append(pair)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['live', 'offline'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    cases = workload()
    manifest = Path('reports/ontology-cache-workload.json')
    if manifest.exists():
        assert json.loads(manifest.read_text()) == cases, 'Frozen workload changed'
    else:
        manifest.write_text(json.dumps(cases, ensure_ascii=False, indent=2)+'\n')
    retrievers = {arm: Retriever(ROOT) for arm in ['before', 'after']}
    # Warm encoder/query vectors equally; keep ontology caches cold at benchmark start.
    queries = set()
    for case in cases['sessions']:
        history = []
        for turn in case['turns']:
            if case['id'].startswith('product_switch') and len(history) == 1:
                history = []
            queries.add('\n'.join(history[-2:] + [turn['message']]))
            history.append(turn['message'])
    for arm, retriever in retrievers.items():
        if retriever.vectors is not None:
            vectors = retriever._encoder(retriever.vector_meta['revision']).encode(['query: '+q for q in sorted(queries)], normalize_embeddings=True, batch_size=16)
            retriever.query_vectors.update(zip(sorted(queries), vectors))
    agents = {arm: Agent(ROOT, retriever, ontology_cache=arm == 'after') for arm, retriever in retrievers.items()}
    result = {'mode': args.mode, 'workload_sha256': cases['sha256'], 'method': 'Same 78 requests; separate sessions per arm; random within-pair order; two concurrent sessions; equal embedding warmup; ontology starts cold; no answer cache', 'runtime_sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path('ontocare/agent.py'), Path('ontocare/ontology_cache.py'), Path(__file__).relative_to(ROOT)]}, 'pairs': []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        bases = {arm: stack.enter_context(http_server(create_app(ROOT, agent), threaded=True)) for arm, agent in agents.items()}
        with ThreadPoolExecutor(max_workers=2) as pool:
            for future in as_completed([pool.submit(session_pair, c, bases, args.mode) for c in cases['sessions']]):
                completed = future.result(); result['pairs'].extend(completed)
                args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
                print(json.dumps({'completed_pairs': len(result['pairs']), 'session': completed[0]['session'], 'statuses': {arm: [t['arms'][arm].get('reply', {}).get('model_status', t['arms'][arm].get('error_type')) for t in completed] for arm in bases}}, ensure_ascii=False), flush=True)
    print('Completed all',len(result['pairs']),'matched pairs', flush=True)


if __name__ == '__main__':
    main()
