"""Recount the actual old workbench retrieval on the SAME exposed reserve."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import argparse
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ontocare.customer_retrieval import Retriever
from ontocare.data import load_json,write_json
from ontocare.benchmark_metrics import retrieval_scores,summarize_retrieval

parser=argparse.ArgumentParser();parser.add_argument('--current',action='store_true');args=parser.parse_args()
if args.current:
    from ontocare.grounded_retrieval_v2 import Retriever
profile='body_hybrid' if args.current else 'title_focused'
label='current-profile' if args.current else 'title-profile'
r=Retriever(ROOT);r._encoder(r.vector_meta['revision'])
cases=load_json(ROOT/'evaluation/grounded-reserve-v2/final.json')['cases'];rows=[]
def one(c,lang):
    path=ROOT/('local/workbench-v4-'+label+'-regression')/(c['id']+'-'+lang+'.json')
    if path.exists():return load_json(path)
    q=c['questions'][lang];result=r.search(q,c['pn'],allow_rewrite=True,ranking_profile=profile);ids=[d['id'] for d in result['documents']]
    row={'id':c['id']+':'+lang,'family_id':c['family_id'],'language':lang,'pn':c['pn'],'original_query':q,'gold_ids':c['gold_ids'],'ranked_ids':ids,'scores':retrieval_scores(c['gold_ids'],ids),'rewrite':result.get('query_rewrite')};write_json(path,row);return row
with ThreadPoolExecutor(max_workers=3) as pool:
    for f in as_completed([pool.submit(one,c,l) for c in cases for l in ['zh','en']]):
        rows.append(f.result())
        if len(rows)%30==0:print(label,len(rows),'/300',flush=True)
result={'scope':'Actual workbench retriever; same exposed historical reserve, PN supplied, unchanged gold; query/rerank caches may be reused, not a fresh final','profile':profile,'metrics':summarize_retrieval(rows),'cases':rows}
write_json(ROOT/'reports/workbench-v4'/(label+'-legacy.json'),result);print(result['metrics'],flush=True)
