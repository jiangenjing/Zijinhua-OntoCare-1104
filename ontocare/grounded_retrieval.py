"""Selected source-scoped retrieval arm; no benchmark labels are read at runtime."""
from .customer_retrieval import Retriever as OriginalRetriever
from .ranking import RankingIndex, PROFILES
from .query_rewrite import rewrite_one


class Retriever(OriginalRetriever):
    def search(self, query, pn=None, error_code=None, limit=6, use_scope=True,
               allow_rewrite=False, ranking_profile=None):
        search_query = query
        info = {'used': False, 'status': 'disabled', 'model_calls': []}
        if allow_rewrite:
            search_query, info = rewrite_one(query, self.root)
        if ranking_profile is not None and self.vectors is not None:
            if ranking_profile not in PROFILES:
                raise ValueError('Unknown ranking profile')
            if not hasattr(self, 'grounded_index'):
                self.grounded_index = RankingIndex(self)
            result = self.grounded_index.search(search_query, pn, error_code, limit, use_scope, PROFILES[ranking_profile])
        else:
            result = super().search(search_query, pn, error_code, limit, use_scope)
        return {**result, 'query_rewrite': info, 'search_query': search_query}
