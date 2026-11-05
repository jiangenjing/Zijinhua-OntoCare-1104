"""Constructed integration scenarios, not a customer-resolution benchmark."""
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
from pathlib import Path
import urllib.request

CASES=[
 ('split_fulfillment',{'message':'Anker008 每件商品发货了吗？源资料金额各是多少？'}),
 ('two_packages',{'message':'Anker001 有几个包裹？可以确定每个包裹里是什么吗？'}),
 ('dealer_match',{'message':'这个购买渠道能直接保修吗？','context':{'country':'US','seller':'best buy','order_number':'Anker001'}}),
 ('dealer_unknown',{'message':'这个销售方是否授权？','context':{'country':'ZZ','seller':'best buy'}}),
 ('e25_fault',{'message':'我的 E25 报错误码3212，还没做过检查，先做什么？'}),
 ('parts_warranty',{'message':'T8D04 的可清洗配件保修多久？','context':{'country':'US','seller':'best buy'}}),
 ('missing_country',{'message':'这个卖家能保修吗？','context':{'seller':'best buy'}}),
 ('mail_draft',{'message':'请帮我写邮件回复：Anker005 主机和配件的物流状态分别是什么？'})]

def run(case):
 ident,payload=case
 req=urllib.request.Request('http://127.0.0.1:5112'+('/api/mail/draft' if ident=='mail_draft' else '/api/chat'),data=json.dumps({**payload,'mode':'live'}).encode(),headers={'Content-Type':'application/json'})
 try:
  with urllib.request.urlopen(req,timeout=180) as r:reply=json.load(r)
  checks={'live_completed':reply['model_status']=='completed','source_checks':all(c['passed'] for c in reply['checks']),'bilingual_sections':set(reply.get('sections',{}))=={'zh','en'}}
  if ident=='split_fulfillment':checks['split_items']=reply['business_context']['order']['order']['properties']['status']=='PARTIALLY_SHIPPED'
  if ident=='two_packages':checks['two_packages']=len(reply['business_context']['order']['shipments'])==2
  if ident.startswith('dealer') or ident=='missing_country':checks['no_eligibility_claim']=reply['business_context']['dealer_check']['eligible'] is None
  if ident=='mail_draft':checks['not_sent']=reply['draft']['sent'] is False
  return {'id':ident,'checks':checks,'passed':all(checks.values()),'reply':reply}
 except Exception as e:return {'id':ident,'passed':False,'error_type':type(e).__name__}

if __name__=='__main__':
 result={'provenance':'8 constructed integration scenarios, not real resolution rate or independent quality evaluation','cases':[]}
 out=Path('local/business-live-smoke.json')
 with ThreadPoolExecutor(max_workers=2) as pool:
  for f in as_completed([pool.submit(run,c) for c in CASES]):
   r=f.result();result['cases'].append(r);out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'id':r['id'],'passed':r['passed'],'status':r.get('reply',{}).get('model_status',r.get('error_type'))},ensure_ascii=False),flush=True)
 print('completed',len(result['cases']),'passed',sum(r['passed'] for r in result['cases']),flush=True)
