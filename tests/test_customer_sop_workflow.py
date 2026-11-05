import json,uuid
from pathlib import Path
import pytest
from ontocare.customer_workflow import classify,advance,get_case,connect,dealer,validate,graph_projection


def call(root,session,text='',event=None,context=None,previous=None):
 previous=get_case(root,session)
 return advance(root,session,text,classify(text,previous),context or {},event)


def test_separate_fault_and_refund():
 x=classify('设备坏了，我要申请退款');assert x['issue_type']=='fault';assert x['requested_remedy']=='refund'


def test_model_is_constrained_fallback(monkeypatch,test_root):
 from ontocare.provider import Provider
 monkeypatch.setattr(Provider,'chat',lambda *a,**k:{'content':'{"intent":"shipping","issue_kind":"shipping","confidence":0.94,"reason":"Parcel tracking inquiry","evidence":"parcel"}'})
 x=classify('Where is my parcel?',live=True,root=test_root);assert x['method']=='llm_assisted';assert x['issue_type']=='shipping';assert x['verified_facts'] is False


def test_injected_verified_field_rejected():
 with pytest.raises(ValueError):validate({'purchase_proof_verified':True})
 with pytest.raises(ValueError):validate({'event':'approve'})


def test_outside_scope_persists_actual_task_and_is_idempotent(test_root):
 sid=uuid.uuid4().hex;c=call(test_root,sid,'请给我股票推荐');assert c['state']=='HUMAN_PENDING';task=c['human_task']['id'];again=call(test_root,sid,'请转人工',{'event':'human'});assert again['human_task']['id']==task;assert again['human_task']['approved'] is False


def test_resolution_and_survey_saved(test_root):
 sid=uuid.uuid4().hex;c=call(test_root,sid,'E25怎么使用');assert c['state']=='QA';c=call(test_root,sid,'问题解决了',{'event':'resolved'});assert c['state']=='CLOSED';assert c['survey']['sent_external'] is False
 c=call(test_root,sid,'评价',{'event':'feedback','csat':5});assert c['survey']['csat']==5


def test_decline_and_continue(test_root):
 sid=uuid.uuid4().hex;call(test_root,sid,'E25故障');c=call(test_root,sid,'仍未解决',{'event':'unresolved'});assert c['state']=='CONSENT';c=call(test_root,sid,'继续咨询',{'event':'decline'});assert c['state']=='QA';assert c['consent'] is False


def test_fault_refund_requires_sn_and_materials_then_creates_receipt(test_root):
 sid=uuid.uuid4().hex;c=call(test_root,sid,'设备坏了，我要申请退款',event={'troubleshooting_completed':True,'issue_persists':True},context={'country':'US','seller':'best buy'});assert c['state']=='MATERIALS';assert 'serial_number' in c['missing_materials'];assert c['consent'] is True
 with connect(test_root) as conn:
  for kind in ['purchase_proof','media']:
   receipt={'id':'m-'+uuid.uuid4().hex,'kind':kind,'case_id':c['id'],'status':'RECEIVED_UNVERIFIED'};conn.execute('INSERT INTO materials VALUES(?,?,?,?)',(receipt['id'],c['id'],kind,json.dumps(receipt)))
 c=call(test_root,sid,'补充信息',{'serial_number':'DEMO-SN','address':'演示寄送地址','event':'continue'});assert c['state']=='READY';assert 'address' not in c['claims']
 c=call(test_root,sid,'确认提交',{'event':'submit'});assert c['state']=='HUMAN_PENDING';assert c['request']['status']=='PENDING_HUMAN';assert c['request']['approved'] is False
 again=call(test_root,sid,'重复提交',{'event':'submit'});assert again['request']['id']==c['request']['id'];assert again['human_task']['id']==c['human_task']['id']
 nodes,links=graph_projection(test_root);ids={n['id'] for n in nodes}|{s['id'] for s in json.loads((test_root/'data/service-sop-v1.json').read_text())['steps']};assert all(l['source'] in ids and l['target'] in ids for l in links)


def test_missing_material_cannot_submit(test_root):
 sid=uuid.uuid4().hex;c=call(test_root,sid,'故障，我要申请退款',event={'troubleshooting_completed':True,'issue_persists':True},context={'country':'US','seller':'best buy'});c=call(test_root,sid,'提交',{'event':'submit'});assert c['state']=='MATERIALS';assert not c.get('request')


def test_non_authorized_and_exact_country(test_root):
 assert dealer('US','best buy',test_root)['authorized_by_brief'] is True
 assert dealer('GB','best buy',test_root)['authorized_by_brief'] is False
 sid=uuid.uuid4().hex;c=call(test_root,sid,'设备坏了，我要退款',context={'country':'US','seller':'zzzz-not-listed'});assert c['state']=='NON_AUTHORIZED'


def test_invalid_target_item_rejected(test_root):
 sid=uuid.uuid4().hex;call(test_root,sid,'设备坏了，我要退款',context={'order_number':'Anker008'})
 with pytest.raises(ValueError):call(test_root,sid,'选择',{'event':'select_item','item_id':'other-order-item'})

@pytest.mark.parametrize('expiry,done,persists,expected',[('2020/01/01',True,True,'EXPIRED'),('2099/01/01',False,True,'TROUBLESHOOT'),('2099/01/01',True,True,'MATERIALS')])
def test_target_warranty_and_fault_gate(test_root,monkeypatch,expiry,done,persists,expected):
 import ontocare.customer_workflow as w
 monkeypatch.setattr(w,'order_detail',lambda *args:{'status':'FOUND_LOCAL_SNAPSHOT','items':[{'id':'item-demo','properties':{'sku':'T2353','warranty_end':expiry}}],'shipments':[]})
 c=call(test_root,uuid.uuid4().hex,'设备坏了，我要换货',{'troubleshooting_completed':done,'issue_persists':persists},{'order_number':'Anker001'})
 assert c['state']==expected

@pytest.mark.parametrize('delivery,expected',[('DELIVERED','HUMAN_PENDING'),('IN_TRANSIT','MATERIALS'),('UNKNOWN','HUMAN_PENDING')])
def test_shipping_condition_never_approves_remedy(test_root,monkeypatch,delivery,expected):
 import ontocare.customer_workflow as w
 monkeypatch.setattr(w,'order_detail',lambda *args:{'status':'FOUND_LOCAL_SNAPSHOT','items':[{'id':'item-demo','properties':{'sku':'T2353','warranty_end':'2020-01-01'}}],'shipments':[{'properties':{'status':delivery}}]})
 c=call(test_root,uuid.uuid4().hex,'包裹未收到，我要申请补发',{'customer_received':False},{'order_number':'Anker001'})
 assert c['state']==expected
 assert not c.get('request',{}).get('approved')


def test_policy_inquiry_does_not_activate_later_application(test_root):
 sid=uuid.uuid4().hex;first=call(test_root,sid,'退款条件是什么？');assert first['state']=='QA'
 second=call(test_root,sid,'E25怎么清洁？');assert second['state']=='QA';assert second['requested_remedy']=='none'


def test_pending_task_is_not_silently_closed(test_root):
 sid=uuid.uuid4().hex;call(test_root,sid,'股票推荐');result=call(test_root,sid,'问题解决了',{'event':'resolved'});assert result['state']=='HUMAN_PENDING';assert not result.get('survey')
