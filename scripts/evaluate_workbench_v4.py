"""Three repeated paired HTTP runs of the actual workbench Agent contracts."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from pathlib import Path
import argparse
import json
import os
import random
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.setdefault('ONTOCARE_LLM_CONFIG',str(ROOT/'local/deepseek-config.json'))
from ontocare.app import create_app
from ontocare.customer_agent import Agent as BeforeAgent
from ontocare.data import load_json,write_json,digest
from ontocare.evaluation import http_server
from ontocare.benchmark_metrics import latency,retrieval_scores,summarize_retrieval
from live_grounded_eval import judge

OUT=ROOT/'reports/workbench-v4';LOCAL=ROOT/'local/workbench-v4'


def summarize(rows):
    calls=[];times=[];graph=[];retrieval=[];scores=[];passed=0;completed=0;bad=Counter();dimensions={};recall=[];judge_calls=[];turn_completed=0;by_kind={};tool_counts=Counter()
    for row in rows:
        reply=row['turns'][-1].get('reply',{});j=row['judge'];complete=all(t.get('reply',{}).get('model_status')=='completed' for t in row['turns']) and len(row['turns'])==len(row['case']['turns'])
        hard=all(c['passed'] for t in row['turns'] for c in t.get('reply',{}).get('checks',[]))
        ok=complete and hard and j.get('passed') is True
        passed+=ok;completed+=complete
        kind=by_kind.setdefault(row['case']['kind'],{'passed':0,'planned':0});kind['passed']+=ok;kind['planned']+=1
        if not ok:bad['provider_or_validator' if not complete or not hard else j.get('attribution','judge_pending')]+=1
        if j.get('status')=='completed':
            scores.append(j.get('total',0))
            for key,value in j['dimensions'].items():dimensions.setdefault(key,[]).append(value['score'])
        judge_calls+=j.get('model_calls',[])
        for t in row['turns']:
            r=t.get('reply',{});times.append(t['http_ms']);calls+=r.get('model_calls',[])+r.get('retrieval_model_calls',[])
            turn_completed+=r.get('model_status')=='completed'
            tool_counts.update(tool['name'] for tool in r.get('tools',[]))
            for key,target in [('graph_ms',graph),('retrieval_ms',retrieval)]:
                if key=='graph_ms' and r.get('retrieval') is None:continue
                if key=='retrieval_ms' and not any(tool['name']=='search_evidence' for tool in r.get('tools',[])):continue
                if r.get('timings',{}).get(key) is not None:target.append(r['timings'][key])
        if row['case'].get('gold_ids'):
            ids=next((t['result'].get('ids',[]) for t in reply.get('tools',[]) if t['name']=='search_evidence'),[])
            recall.append({'family_id':row['case']['family_id'],'language':row['case']['language'],'scores':retrieval_scores(row['case']['gold_ids'],ids)})
    usage=lambda cs:{k:sum((c.get('usage') or {}).get(k,0) for c in cs) for k in ['prompt_tokens','completion_tokens','total_tokens']}
    n=len(rows)
    return {'scenarios':n,'passed':passed,'task_pass_rate':passed/n if n else None,'model_completed':completed,
            'turns':len(times),'model_completed_turns':turn_completed,'pass_by_kind':by_kind,'tool_invocations':dict(tool_counts),
            'judge_completed':len(scores),'task_denominator':'all planned finished rows, including model/judge failures; not only judged successes',
            'mean_judge_score':sum(scores)/len(scores) if scores else None,'dimension_means':{k:sum(v)/len(v) for k,v in dimensions.items()},
            'http_latency':latency(times),'graph_latency':latency(graph),'retrieval_latency':latency(retrieval),
            'inference_tokens':usage(calls),'judge_tokens':usage(judge_calls),'money_cost':None,'money_reason':'No verified gateway prices',
            'retrieval_on_knowledge':summarize_retrieval(recall) if recall else None,'bad_case_attribution':dict(bad)}


def main():
    p=argparse.ArgumentParser();p.add_argument('--prepare',action='store_true');args=p.parse_args()
    cases=load_json(ROOT/'reports/grounded-eval/live-sampling.json')['cases']
    old=BeforeAgent(ROOT);apps={'before':create_app(ROOT,old),'after':create_app(ROOT)}
    old.retriever._encoder(old.retriever.vector_meta['revision'])
    apps['after'].extensions['ontocare_service'].retriever.encoder=old.retriever.encoder
    # E5 is already loaded in before; sharing weights changes neither query nor answer caches.
    # The default after instance is intentionally constructed by create_app, matching the landing page.
    runtimes={arm:app.test_client().get('/api/runtime').json for arm,app in apps.items()}
    protocol={'dataset_sha256':digest(cases),'scenarios_per_repeat':len(cases),'repeats':3,'workers':3,
              'runtimes':runtimes,'latency_boundary':'localhost HTTP send to complete JSON; model weights warm; query caches in their actual recorded state; not browser latency or TTFT',
              'scope':'seen validation replay; synthetic knowledge and manually specified boundaries; not independent final or production resolution',
              'judge':'same gateway model, blind version names; reference plus actually retrieved evidence; reasons per dimension; no human confirmation',
              'palantir_method':'object/source-derived inputs + manually defined boundaries + expected outputs + evaluators + repeated experiments on fixed cases',
              'source':'https://www.palantir.com/docs/foundry/aip-evals/create-suite'}
    path=OUT/'protocol.json'
    if path.exists() and load_json(path)!=protocol:raise ValueError('Workbench runtime or protocol changed. Preserve the old run and use a new version.')
    write_json(path,protocol)
    if args.prepare:print({'prepared':True,'runtime_ids':{k:v['id'] for k,v in runtimes.items()}});return
    def one(base,arm,repeat,case):
        path=LOCAL/arm/str(repeat)/(case['id'].replace(':','-')+'.json')
        if path.exists():return load_json(path)
        turns=[];session=None
        for question in case['turns']:
            payload={'message':question,'mode':'live','context':case.get('context',{})}
            if session:payload['session_id']=session
            started=time.perf_counter()
            try:
                req=urllib.request.Request(base+'/api/chat',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(req,timeout=240) as response:reply=json.load(response)
                if reply['runtime']['id']!=runtimes[arm]['id']:raise ValueError('runtime_mismatch')
                session=reply['session_id'];turns.append({'question':question,'http_ms':(time.perf_counter()-started)*1000,'reply':reply})
            except Exception as error:
                turns.append({'question':question,'http_ms':(time.perf_counter()-started)*1000,'error':type(error).__name__});break
        row={'id':case['id'],'arm':arm,'repeat':repeat,'case':case,'turns':turns}
        row['judge']=judge(row)
        gates=[str(t.get('reply',{}).get('model_status',t.get('error','missing_reply'))) for t in turns if t.get('reply',{}).get('model_status')!='completed' or any(not c['passed'] for c in t.get('reply',{}).get('checks',[]))]
        if gates:
            row['judge']['passed']=False
            row['judge']['verdict_reason']=row['judge'].get('verdict_reason','')+'; all-turn program gate failed: '+', '.join(gates)
        write_json(path,row);return row
    results=[]
    with ExitStack() as stack:
        bases={arm:stack.enter_context(http_server(app,threaded=True)) for arm,app in apps.items()}
        for repeat in range(1,4):
            jobs=[(arm,case) for case in cases for arm in apps];random.Random(20261103+repeat).shuffle(jobs)
            with ThreadPoolExecutor(max_workers=3) as pool:
                for f in as_completed([pool.submit(one,bases[arm],arm,repeat,case) for arm,case in jobs]):
                    results.append(f.result())
                    if len(results)%20==0:print('paired HTTP',len(results),'/',len(cases)*6,flush=True)
                    write_json(OUT/'progress.json',{'completed':len(results),'planned':len(cases)*6,'status':'running'})
    summary={'protocol':protocol,'arms':{arm:{'pooled':summarize([r for r in results if r['arm']==arm]),'repeats':[summarize([r for r in results if r['arm']==arm and r['repeat']==i]) for i in range(1,4)]} for arm in apps},
             'business':{'actual_resolution_rate':None,'actual_handoff_rate':None,'csat':None,'repeat_contact_rate':None,'reason':'No production outcome labels; demo feedback is separately collected.'}}
    write_json(OUT/'summary.json',summary);write_json(OUT/'progress.json',{'completed':len(results),'planned':len(results),'status':'complete'})
    print({a:m['pooled']['task_pass_rate'] for a,m in summary['arms'].items()},flush=True)


if __name__=='__main__':main()
