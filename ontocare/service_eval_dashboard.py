"""Source-grouped customer QA evaluations, distinct from engineering test counts."""
from collections import Counter, defaultdict
from functools import lru_cache
import json
from pathlib import Path
import random
import re
import time

import numpy as np
from flask import jsonify, request, send_file, Response

from .data import load_json

NAMESPACE = 'customer-service-v2'


def safe_text(text):
    text=re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[EMAIL]', text)
    return re.sub(r'(?<!\w)(?:\+?\d[\d ()-]{8,}\d)(?!\w)',
                  lambda m:'[PHONE]' if len(re.sub(r'\D','',m[0]))>=10 else m[0], text)


def percentile(values):
    return {'n': len(values), 'p50_ms': float(np.percentile(values, 50)) if values else None,
            'p99_ms': float(np.percentile(values, 99)) if values else None}


def labelled(case):
    return case.get('kind') != 'seen_ticket' and (case.get('reference') is not None or case.get('expected_decision') is not None)


def task_verdict(case, answer, judge):
    if not labelled(case) or judge.get('status') != 'completed':
        return None
    reply = answer['turns'][-1].get('reply', {})
    decision_ok = not case.get('expected_decision') or reply.get('decision') == case['expected_decision']
    return bool(judge['answer_correct'] and judge['policy_safe'] and judge['history_ok']
                and decision_ok and all(c['passed'] for c in reply.get('checks', [])))


def score_run(root, label, case_ids=None, first_repeat_only=False):
    local = root / 'local' / NAMESPACE
    answers = [load_json(p) for p in sorted((local/'answers'/label).glob('*.json'))]
    if case_ids is not None:answers=[a for a in answers if a['id'] in case_ids]
    if first_repeat_only:answers=[a for a in answers if a['repeat']==0]
    counts = Counter(); bad = Counter(); scored = []; faithful = []
    http_ms = []; graph_ms = []; graph_hit_ms = []; graph_miss_ms = []; retrieval_ms = []; model_calls = []; judge_calls = []
    by_kind = defaultdict(lambda: {'passed': 0, 'n': 0})
    graph_requests = 0; graph_edges = 0; handoff = 0; supported = total = 0
    repeats = Counter(); outcomes = defaultdict(list); labelled_attempts = 0
    statuses = Counter(); prompts = Counter(); failed_validators = Counter(); safety_flags = 0
    for a in answers:
        case = a['case']; repeats[a['id']] += 1
        labelled_attempts += labelled(case)
        if labelled(case):by_kind[case['kind']]['n'] += 1
        jp = local/'judges'/label/(a['id']+f"-r{a['repeat']}.json")
        j = load_json(jp) if jp.exists() else {}
        counts['judged'] += j.get('status') == 'completed'
        safety_flags += j.get('status') == 'completed' and not j.get('policy_safe', True)
        verdict = task_verdict(case, a, j)
        if labelled(case):outcomes[a['id']].append(verdict)
        if verdict is not None:
            scored.append(verdict)
            by_kind[case['kind']]['passed'] += int(verdict)
            if not verdict:
                category=j.get('bad_case_category','workflow')
                bad['workflow' if category=='none' else category] += 1
        elif j.get('status') == 'completed' and not j.get('policy_safe'):
            bad[j.get('bad_case_category', 'policy')] += 1
        if j.get('status') == 'completed':
            supported += j['supported_claims']; total += j['total_claims']
            faithful.extend([j['faithfulness']] if j.get('faithfulness') is not None else [])
        judge_calls.extend(j.get('model_calls', []))
        for turn in a['turns']:
            http_ms.append(turn['http_ms']); r = turn.get('reply', {})
            counts['turns'] += 1; counts['live_completed'] += r.get('model_status') == 'completed'
            statuses[r.get('model_status','http_error')] += 1
            if r.get('prompt',{}).get('system_sha256'):prompts[r['prompt']['system_sha256']] += 1
            for check in r.get('checks',[]):
                if not check['passed']:failed_validators[check['name']] += 1
            if r.get('decision') == 'manual_review':handoff += 1
            model_calls.extend(r.get('model_calls', []) + r.get('retrieval_model_calls', []))
            timing = r.get('timings', {})
            if timing.get('retrieval_ms') is not None:retrieval_ms.append(timing['retrieval_ms'])
            if r.get('retrieval'):
                graph_requests += 1; graph_edges += len(r['retrieval'].get('edges', []))
                if timing.get('graph_ms') is not None:
                    graph_ms.append(timing['graph_ms'])
                    (graph_hit_ms if r.get('ontology_cache',{}).get('graph_hits') else graph_miss_ms).append(timing['graph_ms'])
    def tokens(calls):
        return {k: sum((c.get('usage') or {}).get(k, 0) for c in calls)
                for k in ['prompt_tokens', 'completion_tokens', 'total_tokens']}
    return {'label': label, 'attempts': len(answers), 'unique_cases': len(repeats), **counts,
            'three_repeat_cases': sum(n >= 3 for n in repeats.values()),
            'three_repeat_robustness': {'n':sum(len(v)>=3 and all(x is not None for x in v) for v in outcomes.values()),
                 'all_passed':sum(len(v)>=3 and all(x is True for x in v) for v in outcomes.values()),
                 'definition':'all three executions pass, not any one of three; identical cached r0 never counted twice'},
            'model_status_counts': dict(statuses), 'system_prompt_hashes': dict(prompts),
            'failed_validators': dict(failed_validators), 'judge_safety_flags': safety_flags,
            'task_pass': {'passed': sum(scored), 'n': labelled_attempts, 'assessed_n': len(scored),
                          'unassessed_n': labelled_attempts-len(scored),
                          'value': sum(scored)/labelled_attempts if labelled_attempts else None,
                          'assessed_value': sum(scored)/len(scored) if scored else None,
                          'definition': 'source-labelled tasks; judge correctness + safety + history + expected workflow + trace validators; seen tickets excluded'},
            'task_by_kind': dict(by_kind), 'faithfulness': {'n': len(faithful), 'supported_claims': supported,
                'total_claims': total, 'value': supported/total if total else None, 'macro': float(np.mean(faithful)) if faithful else None,
                'definition': 'LLM judge atomic claim support; same model family, separate call; no human verification'},
            'latency_http': percentile(http_ms), 'latency_graph': percentile(graph_ms),
            'latency_graph_cache_hit':percentile(graph_hit_ms), 'latency_graph_cache_miss':percentile(graph_miss_ms),
            'latency_retrieval': percentile(retrieval_ms), 'graph_requests': graph_requests, 'traversed_edges': graph_edges,
            'answer_tokens': tokens(model_calls), 'judge_tokens': tokens(judge_calls),
            'money_cost': None, 'money_cost_reason': 'gateway input/output/cache unit prices unavailable; tokens are measured',
            'bad_case_categories': dict(bad), 'business': {'actual_resolution': None, 'actual_handoff_rate': None,
                'csat': None, 'repeat_contact_rate': None, 'manual_review_recommendation': handoff/counts['turns'] if counts['turns'] else None,
                'reason': 'No production ticket closures, transfer receipts, survey or linked repeat-contact outcomes; recommendation is a proxy only'}}


def retrieval_interval(rows):
    groups = defaultdict(list)
    for r in rows:groups[r['group']].append(float(bool(r['ranked_ids'] and r['ranked_ids'][0] in r['gold_ids'])))
    means = [sum(v)/len(v) for v in groups.values()]
    rng = random.Random(20261103)
    boot = sorted(sum(rng.choices(means, k=len(means)))/len(means) for _ in range(2000)) if means else []
    return {'source_groups': len(means), 'interval_95': [boot[50], boot[1949]] if boot else None,
            'method': 'source-group bootstrap; bilingual variants are correlated, not independent trials'}


@lru_cache(maxsize=4)
def summary(root_string, time_bucket):
    root = Path(root_string); local = root/'local'/NAMESPACE; reports = root/'reports'/NAMESPACE
    manifest = load_json(root/'evaluation'/NAMESPACE/'manifest.json')
    runs = [score_run(root, p.name) for p in sorted((local/'answers').glob('*')) if p.is_dir()]
    for run in runs:
        if run['label']=='candidate-final':run['first_attempt']=score_run(root,'candidate-final',first_repeat_only=True)
    parent_ids={p.name for p in (local/'answers/parent-pilot').glob('*-r0.json')}
    candidate_ids={p.name for p in (local/'answers/candidate-final').glob('*-r0.json')}
    paired_ids={name.removesuffix('-r0.json') for name in parent_ids&candidate_ids}
    paired={name:score_run(root,name,paired_ids,True) for name in ['parent-pilot','candidate-final']}
    retrieval = []
    for p in sorted(reports.glob('retrieval-*-metrics.json')):
        d = load_json(p); private = local/f"retrieval-{d['label']}.json"
        rows = load_json(private)['cases'] if private.exists() else []
        d['intervals'] = {split: retrieval_interval([r for r in rows if r['split'] == split])
                          for split, metric in d['metrics'].items() if metric['n'] and split in {'development','validation','holdout'}}
        retrieval.append(d)
    return {'manifest': manifest, 'runs': runs, 'retrieval': retrieval,
            'paired_answer_comparison': {'n':len(paired_ids),'runs':paired,'selection':'same deterministic 40-case development pilot, r0 only; no outcome-based selection'},
            'ragas': [load_json(p) for p in sorted(reports.glob('ragas-*.json'))],
            'evolution': load_json(reports/'evolution.json') if (reports/'evolution.json').exists() else {},
            'note': 'Engineering test counts are not QA task scores. Recall@1 here is query-level first-hit of an accepted equivalent source group, not set recall of every required document.',
            'refreshed_at': time.time()}


def register(app, root):
    root = Path(root)
    dataset_path = root/'evaluation'/NAMESPACE/'cases.json'
    if not dataset_path.exists():return
    cases = load_json(dataset_path)['cases']; by_id = {c['id']: c for c in cases}
    local = root/'local'/NAMESPACE

    @app.get('/evaluations')
    def evaluations_page():
        return send_file(root/'web/evaluations.html')

    @app.get('/api/service-evals/summary')
    def evaluation_summary():
        return jsonify(summary(str(root), int(time.time()/8)))

    def valid_label():
        label = request.args.get('run', 'candidate-final')
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', label):raise ValueError('invalid run')
        return label

    def repeat_verdicts(case, label):
        verdicts=[]
        for p in (local/'answers'/label).glob(case['id']+'-r*.json'):
            jp=local/'judges'/label/p.name
            verdicts.append(task_verdict(case,load_json(p),load_json(jp) if jp.exists() else {}))
        return verdicts

    def detail(case, label):
        outputs = []
        for p in sorted((local/'answers'/label).glob(case['id']+'-r*.json')):
            a = load_json(p); jp = local/'judges'/label/p.name; j = load_json(jp) if jp.exists() else {}
            turns = []
            for t in a['turns']:
                r = t.get('reply', {})
                search_result=next((tool['result'] for tool in r.get('tools',[]) if tool['name']=='search_evidence'),{})
                turns.append({'question':t['question'], 'zh':r.get('zh'), 'en':r.get('en'),
                    'decision':r.get('decision'), 'model_status':r.get('model_status'), 'trace_id':r.get('trace_id'),
                    'http_ms':t['http_ms'], 'timings':r.get('timings'), 'citations':r.get('citations',[]),
                    'graph':r.get('retrieval'), 'checks':r.get('checks'), 'validation_retries':r.get('response_validation_retries',0),
                    'retrieval_contract':search_result.get('ranking_contract'), 'query_rewrite':search_result.get('query_rewrite')})
            outputs.append({'repeat':a['repeat'],'turns':turns,'judge':{k:v for k,v in j.items() if k!='model_calls'},
                            'task_pass':task_verdict(case,a,j)})
        # Strip personal contacts before returning even local historical ticket text.
        def sanitize(value):
            if isinstance(value, str):return safe_text(value)
            if isinstance(value, list):return [sanitize(v) for v in value]
            if isinstance(value, dict):return {k:sanitize(v) for k,v in value.items()}
            return value
        return sanitize({'case':case,'outputs':outputs})

    @app.get('/api/service-evals/cases')
    def evaluation_cases():
        try:label=valid_label();page=max(1,int(request.args.get('page','1')))
        except ValueError:return jsonify({'error':'invalid request'}),400
        query=request.args.get('q','').casefold();split=request.args.get('split','');kind=request.args.get('kind','')
        verdict_filter=request.args.get('verdict','')
        selected=[c for c in cases if (not split or c['split']==split) and (not kind or c['kind']==kind)
                  and (not query or query in json.dumps(c,ensure_ascii=False).casefold())]
        if verdict_filter:
            filtered=[]
            for c in selected:
                p=local/'answers'/label/(c['id']+'-r0.json');jp=local/'judges'/label/p.name
                a=load_json(p) if p.exists() else None;j=load_json(jp) if jp.exists() else {}
                verdict=task_verdict(c,a,j) if a else None
                verdicts=repeat_verdicts(c,label)
                if (verdict_filter=='failed' and any(v is False for v in verdicts)) or (verdict_filter=='passed' and verdicts and all(v is True for v in verdicts)) or (verdict_filter=='pending' and verdict is None):filtered.append(c)
            selected=filtered
        items=[]
        for c in selected[(page-1)*20:page*20]:
            p=local/'answers'/label/(c['id']+'-r0.json');jp=local/'judges'/label/p.name
            a=load_json(p) if p.exists() else None;j=load_json(jp) if jp.exists() else {}
            verdicts=repeat_verdicts(c,label)
            items.append({**c,'answer_status':a['turns'][-1].get('reply',{}).get('model_status','http_error') if a else 'pending',
                          'repeat_n':len(verdicts),'repeat_failures':sum(v is False for v in verdicts),
                          'task_pass':task_verdict(c,a,j) if a else None,'judge_category':j.get('bad_case_category'),
                          'actual_zh':safe_text(a['turns'][-1].get('reply',{}).get('zh','')) if a else None})
        return jsonify({'total':len(selected),'page':page,'items':items})

    @app.get('/api/service-evals/cases/<case_id>')
    def evaluation_detail(case_id):
        try:label=valid_label()
        except ValueError:return jsonify({'error':'invalid run'}),400
        if case_id not in by_id:return jsonify({'error':'not_found'}),404
        return jsonify(detail(by_id[case_id],label))

    @app.get('/api/service-evals/download')
    def evaluation_download():
        return Response(json.dumps(load_json(dataset_path),ensure_ascii=False,indent=2),mimetype='application/json',
                        headers={'Content-Disposition':'attachment; filename="customer-service-611-cases.json"'})

    @app.get('/api/service-evals/export')
    def evaluation_export():
        path=root/'reports'/NAMESPACE/'all-questions-answers-scores.csv'
        return send_file(path,as_attachment=True,download_name='customer-service-questions-answers-scores.csv') if path.exists() else (jsonify({'error':'not_generated'}),404)

    @app.get('/api/service-evals/guide')
    def evaluation_guide():
        return send_file(root/'docs/客服评测集与自进化闭环.md',mimetype='text/plain')
