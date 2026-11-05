"""Seen fixed-subset ablations; Skill text and state are both removed in isolation."""
from pathlib import Path
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
import os
import shutil
import sqlite3
import sys
import time
import urllib.request
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.setdefault('ONTOCARE_LLM_CONFIG',str(ROOT/'local/deepseek-config.json'))
from ontocare.app import create_app
from ontocare.data import load_json,write_json,digest
from ontocare.evaluation import http_server
from evaluate_workbench_v4 import summarize
from live_grounded_eval import judge


def skill_root():
    root=ROOT/'local/workbench-ablation/no-skill-root'
    if root.exists():return root
    root.mkdir(parents=True)
    for name in ['data','ontology','web','evaluation','actions']:(root/name).symlink_to(ROOT/name,target_is_directory=True)
    shutil.copytree(ROOT/'prompts',root/'prompts')
    for path in (root/'prompts/skills').glob('*.md'):path.write_text('')
    (root/'local').mkdir()
    for name in ['service.sqlite','business.sqlite','grounded-query-rewrites.sqlite','evidence-rerank.sqlite']:
        if (ROOT/'local'/name).exists():
            with closing(sqlite3.connect(ROOT/'local'/name)) as source,closing(sqlite3.connect(root/'local'/name)) as target:source.backup(target)
    for name in ['vectors.npz','vectors.json','ranking-title-vectors.npz','ranking-title-vectors.json']:
        if (ROOT/'local'/name).exists():(root/'local'/name).symlink_to(ROOT/'local'/name)
    return root


def main():
    # Keep the repeated main HTTP run intact and finish it before this extra model load.
    while not (ROOT/'reports/workbench-v4/summary.json').exists():time.sleep(5)
    allcases=load_json(ROOT/'reports/grounded-eval/live-sampling.json')['cases']
    cases=allcases[:12]+[c for kind in ['multi_turn','business','boundary'] for c in [x for x in allcases if x['kind']==kind][:2]]
    out=ROOT/'reports/workbench-v4';protocol={'case_ids':[c['id'] for c in cases],'case_sha256':digest(cases),'cases_per_ablation':len(cases),'repeats':1,
            'no_skill':'variant=no_skill AND empty Skill markdown in isolated prompt root; system format and hard business safety checks retained',
            'no_ontology':'built-in variant removes scope/graph/ontology tools together; not an isolated BFS-only causal ablation',
            'comparison':'same cases from after repeat1; seen validation; no model or test-set tuning'}
    write_json(out/'ablation-protocol.json',protocol);results={}
    for arm,root,variant in [('no_skill',skill_root(),'no_skill'),('no_ontology',ROOT,'no_ontology')]:
        app=create_app(root)
        app.extensions['ontocare_service'].retriever._encoder(app.extensions['ontocare_service'].retriever.vector_meta['revision'])
        def one(base,case):
            path=ROOT/'local/workbench-ablation/runs'/arm/(case['id'].replace(':','-')+'.json')
            if path.exists():return load_json(path)
            turns=[];session=None
            for q in case['turns']:
                body={'message':q,'mode':'live','variant':variant,'context':case.get('context',{})}
                if session:body['session_id']=session
                start=time.perf_counter()
                try:
                    req=urllib.request.Request(base+'/api/chat',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
                    with urllib.request.urlopen(req,timeout=240) as response:r=json.load(response)
                    session=r['session_id'];turns.append({'question':q,'http_ms':(time.perf_counter()-start)*1000,'reply':r})
                except Exception as e:turns.append({'question':q,'http_ms':(time.perf_counter()-start)*1000,'error':type(e).__name__});break
            row={'id':case['id'],'case':case,'arm':arm,'repeat':1,'turns':turns};row['judge']=judge(row);write_json(path,row);return row
        rows=[]
        with http_server(app,threaded=True) as base:
            with ThreadPoolExecutor(max_workers=3) as pool:
                for f in as_completed([pool.submit(one,base,c) for c in cases]):rows.append(f.result());print(arm,len(rows),'/',len(cases),flush=True)
        results[arm]=summarize(rows)
    normal=[load_json(ROOT/'local/workbench-v4/after/1'/(c['id'].replace(':','-')+'.json')) for c in cases]
    write_json(out/'ablation.json',{'protocol':protocol,'full':summarize(normal),**results})


if __name__=='__main__':main()
