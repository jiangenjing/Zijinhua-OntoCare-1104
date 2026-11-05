"""Business facts must reach the customer Agent, rather than only the manager UI."""
import http.client
import json
import shutil

import pytest

from ontocare.agent import Agent
from ontocare.business import check_seller, projection
from ontocare.data import ROOT


@pytest.fixture()
def business_agent(test_root, tmp_path):
    for name in ['data', 'ontology', 'prompts']:
        shutil.copytree(test_root / name, tmp_path / name)
    (tmp_path / 'local').mkdir()
    for name in ['service.sqlite', 'business.sqlite']:
        shutil.copy2(test_root / 'local' / name, tmp_path / 'local' / name)
    return Agent(tmp_path)


def test_item_fulfillment_amount_and_packages_reach_agent_with_known_pn(business_agent):
    r = business_agent.run({'message':'E25，查 Anker008 的订单金额和每件商品发货状态'})
    o = r['business_context']['order']
    assert r['decision'] == 'report_snapshot'
    assert o['order']['properties']['status'] == 'PARTIALLY_SHIPPED'
    assert len(o['items']) == 2 and len(o['shipments']) == 1
    assert all(n['properties']['amount_raw'] in r['zh'] for n in o['items'])
    assert '不自动相加' in r['zh']
    assert [t['name'] for t in r['tools']] == ['lookup_order', 'evaluate_service_decision']
    assert r['business_context']['service_decision']['can_execute'] is False
    assert 'customer_received' in r['business_context']['service_decision']['missing_facts']
    assert r['business_context']['service_decision']['subject_scope'] == 'MULTIPLE_ITEMS_REQUIRE_TARGET_SELECTION'
    assert r['business_context']['service_decision']['outcome'] == 'NEED_INFORMATION'
    assert all(c['passed'] for c in r['checks'])


def test_followup_reuses_explicit_order_but_never_first_of_multiple(business_agent):
    r = business_agent.run({'message':'Anker001 有几个包裹？'})
    assert len(r['business_context']['order']['shipments']) == 2
    followup = business_agent.run({'message':'金额是多少？', 'session_id':r['session_id']})
    assert followup['business_context']['order']['order']['label'] == 'Anker001'
    multi = business_agent.run({'message':'查询 Anker001 和 Anker008 的包裹', 'session_id':r['session_id']})
    assert multi['decision'] == 'collect_order'


def test_dealer_decision_has_provenance_and_real_topology_links(business_agent):
    r = business_agent.run({'message':'这个卖家能直接保修吗？', 'context':{'country':'US','seller':'best buy','order_number':'Anker001'}})
    d = r['business_context']['dealer_check']
    assert d['competition_authorization'] == 'MATCHED_BY_BRIEF_RULE'
    assert d['eligible'] is None
    assert 'check_dealer' in [t['name'] for t in r['tools']]
    p = projection(business_agent.root)
    ident = r['business_context']['dealer_check_id']
    links = [e for e in p['links'] if e['source'] == ident]
    assert {e['relation'] for e in links} == {'stated_purchase_country','candidate_dealer','claimed_order'}
    assert next(n for n in p['nodes'] if n['id'] == ident)['properties']['claim_status'] == 'USER_REPORTED'
    assert not any(e['source']=='order:Anker001' and e['target'].startswith('dealer:') for e in p['links'])


def test_missing_country_and_weak_seller_are_not_eligible(business_agent):
    r = business_agent.run({'message':'购买渠道是否授权？', 'context':{'seller':'best buy'}})
    assert r['business_context']['dealer_check']['status'] == 'NEED_COUNTRY_AND_SELLER'
    assert check_seller('US','best',business_agent.root)['status'] == 'REVIEW_REQUIRED'
    assert check_seller('ZZ','best buy',business_agent.root)['competition_authorization'] == 'NOT_MATCHED_BY_BRIEF_RULE'


def test_actual_model_packet_contains_business_results_and_skill(monkeypatch,business_agent):
    seen = {}
    class FakeProvider:
        key='';calls=[]
        def generate(self,context,invoke,budget):
            seen.update(context)
            assert budget == 0
            return {'zh':'本地资料显示部分发货，金额与包裹内容待核查。','en':'The local snapshot shows partial fulfillment. Amounts and package contents need review.','citation_ids':[]}
    monkeypatch.setattr('ontocare.agent.Provider',FakeProvider)
    r=business_agent.run({'message':'Anker008 的物流和金额是多少？','mode':'live'})
    assert r['model_status']=='completed'
    assert seen['business_context']['order']['items']
    assert '金额' in seen['response_contract']['skill_text']
    assert not seen['evidence']


def test_transport_disconnect_is_reported_not_uncaught(monkeypatch):
    from ontocare.provider import Provider,ModelUnavailable
    p=Provider();p.base='https://provider.invalid/v1';p.key='test-secret';p.model='test-model'
    class Opener:
        def open(self,*a,**kw):raise http.client.RemoteDisconnected('connection closed')
    monkeypatch.setattr('urllib.request.build_opener',lambda *a:Opener())
    with pytest.raises(ModelUnavailable,match='connection_or_response_error'):p.chat([])
    assert p.calls[-1]['status']=='failed'
    assert 'test-secret' not in json.dumps(p.calls)
