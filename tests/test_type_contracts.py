"""Business contracts must execute; a status badge is not sufficient evidence."""
from concurrent.futures import ThreadPoolExecutor
import json,sqlite3,uuid
from pathlib import Path
import pytest
from ontocare.type_contracts import execute,initialize,connect,applicable_steps,suggest_next_check,projection,DEFAULT_ACTOR
from ontocare.app import create_app
from ontocare.customer_workflow_agent import CustomerWorkflowAgent
from ontocare.retrieval import Retriever
from ontocare.ontology import active

@pytest.fixture
def contract_app(test_root):
 return create_app(test_root,CustomerWorkflowAgent(test_root,Retriever(test_root)))

def command(action,parameters,**extra):
 return {'actionType':action,'parameters':parameters,'requestId':'test-'+uuid.uuid4().hex,**extra}

def start(client):
 sid='contract-test-'+uuid.uuid4().hex
 reply=client.post('/api/chat',json={'message':'T2353 错误码3212','mode':'offline','session_id':sid}).get_json()
 assert reply.get('service_task_id'),reply
 from ontocare.type_contracts import records
 return sid,reply

def task_from_reply(root,reply):
 with connect(root) as c:return json.loads(c.execute('SELECT payload FROM service_tasks WHERE id=?',(reply['service_task_id'],)).fetchone()[0])

def check_args(task,step,statement='已经检查并清理滚筒异物，问题仍然存在。',result='PERSISTS'):
 return {'task':{'objectType':'ServiceTask','id':task['id']},'step':{'objectType':'CheckStep','id':step['id']},'statement':statement,'result':result}

def test_real_objects_relationships_and_skill_state(contract_app,test_root):
 client=contract_app.test_client();sid,reply=start(client);task=task_from_reply(test_root,reply)
 result=client.post('/api/type-contracts/functions/suggestNextCheck',json={'model':{'objectType':'ProductModel','id':'pn:T2353'},'errorCode':'3212','completedChecks':[]})
 assert result.status_code==200,result.get_json();step=result.json['result']['nextCheck'];assert step and step['action']=='roller_inspect'
 body=command('recordCheckResult',check_args(task,step),expectedRevision=task['revision']);r=client.post('/api/type-contracts/actions/execute',json=body);assert r.status_code==200,r.json
 obs=r.json['observation'];assert obs['verificationStatus']=='REPORTED';assert r.json['committed'];assert r.json['externalExecution'] is False
 with sqlite3.connect(test_root/'local/service.sqlite') as c:
  state=json.loads(c.execute('SELECT payload FROM sessions WHERE id=?',(sid,)).fetchone()[0]);assert 'roller_inspect' in state['completed_actions'];assert state['verified']=={}
 next_=suggest_next_check(test_root,{'objectType':'ProductModel','id':'pn:T2353'},'3212',r.json['task']['completedChecks']);assert next_['status']=='MANUAL_REVIEW'
 again=client.post('/api/type-contracts/actions/execute',json=body);assert again.json['actionId']==r.json['actionId'];assert again.json['replayed']
 graph=client.get('/api/ontology-manager').json;ids={n['id'] for n in graph['nodes']};assert task['id'] in ids and obs['id'] in ids
 assert any(e['source']==task['id'] and e['target']==obs['id'] and e['relation']=='HAS_OBSERVATION' for e in graph['links'])
 assert any(e['source']==obs['id'] and e['target']==step['id'] for e in graph['links'])


def test_invalid_outcome_scope_and_server_permissions(contract_app,test_root):
 client=contract_app.test_client();_,reply=start(client);task=task_from_reply(test_root,reply);step=applicable_steps(test_root,'T2353','3212')[0]
 for statement,outcome in [('我没有做过检查','PERSISTS'),('已经检查并清理滚筒异物，问题仍然存在','RESOLVED')]:
  r=client.post('/api/type-contracts/actions/execute',json=command('recordCheckResult',check_args(task,step,statement,outcome)));assert r.status_code==400,r.json
 foreign=next(s for s in applicable_steps(test_root,'T2351','2113'))
 r=client.post('/api/type-contracts/actions/execute',json=command('recordCheckResult',check_args(task,foreign)));assert r.status_code==400
 forged=command('recordCheckResult',check_args(task,step));forged['roles']=['CustomerServiceSupervisor'];assert client.post('/api/type-contracts/actions/execute',json=forged).status_code==400
 contract_app.config['ONTOCARE_ACTION_ACTOR']={**DEFAULT_ACTOR,'id':'other-owner'}
 assert client.post('/api/type-contracts/actions/execute',json=command('recordCheckResult',check_args(task,step))).status_code==403
 contract_app.config['ONTOCARE_ACTION_ACTOR']={**DEFAULT_ACTOR,'roles':['Viewer']}
 assert client.post('/api/type-contracts/actions/execute',json=command('createServiceTask',{'source':{'objectType':'SupportTicket','id':'ticket:ticket-001'}})).status_code==403


def test_manual_request_has_real_queue_and_human_review_updates_objects(contract_app,test_root):
 client=contract_app.test_client();_,reply=start(client);task=task_from_reply(test_root,reply)
 args={'task':{'objectType':'ServiceTask','id':task['id']},'reason':'来源检查仍未明确，申请人工复核','evidenceRefs':[]}
 r=client.post('/api/type-contracts/actions/execute',json=command('submitManualReview',args));assert r.status_code==200,r.json
 req=r.json['request'];human=r.json['humanTask'];assert req['status']=='SUBMITTED';assert req['kind']=='MANUAL_REVIEW';assert req['externalExecution'] is False
 again=client.post('/api/type-contracts/actions/execute',json=command('submitManualReview',args));assert again.json['request']['id']==req['id']
 detail=client.get('/api/workflow/tasks/'+human['id']);assert detail.status_code==200
 review=client.post('/api/workflow/tasks/'+human['id']+'/decision',json={'decision':'ACCEPT_FOR_LOCAL_PROCESSING','note':'构造记录的本地审核流程测试'});assert review.status_code==200,review.json
 nodes,links=projection(test_root);request=next(n for n in nodes if n['id']==req['id']);assert request['properties']['status']=='COMPLETED';assert request['properties']['externalExecution'] is False
 assert any(e['source']==req['id'] and e['target']==task['id'] and e['relation']=='REQUEST_HANDLES_TASK' for e in links)


def test_update_session_action_is_bounded_and_audited(contract_app,test_root):
 client=contract_app.test_client();sid,reply=start(client)
 r=client.post('/api/type-contracts/actions/execute',json=command('updateSessionCheckState',{'sessionId':sid,'message':'已经检查并清理滚筒异物'}));assert r.status_code==200,r.json;assert r.json['completedChecks']==['roller_inspect']
 denied=client.post('/api/type-contracts/actions/execute',json=command('updateSessionCheckState',{'sessionId':sid,'message':'还没有检查滚筒'}));assert denied.status_code==400
 history=client.get('/api/type-contracts/records').json;assert any(r['actionType']=='updateSessionCheckState' and r['committed'] for r in history['actions'])


def test_stale_revision_and_atomic_rollback(contract_app,test_root):
 client=contract_app.test_client();_,reply=start(client);task=task_from_reply(test_root,reply);step=applicable_steps(test_root,'T2353','3212')[0]
 r=client.post('/api/type-contracts/actions/execute',json=command('recordCheckResult',check_args(task,step),expectedRevision=999));assert r.status_code==409
 with connect(test_root) as c:c.execute("CREATE TRIGGER fail_contract_event BEFORE INSERT ON contract_events BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
 try:
  r=client.post('/api/type-contracts/actions/execute',json=command('recordCheckResult',check_args(task,step)));assert r.status_code==503
  with connect(test_root) as c:assert not any(json.loads(o[0])['taskId']==task['id'] for o in c.execute('SELECT payload FROM check_observations'))
 finally:
  with connect(test_root) as c:c.execute('DROP TRIGGER fail_contract_event')


def test_all_catalog_entries_have_implementation_and_actual_counts(contract_app):
 c=contract_app.test_client();catalog=c.get('/api/ontology-manager/types').json;assert len({e['id'] for e in catalog['entries']})==len(catalog['entries'])
 assert all(e['status']=='implemented' for e in catalog['entries'])
 for name in ['ServiceTask','CheckObservation','ServiceRequest']:
  entry=next(e for e in catalog['entries'] if e['id']=='object:'+name);assert entry['classId']==name
 for name in ['HAS_OBSERVATION','REQUEST_HANDLES_TASK']:
  assert next(e for e in catalog['entries'] if e['id']=='link:'+name)['relationId']==name
 assert c.get('/ontology/contracts').status_code==200
 assert c.post('/api/type-contracts/functions/identifyProduct',json={'text':'E25'}).json['result']==['T2353']
 assert c.post('/api/type-contracts/functions/observed_actions',json={'text':'已经重启'}).json['result']==['restart']
 assert c.post('/api/type-contracts/functions/resolve_semantics',json={'mentions':['pn:T2353'],'context':'错误码3212'}).status_code==200
 assert c.post('/api/type-contracts/functions/classifyServiceIntent',json={'message':'查物流'}).json['result']['intent']=='shipping'
 assert c.post('/api/type-contracts/functions/evaluateServiceEligibility',json={'issue_type':'fault','remedy':'refund','claims':{}}).json['result']['can_execute_remedy'] is False
 assert c.post('/api/type-contracts/functions/identifyProduct',json={'text':'E25','roles':['admin']}).status_code==400
 assert c.post('/api/type-contracts/functions/advanceServiceCase',json={}).status_code==400

@pytest.mark.parametrize('outcome,statement,status',[
 ('RESOLVED','已经检查并清理滚筒异物，问题已经解决了','RESOLVED'),
 ('PERSISTS','已经检查并清理滚筒异物，问题仍然存在','IN_PROGRESS'),
 ('INCONCLUSIVE','结果不确定，无法判断','WAITING_CUSTOMER'),
 ('NOT_PERFORMED','还没执行这一步','WAITING_CUSTOMER')])
def test_all_reported_outcomes(contract_app,test_root,outcome,statement,status):
 client=contract_app.test_client();_,reply=start(client);task=task_from_reply(test_root,reply);step=applicable_steps(test_root,'T2353','3212')[0]
 r=client.post('/api/type-contracts/actions/execute',json=command('recordCheckResult',check_args(task,step,statement,outcome)));assert r.status_code==200,r.json
 assert r.json['task']['status']==status;assert r.json['observation']['verificationStatus']=='REPORTED'


def test_conflicting_observation_preserves_history_and_unsets_completion(contract_app,test_root):
 client=contract_app.test_client();sid,reply=start(client);task=task_from_reply(test_root,reply);step=applicable_steps(test_root,'T2353','3212')[0]
 first=client.post('/api/type-contracts/actions/execute',json=command('recordCheckResult',check_args(task,step))).json
 second=client.post('/api/type-contracts/actions/execute',json=command('recordCheckResult',check_args(task,step,'我还没执行这一步','NOT_PERFORMED'))).json
 assert second['observation']['verificationStatus']=='CONFLICT';assert second['observation']['previousObservationId']==first['observation']['id'];assert not second['task']['completedChecks']
 with sqlite3.connect(test_root/'local/service.sqlite') as c:assert 'roller_inspect' not in json.loads(c.execute('SELECT payload FROM sessions WHERE id=?',(sid,)).fetchone()[0])['completed_actions']


def test_product_change_starts_new_task_and_old_observation_does_not_poison_new_session(contract_app,test_root):
 client=contract_app.test_client();sid,reply=start(client);old=task_from_reply(test_root,reply);step=applicable_steps(test_root,'T2353','3212')[0]
 switched=client.post('/api/chat',json={'session_id':sid,'message':'现在咨询 T2351 错误码2113','mode':'offline'}).json
 assert switched['service_task_id']!=old['id'];assert switched['state']['pn']=='T2351'
 recorded=client.post('/api/type-contracts/actions/execute',json=command('recordCheckResult',check_args(old,step)));assert recorded.status_code==200
 with sqlite3.connect(test_root/'local/service.sqlite') as c:
  state=json.loads(c.execute('SELECT payload FROM sessions WHERE id=?',(sid,)).fetchone()[0]);assert state['pn']=='T2351';assert 'roller_inspect' not in state['completed_actions']


def test_read_functions_all_registered_names(contract_app,monkeypatch):
 from ontocare.provider import Provider,ModelUnavailable
 monkeypatch.setattr(Provider,'chat',lambda *a,**k:(_ for _ in ()).throw(ModelUnavailable('test_no_network')))
 client=contract_app.test_client()
 for name,args in [('lookup_order',{'order_number':'Anker003'}),('check_dealer',{'country':'US','seller':'best buy'}),('evaluate_service_decision',{'facts':{'intent':'fault'}}),('plan_customer_service',{'message':'E25 错误码3212','pn':'T2353'}),('search_evidence',{'pn':'T2353','query':'error 3212','error_code':'3212'})]:
  r=client.post('/api/type-contracts/functions/'+name,json=args);assert r.status_code==200,(name,r.json);assert r.json['readOnly'] is True


def test_action_key_conflict_and_remote_origin(contract_app,test_root):
 client=contract_app.test_client();_,reply=start(client);task=task_from_reply(test_root,reply);step=applicable_steps(test_root,'T2353','3212')[0];body=command('recordCheckResult',check_args(task,step))
 assert client.post('/api/type-contracts/actions/execute',json=body,headers={'Origin':'https://example.com'}).status_code==403
 assert client.post('/api/type-contracts/actions/execute',json=body).status_code==200
 body['parameters']['statement']='已经检查并清理滚筒异物，但是问题仍然存在';assert client.post('/api/type-contracts/actions/execute',json=body).status_code==409
