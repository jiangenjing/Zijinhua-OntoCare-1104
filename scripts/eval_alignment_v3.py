"""Evaluate a source-only alignment candidate; confirmation remains locked."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import argparse
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ontocare.data import load_json,write_json,digest
from ontocare.grounded_eval import read_split
from ontocare.aligned_retrieval import Retriever,PROMPT
from ontocare.benchmark_metrics import retrieval_scores,summarize_retrieval

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--split',choices=['development','validation','legacy'],default='development');parser.add_argument('--method',choices=['alignment','intent'],default='alignment');args=parser.parse_args()
    if args.split=='legacy':cases=load_json(ROOT/'evaluation/grounded-reserve-v2/final.json')['cases']
    else:cases=read_split(args.split)
    if args.split=='development':cases=sorted(cases,key=lambda c:digest(c['family_id']))[:30]
    selected_retriever=Retriever
    if args.method=='intent':
        from ontocare.intent_retrieval import Retriever as IntentRetriever
        selected_retriever=IntentRetriever
    r=selected_retriever(ROOT);r._encoder(r.vector_meta['revision']);folder=ROOT/'local/reranker-v3'/args.method/args.split;folder.mkdir(parents=True,exist_ok=True);rows=[]
    def one(c,lang):
        q=c['questions'][lang];key=c['id']+':'+lang;p=folder/(key.replace(':','-')+'.json')
        if p.exists():return load_json(p)
        result=r.search(q,c['pn'],allow_rewrite=True,ranking_profile='body_hybrid');ids=[d['id'] for d in result['documents']]
        row={'id':key,'family_id':c['family_id'],'split':args.split,'pn':c['pn'],'language':lang,'original_query':q,'query':q,'gold_ids':c['gold_ids'],'ranked_ids':ids,'scores':retrieval_scores(c['gold_ids'],ids),'alignment':result.get('intent_alignment',result.get('evidence_alignment')),'candidate_count':result.get('distinct_candidate_count'),'retrieval_calls':result.get('query_rewrite',{}).get('model_calls',[])};write_json(p,row);return row
    with ThreadPoolExecutor(max_workers=3) as pool:
        for f in as_completed([pool.submit(one,c,lang) for c in cases for lang in ['zh','en']]):
            rows.append(f.result())
            if len(rows)%20==0:print(args.split,len(rows),'/',len(cases)*2,flush=True)
    if args.method=='intent':
        from ontocare.intent_retrieval import TITLE_PROMPT,BODY_PROMPT
        prompt_hash=digest([TITLE_PROMPT,BODY_PROMPT])
    else:prompt_hash=digest(PROMPT)
    result={'name':args.method,'prompt_sha256':prompt_hash,'metrics':summarize_retrieval(rows),'cases':sorted(rows,key=lambda c:c['id']),'scope':'legacy is exposed regression; development/validation used for candidate selection; no confirmation queries read'}
    write_json(ROOT/'reports/reranker-v3'/(args.method+'-'+args.split+'.json'),result);print(result['metrics'],flush=True)
if __name__=='__main__':main()
