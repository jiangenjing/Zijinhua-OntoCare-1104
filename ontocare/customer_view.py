"""Read-only customer projections, backed by returned evidence and exact source joins."""
from collections import defaultdict
import json
from pathlib import Path

from .business import connect
from .data import load_json

LABELS = {'contains_item': '包含商品行', 'purchases_offering': '购买商品', 'has_shipment': '记录包裹',
          'reported_on_item': '物流源于商品行', 'offering_model_candidate': '型号候选',
          'candidate_dealer': '销售方候选', 'stated_purchase_country': '陈述的购买国家',
          'claimed_order': '会话提及订单', 'association': '资料记录关联'}
FIELDS = {'sku': '商品SKU', 'description': '名称（源表原文）', 'quantity': '数量', 'purchase_date': '购买日期',
          'fulfillment_status': '商品发货状态', 'shipping_status': '源物流状态', 'amount_raw': '源商品行金额（币种与粒度待核）',
          'status': '状态', 'tracking_number': '物流单号', 'carrier': '承运商', 'contents_verified': '包裹内容是否核实',
          'country': '国家', 'country_claim': '陈述的购买国家', 'seller_claim': '陈述的销售方',
          'competition_authorization': '比赛名录匹配结果（不等于售后资格）', 'reason': '说明'}


def business_snapshot(root):
    if root is None or not (Path(root) / 'local/business.sqlite').exists(): return {'nodes': [], 'links': []}
    with connect(root) as connection:
        row = connection.execute("SELECT payload FROM records WHERE id='snapshot'").fetchone()
    return json.loads(row[0]) if row else {'nodes': [], 'links': []}


def order_examples(root):
    snapshot = business_snapshot(root); items = defaultdict(list)
    for node in snapshot['nodes']:
        if node['type'] == 'OrderItem': items[node['properties']['order_number']].append(node)
    examples = []
    for order in snapshot['nodes']:
        if order['type'] != 'Order': continue
        rows = sorted(items[order['label']], key=lambda n: n['properties']['source_row'])
        if not rows: continue
        first = rows[0]['properties']
        examples.append({'id': order['id'], 'order_number': order['label'], 'title': first['description'],
                         'sku': first['sku'], 'purchase_date': first.get('purchase_date'), 'status': order['properties']['status'],
                         'item_rows': len(rows), 'source_rows': order['properties'].get('source_rows', []),
                         'source_sheet': '订单信息'})
    return {'orders': sorted(examples, key=lambda o: (str(o['purchase_date'] or ''), o['order_number']), reverse=True),
            'scope': 'competition_snapshot_not_personal_orders', 'notice': '赛题演示订单，按源表购买日期排序；不代表你的个人购买记录。'}


def conversation_graph(reply, root=None, snapshot=None, preview=False):
    nodes = {}; edges = []
    def add(ident, kind, label, details=None, source=None, **extra):
        nodes[ident] = {'id': ident, 'type': kind, 'label': label, 'details': details or {}, 'source': source, **extra}
    def edge(source, target, relation, basis=None, context=False):
        edges.append({'source': source, 'target': target, 'relation': relation, 'label': LABELS.get(relation, relation),
                      'basis': basis, 'context': context})
    graph = reply.get('retrieval') or {}
    for node in graph.get('nodes', []):
        add(node['id'], node['type'], node['name'], {'适用范围': node.get('scope'), '证据标识': node.get('evidence_ids', [])})
    for relation in graph.get('edges', []): edge(relation['source'], relation['target'], relation['type'], {'证据标识': relation.get('evidence_ids', [])})
    for citation in reply.get('citations', []):
        ident = 'knowledge:' + citation['id']
        add(ident, 'knowledge_topic' if preview else 'KnowledgeArticle', citation['title'],
            {'适用型号': citation.get('pns', []), '原始正文': citation['quote']}, citation.get('source'), cited=not preview)
        for reference in citation.get('references', []):
            add(reference['id'], 'OfficialArticle', reference['title'], {'适用型号': reference['pns'], '抓取时间': reference['retrieved_at'],
                '正文哈希': reference['content_sha256'], '官方正文': reference['text']}, {'url': reference['url']})
            edge(ident, reference['id'], '补充官方正文', {'父Q&A': citation['id'], '正文哈希': reference['content_sha256']})
    business = reply.get('business_context') or {}; order = business.get('order') or {}
    if order.get('status') == 'FOUND_LOCAL_SNAPSHOT':
        selected = {order['order']['id']: order['order']}
        selected.update({n['id']: n for n in order.get('items', []) + order.get('shipments', [])})
        snapshot = snapshot if snapshot is not None else business_snapshot(root)
        indexed = {n['id']: n for n in snapshot['nodes']}
        # Only traverse typed order/SKU relations already recorded in the source projection.
        for relation in snapshot['links']:
            if relation['source'] in selected and relation['relation'] == 'purchases_offering' and relation['target'] in indexed:
                selected[relation['target']] = indexed[relation['target']]
        for node in selected.values():
            props = node.get('properties', {})
            add(node['id'], node['type'], props.get('description') or node['label'],
                {label: props.get(key) for key, label in FIELDS.items() if key in props},
                props.get('source') or {'sheet': '订单信息', 'rows': props.get('source_rows', [])})
        for item in order.get('items', []):
            # Same exact foreign-key join used by the workbench; not inferred package contents.
            if item['properties']['order_number'] == order['order']['label']:
                edge(order['order']['id'], item['id'], 'contains_item', item['properties'].get('source'))
        for relation in snapshot['links']:
            if relation['source'] in selected and relation['target'] in selected:
                edge(relation['source'], relation['target'], relation['relation'], relation.get('basis'))
    dealer = business.get('dealer_check')
    if dealer:
        ident = business.get('dealer_check_id') or 'dealer-check:' + reply.get('trace_id', 'preview')
        add(ident, 'DealerCheck', '购买渠道核查', {'状态': dealer['status'], '说明': dealer.get('reason'), '售后资格': '尚未核验'})
        for candidate in dealer.get('candidates', []):
            add(candidate['id'], 'Dealer', candidate['label'], {'国家': candidate.get('properties', {}).get('country')})
            edge(ident, candidate['id'], 'candidate_dealer', {'匹配状态': dealer['status'], '注意': '名单候选不代表资格已通过'}, True)
    pn = None if reply.get('decision') == 'clarify_product' else (reply.get('state') or {}).get('pn')
    if pn and root is not None and pn in {p['pn'] for p in load_json(Path(root) / 'data/products.json')}:
        if 'pn:' + pn not in nodes: add('pn:' + pn, 'product_model', pn, {'说明': '本轮会话识别的型号，不自动证明SKU主数据映射'})
        if order.get('order'):
            edge(order['order']['id'], 'pn:' + pn, '本轮识别型号', {'性质': '会话上下文；不是SKU主数据映射'}, True)
    decision = business.get('service_decision')
    if decision:
        ident = 'decision:' + reply.get('trace_id', 'preview')
        add(ident, 'Decision', '服务条件核查', {'判断': decision['outcome'], '待核实': decision.get('missing_facts', []), '下一步': decision.get('next_step')})
        subject = (order.get('order') or {}).get('id') or ('pn:' + pn if pn else None)
        if subject in nodes: edge(subject, ident, '本轮条件判断', {'性质': '运行时判断，不是执行或审批回执'}, True)
    workflow=reply.get('workflow')
    if workflow:
        ident=workflow['id'];add(ident,'ServiceCase',workflow['state_label'],{'流程状态':workflow['state'],'版本':workflow['revision'],'范围':'本地工作流；客户陈述不等于已核验事实'})
        for key,kind,label in [('request','AftersalesRequest','本地售后申请'),('human_task','HumanServiceTask','人工待办'),('survey','ServiceSurvey','满意度调查')]:
            record=workflow.get(key)
            if record:
                add(record['id'],kind,label,{'状态':record.get('status'),'编号':record['id'],'外部操作已执行':False})
                edge(ident,record['id'],'关联'+label,{'来源':'本地事务回执'})
        subject=(order.get('order') or {}).get('id')
        if subject in nodes:edge(ident,subject,'本案提及订单',{'注意':'不是订单归属核验'},True)
    priority = {'ServiceCase':-2,'AftersalesRequest':-1,'HumanServiceTask':-1,'Order': 0, 'product_model': 1, 'OrderItem': 2, 'Shipment': 3, 'KnowledgeArticle': 4,
                'ProductOffering': 5, 'error_code': 6, 'Decision': 7, 'OfficialArticle': 8}
    ordered = sorted(nodes.values(), key=lambda n: (priority.get(n['type'], 9), n['id']))
    visible = ordered[:32]; ids = {n['id'] for n in visible}
    clean_edges = {}; all_ids = set(nodes)
    for relation in edges:
        if relation['source'] in all_ids and relation['target'] in all_ids:
            clean_edges[(relation['source'], relation['target'], relation['relation'])] = relation
    return {'nodes': visible, 'edges': [e for e in clean_edges.values() if e['source'] in ids and e['target'] in ids],
            'total_nodes': len(nodes), 'truncated': len(nodes) > len(visible),
            'notice': '实线表示来源记录；虚线表示会话上下文或匹配候选，不代表业务审批。'}
