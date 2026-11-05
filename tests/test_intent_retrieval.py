from copy import deepcopy
from types import SimpleNamespace
from ontocare import intent_retrieval as module


def test_question_catalog_and_body_choice_cannot_cross_product_scope(tmp_path,monkeypatch):
    monkeypatch.setattr(module,'Provider',lambda **kw:SimpleNamespace(calls=[],model='test'))
    docs=[{'id':'a','pns':['T2353'],'title':'Question A','content':'Evidence A'},
          {'id':'b','pns':['T2353'],'title':'Question B','content':'Evidence B'},
          {'id':'other','pns':['T8170'],'title':'Question A','content':'Other model'}]
    original={'documents':[docs[0]],'search_query':'question','query_rewrite':{'model_calls':[]}}
    monkeypatch.setattr(module.HybridRetriever,'search',lambda *a,**kw:deepcopy(original))
    packets=[]
    def fake(provider,prompt,packet,root):
        packets.append(packet)
        return ({'ids':['b'],'reason':'same task'} if len(packets)==1 else {'best_id':'other','reason':'invalid selection'}),False
    monkeypatch.setattr(module,'ask',fake)
    r=object.__new__(module.Retriever);r.docs=docs;r.root=tmp_path
    result=r.search('question','T2353',allow_rewrite=True,ranking_profile='body_hybrid')
    assert {q['id'] for q in packets[0]['questions']}=={'a','b'}
    assert result['documents']==original['documents']
    assert result['intent_alignment']['status']=='fallback_original_order'


def test_validated_question_match_preserves_source_content(tmp_path,monkeypatch):
    monkeypatch.setattr(module,'Provider',lambda **kw:SimpleNamespace(calls=[],model='test'))
    docs=[{'id':'a','pns':['T2353'],'title':'A','content':'Original A'},
          {'id':'b','pns':['T2353'],'title':'B','content':'Original B'}]
    original=deepcopy(docs)
    monkeypatch.setattr(module.HybridRetriever,'search',lambda *a,**kw:{'documents':docs,'search_query':'question','query_rewrite':{'model_calls':[]}})
    replies=iter([({'ids':['b'],'reason':'same task'},False),({'best_id':'b','reason':'body supports task'},False)])
    monkeypatch.setattr(module,'ask',lambda *a:next(replies))
    r=object.__new__(module.Retriever);r.docs=docs;r.root=tmp_path
    result=r.search('question','T2353',allow_rewrite=True,ranking_profile='body_hybrid')
    assert result['documents'][0]['id']=='b'
    assert docs==original
    assert result['intent_alignment']['status']=='completed'
