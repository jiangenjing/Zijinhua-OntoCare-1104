from pathlib import Path
import pytest
from ontocare.benchmark_metrics import retrieval_scores,summarize_retrieval
from ontocare.grounded_eval import read_split


def test_hit_rate_and_document_set_recall_have_different_denominators():
    s=retrieval_scores(['a','b'],['a','z','b'])
    assert s['hit_at_1']==1 and s['recall_at_1']==.5
    assert s['recall_at_3']==1 and s['mrr']==1


def test_final_requires_explicit_freeze_gate():
    with pytest.raises(ValueError,match='locked'):read_split('final')


def test_chinese_touching_model_and_error_are_identified(agent):
    assert agent.identify('我的T2353报错3212')==['T2353']
    r=agent.run({'message':'我的T2353报错3212，还没检查'})
    assert r['state']['pn']=='T2353' and r['state']['error_code']=='3212'
    assert r['citations']


def test_solar_accessory_code_is_source_grounded_but_unknown_device_stays_ambiguous(agent):
    assert agent.identify('T8170能连接T8700太阳能板吗？')==['T8170']
    assert agent.identify('T8170和T9999哪个更好？')==['T8170','T9999']


@pytest.mark.parametrize('reply_pn,expected',[('T9999','completed'),('T2353','cross_product_answer')])
def test_product_clarification_may_repeat_user_code_but_cannot_invent_one(agent,monkeypatch,reply_pn,expected):
    from ontocare import agent as module
    class FakeProvider:
        def __init__(self):self.calls=[];self.key=''
        def generate(self,context,invoke,budget):
            return {'zh':f'请核对标签型号 {reply_pn}，目前无法确认适用的保修资料。','en':f'Please verify the label model {reply_pn}; applicable warranty evidence is not confirmed.','citation_ids':[]}
    monkeypatch.setattr(module,'Provider',FakeProvider)
    r=agent.run({'message':'请核实后回答：T9999 保修多久？','mode':'live'})
    assert r['model_status']==expected
    assert r['decision']=='clarify_product'


@pytest.mark.parametrize('failure,expected,calls',[('invalid_structured_answer','completed',2),('http_403','http_403',1)])
def test_structured_answer_gets_one_bounded_retry_but_auth_failure_stays_visible(agent,monkeypatch,failure,expected,calls):
    from ontocare import agent as module
    from ontocare.provider import ModelUnavailable
    attempted=[]
    class FakeProvider:
        def __init__(self):self.calls=[];self.key=''
        def generate(self,context,invoke,budget):
            attempted.append(context)
            if len(attempted)==1:raise ModelUnavailable(failure)
            return {'zh':'请依据资料检查 T2353 滚筒是否缠绕异物。','en':'Check the T2353 roller for tangled debris according to the source.','citation_ids':[context['evidence'][0]['id']]}
    monkeypatch.setattr(module,'Provider',FakeProvider)
    reply=agent.run({'message':'我的 T2353 报错3212，怎么检查？','mode':'live'})
    assert reply['model_status']==expected and len(attempted)==calls
    assert reply['response_validation_retries']==calls-1
