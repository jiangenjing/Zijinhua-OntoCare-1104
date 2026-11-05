"""A single new-source holdout after a validation-gated, frozen v2 release."""
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ontocare.data import load_json,write_json,digest
from ontocare.grounded_eval import Experiment
from ontocare.grounded_retrieval_v2 import Retriever
from ontocare.benchmark_metrics import retrieval_scores,summarize_retrieval

def main():
    out=ROOT/'reports/grounded-eval';cache=ROOT/'local/eval-v2/reserve';cache.mkdir(parents=True,exist_ok=True)
    validation=load_json(out/'verify-validation.json')['metrics']
    old=load_json(out/'translated-validation.json')['metrics']
    if validation['hit_at_1']<old['hit_at_1']:raise ValueError('V2 failed validation gate; reserve remains unopened')
    names=['ontocare/grounded_retrieval_v2.py','ontocare/evidence_rerank.py','ontocare/grounded_retrieval.py','ontocare/ranking.py','ontocare/query_rewrite.py','ontocare/customer_retrieval.py']
    manifest=load_json(ROOT/'evaluation/grounded-reserve-v2/manifest.json')
    frozen={'runtime':{n:digest((ROOT/n).read_bytes()) for n in names},'manifest':manifest,'validation_gate':validation,'prior_final_failure':.88,'target':.90,'test_policy':'all 150 pre-reserved source families; one new test after freeze; no test feedback to tuning'}
    p=out/'release-freeze-v2.json'
    if p.exists() and load_json(p)!=frozen:raise ValueError('V2 frozen code changed')
    write_json(p,frozen)
    payload=load_json(ROOT/'evaluation/grounded-reserve-v2/final.json')
    if digest(payload)!=manifest['split_sha256']['final']:raise ValueError('Reserve split changed')
    cases=payload['cases'];exp=Experiment(ROOT);base=exp.evaluate(cases)
    write_json(out/'baseline-reserve.json',base)
    r=Retriever(ROOT);r.encoder=exp.r.encoder;rows=[]
    def one(c,lang):
        key=c['id']+':'+lang;p=cache/(key.replace(':','-')+'.json')
        if p.exists():return load_json(p)
        q=c['questions'][lang];result=r.search(q,c['pn'],allow_rewrite=True,ranking_profile='body_hybrid')
        ids=[d['id'] for d in result['documents']]
        row={'id':key,'family_id':c['family_id'],'split':'reserve_final','pn':c['pn'],'language':lang,'query':q,'search_query':result['search_query'],'source_id':c['source_id'],'gold_ids':c['gold_ids'],'ranked_ids':ids,'scores':retrieval_scores(c['gold_ids'],ids),'pre_rerank_ids':result['pre_rerank_ids'],'query_rewrite':result['query_rewrite'],'evidence_rerank':result['evidence_rerank']};write_json(p,row);return row
    with ThreadPoolExecutor(max_workers=4) as pool:
        for f in as_completed([pool.submit(one,c,lang) for c in cases for lang in ['zh','en']]):
            rows.append(f.result())
            if len(rows)%20==0:print('reserve test',len(rows),'/300',flush=True)
    rows.sort(key=lambda c:c['id']);result={'profile':'evidence_verify_v2','metrics':summarize_retrieval(rows),'cases':rows,'freeze_sha256':digest(frozen)};write_json(out/'candidate-reserve.json',result)
    ablation=[{**c,'ranked_ids':c['pre_rerank_ids'],'scores':retrieval_scores(c['gold_ids'],c['pre_rerank_ids'])} for c in rows]
    summary={'baseline':base['metrics'],'candidate':result['metrics'],'ablation_without_evidence_verify':summarize_retrieval(ablation),'target_passed':result['metrics']['hit_at_1']>=.90,'freeze_sha256':digest(frozen),'coverage_by_pn':manifest['coverage_by_pn'],'prior_final_failure_retained':.88,'used_for_tuning':False}
    write_json(out/'reserve-comparison.json',summary);print(json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
