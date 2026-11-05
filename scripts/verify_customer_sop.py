"""Exercise real local HTTP transitions and uploads; no external remedies."""
import json,urllib.request,uuid
from pathlib import Path
import os
BASE=os.environ.get('ONTOCARE_SOP_TEST_URL','http://127.0.0.1:5124');results=[]
def post(text,session=None,event=None,context=None,mode='offline'):
 body={'message':text,'mode':mode,'context':context or {},'workflow':event or {}}
 if session:body['session_id']=session
 req=urllib.request.Request(BASE+'/api/chat',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=150) as r:return json.load(r)
r=post('设备坏了，我要申请退款',context={'country':'US','seller':'best buy'});sid=r['session_id'];assert r['workflow']['state']=='MATERIALS';assert 'serial_number' in r['workflow']['missing_materials']
for kind in ['purchase_proof','media']:
 boundary='----demo'+uuid.uuid4().hex
 body=(f'--{boundary}\r\nContent-Disposition: form-data; name="kind"\r\n\r\n{kind}\r\n--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="demo.pdf"\r\nContent-Type: application/pdf\r\n\r\n%PDF-1.4\n% local workflow test only\n%%EOF\r\n--{boundary}--\r\n').encode()
 req=urllib.request.Request(BASE+'/api/workflow/materials/'+sid,data=body,headers={'Content-Type':'multipart/form-data; boundary='+boundary})
 with urllib.request.urlopen(req) as response:receipt=json.load(response);assert receipt['status']=='RECEIVED_UNVERIFIED'
r=post('补充申请信息',sid,{'serial_number':'TEST-SN-ONLY','address':'本地演示地址','event':'continue'});assert r['workflow']['state']=='READY'
r=post('确认提交',sid,{'event':'submit'});case=r['workflow'];assert case['state']=='HUMAN_PENDING';assert not case['request']['approved'];request_id=case['request']['id'];task_id=case['human_task']['id']
r2=post('重复提交',sid,{'event':'submit'});assert r2['workflow']['request']['id']==request_id
with urllib.request.urlopen(BASE+'/api/workflow/tasks/'+task_id) as response:detail=json.load(response);assert detail['application']['id']==request_id
results.append({'scenario':'fault refund + SN + actual material upload + persistent request + pending queue + idempotency','session_id':sid,'request':request_id,'task':task_id,'passed':True})
r=post('请给我股票推荐');assert r['workflow']['state']=='HUMAN_PENDING';results.append({'scenario':'out of scope -> saved local human task','passed':True})
r=post('E25 怎么使用？');sid=r['session_id'];r=post('问题已解决',sid,{'event':'resolved'});assert r['workflow']['state']=='CLOSED';r=post('评价',sid,{'event':'feedback','csat':5});assert r['workflow']['survey']['csat']==5;results.append({'scenario':'resolved -> closed -> presented survey -> feedback saved','passed':True})
r=post('我要退款',context={'country':'US','seller':'not-listed-zzzz'});assert r['workflow']['state']=='NON_AUTHORIZED';results.append({'scenario':'non-authorized seller -> contact seller branch','passed':True})
r=post('退款条件是什么？');assert r['workflow']['state']=='QA';results.append({'scenario':'policy inquiry stays QA, not a consent/application claim','passed':True})
r=post('Where is my parcel?',mode='live');assert r['workflow']['classification']['method']=='llm_assisted';assert r['workflow']['issue_type']=='shipping';results.append({'scenario':'real LLM fallback classification','method':r['workflow']['classification']['method'],'passed':True})
with urllib.request.urlopen(BASE+'/api/ontology-manager') as response:g=json.load(response)
ids={n['id'] for n in g['nodes']};assert all(e['source'] in ids and e['target'] in ids for e in g['links']);assert any(n['type']=='ServiceCase' for n in g['nodes'])
Path('reports/customer-sop-live-checks.json').write_text(json.dumps({'scope':'local demo fixtures; not real customer fulfillment','scenarios':results,'ontology_has_execution_records':True,'no_dangling_edges':True},ensure_ascii=False,indent=2)+'\n');print(json.dumps(results,ensure_ascii=False))
