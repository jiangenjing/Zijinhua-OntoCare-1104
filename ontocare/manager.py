"""Read-only business ontology projection, including explicit join diagnostics."""
from collections import Counter
from functools import lru_cache
from pathlib import Path
import json

from flask import Blueprint, jsonify, request, send_file

from .data import load_json, rows
from .sop import SCHEMA as SOP_SCHEMA, SOP_FILE


LABELS = {
    'ProductModel': '产品型号', 'KnowledgeArticle': '知识条目', 'ErrorCode': '错误码记录',
    'CheckStep': '检查步骤', 'Component': '部件', 'Condition': '资格条件',
    'Evidence': '来源证据', 'Mapping': '数据映射', 'Constraint': '业务约束',
    'SupportTicket': '客诉工单', 'Order': '订单', 'OrderItem': '订单商品', 'Dealer': '经销商', 'ReviewTask': '复核任务',
}
from .type_contracts import OBJECTS as CONTRACT_OBJECTS, LINKS as CONTRACT_LINKS
LABELS.update(CONTRACT_OBJECTS)
LABELS.update(ServiceCase='服务案件',AftersalesRequest='本地售后申请',HumanServiceTask='本地人工待办',ServiceSurvey='满意度调查',CustomerMaterial='客户提交材料')
TERM_TYPES = dict(product_model='ProductModel', knowledge_topic='KnowledgeArticle',
                  error_code='ErrorCode', check_action='CheckStep', component='Component', condition='Condition')
RELATIONS = [
    ('case_at_sop_step','案件当前流程','ServiceCase','SOPStep','N:1','实际案件状态，不表示已完成所有前置核验'),
    *[(r,label,'ServiceCase',target,'1:N','本机事务保存的对象，不代表外部业务已执行') for r,label,target in [('case_has_requests','提出售后申请','AftersalesRequest'),('case_has_tasks','生成人工待办','HumanServiceTask'),('case_has_surveys','关联调查','ServiceSurvey'),('case_has_material','提交材料','CustomerMaterial')]],
    ('applies_to', '适用知识', 'ProductModel', 'KnowledgeArticle', 'N:N', '知识 PN 明确包含产品型号'),
    ('has_error', '适用错误码', 'ProductModel', 'ErrorCode', 'N:N', '来源明确列出的型号与错误码'),
    ('explained_by', '故障说明', 'ErrorCode', 'KnowledgeArticle', 'N:1', '来源范围内的错误码记录'),
    ('supports_step', '支持检查步骤', 'KnowledgeArticle', 'CheckStep', '1:N', '原文支持的检查概念，不代表已执行'),
    ('has_component', '政策涉及部件', 'ProductModel', 'Component', '1:N', '来源政策中的部件'),
    ('requires_condition', '政策涉及条件', 'ProductModel', 'Condition', '1:N', '来源政策中的资格条件'),
    ('grounded_in', '来源依据', '*', 'Evidence', 'N:N', '节点明确引用的来源证据 ID'),
    ('mapped_by', '数据定位', 'KnowledgeArticle', 'Mapping', '1:1', 'Mapping.term_id 精确匹配'),
    ('constrained_by', '受约束', '*', 'Constraint', '1:N', 'Constraint.target 精确匹配'),
    ('mentions_product', '记录涉及型号', 'SupportTicket', 'ProductModel', 'N:1', '已导入工单 pn；不代表客户归属核验'),
    ('references_order', '提及订单', 'SupportTicket', 'Order', 'N:1', '订单号精确匹配；不代表身份核验'),
    ('contains_item', '包含商品行', 'Order', 'OrderItem', '1:N', '商品行 order_number 精确匹配'),
    ('item_model', '商品型号', 'OrderItem', 'ProductModel', 'N:1', '唯一且精确的已收录 SKU 别名匹配'),
    ('needs_review', '提交复核', 'SupportTicket', 'ReviewTask', '1:N', '本地 ActionType 已提交事务创建的关系，依据为动作审计 ID'),
]


RELATIONS.extend((i,label,a,b,cardinality,'受控动作事务创建；本地运行数据') for i,label,a,b,cardinality in CONTRACT_LINKS)

BUSINESS_SCHEMA = load_json(Path(__file__).resolve().parents[1] / 'data/business-schema.json')
LABELS.update({t['id']: t['label'] for t in BUSINESS_SCHEMA['objectTypes']})
RELATIONS.extend((r['id'], r['label'], r['source'], r['target'], r['cardinality'], r['rule']) for r in BUSINESS_SCHEMA['relations'])
LABELS.update({t['id']: t['label'] for t in SOP_SCHEMA['objectTypes']})
RELATIONS.extend((r['id'], r['label'], r['source'], r['target'], r['cardinality'], r['rule']) for r in SOP_SCHEMA['relations'])


def snapshot(root, version):
    root = Path(root)
    directory = root / 'ontology/versions' / version
    if directory.parent != root / 'ontology/versions' or not directory.is_dir():
        raise ValueError('未知本体版本')
    files = [root / 'data/competition-rules.json', root / SOP_FILE] + list(directory.glob('*.json')) + [root / 'data/knowledge.json', root / 'local/service.sqlite']
    if (root / 'local/business.sqlite').exists():
        files.append(root / 'local/business.sqlite')
    if (root / 'local/customer-sop.sqlite').exists():
        files.append(root / 'local/customer-sop.sqlite')
    if (root / 'local/actions.sqlite').exists():
        files.append(root / 'local/actions.sqlite')
    signature = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in sorted(files))
    return _snapshot(str(root), version, signature)


@lru_cache(maxsize=4)
def _snapshot(root, version, signature):
    root = Path(root)
    directory = root / 'ontology/versions' / version
    records = {name: load_json(directory / (name + '.json')) for name in ['terms', 'relations', 'evidence', 'mappings', 'constraints']}
    documents = {d['id']: d for d in load_json(root / 'data/knowledge.json')}
    nodes, links, diagnostics = {}, [], []

    def node(ident, kind, label, properties):
        nodes[ident] = dict(id=ident, type=kind, label=label, properties=properties)

    def link(source, target, relation, basis):
        if source not in nodes or target not in nodes:
            diagnostics.append(dict(level='error', code='missing_endpoint', source=source, target=target, detail=basis))
            return
        links.append(dict(source=source, target=target, relation=relation, basis=basis))

    for term in records['terms']:
        properties = dict(term)
        if term['id'].startswith('knowledge:'):
            properties.update(documents[term['id'].removeprefix('knowledge:')])
        node(term['id'], TERM_TYPES[term['type']], term['name'], properties)
    # Hidden Q&A remain inspectable, without being connected to the customer retrieval graph.
    for doc in documents.values():
        if 'knowledge:' + doc['id'] not in nodes:
            node('knowledge:' + doc['id'], 'KnowledgeArticle', doc['title'], doc)
    for family, kind in [('evidence', 'Evidence'), ('mappings', 'Mapping'), ('constraints', 'Constraint')]:
        for row in records[family]:
            node(row['id'], kind, row.get('query') or row.get('description') or row['id'], row)
    for rel in records['relations']:
        a, b = nodes.get(rel['source']), nodes.get(rel['target'])
        pair = (a['type'], b['type']) if a and b else None
        relation = {('ProductModel', 'KnowledgeArticle'): 'applies_to', ('ProductModel', 'ErrorCode'): 'has_error',
                    ('ErrorCode', 'KnowledgeArticle'): 'explained_by', ('KnowledgeArticle', 'CheckStep'): 'supports_step',
                    ('ProductModel', 'Component'): 'has_component', ('ProductModel', 'Condition'): 'requires_condition'}.get(pair)
        if relation is None:
            diagnostics.append(dict(level='error', code='unknown_relation', detail=rel))
            continue
        link(rel['source'], rel['target'], relation, dict(native_relation=rel['id'], evidence=rel.get('evidence', []), description=rel.get('description')))
    for family in ['terms', 'mappings', 'constraints']:
        for row in records[family]:
            for eid in row.get('evidence', row.get('evidence_refs', [])):
                link(row['id'], eid, 'grounded_in', '原生记录明确引用证据 ID')
    for row in records['mappings']:
        link(row['term_id'], row['id'], 'mapped_by', 'Mapping.term_id')
    for row in records['constraints']:
        link(row['target'], row['id'], 'constrained_by', 'Constraint.target')

    products, tickets, orders, items, dealers = [rows(name, root) for name in ['products', 'tickets', 'orders', 'order_items', 'dealers']]
    for row in tickets:
        node('ticket:' + row['id'], 'SupportTicket', row['id'] + ' · ' + row['scene'], row)
    for row in orders:
        node('order:' + row['order_number'], 'Order', row['order_number'], row)
    for row in items:
        node('item:' + str(row['source_row']), 'OrderItem', row['sku'], row)
    for index, row in enumerate(dealers):
        node('dealer:' + str(index), 'Dealer', row['country'] + ' · ' + row['seller'], row)
    for row in tickets:
        ident = 'ticket:' + row['id']
        if row['pn']:
            link(ident, 'pn:' + row['pn'], 'mentions_product', '导入工单 pn；原始行 ' + str(row['source_row']))
        else:
            diagnostics.append(dict(level='review', code='unresolved_ticket_model', node=ident, detail='SKU 未唯一映射型号：' + row['sku']))
        if row['order_number']:
            if 'order:' + row['order_number'] in nodes:
                link(ident, 'order:' + row['order_number'], 'references_order', '工单与订单的 order_number 完全相同；未核验客户身份')
            else:
                diagnostics.append(dict(level='review', code='order_not_in_snapshot', node=ident, detail='工单提及的订单不在本地快照'))
    for row in items:
        ident = 'item:' + str(row['source_row'])
        link('order:' + row['order_number'], ident, 'contains_item', 'order_number 精确匹配；原始行 ' + str(row['source_row']))
        matches = [p for p in products if row['sku'].upper() in p['aliases']]
        if len(matches) == 1:
            link(ident, 'pn:' + matches[0]['pn'], 'item_model', '已收录 SKU 别名完全匹配：' + row['sku'])
        else:
            diagnostics.append(dict(level='review', code='unresolved_item_model', node=ident, detail='未建立唯一 SKU→PN 映射；不强制关联主机：' + row['sku']))

    from .actions import runtime
    live = runtime(root)
    for state in live['states']:
        if 'ticket:' + state['ticket_id'] in nodes:
            nodes['ticket:' + state['ticket_id']]['properties'].update(state)
    for task in live['tasks']:
        node(task['id'], 'ReviewTask', task['id'], task)
    for relation in live['links']:
        link(relation['source'], relation['target'], relation['relation'], {'action_id': relation['action_id'], 'source': 'local/actions.sqlite', 'scope': 'local_demo'})
    from .business import projection
    business = projection(root)
    if business['nodes']:
        nodes = {key: value for key, value in nodes.items() if value['type'] != 'Dealer'}
    for record in business['nodes']:
        nodes[record['id']] = record
    for relation in business['links']:
        link(relation['source'], relation['target'], relation['relation'], relation['basis'])
    diagnostics.extend(business['diagnostics'])
    rules = load_json(root / 'data/competition-rules.json')['rules']
    for rule in rules:
        node(rule['id'], 'ServiceRule', rule['name'], rule)
    existing_rule_links = {(e['source'], e['target']) for e in links if e['relation'] == 'governed_by_service_rule'}
    for record in list(nodes.values()):
        for rule in rules:
            if record['type'] in rule['subjects'] and (record['id'], rule['id']) not in existing_rule_links:
                link(record['id'], rule['id'], 'governed_by_service_rule', rule['source'])
    from .sop import projection as sop_projection
    sop = sop_projection(root, list(nodes.values()))
    for record in sop['nodes']:
        nodes[record['id']] = record
    for relation in sop['links']:
        link(relation['source'], relation['target'], relation['relation'], relation['basis'])
    from .customer_workflow import graph_projection
    case_nodes, case_links = graph_projection(root)
    for record in case_nodes:
        nodes[record['id']] = record
    for relation in case_links:
        link(relation['source'], relation['target'], relation['relation'], relation['basis'])
    from .type_contracts import projection as contract_projection
    contract_nodes, contract_links = contract_projection(root)
    for record in contract_nodes:
        nodes[record['id']] = record
    for relation in contract_links:
        link(relation['source'], relation['target'], relation['relation'], relation['basis'])
    counts = Counter(n['type'] for n in nodes.values())
    relation_counts = Counter(l['relation'] for l in links)
    classes = [dict(id=key, label=value, count=counts[key]) for key, value in LABELS.items()]
    relations = [dict(id=i, label=label, source=a, target=b, cardinality=c, rule=rule, count=relation_counts[i]) for i, label, a, b, c, rule in RELATIONS]
    properties = []
    for kind in LABELS:
        fields = {}
        for n in nodes.values():
            if n['type'] != kind:
                continue
            for key, value in n['properties'].items():
                fields.setdefault(key, set()).add(type(value).__name__)
        properties.extend(dict(owner=kind, name=key, types=sorted(values)) for key, values in sorted(fields.items()))
    bundle = load_json(directory / 'bundle.json')
    actions = [dict(name=t['name'], status='只读查询' if t['read_only'] else '仅本地会话状态更新', definition=t) for t in bundle['tools']]
    return dict(version=version, sop=sop['metadata'], nodes=list(nodes.values()), links=links, classes=classes,
                relations=relations, properties=properties, diagnostics=diagnostics, actions=actions)


def register(app, root):
    root = Path(root)
    bp = Blueprint('ontology_manager', __name__)

    @bp.get('/ontology/manager')
    def page():
        return send_file(root / 'web/manager.html')

    @bp.get('/api/ontology-manager')
    def data():
        version = request.args.get('version') or load_json(root / 'ontology/active.json')['active_version']
        try:
            result = snapshot(root, version)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        response = jsonify(result)
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @bp.get('/api/ontology-manager/types')
    def types():
        from .type_catalog import catalog
        version = request.args.get('version') or load_json(root / 'ontology/active.json')['active_version']
        try:
            result = catalog(root, snapshot(root, version))
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        response = jsonify(result)
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @bp.get('/api/ontology-manager/legacy-audit')
    def audit():
        return jsonify(load_json(root / 'reports/legacy-ontology-audit.json'))

    @bp.post('/api/ontology-service/call')
    def service_call():
        from .service_api import OntologyService
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get('arguments', {}), dict):
            return jsonify(error='请提供工具名称和参数对象'), 400
        try:
            result = OntologyService(root).call(payload.get('name', ''), payload.get('arguments', {}))
        except (ValueError, TypeError, KeyError) as exc:
            return jsonify(error=str(exc)), 400
        response = jsonify(result)
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @bp.get('/api/ontology-service/source-rows')
    def source_rows():
        from .business import connect, coverage
        sheet = request.args.get('sheet', '')
        try:
            page = int(request.args.get('page', 1))
            if page < 1 or sheet not in {s['sheet'] for s in coverage(root)['sheets']}:
                raise ValueError('工作表或页码无效')
            with connect(root) as conn:
                rows = conn.execute('SELECT rownum,payload FROM raw_rows WHERE sheet=? ORDER BY rownum LIMIT 20 OFFSET ?', (sheet, (page-1)*20)).fetchall()
                total = conn.execute('SELECT count(*) FROM raw_rows WHERE sheet=?', (sheet,)).fetchone()[0]
            result = dict(sheet=sheet, page=page, total=total, items=[dict(source_row=n, fields=json.loads(payload)) for n, payload in rows])
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        response = jsonify(result)
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    app.register_blueprint(bp)
