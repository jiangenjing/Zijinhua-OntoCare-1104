"""Candidate: the rank verifier can read the same approved bodies as generation."""
from .grounded_retrieval import Retriever as HybridRetriever
from .reference_agent import ReferenceRetriever
from .evidence_rerank import rerank, VERIFY_PROMPT


class Retriever(ReferenceRetriever):
    def search(self, query, pn=None, error_code=None, limit=6, use_scope=True,
               allow_rewrite=False, ranking_profile=None):
        result = HybridRetriever.search(self, query, pn, error_code, limit, use_scope, allow_rewrite, ranking_profile)
        documents = self.references.attach(result['documents'], pn)
        if allow_rewrite:
            views = [{**d, 'content': d['content'] + ''.join('\nOfficial reference body (' + ref['url'] + '):\n' + ref['text'] for ref in d['references'])} for d in documents]
            ranked, info = rerank(result['search_query'], views, self.root, prompt=VERIFY_PROMPT)
            by_id = {d['id']: d for d in documents}
            # Never replace a source-cell quote/hash with the ranking-only combined view.
            documents = [by_id[d['id']] for d in ranked]
            result = {**result, 'evidence_rerank': info, 'query_rewrite': {**result['query_rewrite'], 'model_calls': result['query_rewrite'].get('model_calls', []) + info.get('model_calls', [])}}
        return {**result, 'documents': documents, 'reference_snapshot_sha256': self.references.sha256}
