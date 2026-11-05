import json

import pytest

from ontocare.data import digest, load_json
from ontocare.manager import snapshot
from ontocare.service_api import OntologyService
from ontocare.sop import SOP_FILE, projection


def test_sop_is_in_same_graph_with_source_bound_definitions(test_root):
    graph = snapshot(test_root, 'candidate-1')
    indexed = {n['id']: n for n in graph['nodes']}
    meta = graph['sop']
    assert meta['definition_sha256'] == digest(load_json(test_root / SOP_FILE))
    assert meta['source']['image_sha256'] == load_json(test_root / 'data/competition-rules.json')['rules'][0]['source']['image_sha256']
    steps = [n for n in graph['nodes'] if n['type'] == 'SOPStep']
    assert len(steps) == 20
    assert {'sop:step:boundary', 'sop:step:resolved', 'sop:step:warranty', 'sop:step:authorized',
            'sop:step:request', 'sop:step:human', 'sop:step:close'} <= set(meta['step_ids'])
    assert all(n['properties']['record_kind'] == '流程定义，不是工单执行记录' for n in steps)
    flows = [e for e in graph['links'] if e['relation'] == 'sop_next_step']
    assert len(flows) == 32
    assert all(e['source'] in indexed and e['target'] in indexed and e['basis']['condition'] for e in flows)
    assert any(e['source'] == 'sop:step:boundary' and e['target'] == 'sop:step:human' for e in flows)
    assert any(e['source'] == 'sop:step:consent' and e['target'] == 'sop:step:retrieve' for e in flows)
    assert any(e['basis']['origin'] == 'engineering_guard' for e in flows)
    assert any(e['source'] == 'sop:step:warranty' and e['target'] == 'sop:step:fault-readiness' for e in flows)
    assert any(e['source'] == 'sop:step:fault-readiness' and e['target'] == 'sop:step:materials'
               and '排障已完成' in e['basis']['condition'] for e in flows)
    for edge in flows:
        if edge['basis']['origin'] == 'engineering_guard':
            assert edge['basis']['source']['file'] == SOP_FILE
        if edge['basis']['origin'] == 'tool_requirement':
            assert edge['basis']['source']['section'] == '五、相关工具'


def test_bindings_show_visible_source_examples_without_case_execution_claims(test_root):
    graph = snapshot(test_root, 'candidate-1')
    indexed = {n['id']: n for n in graph['nodes']}
    examples = [e for e in graph['links'] if e['relation'] == 'sop_binding_example']
    assert len(examples) == 9
    for edge in examples:
        binding, target = indexed[edge['source']], indexed[edge['target']]
        assert binding['properties']['object_type'] == target['type']
        assert set(binding['properties']['fields_used']) <= set(target['properties'])
        assert target['properties'].get('visible') is not False
        assert '不表示' in edge['basis']['meaning']
    assert any(indexed[e['target']]['type'] == 'Order' for e in examples)
    assert any(indexed[e['target']]['type'] == 'Shipment' for e in examples)
    assert any(indexed[e['target']]['type'] == 'Dealer' for e in examples)


def test_materials_and_action_definitions_never_approve_a_remedy(app, test_root):
    graph = snapshot(test_root, 'candidate-1')
    indexed = {n['id']: n for n in graph['nodes']}
    materials = [n for n in graph['nodes'] if n['type'] == 'RequiredMaterial']
    assert len(materials) == 4
    assert '故障问题需要' in indexed['sop:material:sn']['properties']['condition']
    assert all('reship' not in n['properties']['required_for'] for n in materials)
    assert all(n['properties']['receipt_status'] == '定义不记录已收到' for n in materials)
    for ident in ['refund', 'replacement', 'reship']:
        assert indexed['sop:action:' + ident]['properties']['runtime_status'] == 'connected_local'
        assert indexed['sop:action:' + ident]['properties']['handler'].startswith('ontocare.customer_workflow.')
    assert indexed['sop:step:shipping']['properties']['runtime_status'] == 'connected_local'
    assert indexed['sop:step:resolved']['properties']['runtime_status'] == 'connected_local'
    registered = app.test_client().get('/api/action-types').json['types']
    assert [entry['ActionType'] for entry in registered] == ['submitForReview']


def test_sop_is_available_to_classes_types_and_existing_mcp_read_tools(app, test_root):
    client = app.test_client()
    graph = client.get('/api/ontology-manager').json
    assert {'SOPStep', 'RequiredMaterial', 'SOPAction', 'SOPDataBinding', 'ServiceProcess'} <= {c['id'] for c in graph['classes']}
    catalog = client.get('/api/ontology-manager/types').json
    entry = next(e for e in catalog['entries'] if e['id'] == 'object:SOPStep')
    assert SOP_FILE in entry['source']
    assert '不代表流程已自动执行' in entry['statusDetail']
    service = OntologyService(test_root)
    assert service.search_instances('SOPStep')['total'] == 20
    topology = service.get_instance_topology('sop:step:shipping', 2)
    assert any(n['id'] == 'brief:reship' for n in topology['nodes'])
    assert any(n['type'] == 'Shipment' for n in topology['nodes'])


def test_invalid_sop_does_not_invent_missing_endpoints(tmp_path, test_root):
    path = tmp_path / SOP_FILE
    path.parent.mkdir(parents=True)
    definition = load_json(test_root / SOP_FILE)
    definition['transitions'][0]['target'] = 'sop:step:does-not-exist'
    path.write_text(json.dumps(definition))
    with pytest.raises(ValueError, match='有效端点'):
        projection(tmp_path, [])


def test_sop_dependency_is_part_of_manager_cache_signature(tmp_path, test_root):
    import shutil
    for name in ['data', 'ontology', 'local']:
        shutil.copytree(test_root / name, tmp_path / name)
    before = snapshot(tmp_path, 'candidate-1')
    path = tmp_path / SOP_FILE
    definition = load_json(path)
    definition['steps'][0]['runtime_note'] += '；核对缓存更新'
    path.write_text(json.dumps(definition, ensure_ascii=False))
    after = snapshot(tmp_path, 'candidate-1')
    assert before['sop']['definition_sha256'] != after['sop']['definition_sha256']
    assert any('核对缓存更新' in n['properties'].get('runtime_note', '') for n in after['nodes'])
