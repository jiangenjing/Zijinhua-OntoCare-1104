import asyncio
from copy import deepcopy
import json
import os
import shutil
import sys

import pytest

from ontocare.data import ROOT, digest
from ontocare import reports


@pytest.fixture()
def report_root(test_root,tmp_path):
    for name in ['data','ontology','web','prompts','skills','actions','evaluation']:
        shutil.copytree(ROOT/name,tmp_path/name)
    (tmp_path/'local').mkdir()
    for name in ['service.sqlite','business.sqlite']:
        shutil.copy2(test_root/'local'/name,tmp_path/'local'/name)
    return tmp_path


def test_snapshot_reconciles_grains_visibility_and_sensitive_fields(report_root):
    p=reports.evidence_packet(report_root)
    assert {k:p['evidence'][k]['value'] for k in ['tickets','orders','items','shipments','dealers','knowledge']} == dict(tickets=63,orders=16,items=24,shipments=20,dealers=330,knowledge=872)
    assert sum(r['count'] for r in p['charts']['item_flow'])==24
    assert sum(p['charts']['country_directory'].values())==330
    assert sum(p['charts']['ticket_scenes'].values())==63
    assert len(p['order_rows'])==16
    raw=json.dumps(p)
    assert 'amount_raw' not in raw and 'address' not in raw and 'customer_email' not in raw
    assert p['business_snapshot_as_of'] is None


def test_templates_are_real_skills_and_snapshot_generation_does_not_call_model(report_root,monkeypatch):
    class Forbidden:
        def __init__(self):raise AssertionError('snapshot must not invoke a model')
    monkeypatch.setattr(reports,'Provider',Forbidden)
    catalog=reports.templates(report_root)
    assert len(catalog['templates'])==4
    before=digest((report_root/'local/business.sqlite').read_bytes())
    for t in catalog['templates']:
        assert t['skill'].startswith('---\nname:') and t['prompt']
        r=reports.generate(t['id'],mode='snapshot',root=report_root)
        assert r['generation_status']=='snapshot_only'
        assert len(r['narrative']['sections'])==4
    assert len(reports.list_reports(report_root)['reports'])==4
    assert digest((report_root/'local/business.sqlite').read_bytes())==before


def test_live_generation_uses_selected_skill_and_invalid_claims_fall_back(report_root,monkeypatch):
    captured={}
    packet=reports.evidence_packet(report_root)
    good=reports.baseline(reports.templates(report_root)['templates'][1],packet)
    class Fake:
        def __init__(self, **kwargs):pass
        model='test-model';key='secret-test';calls=[{'status':'completed'}]
        def chat(self,messages):captured['messages']=messages;return {'content':json.dumps(good,ensure_ascii=False)}
    monkeypatch.setattr(reports,'Provider',Fake)
    r=reports.generate('gtm',focus='渠道策略',root=report_root)
    assert r['generation_status']=='completed' and 'ontocare-report-gtm' in captured['messages'][0]['content']
    good['sections'][3]['evidence_ids']=list(packet['evidence'])
    assert reports.generate('gtm',root=report_root)['generation_status']=='completed'
    bad=deepcopy(good);bad['sections'][0]['evidence_ids']=['fake-evidence']
    good.clear();good.update(bad)
    r=reports.generate('gtm',root=report_root)
    assert r['generation_status']=='fallback_invalid_report'
    good.update(reports.baseline(reports.templates(report_root)['templates'][1],packet));good['summary']='收入增长99%'
    assert reports.generate('gtm',root=report_root)['generation_status']=='fallback_invalid_report'


def test_saved_snapshot_does_not_change_with_current_graph(report_root,monkeypatch):
    r=reports.generate('executive',mode='snapshot',root=report_root)
    monkeypatch.setattr(reports,'evidence_packet',lambda *a: {'changed':True})
    saved=reports.get_report(r['id'],report_root)
    assert saved['snapshot']==r['snapshot']
    source=reports.report_evidence(r['id'],'items',report_root)
    assert source['value']==24 and len(source['source_ids'])==24


def test_routes_history_exports_and_bad_inputs(report_root):
    from ontocare.app import create_app
    client=create_app(report_root).test_client()
    assert client.get('/reports').status_code==200
    assert len(client.get('/api/strategy-reports/templates').json['templates'])==4
    r=client.post('/api/strategy-reports',json={'template_id':'executive','mode':'snapshot'})
    assert r.status_code==201
    ident=r.json['id']
    assert client.get('/api/strategy-reports/'+ident).json['snapshot']['evidence']['items']['value']==24
    assert client.get('/api/strategy-reports/'+ident+'/export/markdown').status_code==200
    assert client.get('/api/strategy-reports/'+ident+'/export/json').json['id']==ident
    assert client.get('/api/strategy-reports/'+ident+'/export/sh').status_code==404
    assert client.post('/api/strategy-reports',json={'template_id':'bad'}).status_code==400
    assert client.post('/api/strategy-reports',json=[]).status_code==400
    assert client.get('/api/strategy-reports/not-an-id').status_code==404
    assert len(client.get('/api/strategy-reports').json['reports'])==1


def test_mcp_can_generate_and_retrieve_report_without_enabling_business_writes(report_root):
    from mcp import ClientSession,StdioServerParameters
    from mcp.client.stdio import stdio_client
    async def verify():
        params=StdioServerParameters(command=sys.executable,args=['-m','ontocare.service_mcp'],cwd=str(ROOT),env={**os.environ,'PYTHONPATH':str(ROOT),'ONTOCARE_WORKSPACE':str(report_root),'ONTOCARE_MCP_ALLOW_WRITES':'0'})
        async with stdio_client(params) as (read,write):
            async with ClientSession(read,write) as s:
                await s.initialize()
                tools=(await s.list_tools()).tools
                assert len(tools)==22
                generation=next(t for t in tools if t.name=='generate_report')
                assert generation.annotations.readOnlyHint is False
                result=await s.call_tool('generate_report',{'template_id':'gtm','mode':'snapshot'})
                assert not result.isError
                p=result.structuredContent or json.loads(result.content[0].text)
                saved=await s.call_tool('get_report',{'report_id':p['id']})
                q=saved.structuredContent or json.loads(saved.content[0].text)
                assert q['snapshot']['evidence']['dealers']['value']==330
                assert not p['business_data_modified']
    asyncio.run(verify())


def test_report_freezes_graph_lineage_and_exports_all_chart_sources(report_root,monkeypatch):
    first=reports.generate('executive',mode='snapshot',root=report_root)
    packet=first['snapshot']
    assert set(packet['lineage'])=={'semantic_bundle_sha256','business_source_file','business_source_sha256','graph_sha256'}
    assert all(len(packet['lineage'][k])==64 for k in ['semantic_bundle_sha256','business_source_sha256','graph_sha256'])
    from ontocare.service_api import OntologyService
    original=OntologyService.visible_graph
    def changed(self,version=None):
        nodes,edges=original(self,version)
        nodes=deepcopy(nodes)
        nodes[0]['properties']['verification_note']='source changed without changing object counts'
        return nodes,edges
    monkeypatch.setattr(OntologyService,'visible_graph',changed)
    second=reports.evidence_packet(report_root)
    assert second['fingerprint']!=packet['fingerprint']
    assert second['lineage']['graph_sha256']!=packet['lineage']['graph_sha256']
    assert second['evidence']['items']['value']==packet['evidence']['items']['value']
    exported=reports.markdown(reports.get_report(first['id'],report_root))
    assert all(x in exported for x in ['工单样例场景分布','销售方名录国家分布','商品项履约资料流','订单快照明细','Anker008',packet['lineage']['graph_sha256']])


def test_one_bounded_correction_retains_rejection_record(report_root,monkeypatch):
    packet=reports.evidence_packet(report_root)
    good=reports.baseline(reports.templates(report_root)['templates'][0],packet)
    bad=deepcopy(good);bad['sections'][0]['evidence_ids']=['not-a-source']
    class Fake:
        def __init__(self,**kwargs):self.calls=[];self.model='test-model';self.key=''
        def chat(self,messages):
            self.calls.append({'status':'completed'})
            return {'content':json.dumps(bad if len(self.calls)==1 else good,ensure_ascii=False)}
    monkeypatch.setattr(reports,'Provider',Fake)
    r=reports.generate('executive',root=report_root)
    assert r['generation_status']=='completed'
    assert [v['passed'] for v in r['validation_checks']]==[False,True]
    assert len(r['model_calls'])==2


def test_model_knowledge_counts_overlap_but_unique_articles_stay_unique(report_root):
    p=reports.evidence_packet(report_root)
    counts=p['charts']['product_knowledge']
    assert len(counts)==19
    assert sum(counts.values())==1042
    assert p['evidence']['knowledge']['value']==872
    assert '不能相加' in p['evidence']['product_knowledge']['definition']
