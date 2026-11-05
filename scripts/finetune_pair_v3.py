"""Train only the final two layers of a small reranker on development hard negatives."""
import argparse
import json
from pathlib import Path
import random
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
import torch
from sentence_transformers import CrossEncoder
from safetensors.torch import save_file
from ontocare.data import load_json,write_json,digest
from ontocare.grounded_eval import Experiment
from ontocare.ranking import PROFILES
from ontocare.benchmark_metrics import retrieval_scores,summarize_retrieval
from train_reranker_v3 import prepare,evaluate,fit

LOCAL=ROOT/'local/reranker-v3';OUT=ROOT/'reports/reranker-v3'

def source_text(r,d,query):
    indices=[i for i,k in enumerate(r.vector_ids) if k==d['id']]
    q=r.query_vectors[query];best=max(range(len(indices)),key=lambda i:float(r.vectors[indices[i]]@q))
    words=(d['title']+'\n'+d['content']).split()
    return d['title']+'\n'+' '.join(words[best*160:best*160+200])

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--lr',type=float,default=1e-5);args=ap.parse_args()
    torch.manual_seed(20261103);random.seed(20261103);np.random.seed(20261103)
    cfg=load_json(LOCAL/'english-model.json');exp=Experiment(ROOT)
    dev=load_json(ROOT/'reports/grounded-eval/translated-development.json')['cases']
    queries=list(dict.fromkeys(c['query'] for c in dev));vec=exp.r._encoder(exp.r.vector_meta['revision']).encode(['query: '+q for q in queries],batch_size=48,normalize_embeddings=True,show_progress_bar=False);exp.r.query_vectors.update(zip(queries,vec))
    groups=[]
    for c in dev:
        candidates=exp.index.search(c['query'],c['pn'],limit=20,weights=PROFILES['body_hybrid'])['documents']
        positives=[exp.r.by_id[k] for k in c['gold_ids']]
        # Canonical-title siblings may be equivalent; do not force them into hard negatives.
        case=next(x for x in load_json(ROOT/'evaluation/grounded-1200/development.json')['cases'] if x['id']+':'+c['language']==c['id'])
        excluded=set(case['all_family_ids'])|set(c['gold_ids'])
        negatives=[d for d in candidates if d['id'] not in excluded][:3]
        if len(negatives)<3:continue
        docs=[positives[0]]+negatives
        groups.append({'query':c['query'],'passages':[source_text(exp.r,d,c['query']) for d in docs],'family_id':c['family_id']})
    write_json(OUT/'tail-training-protocol.json',{'source':'original development only','queries':len(groups),'source_families':len({c['family_id'] for c in groups}),'loss':'listwise cross entropy, one source positive and three same-product hard negatives; canonical-family siblings excluded from negatives','epochs':3,'learning_rate':args.lr,'backbone':{k:cfg[k] for k in ['model','revision']},'trainable':'encoder layers 4 and 5, pooler, classifier; early layers frozen','validation':'original validation only for checkpoint/config selection','confirmation_access':False,'human_gold_review':'pending'})
    model=CrossEncoder(cfg['path'],device='mps',max_length=384,activation_fn=torch.nn.Identity(),local_files_only=True,model_kwargs={'attn_implementation':'eager'})
    for name,p in model.model.named_parameters():p.requires_grad_('encoder.layer.4.' in name or 'encoder.layer.5.' in name or 'pooler.' in name or 'classifier.' in name)
    trained=[(n,p) for n,p in model.model.named_parameters() if p.requires_grad]
    print('trainable parameters',sum(p.numel() for _,p in trained),'queries',len(groups),flush=True)
    opt=torch.optim.AdamW([p for _,p in trained],lr=args.lr,weight_decay=.01)
    # Tokenize once on CPU; no validation or confirmation text participates in gradient updates.
    encoded=model.tokenizer([g['query'] for g in groups for _ in range(4)],[p for g in groups for p in g['passages']],padding='max_length',max_length=384,truncation=True,return_tensors='pt')
    for epoch in range(1,4):
        model.model.train();indices=list(range(len(groups)));random.shuffle(indices);losses=[]
        for start in range(0,len(indices),8):
            take=indices[start:start+8];flat=[4*i+j for i in take for j in range(4)]
            batch={k:v[flat].to('mps') for k,v in encoded.items()};scores=model.model(**batch).logits.reshape(len(take),4)
            loss=torch.nn.functional.cross_entropy(scores,torch.zeros(len(take),dtype=torch.long,device='mps'))
            opt.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_([p for _,p in trained],1.);opt.step();losses.append(float(loss.detach().cpu()))
            if (start//8)%20==0:print('epoch',epoch,'groups',start,'loss',losses[-1],flush=True)
        delta=LOCAL/f'english-tail-{args.lr}-epoch{epoch}.safetensors';save_file({n:p.detach().cpu().contiguous() for n,p in trained},str(delta))
        config={**cfg,'delta_path':str(delta),'delta_sha256':digest(delta.read_bytes())};write_json(LOCAL/f'english-tail-{args.lr}-epoch{epoch}-model.json',config)
        print('saved epoch',epoch,'mean loss',sum(losses)/len(losses),flush=True)
    del model;torch.mps.empty_cache()
    history=[]
    for epoch in range(1,4):
        name=f'tail-{args.lr}-epoch{epoch}';config=load_json(LOCAL/f'english-tail-{args.lr}-epoch{epoch}-model.json')
        a=prepare(exp,'development',name,config);b=prepare(exp,'validation',name,config)
        for penalty in [.01,.1]:
            weights=fit(a,penalty);x=evaluate(a,weights);y=evaluate(b,weights)
            row={'name':name+'-head'+str(penalty),'weights':weights,'development':x['metrics'],'validation':y['metrics'],'config':config,'train_scope':'development only; validation selection; confirmation unopened'}
            write_json(OUT/(row['name']+'-validation.json'),y);history.append(row);print(json.dumps({k:v for k,v in row.items() if k!='config'}),flush=True)
        write_json(OUT/f'tail-{args.lr}-selection.json',{'trials':history,'selected':max(history,key=lambda x:(x['validation']['recall_at_1'],x['validation']['hit_at_1']))})

if __name__=='__main__':main()
