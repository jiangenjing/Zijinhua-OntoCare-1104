"""Integration checks, not an independent customer quality benchmark."""
import io
import json
import uuid
import pytest
from ontocare.customer_workflow import advance,classify,connect,get_case
from ontocare.intent_router import observed_claims


def step(root,sid,text='',event=None,context=None):
 return advance(root,sid,text,classify(text,get_case(root,sid)),context or {},event)


def test_negative_and_conflicting_customer_statements():
 assert observed_claims('问题仍未解决')['issue_persists']['value'] is True
 assert observed_claims('问题已经解决了')['issue_persists']['value'] is False
 assert observed_claims('以前没有收到，现在我收到了')['customer_received']['value'] is None


def test_model_low_confidence_and_fabricated_evidence(monkeypatch,test_root):
 from ontocare.provider import Provider
 for value in [dict(intent='shipping',issue_kind='shipping',confidence=.5,reason='Ambiguous',evidence='thing'),dict(intent='shipping',issue_kind='shipping',confidence=.99,reason='Guessed',evidence='fabricated quote')]:
  monkeypatch.setattr(Provider,'chat',lambda *a,**k:{'content':json.dumps(value)})
  routed=classify('Where is that thing?',live=True,root=test_root);assert routed['intent']=='clarification'
  c=advance(test_root,uuid.uuid4().hex,'Where is that thing?',routed,{});assert c['state']=='INTENT'


def test_stale_case_revision_and_unknown_remedy(test_root):
 sid=uuid.uuid4().hex
 c=step(test_root,sid,'我要退款');assert c['state']=='INTENT';assert not c.get('request')
 with pytest.raises(ValueError,match='案件已更新'):step(test_root,sid,'继续',{'expected_revision':0})
 c=step(test_root,sid,'是产品故障',{'issue_type':'fault'});assert c['state']=='CHANNEL'


def test_multiple_packages_require_selection_and_preserve_uncertainty(test_root,monkeypatch):
 import ontocare.customer_workflow as w
 monkeypatch.setattr(w,'order_detail',lambda *args:{'status':'FOUND_LOCAL_SNAPSHOT','items':[{'id':'i','properties':{'sku':'T2353','warranty_end':'2099-01-01T00:00:00'}}],'shipments':[{'id':'s1','properties':{'status':'DELIVERED'}},{'id':'s2','properties':{'status':'IN_TRANSIT'}}]})
 sid=uuid.uuid4().hex;c=step(test_root,sid,'包裹没收到，我要补发',{'customer_received':False},{'order_number':'Anker001'});assert c['state']=='SHIPMENT'
 with pytest.raises(ValueError):step(test_root,sid,'选择',{'shipment_id':'foreign'})
 c=step(test_root,sid,'选在途包裹',{'event':'select_shipment','shipment_id':'s2'});assert c['state']=='MATERIALS';assert c['delivery_basis']['contents_verified'] is False


def test_http_files_review_roles_receipts_and_trace(test_root):
 from ontocare.app import create_app
 from ontocare.customer_workflow_agent import CustomerWorkflowAgent
 from ontocare.retrieval import Retriever
 app=create_app(test_root,CustomerWorkflowAgent(test_root,Retriever(test_root)));client=app.test_client();sid='sop-'+uuid.uuid4().hex
 def chat(text,event=None):
  r=client.post('/api/chat',json={'session_id':sid,'message':text,'mode':'offline','context':{'country':'US','seller':'best buy'},'workflow':event or {}})
  assert r.status_code==200,r.get_json();return r.get_json()
 first=chat('机器坏了，我要申请退款',{'troubleshooting_completed':True,'issue_persists':True});assert first['workflow']['state']=='MATERIALS'
 for kind in ['purchase_proof','media']:
  r=client.post('/api/workflow/materials/'+sid,data={'kind':kind,'file':(io.BytesIO(b'%PDF-1.4\nCONSTRUCTED TEST ONLY'),kind+'.pdf')});assert r.status_code==200;assert r.json['status']=='RECEIVED_UNVERIFIED'
 ready=chat('补充申请信息',{'address':'TEST PRIVATE ADDRESS','serial_number':'TEST-SN'});assert ready['workflow']['state']=='READY'
 submitted=chat('确认提交',{'event':'submit'});assert submitted['workflow']['state']=='HUMAN_PENDING';assert submitted['model_status']=='workflow_contract'
 assert 'TEST PRIVATE ADDRESS' not in json.dumps(submitted);task=submitted['workflow']['human_task']['id']
 assert 'TEST PRIVATE ADDRESS' not in client.get('/api/workflow/tasks/'+task).get_data(as_text=True)
 assert client.get('/api/workflow/tasks/'+task+'/private').json['address']=='TEST PRIVATE ADDRESS'
 body={'decision':'ACCEPT_FOR_LOCAL_PROCESSING','note':'测试核验的明确理由','ownership_checked':True,'policy_checked':True}
 assert client.post('/api/workflow/tasks/'+task+'/decision',json=body).status_code==400
 mats=client.get('/api/workflow/tasks/'+task).json['materials']
 app.config['ONTOCARE_REVIEW_ACTOR']={'id':'model','roles':[]}
 assert client.post('/api/workflow/material/'+mats[0]['id']+'/review',json={'status':'VERIFIED','note':'测试材料来源人工核验'}).status_code==403
 app.config['ONTOCARE_REVIEW_ACTOR']={'id':'test-reviewer','roles':['CustomerServiceSupervisor']}
 for m in mats:
  assert client.get('/api/workflow/material/'+m['id']+'/download').status_code==200
  assert client.post('/api/workflow/material/'+m['id']+'/review',json={'status':'VERIFIED','note':'测试材料来源人工核验'}).status_code==200
 r=client.post('/api/workflow/tasks/'+task+'/decision',json=body);assert r.status_code==200,r.json;assert r.json['case']['state']=='REVIEWED';assert r.json['external_execution'] is False;assert r.json['task']['approved'] is False
 final=chat('查看审核进度');assert final['workflow']['state']=='REVIEWED';assert final['model_status']=='workflow_contract'
 assert client.post('/api/workflow/materials/'+sid,data={'kind':'media','file':(io.BytesIO(b'%PDF-test'),'x.pdf')}).status_code==400
 from ontocare.manager import snapshot
 from ontocare.ontology import active
 graph=snapshot(test_root,active(test_root));assert any(n['id']==submitted['workflow']['id'] for n in graph['nodes'])
 assert any(e['source']==submitted['workflow']['id'] and e['relation']=='case_has_tasks' for e in graph['links'])
 with connect(test_root) as c:assert any(json.loads(row[0]).get('function')=='reviewLocalServiceRequest' for row in c.execute('SELECT payload FROM events WHERE case_id=?',(submitted['workflow']['id'],)))
