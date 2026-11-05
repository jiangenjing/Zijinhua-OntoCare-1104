"""Development-only direct first-hit calibration; untouched confirmation is never read."""
from pathlib import Path
import argparse
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
from ontocare.data import load_json,write_json
from ontocare.benchmark_metrics import retrieval_scores,summarize_retrieval

def raw(x):
    x=np.asarray(x,dtype=np.float32).copy();x[:,3:5]/=12;x[:,5]/=10;return x

def read(model,split):
    expected=load_json(ROOT/'reports/grounded-eval'/('translated-'+split+'.json'))['cases'];cached={}
    for p in (ROOT/'local/reranker-v3'/(model+'-'+split)).glob('*.json'):
        c=load_json(p);cached[(c['pn'],c['query'])]=c
    rows=[]
    for c in expected:
        f=cached[(c['pn'],c['query'])];rows.append({**f,**{k:c[k] for k in ['id','family_id','split','language','pn','query','source_id','gold_ids']}})
    return rows

def evaluate(rows,w):
    result=[]
    for c in rows:
        indices=np.argsort(-(raw(c['features'])@w),kind='stable');ids=[c['pool_ids'][i] for i in indices[:6]]
        result.append({k:c[k] for k in ['id','family_id','split','language','pn','query','source_id','gold_ids']}|{'ranked_ids':ids,'scores':retrieval_scores(c['gold_ids'],ids)})
    return {'metrics':summarize_retrieval(result),'cases':result}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--model',default='english');a=ap.parse_args();dev=read(a.model,'development');val=read(a.model,'validation')
    width=max(len(c['pool_ids']) for c in dev);x=np.zeros((len(dev),width,7),np.float32);g=np.zeros((len(dev),width));valid=np.zeros((len(dev),width),bool)
    for i,c in enumerate(dev):
        n=len(c['pool_ids']);x[i,:n]=raw(c['features']);valid[i,:n]=True;g[i,:n]=[float(k in c['gold_ids'])/len(c['gold_ids']) for k in c['pool_ids']]
    rng=np.random.default_rng(20261103);weights=[np.array([.35,.5,.15,0,0,0,0]),np.array([0,0,0,0,0,0,1])]
    weights+=list(rng.dirichlet([4,5,2,.3,.3,.3,.3],size=3000));weights+=list(rng.dirichlet([1]*7,size=2000))
    trials=[]
    for i,w in enumerate(weights):
        scores=np.einsum('qdf,f->qd',x,w);scores[~valid]=-np.inf;best=scores.argmax(1);recall=float(g[np.arange(len(dev)),best].mean());hit=float((g[np.arange(len(dev)),best]>0).mean());trials.append({'trial':i,'weights':w.tolist(),'development_recall_at_1':recall,'development_hit_at_1':hit})
    # Validation is used only for the three best development configurations.
    selected=sorted(trials,key=lambda c:(-c['development_recall_at_1'],-c['development_hit_at_1'],np.count_nonzero(c['weights'])))[:3];out=ROOT/'reports/reranker-v3'
    for t in selected:
        r=evaluate(val,np.asarray(t['weights']));t['validation']=r['metrics'];write_json(out/f"{a.model}-raw-{t['trial']}-validation.json",r)
    result={'model':a.model,'transform':'original dense/BM25 raw; CE logits / 12; log length / 10; no per-query z-normalization','scope':'5002 seven-global-weight development calibration trials; only top three inspected on validation; no confirmation access','development_trials':trials,'validation_candidates':selected,'selected':max(selected,key=lambda c:c['validation']['recall_at_1'])};write_json(out/(a.model+'-raw-selection.json'),result)
    print([(t['trial'],t['development_hit_at_1'],t['validation']['hit_at_1'],t['validation']['recall_at_1']) for t in selected],flush=True)
if __name__=='__main__':main()
