"""Freeze retrieval code, then run the untouched final split through the selected engine."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ontocare.data import digest,load_json,write_json
from ontocare.grounded_eval import read_split,Experiment
from ontocare.grounded_retrieval import Retriever
from ontocare.ranking import PROFILES
from ontocare.query_rewrite import PROMPT
from ontocare.benchmark_metrics import retrieval_scores,summarize_retrieval


def main():
    out=ROOT/'reports/grounded-eval';cache=ROOT/'local/eval-v2/final-retrieval';cache.mkdir(parents=True,exist_ok=True)
    files=['ontocare/grounded_retrieval.py','ontocare/ranking.py','ontocare/query_rewrite.py','ontocare/customer_retrieval.py','evaluation/grounded-1200/baseline_retrieval.py']
    stamp={'files':{f:digest((ROOT/f).read_bytes()) for f in files},'weights':PROFILES['body_hybrid'],'rewrite_prompt_sha256':digest(PROMPT),'dataset':load_json(ROOT/'evaluation/grounded-1200/manifest.json'),'opened_final_after_freeze':True,'target':.90}
    freeze=out/'release-freeze.json'
    if freeze.exists() and load_json(freeze)!=stamp:raise ValueError('Frozen retrieval release changed; do not retune on this final set')
    write_json(freeze,stamp)
    # This is the first point at which final questions are made available to this process.
    cases=read_split('final',ROOT,allow_final=True)
    exp=Experiment(ROOT);baseline=exp.evaluate(cases);write_json(out/'baseline-final.json',baseline)
    r=Retriever(ROOT)
    # Share the already-loaded pinned encoder; actual query translations are individual runtime calls.
    r.encoder=exp.r.encoder
    rows=[]
    def one(c,lang):
        q=c['questions'][lang];key=c['id']+':'+lang;path=cache/(key.replace(':','-')+'.json')
        if path.exists():return load_json(path)
        start=time.perf_counter()
        result=r.search(q,c['pn'],limit=6,allow_rewrite=True,ranking_profile='body_hybrid')
        ranked=[d['id'] for d in result['documents']]
        row={'id':key,'family_id':c['family_id'],'split':'final','language':lang,'pn':c['pn'],'query':q,'gold_ids':c['gold_ids'],'source_id':c['source_id'],'ranked_ids':ranked,'scores':retrieval_scores(c['gold_ids'],ranked),'search_query':result['search_query'],'query_rewrite':result['query_rewrite'],'retrieval_wall_ms':(time.perf_counter()-start)*1000}
        write_json(path,row);return row
    with ThreadPoolExecutor(max_workers=4) as pool:
        for f in as_completed([pool.submit(one,c,lang) for c in cases for lang in ['zh','en']]):
            rows.append(f.result())
            if len(rows)%20==0:print('final retrieval',len(rows),'/300',flush=True)
    rows.sort(key=lambda r:r['id'])
    result={'profile':'translated_body_hybrid','freeze_sha256':digest(stamp),'metrics':summarize_retrieval(rows),'cases':rows,'scope':'Actual production retriever and single-query rewrite; supplied PN. Retrieval component test, not end-to-end answer resolution.'}
    write_json(out/'candidate-final.json',result)
    summary={'baseline':baseline['metrics'],'candidate':result['metrics'],'target_passed':result['metrics']['hit_at_1']>=.90,'freeze_sha256':digest(stamp),'final_used_for_tuning':False}
    write_json(out/'final-comparison.json',summary)
    print(json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
