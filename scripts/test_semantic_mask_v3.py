"""Remove already-filtered model names from similarity text, preserving full evidence."""
from pathlib import Path
import argparse
import re
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
from ontocare.data import load_json,write_json,digest
from ontocare.grounded_eval import Experiment
from ontocare.ranking import PROFILES
from train_reranker_v3 import fit,evaluate

def mask(s):
    s=re.sub(r'(?<![A-Z0-9])T[0-9][A-Z0-9]{3}(?![A-Z0-9])',' ',s,flags=re.I)
    s=re.sub(r'\b(?:eufy|omni|E25|E28|C20|C10|X10\s*Pro|S1\s*Pro|SoloCam\s*S340)\b',' ',s,flags=re.I)
    return re.sub(r'\s+',' ',s).strip()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--legacy',action='store_true');args=parser.parse_args()
    exp=Experiment(ROOT);r=exp.r;enc=r._encoder(r.vector_meta['revision']);out=ROOT/'reports/reranker-v3';cache=ROOT/'local/reranker-v3/masked-index.npz'
    docs=r.docs;texts=[];ids=[]
    for i,d in enumerate(docs):
        words=mask(d['title']+'\n'+d['content']).split()
        for start in range(0,max(1,len(words)),160):texts.append('passage: '+mask(d['title'])+'\n'+' '.join(words[start:start+200]));ids.append(i)
    stamp=digest([texts,[d['title'] for d in docs],r.vector_meta])
    if cache.exists() and load_json(cache.with_suffix('.json'))['sha256']==stamp:
        z=np.load(cache);tv=z['title'];bv=z['body']
    else:
        tv=enc.encode(['passage: '+mask(d['title']) for d in docs],batch_size=48,normalize_embeddings=True,show_progress_bar=False);bv=enc.encode(texts,batch_size=48,normalize_embeddings=True,show_progress_bar=False)
        np.savez_compressed(cache,title=tv,body=bv,ids=ids);write_json(cache.with_suffix('.json'),{'sha256':stamp,'revision':r.vector_meta['revision']})
    sets={}
    for split in (['legacy'] if args.legacy else ['development','validation']):
        if split=='legacy':
            original=load_json(ROOT/'reports/grounded-eval/candidate-reserve.json')['cases']
            original=[{**c,'original_query':c['query'],'query':c['search_query'],'split':'exposed_regression'} for c in original]
        else:original=load_json(ROOT/'reports/grounded-eval'/('translated-'+split+'.json'))['cases']
        questions=[c['query'] for c in original]
        qv=enc.encode(['query: '+q for q in questions],batch_size=48,normalize_embeddings=True,show_progress_bar=False);mv=enc.encode(['query: '+mask(q) for q in questions],batch_size=48,normalize_embeddings=True,show_progress_bar=False);r.query_vectors.update(zip(questions,qv));rows=[]
        for c,m in zip(original,mv):
            f=exp.index.features(c['query'],c['pn']);mt=tv@m;mb=np.full(len(docs),-1.);np.maximum.at(mb,np.asarray(ids),bv@m)
            allowed=f['eligible'];oldscore=.35*f['title']+.5*f['body']+.15*f['lexical'];newscore=.35*mt+.5*mb+.15*f['lexical']
            ordered=sorted(allowed,key=lambda i:-oldscore[i])[:20];extra=sorted(allowed,key=lambda i:-newscore[i])[:20];pool=list(dict.fromkeys(ordered+extra))
            features=[[f['title'][i],f['body'][i],f['lexical'][i],mt[i],mb[i],np.log1p(len(docs[i]['content'].split())),newscore[i]] for i in pool]
            rows.append({**c,'pool_ids':[docs[i]['id'] for i in pool],'features':np.asarray(features,dtype=float).tolist()})
        sets[split]=rows
    if args.legacy:
        selected=load_json(out/'masked-selection.json')['selected'];result=evaluate(sets['legacy'],selected['weights'])
        result['scope']='exposed historical regression; weights selected on original validation only'
        write_json(out/'masked-legacy.json',result);print(result['metrics'],flush=True);return
    trials=[]
    for penalty in [.01,.1,1.]:
        w=fit(sets['development'],penalty);a=evaluate(sets['development'],w);b=evaluate(sets['validation'],w)
        t={'name':'masked-'+str(penalty),'weights':w,'development':a['metrics'],'validation':b['metrics'],'features':['original_title','original_body','title_bm25','masked_title','masked_body','length','masked_fusion']};trials.append(t);write_json(out/(t['name']+'-validation.json'),b)
    write_json(out/'masked-selection.json',{'trials':trials,'selected':max(trials,key=lambda x:x['validation']['recall_at_1'])});print(trials,flush=True)

if __name__=='__main__':main()
