"""Shared bounded tools for the workbench and trusted local external agents."""
from collections import deque
import json
from pathlib import Path
import re

from .data import ROOT, load_json, redact
from .business import coverage, order_detail, check_seller
from .manager import snapshot
from .ontology import active

TOPOLOGIES = {
    'sop': ('业务SOP流程定义', ['ServiceProcess','SOPStep','RequiredMaterial','SOPAction','SOPDataBinding','ServiceRule']),
    'service': ('产品与排障', ['ProductModel', 'SupportTicket', 'KnowledgeArticle', 'ErrorCode', 'CheckStep', 'ReviewTask', 'ExternalMaterial']),
    'orders': ('订单与物流', ['Order', 'OrderItem', 'ProductOffering', 'Shipment', 'ProductModel']),
    'dealers': ('国家与销售方', ['Country', 'Dealer', 'DealerCheck', 'Order']),
    'knowledge': ('知识目录与来源', ['KnowledgeCategory', 'KnowledgeArticle', 'ProductModel', 'Evidence']),
}
TOOL_DESCRIPTIONS = {
    'list_report_templates': '列出经营分析模板、角色 Skill 与 Prompt。',
    'generate_report': '从当前本体生成并保存本地分析报告；不修改业务事实，live 模式调用模型。',
    'list_reports': '列出本地已生成的报告归档。',
    'get_report': '读取已保存报告及冻结的本体证据快照。',
    'get_report_evidence': '读取报告生成时的统计口径与对象标识。',
    'evaluate_service_decision': '按赛题 SOP 评估补发、换货与材料缺口，只给建议，绝不执行售后。',
    'list_ontologies': '列出可用本体、语义版本和本地数据边界。',
    'list_topologies': '列出产品排障、订单物流、经销名录和知识目录拓扑。',
    'list_classes': '列出当前对象类型与真实实例数。',
    'get_class_detail': '读取一个类型的定义、属性和关系。',
    'list_relations': '列出关系含义、基数、端点和依据。',
    'search_instances': '按类型、关键词分页搜索可见实例；不执行 SQL。',
    'get_instance_detail': '按最多 20 个 ID 批量查询实例。',
    'get_instance_topology': '按方向和最多 3 跳查询局部拓扑，最多返回 100 节点。',
    'search_knowledge': '按已确认 PN 和可选错误码检索发布且客户可见的原文证据。',
    'lookup_order': '读取本地订单、逐商品状态和包裹，默认不返回地址。',
    'check_dealer': '按国家检查销售方名录，返回候选与授权范围缺口，不判售后资格。',
    'list_types': '读取 Object/Link/Action/Function 定义及实现状态。',
    'submit_for_review': '经服务端启用后提交本地复核；不退款、不发信、不向真人系统转接。',
    'get_source_coverage': '读取全部 sheet 的纳入方式、字段和来源边界。',
    'plan_customer_service': '根据现有资料给出客服下一步、缺失信息与适用工具，缺条件时追问。',
    'get_delivery_report': '读取交付状态、MCP 配置提示及正式接入仍缺的能力。',
}


class OntologyService:
    def __init__(self, root=ROOT, allow_writes=False):
        self.root = Path(root)
        self.allow_writes = allow_writes
        self._knowledge_retriever = None

    def graph(self, version=None):
        return snapshot(self.root, version or active(self.root))

    def visible_graph(self, version=None):
        g = self.graph(version)
        hidden = {n['id'] for n in g['nodes'] if n['type'] == 'KnowledgeArticle' and not n['properties'].get('visible', True)}
        docs = {n['properties']['id'] for n in g['nodes'] if n['id'] in hidden}
        # Prevent hidden knowledge via its evidence, mapping or technical paths.
        allowed = [n for n in g['nodes'] if n['id'] not in hidden and not any(x in n['id'] for x in docs)]
        ids = {n['id'] for n in allowed}
        return allowed, [e for e in g['links'] if e['source'] in ids and e['target'] in ids]

    def public(self, value):
        if isinstance(value, list):return [self.public(v) for v in value]
        if isinstance(value, dict):return {k: v if k in {'tracking_number', 'tracking', 'actual_shipped_at', 'purchase_date', 'warranty_end', 'ship_date', 'source_sha256'} else self.public(v) for k, v in value.items() if k not in {'address', 'url'}}
        return redact(value) if isinstance(value, str) and ('@' in value or any(sum(c.isdigit() for c in m) >= 10 for m in re.findall(r'\b\+?\d[\d ()-]{9,}\b', value))) else value

    def list_ontologies(self):
        return {'ontologies': [{'id': 'ontocare', 'name': '安克智能客服', 'active_version': active(self.root),
                 'versions': sorted(p.name for p in (self.root / 'ontology/versions').iterdir() if p.is_dir()),
                 'business_projection': 'business-v1', 'scope': 'trusted_local_snapshot', 'write_enabled': self.allow_writes}]}

    def list_topologies(self):
        nodes, edges = self.visible_graph()
        kinds_by_id = {n['id']: n['type'] for n in nodes}
        return {'topologies': [{'id': k, 'name': label, 'classes': kinds, 'instances': sum(n['type'] in kinds for n in nodes),
                 'relations': sum(kinds_by_id[e['source']] in kinds and kinds_by_id[e['target']] in kinds for e in edges)} for k, (label, kinds) in TOPOLOGIES.items()]}

    def list_classes(self):
        g = self.graph();nodes, _ = self.visible_graph()
        return {'classes': [{**c, 'count': sum(n['type'] == c['id'] for n in nodes)} for c in g['classes']]}

    def get_class_detail(self, class_id):
        g = self.graph()
        if class_id not in {c['id'] for c in g['classes']}:raise ValueError('未知对象类型')
        from .type_catalog import catalog
        entry = next(e for e in catalog(self.root, g)['entries'] if e['id'] == 'object:' + class_id)
        return {'class': entry['definition'], 'status': entry['statusLabel'], 'relations': [r for r in g['relations'] if class_id in [r['source'], r['target']]]}

    def list_relations(self):return {'relations': self.graph()['relations']}

    def search_instances(self, class_id='', query='', page=1, page_size=20):
        if page < 1 or not 1 <= page_size <= 50 or len(query) > 500:raise ValueError('分页或搜索参数无效')
        nodes, _ = self.visible_graph()
        if class_id and class_id not in {c['id'] for c in self.graph()['classes']}:raise ValueError('未知对象类型')
        found = [n for n in nodes if (not class_id or n['type'] == class_id) and query.casefold() in json.dumps(self.public(n), ensure_ascii=False).casefold()]
        return {'total': len(found), 'page': page, 'page_size': page_size, 'items': self.public(found[(page-1)*page_size:page*page_size])}

    def get_instance_detail(self, instance_ids):
        if not instance_ids or len(instance_ids) > 20:raise ValueError('每次需提供 1—20 个实例 ID')
        nodes, edges = self.visible_graph();by_id = {n['id']: n for n in nodes}
        return {'results': [self.public({'instance': by_id[i], 'relations': [e for e in edges if i in [e['source'], e['target']]][:100], 'relation_limit': 100}) if i in by_id else {'id': i, 'status': 'NOT_FOUND_OR_NOT_VISIBLE'} for i in instance_ids]}

    def get_instance_topology(self, instance_id, depth=1, direction='both'):
        if not 1 <= depth <= 3 or direction not in {'both', 'incoming', 'outgoing'}:raise ValueError('深度为 1—3，方向为 both/incoming/outgoing')
        nodes, edges = self.visible_graph();by_id = {n['id']: n for n in nodes}
        if instance_id not in by_id:raise ValueError('实例不存在或不可见')
        seen, queue, truncated = {instance_id}, deque([(instance_id, 0)]), False
        while queue:
            current, hop = queue.popleft()
            if hop == depth:continue
            for edge in edges:
                target = edge['target'] if edge['source'] == current and direction in {'both', 'outgoing'} else edge['source'] if edge['target'] == current and direction in {'both', 'incoming'} else None
                if target is None or target in seen:continue
                if len(seen) >= 100:truncated = True;continue
                seen.add(target);queue.append((target, hop+1))
        return self.public({'nodes': [n for n in nodes if n['id'] in seen], 'links': [e for e in edges if e['source'] in seen and e['target'] in seen], 'truncated': truncated, 'max_nodes': 100})

    def search_knowledge(self, pn, query, error_code=None):
        from .reference_agent import ReferenceRetriever as Retriever
        if pn not in {p['pn'] for p in load_json(self.root / 'data/products.json')}:return {'status': 'NEED_CONFIRMED_MODEL', 'documents': []}
        if not query.strip() or len(query) > 4000:raise ValueError('请提供有效查询，长度不超过 4000')
        if self._knowledge_retriever is None:self._knowledge_retriever=Retriever(self.root)
        result = self._knowledge_retriever.search(query, pn=pn, error_code=error_code, allow_rewrite=True, ranking_profile='body_hybrid')
        return {'status': 'FOUND' if result['documents'] else 'NO_APPLICABLE_EVIDENCE', 'mode': result['mode'],
                'ranking_contract': result.get('ranking_contract'), 'query_rewrite': result.get('query_rewrite'),
                'reference_snapshot_sha256': result.get('reference_snapshot_sha256'),
                'documents': [{k: d[k] for k in ['id', 'title', 'content', 'content_hash', 'pns', 'source', 'references']} for d in result['documents']]}

    def lookup_order(self, order_number):return self.public(order_detail(order_number, self.root))
    def check_dealer(self, country, seller):return check_seller(country, seller, self.root)

    def list_types(self, kind=''):
        if kind not in {'', 'ObjectType', 'LinkType', 'ActionType', 'FunctionType'}:raise ValueError('未知 Type 类别')
        from .type_catalog import catalog
        entries = catalog(self.root, self.graph())['entries']
        return {'types': [{k: e[k] for k in ['id', 'kind', 'name', 'label', 'status', 'statusDetail', 'definition']} for e in entries if not kind or e['kind'] == kind]}

    def submit_for_review(self, ticket_id, reason, idempotency_key):
        if not self.allow_writes:return {'status': 'WRITE_DISABLED', 'committed': False, 'message': '当前连接只读；需服务端显式启用本地复核写入。'}
        from .actions import DEFAULT_ACTOR, execute, initialize
        initialize(self.root)
        payload = {'actionType': 'submitForReview', 'parameters': {'ticket': {'objectType': 'SupportTicket', 'id': ticket_id.removeprefix('ticket:')}, 'reason': reason}, 'idempotency_key': idempotency_key}
        result, status = execute(payload, DEFAULT_ACTOR, self.root)
        return self.public({'http_status': status, **result})

    def evaluate_service_decision(self, facts, as_of=None):
        from .decisions import evaluate
        return evaluate(facts, self.root, as_of)

    def get_source_coverage(self):
        result = coverage(self.root)
        rules = load_json(self.root / 'data/competition-rules.json')
        return {**result, 'competition_brief': {'file': rules['rules'][0]['source']['file'], 'rule_count': len(rules['rules']), 'version': rules['version'], 'boundary': '已阅读正文与业务 SOP 原图；外部飞书资料、教程与工单附件内容未完成核验'}}

    def plan_customer_service(self, message, pn='', order_number='', country='', seller=''):
        if not message.strip() or len(message) > 16000:raise ValueError('请输入 1—16000 字符的问题')
        if country or seller:
            result = self.check_dealer(country, seller)
            return {'intent': 'dealer_check', 'result': result, 'next_step': '核对购买国家、销售方、购买凭证及授权范围', 'can_promise_remedy': False}
        order_match = re.findall(r'\bAnker\d{3}\b', message, re.I)
        order_number = order_number or (order_match[0].capitalize() if order_match else '')
        if order_number and re.search('物流|快递|运单|发货|包裹|金额|多少钱|shipping|tracking|deliver|amount', message, re.I):
            return {'intent': 'shipping', 'result': self.lookup_order(order_number), 'next_step': '按商品与包裹分别说明快照状态，未知包裹内容需复核', 'can_promise_remedy': False}
        products = load_json(self.root / 'data/products.json');known = {p['pn'] for p in products}
        candidates = {m for m in re.findall(r'(?<![A-Z0-9])T[0-9][A-Z0-9]{3}(?![A-Z0-9])', message.upper()) if m in known}
        aliases = {'E25': ['T2353'], 'E28': ['T2352'], 'X10 Pro': ['T2351'], 'S1 Pro': ['T2080','T8D04'], 'SoloCam S340':['T8170']}
        for name, ids in aliases.items():
            if name.casefold() in message.casefold():candidates.update(i for i in ids if i in known)
        if pn and pn not in known:return {'intent': 'clarify_product', 'candidates': [], 'next_step': '核对 PN', 'can_promise_remedy': False}
        if pn:candidates = {pn}
        if len(candidates) != 1:return {'intent': 'clarify_product', 'candidates': sorted(candidates), 'next_step': '请确认品类、准确 PN 或设备标签；不自动选择首个候选', 'can_promise_remedy': False}
        pn = next(iter(candidates));codes = re.findall(r'(?:error|code|错误码?|故障码?|报错)\s*[:：#-]?\s*(\d{3,5})|(?<![A-Za-z0-9])(\d{3,5})\s*(?:error|错误|故障|报警)', message, re.I)
        error_code=next((v for v in codes[-1] if v),None) if codes else None
        evidence = self.search_knowledge(pn, message, error_code)
        aftersales = bool(re.search('退款|换货|质保|保修|refund|warranty|replacement', message, re.I))
        return {'intent': 'aftersales' if aftersales else 'troubleshooting', 'pn': pn, 'evidence': evidence,
                'next_step': '按原文适用范围追问并记录已做检查；资格不足转人工复核' if not aftersales else '核对购买日期、地区、部件及凭证；不得承诺资格', 'can_promise_remedy': False}

    def get_delivery_report(self):
        return {'implemented': ['五个 sheet 来源保留', '逐商品状态与金额原值', '多包裹快照', '国家限定卖家名录查询', '知识目录与可见性', '有界拓扑工具', '本地复核事务'],
                'production_gaps': ['客户身份与订单归属认证', '正式工单/订单/退款/物流接口', '授权有效期与品类政策', '图像/附件核验', '远程 MCP 鉴权、租户隔离与部署', '客服质量、成本和时延验收'],
                'scope': 'local_delivery_candidate', 'tools': TOOL_DESCRIPTIONS, 'write_enabled': self.allow_writes}

    def list_report_templates(self):
        from .reports import templates
        return templates(self.root)

    def generate_report(self, template_id, focus='', mode='live', version=None):
        from .reports import generate
        r = generate(template_id, focus, mode, version, self.root)
        return {k: r[k] for k in ['id', 'title', 'generation_status', 'narrative', 'created_at']} | {'view_url': '/reports?id='+r['id'], 'artifact_saved_locally': True, 'business_data_modified': False}

    def list_reports(self):
        from .reports import list_reports
        return list_reports(self.root)

    def get_report(self, report_id):
        from .reports import get_report
        return get_report(report_id, self.root)

    def get_report_evidence(self, report_id, evidence_id):
        from .reports import report_evidence
        return report_evidence(report_id, evidence_id, self.root)

    def call(self, name, arguments):
        if name not in TOOL_DESCRIPTIONS:raise ValueError('未注册工具')
        return getattr(self, name)(**arguments)
