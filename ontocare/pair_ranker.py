"""Source-scoped second-stage ranking. Runtime features never contain gold/source IDs."""
from pathlib import Path
from threading import RLock
import math
import numpy as np
import torch
from sentence_transformers import CrossEncoder
from .data import load_json,digest

FEATURES=['title_dense','body_dense','title_bm25','ce_title','ce_passage','length','initial_rank']


class PairRanker:
    def __init__(self,retriever,model_config):
        self.r=retriever;self.lock=RLock();self.config=model_config
        self.device='mps' if torch.backends.mps.is_available() else 'cpu'
        kwargs={'model_kwargs':{'dtype':torch.float16}} if model_config.get('dtype')=='float16' and self.device=='mps' else {}
        self.model=CrossEncoder(model_config['path'],device=self.device,max_length=384,activation_fn=torch.nn.Identity(),local_files_only=True,**kwargs)
        if model_config.get('delta_path'):
            from safetensors.torch import load_file
            delta=load_file(model_config['delta_path'])
            actual=self.model.model.state_dict()
            if any(k not in actual or actual[k].shape!=v.shape for k,v in delta.items()):raise ValueError('Reranker checkpoint does not match pinned base')
            self.model.model.load_state_dict(delta,strict=False)
        self.chunk_indices={}
        for i,key in enumerate(self.r.vector_ids):self.chunk_indices.setdefault(key,[]).append(i)

    def features(self,query,documents,index_features):
        q=self.r.query_vectors[query];pairs=[]
        for d in documents:
            indices=self.chunk_indices[d['id']]
            best=max(range(len(indices)),key=lambda i:float(self.r.vectors[indices[i]]@q))
            words=(d['title']+'\n'+d['content']).split()
            passage=d['title']+'\n'+' '.join(words[best*160:best*160+200])
            pairs.extend([(query,d['title']),(query,passage)])
        with self.lock:
            values=self.model.predict(pairs,batch_size=32,show_progress_bar=False).reshape(-1,2)
        pos={d['id']:i for i,d in enumerate(self.r.docs)};rows=[]
        for rank,(d,ce) in enumerate(zip(documents,values)):
            i=pos[d['id']]
            rows.append([index_features['title'][i],index_features['body'][i],index_features['lexical'][i],float(ce[0]),float(ce[1]),math.log1p(len(d['content'].split())),1/math.log2(rank+2)])
        return np.asarray(rows,dtype=np.float32)


def normalize(features):
    x=np.asarray(features,dtype=np.float32)
    return (x-x.mean(axis=0))/np.maximum(x.std(axis=0),1e-6)


def order(features,weights):
    x=normalize(features)
    return np.argsort(-(x@np.asarray(weights)),kind='stable').tolist()
