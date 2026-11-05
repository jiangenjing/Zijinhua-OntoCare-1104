"""Retrieval benchmark with disjoint source groups and multiple relevant IDs."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
from pathlib import Path
import re
import sys
import time
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ontocare.data import load_json,write_json,digest
from ontocare.customer_retrieval import Retriever

def code(query):
 hits=re.findall(r'(?:error|code|错误码?|故障码?)\s*[:：#-]?\s*(\d{3,5})|\b(\d{3,5})\s*(?:error|错误|故障)',query,re.I)
 return next(x for x in hits[-1] if x) if hits else None

def metrics(results):
 n=len(results)
 return {'n':n,**{f'recall_at_{k}':sum(any(i in r['gold_ids'] for i in r['ranked_ids'][:k]) for r in results)/n if n else None for k in [1,3,6]},'mrr':sum(next((1/(j+1) for j,x in enumerate(r['ranked_ids']) if x in r['gold_ids']),0) for r in results)/n if n else None}

def run(label='parent',splits=('development','validation')):
 cases=[c for c in load_json(ROOT/'evaluation/customer-service-v2/cases.json')['cases'] if c['kind']=='knowledge' and c['split'] in splits]
 r=Retriever();queries=[c['question'] for c in cases]
 rewrite_records=[]
 embedding_queries=queries
 if not label.startswith('parent'):
  from ontocare.customer_query_rewrite import rewrite
  translated={}
  with ThreadPoolExecutor(max_workers=4) as pool:
   fs={pool.submit(rewrite,q,ROOT):q for q in queries}
   for f in as_completed(fs):
    q=fs[f];target,info=f.result();translated[q]=target;rewrite_records.append({'query':q,'english':target,**info})
    if len(rewrite_records)%30==0:print('rewritten',len(rewrite_records),'/',len(queries),flush=True)
  embedding_queries=[translated[q] for q in queries]
  write_json(ROOT/f'local/customer-service-v2/rewrites-{label}.json',rewrite_records)
 t=time.perf_counter()
 if r.vectors is not None:
  vectors=r._encoder(r.vector_meta['revision']).encode(['query: '+q for q in embedding_queries],batch_size=32,normalize_embeddings=True,show_progress_bar=True)
  r.query_vectors.update(zip(embedding_queries,vectors))
 embedding_ms=(time.perf_counter()-t)*1000
 rows=[]
 for case in cases:
  t=time.perf_counter();hit=r.search(case['question'],case['pn'],code(case['question']),allow_rewrite=not label.startswith('parent'),ranking_profile='title_focused' if 'title-focused' in label else None);elapsed=(time.perf_counter()-t)*1000
  rows.append({**case,'ranked_ids':[d['id'] for d in hit['documents']],'retrieval_ms_warm_query_vector':elapsed,'mode':hit['mode']})
 groups={}
 for split in ['development','validation','holdout']:
  selected=[x for x in rows if x['split']==split];groups[split]=metrics(selected)
  for language in ['zh','en']:groups[split+'_'+language]=metrics([x for x in selected if x['language']==language])
 result={'label':label,'dataset_sha256':load_json(ROOT/'evaluation/customer-service-v2/manifest.json')['case_sha256'],'metrics':groups,'embedding_batch_ms':embedding_ms,'rewrite_calls':sum(len(x.get('model_calls',[])) for x in rewrite_records),'latency_note':'ranking times use precomputed query vectors; full HTTP evaluation separately includes actual query encoding','cases':rows}
 write_json(ROOT/f'local/customer-service-v2/retrieval-{label}.json',result);write_json(ROOT/f'reports/customer-service-v2/retrieval-{label}-metrics.json',{k:v for k,v in result.items() if k!='cases'})
 print(json.dumps(result['metrics'],ensure_ascii=False,indent=2),flush=True)
if __name__=='__main__':run(sys.argv[1] if len(sys.argv)>1 else 'parent',tuple(sys.argv[2:]) or ('development','validation'))
