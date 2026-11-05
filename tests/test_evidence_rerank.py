from copy import deepcopy
import json
from ontocare import evidence_rerank
from ontocare.query_rewrite import validate,rewrite_one
import pytest


def test_reranker_cannot_invent_source_or_mutate_evidence(tmp_path,monkeypatch):
    (tmp_path/'local').mkdir()
    docs=[{'id':'a','title':'A','content':'verified original A'},{'id':'b','title':'B','content':'verified original B'}]
    original=deepcopy(docs)
    class Fake:
        def __init__(self,**kw):self.model='test';self.calls=[]
        def chat(self,messages):return {'content':json.dumps({'best_id':'made-up','reason':'unsupported'})}
    monkeypatch.setattr(evidence_rerank,'Provider',Fake)
    ranked,info=evidence_rerank.rerank('question',docs,tmp_path)
    assert ranked==original and docs==original
    assert info['status']=='fallback_original_ranking'


def test_rerank_cache_binds_source_content_and_prompt(tmp_path,monkeypatch):
    (tmp_path/'local').mkdir();calls=[]
    docs=[{'id':'a','title':'A','content':'original A'},{'id':'b','title':'B','content':'original B'}]
    class Fake:
        def __init__(self,**kw):self.model='test';self.calls=[]
        def chat(self,messages):calls.append(messages);return {'content':json.dumps({'best_id':'b','reason':'B answers the symptom'})}
    monkeypatch.setattr(evidence_rerank,'Provider',Fake)
    ranked,info=evidence_rerank.rerank('question',docs,tmp_path)
    assert ranked[0]['id']=='b' and not info['cache_hit']
    assert evidence_rerank.rerank('question',docs,tmp_path)[1]['cache_hit']
    changed=deepcopy(docs);changed[1]['content']='new version B'
    evidence_rerank.rerank('question',changed,tmp_path)
    evidence_rerank.rerank('question',docs,tmp_path,prompt='different contract')
    assert len(calls)==3


def test_translation_preserves_models_codes_numbers_and_does_not_call_for_english(tmp_path):
    with pytest.raises(ValueError):validate('我的T2353报错3212','My T2352 has error 3212')
    with pytest.raises(ValueError):validate('我的T2353报错3212','My T2353 does not work')
    q='My T2353 has error 3212'
    assert rewrite_one(q,tmp_path)==(q,{'used':False,'status':'already_english','model_calls':[]})
