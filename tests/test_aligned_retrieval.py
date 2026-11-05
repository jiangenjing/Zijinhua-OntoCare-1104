from copy import deepcopy
import json

from ontocare import aligned_retrieval as module


def test_selection_requires_existing_source_and_verbatim_support(tmp_path, monkeypatch):
    (tmp_path / 'local').mkdir()
    docs = [{'id': 'a', 'title': 'A', 'content': 'Verified instructions for the requested product.'},
            {'id': 'b', 'title': 'B', 'content': 'Different verified source for the same product.'}]
    original = deepcopy(docs)

    class Fake:
        def __init__(self, **kwargs):
            self.model, self.calls = 'test', []

        def chat(self, messages):
            return {'content': json.dumps({'intent': 'task', 'best_id': 'invented',
                                           'reason': 'claim', 'source_quote': docs[0]['content']})}

    monkeypatch.setattr(module, 'Provider', Fake)
    ordered, info = module.choose('question', 'question', docs, tmp_path)
    assert ordered == original and docs == original
    assert info['status'] == 'fallback_original_order'


def test_selection_cache_binds_original_question_and_actual_evidence(tmp_path, monkeypatch):
    (tmp_path / 'local').mkdir()
    calls = []
    docs = [{'id': 'a', 'title': 'A', 'content': 'Verified instructions for the requested product.'},
            {'id': 'b', 'title': 'B', 'content': 'Different verified source for the same product.'}]

    class Fake:
        def __init__(self, **kwargs):
            self.model, self.calls = 'test', []

        def chat(self, messages):
            calls.append(messages)
            return {'content': json.dumps({'intent': 'task', 'best_id': 'b',
                                           'reason': 'source supports request', 'source_quote': docs[1]['content']})}

    monkeypatch.setattr(module, 'Provider', Fake)
    ordered, info = module.choose('original request', 'pivot', docs, tmp_path)
    assert ordered[0]['id'] == 'b' and not info['cache_hit']
    assert module.choose('original request', 'pivot', docs, tmp_path)[1]['cache_hit']
    module.choose('different original request', 'pivot', docs, tmp_path)
    changed = deepcopy(docs)
    changed[0]['content'] += ' New source version.'
    module.choose('original request', 'pivot', changed, tmp_path)
    assert len(calls) == 3


def test_pool_dedup_does_not_mutate_source_or_bypass_product_filter(monkeypatch):
    documents = [{'id': 'a', 'content': 'Original body'},
                 {'id': 'b', 'content': ' original   BODY '},
                 {'id': 'c', 'content': 'Another body'}]
    received = []

    def search(self, query, pn, error_code, limit, use_scope, allow_rewrite, ranking_profile):
        received.append((pn, error_code, use_scope))
        return {'documents': documents}

    monkeypatch.setattr(module.HybridRetriever, 'search', search)
    retriever = object.__new__(module.Retriever)
    result = retriever.search('question', 'T2353', error_code='3212')
    assert [d['id'] for d in result['documents']] == ['a', 'c']
    assert received == [('T2353', '3212', True)]
    assert len(documents) == 3
