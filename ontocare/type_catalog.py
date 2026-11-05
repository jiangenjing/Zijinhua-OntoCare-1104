"""Read-only type contracts and clearly separated interview design examples."""
import json
import sqlite3
from pathlib import Path

from .data import load_json
from .sop import SOP_FILE

STATUS = {'implemented': '已实现', 'partial': '部分实现', 'design': '设计示例'}
DESCRIPTIONS = {
    'ProductModel': '可区分的工程型号，不是具体设备，也不是 SKU 前缀。',
    'KnowledgeArticle': '有适用产品范围和可见性限制的知识文章。',
    'CheckStep': '原文支持的检查概念；节点存在不代表客户已执行。',
    'ErrorCode': '来源和型号范围内的错误码记录，不等于已确认根因。',
    'SupportTicket': '客户提出的一次客诉记录；当前资料主要为首封邮件。',
    'Order': '一次购买交易的本地资料快照，不代表实时订单。',
    'OrderItem': '订单中一项购买内容，可有多件商品。',
    'Dealer': '销售组织或店铺的名录记录，关联不等于已核实授权。',
    'Evidence': '支持语义记录的原文及来源定位。',
    'Mapping': '概念到源数据的技术定位，属于溯源视图。',
    'Constraint': '知识适用性或政策核验约束；具体执行需运行代码。',
    'Component': '政策中提及的部件概念，尚非完整部件主数据。',
    'Condition': '政策中提及的资格条件，尚非完整决策引擎。',
    'ReviewTask': '本地 ActionType 创建的复核任务，关联工单、理由与动作审计；不代表外部人工已接单。',
}


def call_records(root, version):
    """Summaries only: never expose prompts, order addresses, or tool payloads."""
    path = Path(root) / 'local/service.sqlite'
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='traces'").fetchone():
            return []
        records = []
        for (payload,) in conn.execute('SELECT payload FROM traces ORDER BY rowid DESC LIMIT 200'):
            trace = json.loads(payload)
            if trace.get('version') != version:
                continue
            for index, tool in enumerate(trace.get('tools', [])):
                records.append(dict(id=f"{trace['trace_id']}:{index}", tool=tool['name'],
                                    traceId=trace['trace_id'], version=version,
                                    mode=trace.get('mode'), decision=trace.get('decision'),
                                    recordKind='local_trace',
                                    provenance='本地调用轨迹，可能包含评测；不代表真实客户或正式办理'))
            for index, tool in enumerate(trace.get('workflow_function_calls', [])):
                records.append(dict(id=f"{trace['trace_id']}:workflow:{index}",tool=tool['name'],traceId=trace['trace_id'],version=version,mode=trace.get('mode'),decision=trace.get('decision'),recordKind='local_workflow_trace',provenance='实际客服函数/动作摘要；不是外部办理回执'))
        return records


def catalog(root, snapshot):
    root = Path(root)
    content = load_json(root / 'web/type-definitions.json')
    entries = []
    schema = load_json(root / 'data/business-schema.json')
    business_types = {t['id']: t for t in schema['objectTypes']}
    sop_types = {t['id']: t for t in load_json(root / SOP_FILE)['schema']['objectTypes']}
    business_types.update(sop_types)
    for cls in snapshot['classes']:
        meanings = {'pn': '工程型号编码', 'name': '语义记录名称，产品概念使用 PN', 'aliases': '已收录型号或 SKU 别名，用于消歧', 'pns': '知识适用型号范围', 'visible': '是否允许客户召回', 'content': '来源知识原文', 'evidence': '支持该概念的证据引用', 'scope': '记录适用范围', 'order_number': '购买订单号，提及不代表归属核验', 'quantity': '该订单项购买数量', 'id': '原始记录标识；管理节点标识位于 node.id', 'type': '语义记录类别', 'status': '该对象当前业务状态'}
        fields = {p['name']: {'observedTypes': p['types'], 'description': meanings.get(p['name'], '当前实例字段，具体含义见来源；非强制校验声明')}
                  for p in snapshot['properties'] if p['owner'] == cls['id']}
        definition = dict(ObjectType=cls['id'], displayName=cls['label'],
                          description=DESCRIPTIONS.get(cls['id'], business_types.get(cls['id'], {}).get('description', cls['label'])), primaryKey='node.id',
                          properties=fields,
                          schemaOrigin='管理投影：字段从当前实例汇总；未声明全量必填/枚举/验证器')
        if cls['id'] == 'ProductModel':
            definition['primaryKey'] = 'pn:{PN}（当前节点标识）'
        if cls['id'] in business_types:
            definition.update(properties=business_types[cls['id']]['properties'], schemaOrigin='业务投影声明 data/business-schema.json；实例保留原始来源')
        entries.append(dict(id='object:' + cls['id'], kind='ObjectType', name=cls['id'], label=cls['label'],
                            status='implemented', statusDetail='已实现读取与关联投影；JSON 是当前结构说明，不是声明式写入执行器。',
                            source=['ontocare/manager.py: LABELS / TERM_TYPES', 'ontology/versions/' + snapshot['version']],
                            definition=definition, classId=cls['id'], examples=[], references=[]))
        if cls['id'] in sop_types:
            entries[-1]['source'] = [SOP_FILE, 'ontocare/sop.py: projection']
            entries[-1]['definition']['schemaOrigin'] = SOP_FILE + '；版本化流程定义与只读数据绑定'
            entries[-1]['statusDetail'] = '已实现本体建模、查询和本机步骤绑定；定义不代表流程已自动执行，实际案件另存。'
    for rel in snapshot['relations']:
        refs = ['object:' + t for t in [rel['source'], rel['target']] if t != '*']
        entries.append(dict(id='link:' + rel['id'], kind='LinkType', name=rel['id'], label=rel['label'],
                            status='implemented', statusDetail='已实现读取关联；基数为现有投影声明，尚不表示数据库自动强制约束。',
                            source=['ontocare/manager.py: RELATIONS / link'], relationId=rel['id'],
                            definition=dict(LinkType=rel['id'], displayName=rel['label'],
                                            **{'from': rel['source'], 'to': rel['target']},
                                            cardinality=rel['cardinality'], description=rel['rule'],
                                            properties={'basis': {'type': 'string | object', 'description': '关联来源依据'}}),
                            examples=[], references=refs))
    for declaration in content['entries']:
        existing=next((e for e in entries if e['id']==declaration['id']),None)
        if existing:
            existing.update({k:v for k,v in declaration.items() if k not in {'definition'}})
            existing['definition'].update(declaration['definition'])
        else:entries.append(declaration)
    from .type_contracts import ACTION_INPUTS, FUNCTION_INPUTS
    for entry in entries:
        if entry['name'] in ACTION_INPUTS:
            entry['definition']['inputSchema']=ACTION_INPUTS[entry['name']]
        if entry['name'] in FUNCTION_INPUTS:
            entry['definition']['inputSchema']=FUNCTION_INPUTS[entry['name']]
            entry['definition']['endpoint']='/api/type-contracts/functions/'+entry['name']
            entry['executionUrl']='/ontology/contracts#'+entry['name']
    entries.append(dict(id='action:createServiceTask',kind='ActionType',name='createServiceTask',label='从来源创建处理任务',status='implemented',statusDetail='只接受真实工单或服务案件引用，同一来源重用任务，不改原始工单。',source=['ontocare/type_contracts.py'],definition={'ActionType':'createServiceTask','inputSchema':ACTION_INPUTS['createServiceTask'],'scope':'LOCAL_ONLY'},executionUrl='/ontology/contracts#createServiceTask',examples=[],references=['object:ServiceTask','object:SupportTicket','object:ServiceCase']))
    entries.append(dict(id='action:submitForReview', kind='ActionType', name='submitForReview', label='提交本地人工复核',
                        status='implemented', statusDetail='已实现本地事务、幂等、角色/用途检查、状态变更、任务与关联、事件和审计；使用本地演示身份，不是生产授权或外部转接。',
                        source=['actions/submit-review.json', 'ontocare/actions.py: execute'],
                        definition=load_json(root / 'actions/submit-review.json'), executionUrl='/ontology/actions',
                        examples=[], references=['object:SupportTicket', 'object:ReviewTask', 'link:needs_review']))
    for name,label,handler in [('classifyServiceIntent','识别服务意图','ontocare.customer_workflow.classify'),('evaluateServiceEligibility','评估服务前置条件','ontocare.customer_workflow.evaluate_eligibility'),('advanceServiceCase','推进本地服务案件','ontocare.customer_workflow.advance')]:
        entries.append(dict(id='function:'+name,kind='FunctionType',name=name,label=label,status='implemented',
                            statusDetail='客服实际调用的 Python 函数；输入受校验，模型识别不构成业务审批。不是部署于 Palantir Foundry 的函数。',
                            source=[handler],definition={'FunctionType':name,'handler':handler,'scope':'LOCAL_ONLY'},examples=[],traceTools=[name],references=['object:ServiceCase']))
    for name,label,url in [('submitAftersalesRequest','提交本地售后申请','/api/chat'),('reviewLocalServiceRequest','人工审核本地申请','/api/workflow/tasks/{id}/decision')]:
        entries.append(dict(id='action:'+name,kind='ActionType',name=name,label=label,status='implemented',
                            statusDetail='实际本机事务保存申请、待办或人工审核结果和审计；不执行外部售后。',source=['ontocare/customer_workflow.py','ontocare/customer_review.py'],
                            definition={'ActionType':name,'endpoint':url,'validation':'类型校验、案件状态与材料前提；人工审核另校验服务端主管角色','audit':True,'external_execution':False},
                            executionUrl='/service' if name=='submitAftersalesRequest' else '/workflow/human',examples=[],traceTools=[name],references=['object:ServiceCase','object:AftersalesRequest','object:HumanServiceTask']))
    for entry in entries:
        if entry['name'] in FUNCTION_INPUTS:
            entry['definition']['inputSchema']=FUNCTION_INPUTS[entry['name']]
            entry['definition']['readOnly']=True
            entry['statusDetail']='已注册本机函数接口，参数按Schema校验并保存真实调用记录；只读查询不执行外部售后。'
            entry['executionUrl']='/ontology/contracts#'+entry['name']
        elif entry['name']=='advanceServiceCase':
            entry['definition'].update(readOnly=False,executionPolicy='只能通过现有客服动作调用，不能从只读函数入口写入')
            entry['executionUrl']='/service'
    calls = call_records(root, snapshot['version'])
    for entry in entries:
        entry['statusLabel'] = STATUS[entry['status']]
        entry['instanceIds'] = [n['id'] for n in snapshot['nodes'] if n['type'] == entry.get('classId')]
        entry['relationCount'] = sum(l['relation'] == entry.get('relationId') for l in snapshot['links'])
        entry['records'] = [r for r in calls if r['tool'] in entry.get('traceTools', [])]
        # Completion inheritance is versioned. Do not label v0 as candidate-1.
        if entry['id'] == 'action:updateSessionCheckState':
            bundle = load_json(root / 'ontology/versions' / snapshot['version'] / 'bundle.json')
            entry['definition']['completionTrackingEnabled'] = bundle['skills']['troubleshooting'].get('track_completed', False)
        entry['recordCount'] = len(entry['records'])
    action_db = root / 'local/actions.sqlite'
    if action_db.exists():
        with sqlite3.connect(action_db.resolve().as_uri() + '?mode=ro', uri=True) as conn:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='action_audit'").fetchone():
                entry = next((e for e in entries if e['id'] == 'action:submitForReview'), None)
                if entry is not None:
                    entry['records'] = [dict(id=r['action_id'], tool=r['actionType'], mode='local_demo',
                                             decision='COMMITTED' if r['committed'] else r.get('error', 'FAILED'),
                                             recordKind='local_action_audit', provenance='独立本地运行层审计，不绑定语义版本；不是外部办理回执')
                                        for (payload,) in conn.execute('SELECT payload FROM action_audit ORDER BY rowid DESC LIMIT 100')
                                        for r in [json.loads(payload)]]
                    entry['recordCount'] = len(entry['records'])
    from .type_contracts import records as contract_records
    local=contract_records(root)
    for entry in entries:
        if entry['kind'] in {'ActionType','FunctionType'}:
            key='actions' if entry['kind']=='ActionType' else 'functions'
            entry['records'].extend({'id':r.get('actionId',r.get('id')),'tool':entry['name'],'mode':'local_contract','decision':('COMMITTED' if r.get('committed') else r.get('error')) if key=='actions' else r.get('status'),'recordKind':'local_contract_audit','provenance':'本地实际事务/调用；不是生产办理回执'} for r in local[key] if r.get('actionType',r.get('name'))==entry['name'])
            entry['recordCount']=len(entry['records'])
    workflow_db=root/'local/customer-sop.sqlite'
    if workflow_db.exists():
        with sqlite3.connect(workflow_db.resolve().as_uri()+'?mode=ro',uri=True) as conn:
            for (raw,) in conn.execute('SELECT payload FROM events ORDER BY rowid DESC LIMIT 100'):
                event=json.loads(raw)
                if event.get('function')=='reviewLocalServiceRequest':
                    entry=next(e for e in entries if e['id']=='action:reviewLocalServiceRequest')
                    entry['records'].append(dict(id=event['id'],tool='reviewLocalServiceRequest',mode='local_human_review',decision=event['details']['decision'],recordKind='local_operator_audit',provenance='实际本机操作员审核；不是外部售后执行'))
                    entry['recordCount']=len(entry['records'])
    ids = {e['id'] for e in entries}
    for entry in entries:
        if set(entry['references']) - ids:
            raise ValueError('类型目录引用不存在：' + entry['id'])
    return dict(version=snapshot['version'], schemaNote=content['schemaNote'], entries=entries,
                articles=content['articles'], traceWindow='最多扫描最近 200 条本地轨迹，再按所选本体版本过滤；不是全量调用统计。')
