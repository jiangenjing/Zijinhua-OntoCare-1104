import json
from pathlib import Path
import pytest
from ontocare.data import ROOT, load_json, digest
from ontocare.customer_query_rewrite import validate
from ontocare.service_eval_dashboard import task_verdict, percentile, score_run


@pytest.mark.skipif(not (ROOT/'evaluation/customer-service-v2/cases.json').exists(),reason='Historical customer-email benchmark remains local')
def test_source_groups_do_not_cross_frozen_splits_and_quotes_are_real():
    cases=load_json(ROOT/'evaluation/customer-service-v2/cases.json')['cases']
    manifest=load_json(ROOT/'evaluation/customer-service-v2/manifest.json')
    docs={d['id']:d for d in load_json(ROOT/'data/knowledge.json')}
    assert len(cases)==611 and digest(cases)==manifest['case_sha256']
    groups={}
    for c in cases:
        assert c['group'] not in groups or groups[c['group']]==c['split']
        groups[c['group']]=c['split']
        if c['kind']=='knowledge':
            assert any(c['support_quote'] in docs[k]['content'] for k in c['gold_ids'])
            assert all(docs[k]['visible'] and c['pn'] in docs[k]['pns'] for k in c['gold_ids'])


def test_query_identifier_adjacent_to_chinese_keeps_same_model():
    assert validate('为什么T2352报3212错误？','Why does T2352 report error 3212?')
    with pytest.raises(ValueError):validate('T2352报3212错误','T2353 error 3212')
    with pytest.raises(ValueError):validate('T2352报3212错误','T2352 is broken')


def test_unknown_production_outcomes_are_null_not_fabricated(tmp_path):
    m=score_run(tmp_path,'empty')
    assert m['task_pass']['value'] is None
    assert m['business']['csat'] is None and m['business']['actual_resolution'] is None
    assert m['business']['actual_handoff_rate'] is None and m['money_cost'] is None
    assert percentile([])['p99_ms'] is None


def test_seen_ticket_not_counted_as_a_labelled_solution():
    answer={'turns':[{'reply':{'decision':'answer','checks':[{'passed':True}]}}]}
    judge={'status':'completed','answer_correct':True,'policy_safe':True,'history_ok':True}
    assert task_verdict({'reference':None},answer,judge) is None
    assert task_verdict({'reference':'source','expected_decision':'manual_review'},answer,judge) is False
    assert task_verdict({'reference':'source'},answer,judge) is True
    assert task_verdict({'reference':'source'},answer,{**judge,'policy_safe':False}) is False


@pytest.mark.skipif(not (ROOT/'evaluation/customer-service-v2/cases.json').exists(),reason='Historical customer-email benchmark remains local')
def test_evaluation_api_browses_questions_and_rejects_path_traversal(app):
    client=app.test_client()
    assert client.get('/evaluations').status_code==200
    rows=client.get('/api/service-evals/cases?kind=knowledge&split=holdout').get_json()
    assert rows['total']==96 and len(rows['items'])==20
    assert rows['items'][0]['answer_status']=='pending'
    case=rows['items'][0]['id']
    detail=client.get('/api/service-evals/cases/'+case).get_json()
    assert detail['case']['id']==case and detail['outputs']==[]
    assert client.get('/api/service-evals/cases?run=../../secret').status_code==400


def test_pn_digits_before_error_are_not_the_error_code(agent):
    reply=agent.run({'message':'T8170 error 3212','version':'candidate-1'})
    assert reply['state']['error_code']=='3212'
    assert reply['decision']=='insufficient_evidence'


def test_mcp_plan_recognizes_pn_next_to_chinese_without_treating_specs_as_errors(test_root, monkeypatch):
    from ontocare.service_api import OntologyService
    service=OntologyService(test_root);seen=[]
    def search(pn,query,error_code=None):
        seen.append((pn,error_code));return {'documents':[]}
    monkeypatch.setattr(service,'search_knowledge',search)
    service.plan_customer_service('T2353的吸力是7000 Pa吗？')
    assert seen==[('T2353',None)]
    service.plan_customer_service('T2353报错3212该怎么办？')
    assert seen[-1]==('T2353','3212')


def test_three_repeat_metric_requires_all_executions_to_pass(tmp_path):
    from ontocare.data import write_json
    base=tmp_path/'local/customer-service-v2'
    for repeat,correct in enumerate([True,False,True]):
        filename=f'example-r{repeat}.json'
        write_json(base/'answers/demo'/filename,{'id':'example','repeat':repeat,'case':{'kind':'knowledge','reference':'source'},'turns':[{'http_ms':10,'reply':{'decision':'answer','model_status':'completed','checks':[]}}]})
        write_json(base/'judges/demo'/filename,{'status':'completed','answer_correct':correct,'policy_safe':True,'history_ok':True,'supported_claims':1,'total_claims':1,'faithfulness':1,'bad_case_category':'none' if correct else 'generation'})
    m=score_run(tmp_path,'demo')
    assert m['three_repeat_cases']==1
    assert m['three_repeat_robustness']['n']==1
    assert m['three_repeat_robustness']['all_passed']==0
    assert score_run(tmp_path,'demo',first_repeat_only=True)['task_pass']['value']==1


def test_workflow_label_is_sufficient_for_boundary_task_without_prose_reference():
    case={'kind':'boundary','reference':None,'expected_decision':'clarify_product'}
    answer={'turns':[{'reply':{'decision':'clarify_product','checks':[]}}]}
    judge={'status':'completed','answer_correct':True,'policy_safe':True,'history_ok':True}
    assert task_verdict(case,answer,judge) is True
    answer['turns'][0]['reply']['decision']='answer'
    assert task_verdict(case,answer,judge) is False
