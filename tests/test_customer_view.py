import json

from ontocare.customer_view import conversation_graph, order_examples


def test_order_cards_are_source_snapshot_without_customer_addresses(app, test_root):
    result = order_examples(test_root)
    assert len(result['orders']) == 16
    assert result['scope'] == 'competition_snapshot_not_personal_orders'
    assert all(order['source_rows'] and order['source_sheet'] == '订单信息' for order in result['orders'])
    assert [order['purchase_date'] for order in result['orders']] == sorted(
        [order['purchase_date'] for order in result['orders']], reverse=True)
    assert 'address' not in json.dumps(result)
    assert app.test_client().get('/api/service/examples').get_json() == result


def test_order_graph_uses_exact_items_without_inventing_model_or_package_contents(agent, test_root):
    reply = agent.run({'message': '查询 Anker003 的商品和包裹'})
    graph = conversation_graph(reply, test_root)
    indexed = {node['id']: node for node in graph['nodes']}
    assert 'order:Anker003' in indexed
    assert 'offering:T2351V11-F' in indexed
    assert not any(node['type'] == 'product_model' for node in graph['nodes'])
    items = {node['id'] for node in reply['business_context']['order']['items']}
    joins = [edge for edge in graph['edges'] if edge['relation'] == 'contains_item']
    assert {edge['target'] for edge in joins} == items
    assert all(edge['source'] == 'order:Anker003' for edge in joins)
    assert not any(edge['relation'] in {'contains_item', 'contains_product'} and indexed[edge['source']]['type'] == 'Shipment' for edge in graph['edges'])
    assert not any(node['type'] == 'Order' and node['id'] != 'order:Anker003' for node in graph['nodes'])


def test_unknown_model_never_becomes_inherited_fact(test_root):
    graph = conversation_graph({'state': {'pn': 'T2353'}, 'decision': 'clarify_product'}, test_root)
    assert graph['nodes'] == []


def test_citation_body_and_reference_keep_their_source_and_scope():
    reply = {'citations': [{'id': 'qa1', 'title': 'Question', 'quote': 'Source text', 'pns': ['T2353'],
        'source': {'sheet': 'Robovacs', 'row': 148}, 'references': [
            {'id': 'official:1', 'title': 'Official', 'pns': ['T2353'], 'retrieved_at': '2026-11-03',
             'content_sha256': 'abc', 'text': 'Official body', 'url': 'https://service.eufy.com/article-description/example'}]}]}
    graph = conversation_graph(reply)
    indexed = {node['id']: node for node in graph['nodes']}
    assert indexed['knowledge:qa1']['source']['row'] == 148
    assert indexed['knowledge:qa1']['details']['原始正文'] == 'Source text'
    assert indexed['official:1']['details']['正文哈希'] == 'abc'
    assert graph['edges'][0]['basis']['父Q&A'] == 'qa1'
    preview = conversation_graph(reply, preview=True)
    candidate = next(node for node in preview['nodes'] if node['id'] == 'knowledge:qa1')
    assert candidate['cited'] is False
    assert candidate['type'] == 'knowledge_topic'
