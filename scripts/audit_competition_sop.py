"""Read-only audit of the selected5120 release against the competition brief."""
import sys,json,urllib.request,hashlib
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ontocare.data import load_json,write_json,rows
DEPLOY=ROOT/'local/customer-service-v2/experience548/deployment.json'
release=load_json(DEPLOY)['version'];frozen=ROOT/'local/customer-service-v2/experience548'/release
# Import the selected release in a separate process when exercising pure functions.
import subprocess
program='''
import json
from ontocare.data import ROOT
from ontocare.decisions import evaluate
from ontocare.business import check_seller,projection
from ontocare.actions import SCHEMA
facts={'intent':'fault','troubleshooting_completed':True,'issue_persists':True,'warranty_end':'2027-01-01','purchase_proof_verified':True,'shipping_address_verified':True,'media_verified':True,'serial_number_verified':True}
orders=[n for n in projection(ROOT)['nodes'] if n['type']=='Order'];items=[n for n in projection(ROOT)['nodes'] if n['type']=='OrderItem']
result={'rules':{'not_delivered':evaluate({'intent':'shipping','delivery_status':'IN_TRANSIT','customer_received':False},ROOT,'2026-11-03')['outcome'],'delivered':evaluate({'intent':'shipping','delivery_status':'DELIVERED','customer_received':False},ROOT,'2026-11-03')['outcome'],'replace_complete':evaluate(facts,ROOT,'2026-11-03'),'expired':evaluate({**facts,'warranty_end':'2025-01-01'},ROOT,'2026-11-03')['outcome']},'dealers':{c+'|'+s:{k:v for k,v in check_seller(c,s,ROOT).items() if k in ['status','country','competition_authorization','eligible','match_policy']} for c,s in [('US','best buy'),('GB','Amazon'),('US','not-a-listed-seller-zzzz')]},'refund_branch_required_fields':evaluate({'intent':'refund'},ROOT,'2026-11-03')['missing_facts'],'order_counts':{'orders':len(orders),'items':len(items)},'order_field_presence':{field:all(field in n['properties'] for n in orders) for field in ['address','source_rows','status']},'item_field_presence':{field:all(field in n['properties'] for n in items) for field in ['order_number','sku','description','quantity','purchase_date','warranty_end','amount_raw','carrier','tracking','ship_date','fulfillment_status']},'action_parameter_fields':list(SCHEMA['properties']['parameters']['properties'])}
print(json.dumps(result,ensure_ascii=False))
'''
import os
env={**os.environ,'PYTHONPATH':str(frozen)}
p=subprocess.run([str(ROOT/'.venv/bin/python'),'-c',program],cwd=frozen,env=env,text=True,capture_output=True,check=True)
observed=json.loads(p.stdout)
with urllib.request.urlopen('http://127.0.0.1:5120/api/runtime') as r:runtime=json.load(r)
probes=[]
for message,context in [('Anker001 物流显示送达，但我没收到，请帮我申请补发。',{'order_number':'Anker001'}),('T8D04 主机已完成所有对应排查，问题仍然存在，我要申请换货。',{'sku':'T8D04'}),('US 的 best buy 能直接保修吗？',{'country':'US','seller':'best buy'})]:
 req=urllib.request.Request('http://127.0.0.1:5120/api/chat',data=json.dumps({'message':message,'context':context,'mode':'offline'}).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req) as r:reply=json.load(r)
 decision=reply.get('business_context',{}).get('service_decision',{})
 probes.append({'question':message,'mode':'offline_code_path_not_model_quality','decision':reply['decision'],'tools':[t['name'] for t in reply['tools']],'service_outcome':decision.get('outcome'),'missing_facts':decision.get('missing_facts'),'facts_checks':decision.get('checks'),'action_receipt':reply.get('action_receipt'),'trace_id':reply['trace_id']})
tickets=rows('tickets',frozen);counts=Counter(t.get('pn') or 'UNRESOLVED' for t in tickets)
result={'release':release,'runtime':runtime,'reference':'original competition DOCX and embedded SOP image; Feishu online page inaccessible','source_docx_sha256':hashlib.sha256((ROOT.parent/'【黑客松】Anekr智能客服赛题（业务资料）.docx').read_bytes()).hexdigest(),'observed':observed,'live_probes':probes,'ticket_counts_by_pn':dict(counts),'source_counts':load_json(frozen/'data/import-audit.json')['raw_counts'],'verdict':'PARTIALLY_ALIGNED_NOT_COMPLETE_WORKFLOW','behavior_changed':False}
write_json(ROOT/'reports/competition-sop-audit.json',result);write_json(ROOT/'web/competition-sop-audit.json',result)
print(json.dumps(result,ensure_ascii=False,indent=2))
