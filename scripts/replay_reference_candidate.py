"""Paired actual HTTP replay; unchanged cases, gold, judge and pass conditions."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from pathlib import Path
import json
import argparse
import os
import shutil
import sys
import time
import urllib.request
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
os.environ.setdefault('ONTOCARE_LLM_CONFIG', str(ROOT / 'local/deepseek-config.json'))
from ontocare.data import load_json, write_json, digest
from ontocare.agent import Agent
from ontocare.reference_agent import ReferenceAgent, SourceActionAgent, VerifiedReferenceAgent
from ontocare.app import create_app
from ontocare.evaluation import http_server
from live_grounded_eval import judge, RUBRIC
from evaluate_workbench_v4 import summarize

SUPPORT_CONTRACT = '''
## Official reference and conditional evidence contract
An evidence item's references are separately captured official article bodies, with explicit product scope, URL, timestamp and content hash. They may support facts only for state.pn. Cite the parent Q&A ID and mention the official article when relying on its body. Original cell text remains unchanged. A URL slug, image, video title, or an unparsed video is NOT evidence for an instruction. If no actual body supports the requested procedure, explain that precise gap and request manual verification instead of making up steps.
Preserve the logical strength of every source statement: "if A, then consider B" must remain conditional on A. A diagnostic test, hypothesis, or a list of possible causes does not establish the actual cause, a most-likely diagnosis, or a guaranteed fix. State the condition and supported next check; do not add causal claims or generic prevention advice. A question asking for evidence is not a confirmed device fact.
'''


def main():
    parser = argparse.ArgumentParser(); variants = parser.add_mutually_exclusive_group(); variants.add_argument('--action-only', action='store_true'); variants.add_argument('--verified-only', action='store_true'); variants.add_argument('--action-fixed', action='store_true'); args = parser.parse_args()
    single = args.action_only or args.verified_only or args.action_fixed
    arm_name = 'action-fixed' if args.action_fixed else 'verified' if args.verified_only else 'action' if args.action_only else 'reference'
    parent = ROOT / 'local/workbench-v5/parent'; candidate = ROOT / 'local/workbench-v5' / (arm_name + '-candidate')
    if not candidate.exists():
        for name in ['data', 'ontology', 'web', 'prompts', 'actions']:
            if (parent / name).exists(): shutil.copytree(parent / name, candidate / name)
        if single:
            import sqlite3
            (candidate / 'local').mkdir()
            for source in (parent / 'local').iterdir():
                if source.suffix == '.sqlite':
                    with sqlite3.connect(source) as a, sqlite3.connect(candidate / 'local' / source.name) as b: a.backup(b)
                elif source.is_file(): shutil.copy2(source, candidate / 'local' / source.name)
        else: shutil.copytree(parent / 'local', candidate / 'local')
        shutil.copy2(ROOT / 'local/reference-snapshots.json', candidate / 'local/reference-snapshots.json')
        prompt = candidate / 'prompts/customer-service.md'; prompt.write_text(prompt.read_text() + SUPPORT_CONTRACT)
    cases = load_json(ROOT / 'reports/grounded-eval/live-sampling.json')['cases']
    candidate_type = VerifiedReferenceAgent if args.verified_only else SourceActionAgent
    agents = {arm_name: candidate_type(candidate)} if single else {'parent': Agent(parent), 'reference': ReferenceAgent(candidate)}
    first = next(iter(agents.values())); first.retriever._encoder(first.retriever.vector_meta['revision'])
    for agent in agents.values(): agent.retriever.encoder = first.retriever.encoder
    apps = {name: create_app(agent.root, agent) for name, agent in agents.items()}
    runtimes = {name: app.test_client().get('/api/runtime').json for name, app in apps.items()}
    protocol = {'cases_sha256': digest(cases), 'n_per_arm': len(cases), 'repeats': 1, 'judge_sha256': digest(RUBRIC),
                'runtimes': runtimes, 'scope': 'seen regression, not confirmation or production resolution',
                'hypothesis': 'Separately grounded official body snapshots and preserving diagnostic conditions fix reference-access and unsupported-cause failures without changing retrieval gold.',
                'judge_and_threshold_changed': False, 'reference_text': 'actual approved snapshots only; video stays unparsed'}
    if single:
        protocol['hypothesis'] = 'Keep official body snapshots and original Prompt; screen graph-proposed actions against source action descriptions, preventing a component mention from becoming an unsupported repair instruction.'
        if args.verified_only: protocol['hypothesis'] += ' Check output claims against cited source bodies before release; retry once on unsupported claims. This is a generation guard, NOT a changed evaluator.'
        protocol['parent_observations'] = 'Reuse saved actual parent outputs from reference-replay; no fresh parent model calls. Do not interpret latency as causal.'
        protocol['parent_protocol_sha256'] = digest(load_json(ROOT / 'reports/workbench-v5/reference-protocol.json'))
    path = ROOT / 'reports/workbench-v5' / (arm_name + '-protocol.json')
    if path.exists() and load_json(path) != protocol: raise ValueError('Frozen replay changed')
    write_json(path, protocol)
    local = ROOT / 'local/workbench-v5' / (arm_name + '-replay')
    def one(base, arm, case):
        path = local / arm / (case['id'].replace(':', '-') + '.json')
        if path.exists(): return load_json(path)
        session = None; turns = []
        for question in case['turns']:
            payload = {'message': question, 'mode': 'live', 'context': case.get('context', {})}
            if session: payload['session_id'] = session
            start = time.perf_counter()
            try:
                request = urllib.request.Request(base + '/api/chat', data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(request, timeout=240) as response: reply = json.load(response)
                if reply['runtime']['id'] != runtimes[arm]['id']: raise ValueError('runtime_mismatch')
                session = reply['session_id']; turns.append({'question': question, 'http_ms': (time.perf_counter() - start) * 1000, 'reply': reply})
            except Exception as error:
                turns.append({'question': question, 'http_ms': (time.perf_counter() - start) * 1000, 'error': type(error).__name__}); break
        row = {'id': case['id'], 'arm': arm, 'repeat': 1, 'case': case, 'turns': turns}
        row['judge'] = judge(row)
        if len(turns) != len(case['turns']) or any(t.get('reply', {}).get('model_status') != 'completed' or any(not c['passed'] for c in t.get('reply', {}).get('checks', [])) for t in turns): row['judge']['passed'] = False
        write_json(path, row); return row
    results = []
    with ExitStack() as stack:
        bases = {arm: stack.enter_context(http_server(app, threaded=True)) for arm, app in apps.items()}
        with ThreadPoolExecutor(max_workers=3) as executor:
            for future in as_completed([executor.submit(one, bases[arm], arm, case) for case in cases for arm in apps]):
                results.append(future.result())
                if len(results) % 12 == 0: print(arm_name + ' HTTP', len(results), '/', len(cases) * len(apps), flush=True)
    arms = {arm: summarize([r for r in results if r['arm'] == arm]) for arm in apps}
    if single:
        baseline = [load_json(ROOT / 'local/workbench-v5/reference-replay/parent' / (c['id'].replace(':', '-') + '.json')) for c in cases]
        arms = {'parent': summarize(baseline), **arms}
    summary = {'protocol': protocol, 'arms': arms}
    write_json(ROOT / 'reports/workbench-v5' / (arm_name + '-result.json'), summary)
    print({arm: result['task_pass_rate'] for arm, result in summary['arms'].items()}, flush=True)


if __name__ == '__main__': main()
