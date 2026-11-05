"""Fit seven global ranking weights on development only; validation selects candidates."""
import argparse
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
import torch
from ontocare.data import load_json,write_json,digest
from ontocare.grounded_eval import Experiment
from ontocare.ranking import PROFILES
from ontocare.pair_ranker import PairRanker,FEATURES,normalize,order
from ontocare.benchmark_metrics import retrieval_scores,summarize_retrieval

OUT=ROOT/'reports/reranker-v3';LOCAL=ROOT/'local/reranker-v3'

def prepare(exp,split,model_name,config,source_rows=None):
    rows=source_rows if source_rows is not None else load_json(ROOT/'reports/grounded-eval'/('translated-'+split+'.json'))['cases']
    questions=list(dict.fromkeys(r['query'] for r in rows));encoder=exp.r._encoder(exp.r.vector_meta['revision'])
    encoded=encoder.encode(['query: '+q for q in questions],batch_size=48,normalize_embeddings=True,show_progress_bar=False)
    exp.r.query_vectors.update(zip(questions,encoded));ce=None;result=[]
    directory=LOCAL/(model_name+'-'+split);directory.mkdir(parents=True,exist_ok=True)
    for n,c in enumerate(rows):
        revision_key=config['revision']+':'+config['dtype'] if config.get('dtype') else config['revision']
        key=digest([c['query'],c['pn'],revision_key,config.get('delta_sha256'),'best-200-word-window-384',exp.r.vector_meta])
        path=directory/(key+'.json')
        if path.exists():record=load_json(path)
        else:
            f=exp.index.features(c['query'],c['pn']);found=exp.index.search(c['query'],c['pn'],limit=20,weights=PROFILES['body_hybrid'],features=f);docs=found['documents']
            if ce is None:ce=PairRanker(exp.r,config)
            started=time.perf_counter();features=ce.features(c['query'],docs,f)
            record={'id':c['id'],'family_id':c['family_id'],'split':c['split'],'language':c['language'],'pn':c['pn'],'query':c['query'],'source_id':c['source_id'],'gold_ids':c['gold_ids'],'pool_ids':[d['id'] for d in docs],'features':features.tolist(),'pair_model_ms':(time.perf_counter()-started)*1000}
            write_json(path,record)
        # Equal translated text can occur in both languages; cache features, never case labels.
        record={**record,**{k:c[k] for k in ['id','family_id','split','language','pn','query','source_id','gold_ids']}}
        result.append(record)
        if (n+1)%50==0:print(model_name,split,'features',n+1,'/',len(rows),flush=True)
    return result

def evaluate(rows,weights):
    records=[]
    for c in rows:
        ids=[c['pool_ids'][i] for i in order(c['features'],weights)][:6]
        records.append({k:c[k] for k in ['id','family_id','split','language','pn','query','source_id','gold_ids']}|{'ranked_ids':ids,'scores':retrieval_scores(c['gold_ids'],ids)})
    return {'metrics':summarize_retrieval(records),'cases':records}

def fit(rows,penalty):
    usable=[c for c in rows if set(c['pool_ids'])&set(c['gold_ids'])]
    sizes={len(c['pool_ids']) for c in usable}
    # Variable pool sizes are padded and masked, never discarded from reporting.
    width=max(sizes);x=np.zeros((len(usable),width,len(FEATURES)),dtype=np.float32);gold=np.zeros((len(usable),width),bool);valid=gold.copy()
    for i,c in enumerate(usable):
        size=len(c['pool_ids']);x[i,:size]=normalize(c['features']);valid[i,:size]=True;gold[i,:size]=[k in c['gold_ids'] for k in c['pool_ids']]
    x=torch.from_numpy(x);gold=torch.from_numpy(gold);valid=torch.from_numpy(valid)
    torch.manual_seed(20261103);p=torch.nn.Parameter(torch.zeros(len(FEATURES)));opt=torch.optim.Adam([p],lr=.03)
    for _ in range(500):
        weights=torch.softmax(p,dim=0);scores=(x@weights)*5;scores=scores.masked_fill(~valid,-10000)
        loss=(torch.logsumexp(scores,1)-torch.logsumexp(scores.masked_fill(~gold,-10000),1)).mean()+penalty*(weights**2).sum()
        opt.zero_grad();loss.backward();opt.step()
    return torch.softmax(p,dim=0).detach().numpy().tolist()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--model',choices=['multilingual','english','bge'],default='english');args=ap.parse_args()
    OUT.mkdir(exist_ok=True);config=load_json(LOCAL/{'english':'english-model.json','multilingual':'model.json','bge':'bge-model.json'}[args.model]);exp=Experiment(ROOT)
    dev=prepare(exp,'development',args.model,config);val=prepare(exp,'validation',args.model,config)
    variants={'ce_title':[0,0,0,1,0,0,0],'ce_passage':[0,0,0,0,1,0,0]}
    for penalty in [.01,.1,1.]:variants['learned-'+str(penalty)]=fit(dev,penalty)
    history=[]
    for name,weights in variants.items():
        a=evaluate(dev,weights);b=evaluate(val,weights);write_json(OUT/(args.model+'-'+name+'-development.json'),a);write_json(OUT/(args.model+'-'+name+'-validation.json'),b)
        history.append({'name':args.model+'-'+name,'features':FEATURES,'weights':weights,'development':a['metrics'],'validation':b['metrics'],'backbone':{k:config[k] for k in ['model','revision']},'trained_backbone':False,'fit_scope':'development queries and labels only; seven global feature weights, no source-ID lookup'})
    chosen=max(history,key=lambda x:(x['validation']['recall_at_1'],x['validation']['hit_at_1']))
    write_json(OUT/(args.model+'-selection.json'),{'trials':history,'selected':chosen});print(json.dumps(chosen,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
