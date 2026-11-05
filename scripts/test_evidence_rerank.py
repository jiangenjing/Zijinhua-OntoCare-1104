"""Development pilot and validation-only gate; never reads original final queries."""
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
from pathlib import Path
import sys
import argparse
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ontocare.data import load_json,write_json,digest
from ontocare.benchmark_metrics import retrieval_scores,summarize_retrieval
from ontocare.evidence_rerank import rerank,PROMPT,VERIFY_PROMPT


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--verify',action='store_true');args=parser.parse_args()
    prompt=VERIFY_PROMPT if args.verify else PROMPT;name='verify' if args.verify else 'rerank'
    docs={d['id']:d for d in load_json(ROOT/'data/knowledge.json')}
    out=ROOT/'reports/grounded-eval';cache=ROOT/'local/eval-v2'/name;cache.mkdir(parents=True,exist_ok=True)
    for split in ['development','validation']:
        source=load_json(out/('translated-'+split+'.json'))['cases']
        if split=='development':
            families=sorted({c['family_id'] for c in source},key=digest)[:30]
            source=[c for c in source if c['family_id'] in families]
        def one(c):
            path=cache/(c['id'].replace(':','-')+'.json')
            if path.exists():return load_json(path)
            ranked,info=rerank(c['query'],[docs[k] for k in c['ranked_ids']],prompt=prompt)
            ids=[d['id'] for d in ranked]
            row={**c,'ranked_ids':ids,'scores':retrieval_scores(c['gold_ids'],ids),'rerank':info};write_json(path,row);return row
        rows=[]
        with ThreadPoolExecutor(max_workers=4) as pool:
            for f in as_completed([pool.submit(one,c) for c in source]):
                rows.append(f.result())
                if len(rows)%20==0:print(split,'rerank',len(rows),'/',len(source),flush=True)
        result={'profile':name+'_v2','metrics':summarize_retrieval(rows),'cases':rows,'prompt_sha256':digest(prompt)}
        write_json(out/(name+'-'+split+'.json'),result)
        print(json.dumps({'split':split,'metrics':result['metrics']},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
