from collections import Counter

from ontocare.manager import snapshot


def test_manager_links_have_real_endpoints_and_source_scopes(test_root):
    result = snapshot(test_root, 'candidate-1')
    nodes = {n['id']: n for n in result['nodes']}
    for edge in result['links']:
        assert edge['source'] in nodes and edge['target'] in nodes
        assert edge['basis']
        if edge['relation'] == 'applies_to':
            assert nodes[edge['source']]['properties']['name'] in nodes[edge['target']]['properties']['pns']
        if edge['relation'] == 'item_model':
            assert nodes[edge['source']]['properties']['sku'] != 'E235311B'
    assert not [d for d in result['diagnostics'] if d['level'] == 'error']


def test_manager_preserves_all_business_records_and_uncertainty(test_root):
    result = snapshot(test_root, 'candidate-1')
    counts = Counter(n['type'] for n in result['nodes'])
    assert counts['KnowledgeArticle'] == 875
    assert counts['SupportTicket'] == 63
    assert counts['Order'] == 16 and counts['OrderItem'] == 24
    assert counts['Dealer'] == 330
    assert any(d['code'] == 'unresolved_ticket_model' for d in result['diagnostics'])
    hidden = {n['id'] for n in result['nodes'] if n['type'] == 'KnowledgeArticle' and not n['properties']['visible']}
    assert len(hidden) == 3
    assert not any(l['target'] in hidden for l in result['links'])


def test_manager_routes_are_read_only_and_reject_other_paths(app):
    client = app.test_client()
    assert client.get('/ontology/manager').status_code == 200
    response = client.get('/api/ontology-manager')
    assert response.status_code == 200
    assert response.json['version'] == 'candidate-1'
    assert client.get('/api/ontology-manager?version=../../data').status_code == 400
    assert client.post('/api/ontology-manager', json={}).status_code == 405


def test_type_catalog_keeps_designs_out_of_real_instances(app):
    client = app.test_client()
    result = client.get('/api/ontology-manager/types').json
    entries = {e['id']: e for e in result['entries']}
    assert len(entries) == len(result['entries'])
    assert entries['action:submitForReview']['status'] == 'implemented'
    assert {e['kind'] for e in entries.values()} == {'ObjectType', 'LinkType', 'ActionType', 'FunctionType'}
    assert len(entries['object:ProductModel']['instanceIds']) == 19
    assert entries['link:contains_item']['relationCount'] == 24
    for ident in ['object:CheckObservation', 'action:recordCheckResult', 'action:submitManualReview']:
        assert entries[ident]['status'] == 'implemented'
        assert all(not i.startswith('demo:') for i in entries[ident]['instanceIds'])
        assert all(r['recordKind']!='design_example' for r in entries[ident]['records'])
    assert entries['action:updateSessionCheckState']['status'] == 'implemented'
    ids = set(entries)
    assert all(set(e['references']) <= ids for e in entries.values())
    assert all('demo:' not in n['id'] for n in client.get('/api/ontology-manager').json['nodes'])
    assert client.post('/api/ontology-manager/types', json={'ActionType': 'submitManualReview'}).status_code == 405
    assert client.get('/api/ontology-manager/types?version=../../data').status_code == 400


def test_type_catalog_uses_selected_version_for_completion(app):
    client = app.test_client()
    for version, expected in [('v0', False), ('candidate-1', True)]:
        result = client.get('/api/ontology-manager/types?version=' + version).json
        entry = next(e for e in result['entries'] if e['id'] == 'action:updateSessionCheckState')
        assert entry['definition']['completionTrackingEnabled'] is expected
        assert all(r['version'] == version for e in result['entries'] for r in e['records'] if r['recordKind'] == 'local_trace')
        # Only allowlisted trace summaries; no prompt, tool args, result or address.
        assert all(set(r) <= {'id', 'tool', 'traceId', 'version', 'mode', 'decision', 'recordKind', 'provenance'}
                   for e in result['entries'] for r in e['records'])


def test_type_guides_and_browser_assets_are_accessible(app):
    client = app.test_client()
    for kind in ['ObjectType', 'LinkType', 'ActionType', 'FunctionType']:
        guide = client.get('/static/type-guides/' + kind + '.md')
        assert guide.status_code == 200
        assert '解释性' in guide.get_data(as_text=True)
    assert client.get('/static/manager-types.js').status_code == 200
    html = client.get('/ontology/manager').get_data(as_text=True)
    assert all('data-view="' + kind + '-types"' in html for kind in ['object', 'link', 'action', 'function'])
