"""Coverage, uncertain business facts and actual MCP transport boundaries."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

from ontocare.business import coverage, projection
from ontocare.data import ROOT
from ontocare.service_api import OntologyService, TOOL_DESCRIPTIONS


@pytest.fixture(scope='module')
def delivery_root(tmp_path_factory, test_root):
    root = tmp_path_factory.mktemp('delivery')
    for name in ['data', 'ontology', 'web', 'actions', 'prompts', 'evaluation']:
        shutil.copytree(test_root / name, root / name)
    (root / 'local').mkdir()
    for name in ['service.sqlite', 'business.sqlite']:
        shutil.copy2(test_root / 'local' / name, root / 'local' / name)
    return root


def test_every_sheet_retains_its_fields_and_explicit_modeling_decisions(delivery_root):
    c = coverage(delivery_root)
    assert [s['rows'] for s in c['sheets']] == [63, 24, 593, 282, 336]
    assert all(s['included'] and s['fields'] and s['decision'] for s in c['sheets'])
    assert c['node_counts']['Dealer'] == 330
    assert c['node_counts']['Shipment'] == 20
    assert c['node_counts']['KnowledgeCategory'] == 13


def test_split_fulfillment_does_not_invent_package_contents_or_currency(delivery_root):
    s = OntologyService(delivery_root)
    result = s.lookup_order('Anker008')
    assert result['order']['properties']['status'] == 'PARTIALLY_SHIPPED'
    assert len({n['properties']['fulfillment_status'] for n in result['items']}) == 2
    assert result['shipments']
    assert all(not n['properties']['contents_verified'] for n in result['shipments'])
    assert all(n['properties']['currency_code'] is None for n in result['items'])
    assert all(n['properties']['amount_raw'] for n in result['items'])
    assert 'address' not in json.dumps(result)
    assert any(n['properties']['tracking_number'] != '[NUMBER]' for n in result['shipments'])
    assert any(d['code'] == 'shipment_before_purchase' for d in projection(delivery_root)['diagnostics'])


def test_seller_match_is_country_scoped_and_never_eligibility(delivery_root):
    s = OntologyService(delivery_root)
    r = s.check_dealer('US', 'best buy')
    assert r['status'] == 'LIST_MATCH_SCOPE_UNKNOWN' and r['eligible'] is None
    assert all(c['properties']['country'] == 'US' for c in r['candidates'])
    assert s.check_dealer('', 'best buy')['status'] == 'NEED_COUNTRY_AND_SELLER'
    assert s.check_dealer('ZZ', 'best buy')['status'] == 'NOT_IN_SNAPSHOT'


def test_bounded_traversal_visibility_and_write_disable(delivery_root):
    s = OntologyService(delivery_root)
    hidden = [n['id'] for n in s.graph()['nodes'] if n['type'] == 'KnowledgeArticle' and not n['properties']['visible']]
    assert len(hidden) == 3
    for ident in hidden:
        assert s.get_instance_detail([ident])['results'][0]['status'] == 'NOT_FOUND_OR_NOT_VISIBLE'
    assert s.search_instances('KnowledgeArticle', page_size=1)['total'] == 872
    with pytest.raises(ValueError):s.search_instances(page_size=500)
    with pytest.raises(ValueError):s.get_instance_topology('order:Anker008', 4)
    graph = s.get_instance_topology('order:Anker008', 3)
    assert len(graph['nodes']) <= 100
    assert not s.submit_for_review('ticket-002','test','test')['committed']
    assert not (delivery_root / 'local/actions.sqlite').exists()
    assert {t['id'] for t in s.list_topologies()['topologies']} == {'sop', 'service', 'orders', 'dealers', 'knowledge'}


def test_http_coverage_and_shared_tools(delivery_root):
    from ontocare.app import create_app
    client = create_app(delivery_root).test_client()
    r = client.get('/api/ontology-service/source-rows?sheet=订单信息')
    assert r.status_code == 200 and r.json['total'] == 24
    assert '订单金额' in r.json['items'][0]['fields']
    assert client.get('/api/ontology-service/source-rows?sheet=missing').status_code == 400
    entries = client.get('/api/ontology-manager/types').json['entries']
    assert all(isinstance(e['source'], list) and isinstance(e['examples'], list) for e in entries)
    assert client.post('/api/ontology-service/call', json={'name':'lookup_order', 'arguments':{'order_number':'Anker008'}}).json['status'] == 'FOUND_LOCAL_SNAPSHOT'
    assert client.post('/api/ontology-service/call', json={'name':'__dict__'}).status_code == 400
    chat = client.post('/api/chat', json={'message':'Anker008 的包裹发货了吗？', 'mode':'offline'})
    assert chat.status_code == 200 and 'PARTIALLY_SHIPPED' in chat.json['zh']
    assert '未发货' in chat.json['zh'] and '已发货' in chat.json['zh']


def test_official_sdk_stdio_lists_and_calls_actual_tools(delivery_root):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    async def verify():
        p = StdioServerParameters(command=sys.executable, args=['-m','ontocare.service_mcp'], cwd=str(ROOT), env={**os.environ, 'PYTHONPATH':str(ROOT), 'ONTOCARE_WORKSPACE':str(delivery_root), 'ONTOCARE_MCP_ALLOW_WRITES':'0'})
        async with stdio_client(p) as (r,w):
            async with ClientSession(r,w) as session:
                await session.initialize()
                assert len((await session.list_tools()).tools) == 22
                result = await session.call_tool('lookup_order', {'order_number':'Anker008'})
                assert not result.isError
                payload = result.structuredContent or json.loads(result.content[0].text)
                assert payload['order']['properties']['status'] == 'PARTIALLY_SHIPPED'
                invalid = await session.call_tool('get_instance_topology', {'instance_id':'order:Anker008','depth':9})
                assert invalid.isError
    asyncio.run(verify())


def test_rule_projection_is_not_counted_twice(delivery_root):
    graph=OntologyService(delivery_root).graph()
    keys=[(e['source'],e['target'],e['relation']) for e in graph['links'] if e['relation']=='governed_by_service_rule']
    assert keys and len(keys)==len(set(keys))
