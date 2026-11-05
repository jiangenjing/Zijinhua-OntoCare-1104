"""Bounded local implementations of the workbench's business type contracts.
No expression evaluation, external remedies or client-supplied permissions.
"""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import uuid

import jsonschema
from .data import digest, load_json, redact, rows
from .ontology import active
from .actions import ActionError, DEFAULT_ACTOR

OBJECTS = {'ServiceTask':'服务任务','CheckObservation':'检查观察记录','ServiceRequest':'本地服务复核申请'}
LINKS = [('HAS_OBSERVATION','任务记录检查','ServiceTask','CheckObservation','1:N'),
         ('REQUEST_HANDLES_TASK','申请处理任务','ServiceRequest','ServiceTask','N:1'),
         ('TASK_FOR_CASE','任务所属案件','ServiceTask','ServiceCase','N:1'),
         ('TASK_FOR_TICKET','任务源工单','ServiceTask','SupportTicket','N:1'),
         ('OBSERVATION_OF_STEP','观察对应步骤','CheckObservation','CheckStep','N:1'),
         ('REQUEST_QUEUED_AS','申请进入人工待办','ServiceRequest','HumanServiceTask','N:1')]
TABLES = {'ServiceTask':'service_tasks','CheckObservation':'check_observations','ServiceRequest':'service_requests'}
RESULTS = ['RESOLVED','PERSISTS','INCONCLUSIVE','NOT_PERFORMED']
TEXT = {'type':'string','minLength':1,'maxLength':4000}

def ref(kind):
    return {'type':'object','additionalProperties':False,'required':['objectType','id'],
            'properties':{'objectType':{'const':kind},'id':{'type':'string','minLength':1,'maxLength':180}}}

def schema(properties,required=None):
    return {'type':'object','additionalProperties':False,'properties':properties,'required':required if required is not None else list(properties)}

ACTION_INPUTS = {
 'createServiceTask':schema({'source':{'oneOf':[ref('SupportTicket'),ref('ServiceCase')]}}),
 'recordCheckResult':schema({'task':ref('ServiceTask'),'step':ref('CheckStep'),'result':{'enum':RESULTS},'statement':TEXT}),
 'submitManualReview':schema({'task':ref('ServiceTask'),'reason':{'type':'string','minLength':6,'maxLength':1000},'evidenceRefs':{'type':'array','maxItems':20,'uniqueItems':True,'items':{'type':'string','maxLength':180}}}),
 'updateSessionCheckState':schema({'sessionId':{'type':'string','pattern':'^[A-Za-z0-9_-]{1,80}$'},'message':TEXT})}
FUNCTION_INPUTS = {
 'identifyProduct':schema({'text':TEXT}), 'observed_actions':schema({'text':TEXT}),
 'suggestNextCheck':schema({'model':ref('ProductModel'),'errorCode':{'type':['string','null'],'maxLength':20},'completedChecks':{'type':'array','maxItems':100,'uniqueItems':True,'items':{'type':'string','maxLength':180}}},['model']),
 'resolve_semantics':schema({'mentions':{'type':'array','minItems':1,'maxItems':5,'items':{'type':'string','maxLength':180}},'context':TEXT},['mentions']),
 'search_evidence':schema({'pn':TEXT,'query':TEXT,'error_code':{'type':['string','null'],'maxLength':20}},['pn','query']),
 'lookup_order':schema({'order_number':TEXT}), 'check_dealer':schema({'country':TEXT,'seller':TEXT}),
 'plan_customer_service':schema({'message':TEXT,**{k:{'type':'string','maxLength':100} for k in ['pn','order_number','country','seller']}},['message']),
 'evaluate_service_decision':schema({'facts':{'type':'object'},'as_of':{'type':['string','null'],'maxLength':30}},['facts']),
 'classifyServiceIntent':schema({'message':TEXT,'live':{'type':'boolean'}},['message']),
 'evaluateServiceEligibility':schema({'issue_type':{'enum':['shipping','fault','product','unknown','out_of_scope']},'remedy':{'enum':['none','refund','replacement','reship']},'claims':schema({k:{'type':'boolean'} for k in ['troubleshooting_completed','issue_persists','customer_received']},[]),'warranty_end':{'type':['string','null'],'maxLength':40}},['issue_type','remedy','claims'])}


def connect(root):
    from .customer_workflow import connect as workflow_connect
    return workflow_connect(root)


def initialize(root):
    with closing(connect(root)) as c, c:
        for table in TABLES.values():c.execute(f'CREATE TABLE IF NOT EXISTS {table}(id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
        c.executescript('''CREATE TABLE IF NOT EXISTS contract_links(id TEXT PRIMARY KEY,source TEXT,target TEXT,relation TEXT,action_id TEXT,UNIQUE(source,target,relation));
        CREATE TABLE IF NOT EXISTS contract_audit(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS contract_receipts(actor TEXT,request_key TEXT,request_hash TEXT,payload TEXT,PRIMARY KEY(actor,request_key));
        CREATE TABLE IF NOT EXISTS contract_events(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS contract_function_calls(id TEXT PRIMARY KEY,payload TEXT NOT NULL);''')


def now():return datetime.now(timezone.utc).isoformat()
def ident(prefix):return prefix+'-'+uuid.uuid4().hex[:20]
def get(c,kind,key):
    row=c.execute(f'SELECT payload FROM {TABLES[kind]} WHERE id=?',(key,)).fetchone()
    if not row:raise ActionError('not_found','引用的业务对象不存在。',404)
    return json.loads(row[0])
def save(c,kind,value):c.execute(f'INSERT OR REPLACE INTO {TABLES[kind]} VALUES(?,?)',(value['id'],json.dumps(value,ensure_ascii=False)))
def edge(c,a,b,relation,action_id):
    c.execute('INSERT OR IGNORE INTO contract_links VALUES(?,?,?,?,?)',(ident('contract-link'),a,b,relation,action_id))

def task_permission(task,actor):
    if task['owner']!=actor.get('id') and 'CustomerServiceSupervisor' not in actor.get('roles',[]):raise ActionError('task_forbidden','当前操作员无权处理该任务。',403)
    if actor.get('task_ids') is not None and task['id'] not in actor['task_ids']:raise ActionError('task_forbidden','任务不在服务端授权范围内。',403)


def source_task(c,root,source,actor,action_id):
    """One processing task per real source and confirmed product/error context."""
    state={};case=None;pn=None
    if source['objectType']=='SupportTicket':
        ticket=next((t for t in rows('tickets',root) if 'ticket:'+t['id']==source['id']),None)
        if not ticket:raise ActionError('source_not_found','原始工单不存在。',404)
        pn=ticket.get('pn');codes=re.findall(r'(?:error|code|错误码?|故障码?|报错)\s*[:：#-]?\s*(\d{3,5})',ticket.get('text',''),re.I)
        if codes:state['error_code']=codes[-1]
    else:
        row=c.execute('SELECT payload FROM cases WHERE id=?',(source['id'],)).fetchone()
        if not row:raise ActionError('source_not_found','服务案件不存在。',404)
        case=json.loads(row[0])
        with closing(sqlite3.connect(Path(root)/'local/service.sqlite')) as service:
            row=service.execute('SELECT payload FROM sessions WHERE id=?',(case['session_id'],)).fetchone();state=json.loads(row[0]) if row else {}
        pn=state.get('pn')
    if pn not in {p['pn'] for p in load_json(Path(root)/'data/products.json')}:pn=None
    for row in c.execute('SELECT payload FROM service_tasks ORDER BY rowid DESC'):
        task=json.loads(row[0])
        if task['sourceObject']==source and task.get('pn')==pn and task.get('errorCode')==state.get('error_code'):
            task_permission(task,actor);return task
    if case is None:
        case_id=ident('case');session=ident('operator-task')
        case={'id':case_id,'session_id':session,'state':'QA','state_label':'基于历史工单创建的本地处理任务','claims':{},'consent':False,'revision':0,'issue_type':'unknown','requested_remedy':'none','created_by':actor['id'],'origin':'OPERATOR_TASK_FROM_SEEN_TICKET_NOT_NEW_CUSTOMER','source_ticket':source['id']}
        c.execute('INSERT INTO cases VALUES(?,?,?)',(case_id,session,json.dumps(case,ensure_ascii=False)))
    task={'id':ident('service-task'),'taskId':None,'status':'NEW','owner':actor['id'],'sourceObject':source,'caseId':case['id'],'sessionId':case['session_id'],'pn':pn,'errorCode':state.get('error_code'),'ontologyVersion':active(root),'revision':0,'createdAt':now(),'creationActionId':action_id,'completedChecks':[],'verificationStatus':'CUSTOMER_REPORTED_NOT_VERIFIED','scope':'LOCAL_ONLY'};task['taskId']=task['id']
    save(c,'ServiceTask',task);edge(c,task['id'],case['id'],'TASK_FOR_CASE',action_id)
    if source['objectType']=='SupportTicket':edge(c,task['id'],source['id'],'TASK_FOR_TICKET',action_id)
    return task


def applicable_steps(root,pn,error_code=None):
    """Reuse the answer engine's actual source-action guard, without an LLM call."""
    from .reference_agent import SourceActionAgent
    from .references import ReferenceStore
    terms=load_json(Path(root)/'ontology/versions'/active(root)/'terms.json')
    documents=[d for d in load_json(Path(root)/'data/knowledge.json') if d['visible'] and pn in d['pns'] and (not error_code or re.search(r'(?<!\d)'+re.escape(error_code)+r'(?!\d)',d['title']))]
    documents=ReferenceStore(root).attach(documents,pn)
    # source_actions only uses the supplied document and its source text.
    guard=object.__new__(SourceActionAgent);out=[]
    for d in documents:
        actions=guard.source_actions(d)
        for t in terms:
            if t['type']=='check_action' and t['id'].startswith('action:'+d['id']+':') and t['id'].rsplit(':',1)[-1] in actions:
                out.append({'id':t['id'],'objectType':'CheckStep','label':t['name'],'action':t['id'].rsplit(':',1)[-1],'evidenceRefs':t.get('evidence',[]),'sourceId':d['id'],'sourceHash':d['content_hash'],'procedureRevision':active(root)+':'+d['content_hash']})
    return sorted(out,key=lambda v:v['id'])


def suggest_next_check(root,model,errorCode=None,completedChecks=None):
    pn=model['id'].removeprefix('pn:');done=set(completedChecks or [])
    if not model['id'].startswith('pn:') or pn not in {p['pn'] for p in load_json(Path(root)/'data/products.json')} or not errorCode:return {'nextCheck':None,'status':'NEED_CONTEXT','evidenceRefs':[],'reason':'需要已确认的产品型号和具体错误码，不能从型号相似度猜检查步骤。'}
    candidates=applicable_steps(root,pn,errorCode);remaining=[s for s in candidates if s['id'] not in done and s['action'] not in done]
    if not candidates:return {'nextCheck':None,'status':'NEED_CONTEXT','evidenceRefs':[],'reason':'没有找到该型号与错误码支持的检查步骤。'}
    return {'nextCheck':remaining[0] if remaining else None,'status':'SUGGEST_CHECK' if remaining else 'MANUAL_REVIEW','evidenceRefs':sorted({e for s in candidates for e in s['evidenceRefs']}),'reason':'仅返回适用且未被报告完成的来源步骤。' if remaining else '来源支持的步骤已被报告完成，建议人工复核。','verification':'reported completion is not physical verification'}


def explicit_result(statement,result,step):
    from .agent import observed_actions
    from .intent_router import observed_claims
    claims=observed_claims(statement);persist=claims.get('issue_persists',{}).get('value')
    done=step['action'] in observed_actions(statement) or bool(re.search(r'已完成(?:该|这个|此)(?:项)?步骤|completed (?:this|the) step',statement,re.I))
    absent=bool(re.search(r'还没|没有做|尚未|not yet|have not|haven.t',statement,re.I))
    if result=='RESOLVED':return persist is False and done and not absent
    if result=='PERSISTS':return persist is True and done and not absent
    if result=='NOT_PERFORMED':return absent
    return bool(re.search(r'不确定|无法判断|不知道结果|not sure|unclear|inconclusive',statement,re.I))



def sync_session_checks(c,root,task):
    if not any(row[1]=='service_db' for row in c.execute('PRAGMA database_list')):
        c.execute('ATTACH DATABASE ? AS service_db',(str(Path(root)/'local/service.sqlite'),))
    row=c.execute('SELECT payload FROM service_db.sessions WHERE id=?',(task['sessionId'],)).fetchone()
    if not row:return
    state=json.loads(row[0])
    if state.get('pn')!=task['pn'] or state.get('error_code')!=task.get('errorCode'):return
    supported=applicable_steps(root,task['pn'],task.get('errorCode'))
    done={s['action'] for s in supported if s['id'] in task['completedChecks']};known={s['action'] for s in supported}
    state['completed_actions']=list(dict.fromkeys([v for v in state.get('completed_actions',[]) if v not in known]+sorted(done)))
    for value in done:state.setdefault('claims',{})[value]='user_reported; not tool-verified'
    c.execute('UPDATE service_db.sessions SET payload=? WHERE id=?',(json.dumps(state,ensure_ascii=False),task['sessionId']))


def record_observation(c,root,task,step_id,result,statement,action_id):
    if task['status'] in {'ESCALATED','RESOLVED'}:raise ActionError('invalid_state','该任务已转人工或已解决，请勿追加排障结果。',409)
    step=next((s for s in applicable_steps(root,task['pn'],task.get('errorCode')) if s['id']==step_id),None) if task['pn'] else None
    if not step:raise ActionError('inapplicable_check','检查步骤不适用于任务型号、错误码或来源正文。')
    if not explicit_result(statement,result,step):raise ActionError('unconfirmed_result','需要明确说明该步骤是否已做及结果；陈述与选择冲突时不写入。')
    previous=[json.loads(r[0]) for r in c.execute('SELECT payload FROM check_observations')]
    last=next((o for o in reversed(previous) if o['taskId']==task['id'] and o['stepId']==step_id),None)
    observation={'id':ident('observation'),'observationId':None,'taskId':task['id'],'stepId':step_id,'result':result,'statement':redact(statement),'verificationStatus':'CONFLICT' if last and last['result'] in {'RESOLVED','PERSISTS'} and result=='NOT_PERFORMED' else 'REPORTED','previousObservationId':last['id'] if last else None,'reportedAt':now(),'procedureRevision':step['procedureRevision'],'evidenceRefs':step['evidenceRefs'],'actionId':action_id};observation['observationId']=observation['id']
    save(c,'CheckObservation',observation);edge(c,task['id'],observation['id'],'HAS_OBSERVATION',action_id);edge(c,observation['id'],step_id,'OBSERVATION_OF_STEP',action_id)
    task['status']='RESOLVED' if result=='RESOLVED' else 'IN_PROGRESS' if result=='PERSISTS' else 'WAITING_CUSTOMER'
    if result in {'RESOLVED','PERSISTS'}:task['completedChecks']=list(dict.fromkeys(task['completedChecks']+[step_id]))
    elif result=='NOT_PERFORMED':task['completedChecks']=[s for s in task['completedChecks'] if s!=step_id]
    task['revision']+=1;save(c,'ServiceTask',task)
    sync_session_checks(c,root,task)
    return observation


def execute(body,actor,root):
    initialize(root);c=connect(root);action_id=ident('contract-action');action=body.get('actionType') if isinstance(body,dict) else None
    try:
        c.execute('BEGIN IMMEDIATE')
        try:
            jsonschema.validate(body,schema({'actionType':{'enum':list(ACTION_INPUTS)},'parameters':{'type':'object'},'requestId':{'type':'string','pattern':'^[A-Za-z0-9_-]{8,100}$'},'expectedRevision':{'type':'integer','minimum':0}},['actionType','parameters','requestId']))
            jsonschema.validate(body['parameters'],ACTION_INPUTS[action])
        except jsonschema.ValidationError:raise ActionError('invalid_parameters','参数不符合已注册的动作契约。') from None
        if not set(actor.get('roles',[])) & {'CustomerServiceAgent','SupportAgent','CustomerServiceSupervisor'} or 'customer-service-review' not in actor.get('purposes',[]):raise ActionError('permission_denied','当前服务端身份没有客服处理角色或用途。',403)
        prior=c.execute('SELECT request_hash,payload FROM contract_receipts WHERE actor=? AND request_key=?',(actor['id'],body['requestId'])).fetchone()
        if prior:
            if prior['request_hash']!=digest(body):raise ActionError('idempotency_conflict','同一请求编号不能改变参数。',409)
            c.rollback();return {**json.loads(prior['payload']),'replayed':True},200
        args=body['parameters'];result={};task=None
        if action=='createServiceTask':task=source_task(c,root,args['source'],actor,action_id);result={'task':task,'existingTask':task.get('creationActionId')!=action_id}
        elif action=='updateSessionCheckState':
            c.execute('ATTACH DATABASE ? AS service_db',(str(Path(root)/'local/service.sqlite'),))
            row=c.execute('SELECT payload FROM service_db.sessions WHERE id=?',(args['sessionId'],)).fetchone()
            if not row:raise ActionError('session_not_found','原会话不存在。',404)
            state=json.loads(row[0])
            task=next((json.loads(r[0]) for r in c.execute('SELECT payload FROM service_tasks ORDER BY rowid DESC') if json.loads(r[0]).get('sessionId')==args['sessionId'] and json.loads(r[0]).get('pn')==state.get('pn') and json.loads(r[0]).get('errorCode')==state.get('error_code')),None)
            if not task:raise ActionError('session_not_bound','当前会话型号与错误码尚未绑定服务任务。',404)
        else:task=get(c,'ServiceTask',args['task']['id'])
        task_permission(task,actor)
        if 'expectedRevision' in body and task['revision']!=body['expectedRevision']:raise ActionError('revision_conflict','任务已更新，请刷新后使用最新版本。',409)
        if action=='recordCheckResult':result={'observation':record_observation(c,root,task,args['step']['id'],args['result'],args['statement'],action_id),'task':task}
        elif action=='submitManualReview':
            if len(args['reason'].strip())<6:raise ActionError('invalid_reason','请填写至少6个非空白字符的理由。')
            steps=applicable_steps(root,task['pn'],task.get('errorCode')) if task['pn'] else []
            allowed={e for s in steps for e in s['evidenceRefs']}
            if set(args['evidenceRefs'])-allowed:raise ActionError('inaccessible_evidence','证据不属于该任务适用范围。')
            existing=next((json.loads(r[0]) for r in c.execute('SELECT payload FROM service_requests') if json.loads(r[0])['taskId']==task['id']),None)
            if existing:result={'request':existing,'task':task,'existingRequest':True}
            else:
                if task['status']=='RESOLVED':raise ActionError('invalid_state','已解决任务不能再提交排障复核。',409)
                from .customer_workflow import queue,LABELS
                case=json.loads(c.execute('SELECT payload FROM cases WHERE id=?',(task['caseId'],)).fetchone()[0]);human=queue(c,case,'TYPE_CONTRACT_MANUAL_REVIEW')
                case.update(state='HUMAN_PENDING',state_label=LABELS['HUMAN_PENDING'],human_task=human,revision=case['revision']+1);c.execute('UPDATE cases SET payload=? WHERE id=?',(json.dumps(case,ensure_ascii=False),case['id']))
                req={'id':ident('service-request'),'requestId':None,'kind':'MANUAL_REVIEW','status':'SUBMITTED','taskId':task['id'],'humanTaskId':human['id'],'reason':redact(args['reason']),'evidenceRefs':args['evidenceRefs'],'submittedAt':now(),'submittedBy':actor['id'],'executionMode':'LOCAL_REVIEW','externalExecution':False};req['requestId']=req['id']
                save(c,'ServiceRequest',req);edge(c,req['id'],task['id'],'REQUEST_HANDLES_TASK',action_id);edge(c,req['id'],human['id'],'REQUEST_QUEUED_AS',action_id);task.update(status='ESCALATED',revision=task['revision']+1);save(c,'ServiceTask',task);result={'request':req,'task':task,'humanTask':human}
        elif action=='updateSessionCheckState':
            if task['status'] in {'ESCALATED','RESOLVED'}:raise ActionError('invalid_state','任务已结束或转人工，不能修改排障状态。',409)
            from .agent import observed_actions
            observed=observed_actions(args['message']);steps=applicable_steps(root,task['pn'],task.get('errorCode')) if task['pn'] else [];matched=[s for s in steps if s['action'] in observed]
            if not matched:raise ActionError('no_explicit_applicable_check','没有识别到适用于此任务的明确已完成检查，未写入。')
            row=c.execute('SELECT payload FROM service_db.sessions WHERE id=?',(args['sessionId'],)).fetchone()
            if not row:raise ActionError('session_not_found','原会话不存在。',404)
            state=json.loads(row[0]);keys=[s['action'] for s in matched];state['completed_actions']=list(dict.fromkeys(state.get('completed_actions',[])+keys));c.execute('UPDATE service_db.sessions SET payload=? WHERE id=?',(json.dumps(state,ensure_ascii=False),args['sessionId']))
            task['completedChecks']=list(dict.fromkeys(task['completedChecks']+[s['id'] for s in matched]));task.update(status='IN_PROGRESS',revision=task['revision']+1);save(c,'ServiceTask',task);result={'task':task,'completedChecks':keys,'verificationStatus':'REPORTED','statement':redact(args['message'])}
        event={'id':ident('contract-event'),'eventType':action,'taskId':task['id'],'at':now(),'delivery':'LOCAL_OUTBOX','externalExecution':False}
        if result.get('existingTask') or result.get('existingRequest'):event=None
        else:c.execute('INSERT INTO contract_events VALUES(?,?)',(event['id'],json.dumps(event)))
        receipt={'actionId':action_id,'actionType':action,'actor':actor['id'],'committed':True,'replayed':False,'createdAt':now(),'scope':'LOCAL_ONLY','externalExecution':False,'event':event,**result}
        c.execute('INSERT INTO contract_audit VALUES(?,?)',(action_id,json.dumps(receipt,ensure_ascii=False)));c.execute('INSERT INTO contract_receipts VALUES(?,?,?,?)',(actor['id'],body['requestId'],digest(body),json.dumps(receipt,ensure_ascii=False)));c.commit();return receipt,200
    except (ActionError,sqlite3.Error) as exc:
        c.rollback();error=exc if isinstance(exc,ActionError) else ActionError('transaction_failed','事务失败，业务修改已回滚。',503)
        record={'actionId':action_id,'actionType':action,'committed':False,'actor':actor.get('id'),'error':error.code,'message':error.message,'createdAt':now(),'externalExecution':False};c.execute('INSERT INTO contract_audit VALUES(?,?)',(action_id,json.dumps(record,ensure_ascii=False)));c.commit();return record,error.status
    finally:c.close()


def sync_case_task(root,case,state,actor=None):
    """Chat uses the same registered action and audit as the workbench."""
    key='auto-'+digest([case['id'],state.get('pn'),state.get('error_code')])[:40]
    receipt,status=execute({'actionType':'createServiceTask','parameters':{'source':{'objectType':'ServiceCase','id':case['id']}},'requestId':key},actor or DEFAULT_ACTOR,root)
    if status!=200:return None
    with closing(connect(root)) as c:return get(c,'ServiceTask',receipt['task']['id'])


def projection(root):
    path=Path(root)/'local/customer-sop.sqlite'
    if not path.exists():return [],[]
    nodes=[];links=[]
    with closing(sqlite3.connect(path)) as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='service_tasks'").fetchone():return [],[]
        for kind,table in TABLES.items():
            for row in c.execute(f'SELECT payload FROM {table}'):
                value=json.loads(row[0]);nodes.append({'id':value['id'],'type':kind,'label':OBJECTS[kind]+' · '+value['id'],'properties':value})
        for row in c.execute('SELECT source,target,relation,action_id FROM contract_links'):
            links.append({'source':row[0],'target':row[1],'relation':row[2],'basis':{'actionId':row[3],'source':'local/customer-sop.sqlite','scope':'LOCAL_ONLY'}})
    return nodes,links


def sync_review(c,case,decision,note):
    """Called inside the existing human-review transaction, never by a model."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='service_requests'").fetchone():return
    for row in c.execute('SELECT payload FROM service_requests').fetchall():
        value=json.loads(row[0]);task=get(c,'ServiceTask',value['taskId'])
        if task['caseId']!=case['id']:continue
        value.update(status={'NEEDS_INFORMATION':'UNDER_REVIEW','ACCEPT_FOR_LOCAL_PROCESSING':'COMPLETED','DECLINED':'REJECTED'}[decision],reviewNote=note,reviewedAt=now(),externalExecution=False)
        task.update(status='WAITING_CUSTOMER' if decision=='NEEDS_INFORMATION' else 'RESOLVED',revision=task['revision']+1,resolutionBasis='LOCAL_HUMAN_REVIEW_NOT_EXTERNAL_REMEDY')
        save(c,'ServiceRequest',value);save(c,'ServiceTask',task)


def call_function(name,args,root,agent):
    if name not in FUNCTION_INPUTS:raise ValueError('未注册的只读函数；写函数必须通过动作或客服流程调用。')
    jsonschema.validate(args,FUNCTION_INPUTS[name]);start=now()
    from .service_api import OntologyService
    service=OntologyService(root)
    if name=='identifyProduct':result=agent.identify(args['text'])
    elif name=='observed_actions':
        from .agent import observed_actions
        result=observed_actions(args['text'])
    elif name=='suggestNextCheck':result=suggest_next_check(root,**args)
    elif name=='resolve_semantics':
        from .ontology import layer
        result=layer(active(root),root).resolve(args['mentions'],args.get('context',''))
    elif name=='search_evidence':result=service.search_knowledge(args['pn'],args['query'],args.get('error_code'))
    elif name=='evaluateServiceEligibility':
        from .customer_workflow import evaluate_eligibility
        result=evaluate_eligibility(**args)
    elif name=='classifyServiceIntent':
        from .customer_workflow import classify
        result=classify(args['message'],live=args.get('live',False),root=root)
    else:result=getattr(service,name)(**args)
    result=service.public(result);record={'id':ident('function-call'),'result':result,'name':name,'calledAt':start,'completedAt':now(),'status':'completed','argumentHash':digest(args),'resultHash':digest(result),'scope':'LOCAL_ONLY','readOnly':True}
    with closing(connect(root)) as c,c:c.execute('INSERT INTO contract_function_calls VALUES(?,?)',(record['id'],json.dumps(record)))
    return {'callId':record['id'],'function':name,'result':result,'readOnly':True,'scope':'LOCAL_ONLY'}


def records(root):
    initialize(root)
    with closing(connect(root)) as c:
        return {'actions':[json.loads(r[0]) for r in c.execute('SELECT payload FROM contract_audit ORDER BY rowid DESC LIMIT 100')],
                'functions':[json.loads(r[0]) for r in c.execute('SELECT payload FROM contract_function_calls ORDER BY rowid DESC LIMIT 100')]}


def register(app,root,agent):
    from flask import current_app,jsonify,request,send_file
    initialize(root);root=Path(root)
    agent.contract_actor=lambda:app.config['ONTOCARE_ACTION_ACTOR']
    def local():
        if request.remote_addr not in {'127.0.0.1','::1'} or request.headers.get('Origin',request.host_url.rstrip('/'))!=request.host_url.rstrip('/'):raise PermissionError('仅允许本机同源调用')
    @app.get('/ontology/contracts')
    def contract_workbench():return send_file(root/'web/contracts.html')
    @app.get('/api/type-contracts')
    def contract_definitions():return jsonify(actions=ACTION_INPUTS,functions=FUNCTION_INPUTS,identity_mode='local_server_identity',scope='LOCAL_ONLY')
    @app.get('/api/type-contracts/records')
    def contract_records():return jsonify(records(root))
    @app.post('/api/type-contracts/actions/execute')
    def contract_action():
        try:local()
        except PermissionError as e:return jsonify(error=str(e)),403
        result,status=execute(request.get_json(silent=True),current_app.config['ONTOCARE_ACTION_ACTOR'],root)
        return jsonify(result),status
    @app.post('/api/type-contracts/functions/<name>')
    def contract_function(name):
        try:
            local();return jsonify(call_function(name,request.get_json(silent=True),root,agent))
        except PermissionError as e:return jsonify(error=str(e)),403
        except (ValueError,TypeError,KeyError,jsonschema.ValidationError):return jsonify(error='函数名称或参数不符合已注册契约'),400
