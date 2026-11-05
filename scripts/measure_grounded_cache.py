"""Paired cold/warm extra-model-call caches; preserve all unrelated cached entries."""
from contextlib import closing
from pathlib import Path
import json
import os
import sqlite3
import sys
import time
import urllib.request
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.setdefault('ONTOCARE_LLM_CONFIG',str(ROOT/'local/deepseek-config.json'))
from ontocare.data import load_json,write_json,digest
from ontocare.agent import Agent
from ontocare.app import create_app
from ontocare.evaluation import http_server
from ontocare.grounded_retrieval_v2 import Retriever
from ontocare.provider import Provider
from ontocare.query_rewrite import PROMPT
from ontocare.evidence_rerank import VERIFY_PROMPT
from ontocare.benchmark_metrics import latency

out=ROOT/'reports/grounded-eval/cache-latency.json'
if out.exists():print('Already measured; do not replace by a luckier timing run');sys.exit()
cases=load_json(ROOT/'evaluation/grounded-1200/final.json')['cases']
selected=[cases[i] for i in [0,25,50,75,100,125]]
r=Retriever(ROOT);p=Provider(config_path=ROOT/'local/deepseek-config.json');saved=[]
for c in selected:
    q=c['questions']['zh'];base=super(Retriever,r).search(q,c['pn'],allow_rewrite=True,ranking_profile='body_hybrid')
    packet={'question':base['search_query'],'candidates':[{'id':d['id'],'title':d['title'],'content':d['content']} for d in base['documents']]}
    keys=[('grounded-query-rewrites.sqlite','rewrites',digest([q,PROMPT,p.model])),('evidence-rerank.sqlite','reranks',digest([packet,VERIFY_PROMPT,p.model]))]
    for name,table,key in keys:
        path=ROOT/'local'/name
        if not path.exists():continue
        with closing(sqlite3.connect(path)) as conn:
            if not conn.execute('SELECT name FROM sqlite_master WHERE type="table" AND name=?',(table,)).fetchone():continue
            row=conn.execute(f'SELECT * FROM {table} WHERE id=?',(key,)).fetchone()
            saved.append((path,table,row))
            with conn:conn.execute(f'DELETE FROM {table} WHERE id=?',(key,))
    r.query_vectors.pop(q,None);r.query_vectors.pop(base['search_query'],None)
records=[]
try:
    with http_server(create_app(ROOT,Agent(ROOT,retriever=r)),threaded=True) as base:
        for c in selected:
            for state in ['cold','warm']:
                start=time.perf_counter();req=urllib.request.Request(base+'/api/chat',data=json.dumps({'message':c['questions']['zh'],'mode':'live'}).encode(),headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(req,timeout=240) as response:reply=json.load(response)
                calls=reply.get('model_calls',[])+reply.get('retrieval_model_calls',[])
                records.append({'id':c['id'],'state':state,'question':c['questions']['zh'],'http_ms':(time.perf_counter()-start)*1000,'model_status':reply['model_status'],'timings':reply['timings'],'extra_model_calls':reply.get('retrieval_model_calls',[]),'total_tokens':sum((x.get('usage') or {}).get('total_tokens',0) for x in calls),'query_rewrite':[t.get('result',{}).get('query_rewrite') for t in reply['tools'] if t['name']=='search_evidence'],'evidence_rerank':[t.get('result',{}).get('evidence_rerank') for t in reply['tools'] if t['name']=='search_evidence']})
                print('cache timing',len(records),'/12',state,reply['model_status'],flush=True)
finally:
    for path,table,row in saved:
        if row:
            with closing(sqlite3.connect(path)) as conn:
                with conn:conn.execute(f'INSERT OR IGNORE INTO {table} VALUES (?,?)',row)
summary={'scope':'six fixed Chinese queries, paired in-order. Cold means query-rewrite and evidence-rerank cache entries removed for these queries only, E5 weights already loaded. Warm immediately repeats in a new conversation; no answer text cache. No unrelated cache entries removed. Concurrent gateway load not controlled. Small-sample P99 is descriptive only.','metrics':{state:latency([r['http_ms'] for r in records if r['state']==state]) for state in ['cold','warm']},'cases':records}
write_json(out,summary);print(json.dumps(summary['metrics']),flush=True)
