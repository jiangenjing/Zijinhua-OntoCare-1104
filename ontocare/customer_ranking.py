"""Versioned, source-scoped retrieval candidates; never read evaluation labels here."""
import collections
import math
import re
from pathlib import Path
from threading import RLock

import numpy as np

from .data import digest,load_json,write_json
from .customer_retrieval import tokens

PROFILES={
 'title_dense':{'title':1.,'body':0.,'lexical':0.},
 'balanced_dense':{'title':.65,'body':.35,'lexical':0.},
 'title_hybrid':{'title':.65,'body':.20,'lexical':.15},
 'title_focused':{'title':.82,'body':.10,'lexical':.08},
 'body_hybrid':{'title':.35,'body':.50,'lexical':.15},
}


class RankingIndex:
    def __init__(self,retriever):
        self.r=retriever;self.lock=RLock();self.title_vectors=None
        self.titles=[collections.Counter(tokens(d['title'])) for d in retriever.docs]
        self.df=collections.Counter(t for c in self.titles for t in c)
        self.avg=sum(sum(c.values()) for c in self.titles)/len(self.titles)
        self.positions={d['id']:i for i,d in enumerate(retriever.docs)}
        self.chunk_positions=[self.positions[k] for k in retriever.vector_ids] if retriever.vector_ids else []

    def prepare_titles(self):
        if self.title_vectors is not None:return
        if self.r.vectors is None:raise ValueError('Dense ranking requires the existing E5 index')
        path=Path(self.r.root)/'local/ranking-title-vectors.npz';meta=path.with_suffix('.json')
        stamp=digest({'titles':[d['title'] for d in self.r.docs],'revision':self.r.vector_meta['revision']})
        with self.lock:
            if path.exists() and meta.exists() and load_json(meta).get('sha256')==stamp:
                self.title_vectors=np.load(path,allow_pickle=False)['vectors']
            else:
                self.title_vectors=self.r._encoder(self.r.vector_meta['revision']).encode(['passage: '+d['title'] for d in self.r.docs],batch_size=48,normalize_embeddings=True,show_progress_bar=False)
                np.savez_compressed(path,vectors=self.title_vectors);write_json(meta,{'sha256':stamp,'model':self.r.vector_meta['model'],'revision':self.r.vector_meta['revision']})

    def features(self,query,pn,error_code=None,use_scope=True):
        self.prepare_titles()
        if query not in self.r.query_vectors:
            with self.lock:
                self.r.query_vectors[query]=self.r._encoder(self.r.vector_meta['revision']).encode(['query: '+query],normalize_embeddings=True)[0]
        q=self.r.query_vectors[query]
        body=np.full(len(self.r.docs),-1.,dtype=float)
        np.maximum.at(body,np.array(self.chunk_positions),self.r.vectors@q)
        title=self.title_vectors@q
        qt=tokens(re.sub(r'(?<![A-Z0-9])T[0-9][A-Z0-9]{3}(?![A-Z0-9])',' ',query,flags=re.I));n=len(self.r.docs)
        lexical=[]
        for c in self.titles:
            length=sum(c.values())
            score=sum(math.log(1+(n-self.df[t]+.5)/(self.df[t]+.5))*c[t]*2.5/(c[t]+1.5*(.25+.75*length/self.avg)) for t in qt if c[t])
            lexical.append(score/(score+10))
        eligible=[i for i,d in enumerate(self.r.docs) if (not use_scope or pn in d['pns']) and (not error_code or re.search(r'(?<!\d)'+re.escape(error_code)+r'(?!\d)',d['title']))]
        return {'title':title,'body':body,'lexical':np.array(lexical),'eligible':eligible}

    def search(self,query,pn,error_code=None,limit=6,use_scope=True,weights=None,features=None):
        if use_scope and not pn:return {'documents':[],'mode':'blocked_unknown_product'}
        weights=weights or PROFILES['title_hybrid']
        if set(weights)!={'title','body','lexical'} or any(not isinstance(v,(int,float)) or not 0<=v<=1 for v in weights.values()) or abs(sum(weights.values())-1)>1e-6:raise ValueError('Invalid fusion weights')
        f=features or self.features(query,pn,error_code,use_scope)
        score=sum(weights[k]*f[k] for k in weights)
        selected=sorted(f['eligible'],key=lambda i:(-score[i],self.r.docs[i]['id']))[:limit]
        return {'documents':[self.r.docs[i] for i in selected],'mode':'bm25_e5_weighted','pn_filter':pn,'error_filter':error_code,'ranking_contract':{'method':'normalized weighted E5 title/body cosine plus saturating title BM25','weights':weights,'policy':'PN and exact error-code scope are hard filters; no evaluation labels or saved gold query lookup'}}
