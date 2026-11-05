"""Second release candidate: scoped weighted retrieval plus evidence reranking."""
from .grounded_retrieval import Retriever as HybridRetriever
from .evidence_rerank import rerank,VERIFY_PROMPT


class Retriever(HybridRetriever):
    def search(self,query,pn=None,error_code=None,limit=6,use_scope=True,allow_rewrite=False,ranking_profile=None):
        result=super().search(query,pn,error_code,limit,use_scope,allow_rewrite,ranking_profile)
        if allow_rewrite:
            before=[d['id'] for d in result['documents']]
            documents,info=rerank(result['search_query'],result['documents'],self.root,prompt=VERIFY_PROMPT)
            result={**result,'documents':documents,'evidence_rerank':info,'pre_rerank_ids':before}
            result['query_rewrite']={**result['query_rewrite'],'model_calls':result['query_rewrite'].get('model_calls',[])+info.get('model_calls',[])}
        return result
