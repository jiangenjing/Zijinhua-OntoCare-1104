"""Local SOP state machine. Customer statements and receipts are never approvals."""
import json,re,sqlite3,uuid,hashlib
from pathlib import Path
from datetime import date,datetime,timezone
from difflib import SequenceMatcher
from .business import order_detail,projection,date_value
from .intent_router import classify as route_intent, observed_claims
from time import perf_counter

ISSUES={'shipping','fault','product','unknown','out_of_scope'}
REMEDIES={'none','refund','replacement','reship'}
EVENTS={'continue','resolved','unresolved','consent','decline','human','submit','feedback','select_item','select_shipment'}
FIELDS={'event','item_id','serial_number','country','seller','troubleshooting_completed','issue_persists','customer_received','remedy','address','csat','issue_type','shipment_id','expected_revision'}
LABELS={'INTENT':'请澄清需要的服务','SHIPMENT':'选择本次目标包裹','REVIEWED':'本地人工已审核，外部操作尚未执行','DECLINED':'本地人工审核未通过','QA':'请确认问题是否已解决','CONSENT':'确认是否进入售后','ORDER':'补充订单或购买渠道','ITEM':'选择需要处理的商品','TROUBLESHOOT':'完成适用排障','CHANNEL':'核实购买渠道','MATERIALS':'补充申请材料','READY':'确认提交本地售后申请','HUMAN_PENDING':'本地人工待办已创建','CLOSED':'已结案，等待满意度反馈','EXPIRED':'按赛题期限提示过保','NON_AUTHORIZED':'按赛题规则引导联系购买商家'}

def validate(value):
 if not isinstance(value,dict) or set(value)-FIELDS:raise ValueError('工作流参数不合法')
 if value.get('event','continue') not in EVENTS:raise ValueError('未知流程事件')
 if value.get('issue_type','unknown') not in ISSUES:raise ValueError('未知问题类型')
 if value.get('remedy','none') not in REMEDIES:raise ValueError('未知申请类型')
 for k in ['troubleshooting_completed','issue_persists','customer_received']:
  if k in value and type(value[k]) is not bool:raise ValueError('客户陈述须为布尔值')
 for k in ['item_id','shipment_id','serial_number','country','seller','address']:
  if k in value and (not isinstance(value[k],str) or len(value[k])>500):raise ValueError('字段长度或类型错误')
 if 'csat' in value and (type(value['csat']) is not int or not 1<=value['csat']<=5):raise ValueError('满意度为1—5')
 if 'expected_revision' in value and (type(value['expected_revision']) is not int or value['expected_revision']<0):raise ValueError('案件版本须为非负整数')
 return value

def classify(message,previous=None,live=False,root=None):
 """Function: issue and remedy are independent; model is a constrained fallback."""
 previous=previous or {};prior=previous.get('classification',{})
 routed=route_intent(message,{'intent':prior.get('intent'),'issue_kind':previous.get('issue_type','unknown')},Path(root) if root else Path(__file__).resolve().parents[1],live)
 remedy=next((name for name,pattern in [('refund',r'退款|退货|\brefund\b'),('replacement',r'换货|换新|\breplacement\b|\breplace\b'),('reship',r'补发|\breship') ] if re.search(pattern,message,re.I)), 'none')
 if remedy=='none' and previous.get('state')!='QA':remedy=previous.get('requested_remedy','none')
 if routed['issue_kind']=='unknown' and previous.get('state') not in {None,'QA','CLOSED'}:routed['issue_kind']=previous.get('issue_type','unknown')
 issue='out_of_scope' if routed['intent']=='out_of_scope' else routed['issue_kind']
 if issue=='unknown' and routed['intent'] in {'product_inquiry','warranty','dealer_check'}:issue='product'
 return {**routed,'issue_type':issue,'requested_remedy':remedy,
         'method':'llm_assisted' if routed['method']=='structured_llm' else 'rules' if routed['method']=='explicit_rules' else routed['method'],
         'verified_facts':False}

def connect(root):
 c=sqlite3.connect(Path(root)/'local/customer-sop.sqlite',timeout=20);c.row_factory=sqlite3.Row
 c.executescript('''CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY, session TEXT UNIQUE, payload TEXT);CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,case_id TEXT,payload TEXT);CREATE TABLE IF NOT EXISTS materials(id TEXT PRIMARY KEY,case_id TEXT,kind TEXT,payload TEXT);CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,case_id TEXT UNIQUE,payload TEXT);CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,case_id TEXT UNIQUE,payload TEXT);CREATE TABLE IF NOT EXISTS surveys(id TEXT PRIMARY KEY,case_id TEXT UNIQUE,payload TEXT);''');return c

def stamp():return datetime.now(timezone.utc).isoformat()

def public(case):
 result=json.loads(json.dumps(case));result.get('claims',{}).pop('address',None)
 if result.get('material_receipts'):result['material_receipts']=[{k:v for k,v in m.items() if k not in {'stored_name','original_name'}} for m in result['material_receipts']]
 return result

def dealer(country,seller,root):
 """Exact source-country code; explicit engineering fuzzy-name threshold."""
 clean=lambda x:re.sub(r'[^\w]','',x.casefold())
 candidates=[n for n in projection(root)['nodes'] if n['type']=='Dealer' and n['properties']['country']==country]
 scores=sorted([(SequenceMatcher(None,clean(seller),clean(n['properties']['seller'])).ratio(),n['id']) for n in candidates],reverse=True)
 matched=bool(scores and scores[0][0]>=.90)
 ambiguous=bool(matched and len(scores)>1 and scores[0][0]-scores[1][0]<.03 and scores[0][0]<1)
 pending=ambiguous or bool(scores and .70<=scores[0][0]<.90)
 matched=matched and not ambiguous
 return {'authorized_by_brief':matched,'needs_review':pending,'match_status':'NEEDS_REVIEW' if pending else 'MATCHED' if matched else 'NOT_MATCHED','country_policy':'exact source code; no GB→UK alias','seller_threshold':.9,'threshold_source':'engineering configuration, not specified numerically in brief','matched_id':scores[0][1] if matched else None,'score':scores[0][0] if scores else 0,'warranty_approved':False}

def queue(c,case,kind):
 old=c.execute('SELECT payload FROM tasks WHERE case_id=?',(case['id'],)).fetchone()
 if old:return json.loads(old[0])
 task={'id':'human-'+uuid.uuid4().hex[:12],'case_id':case['id'],'status':'PENDING_HUMAN','kind':kind,'created_at':stamp(),'scope':'local_demo_queue','external_human_assigned':False,'approved':False}
 c.execute('INSERT INTO tasks VALUES(?,?,?)',(task['id'],case['id'],json.dumps(task)))
 return task

def evaluate_eligibility(issue_type,remedy,claims,warranty_end=None):
 expiry=date_value(warranty_end)
 required=['purchase_proof','media','address'] if remedy in {'refund','replacement'} else ['purchase_proof','address']
 if issue_type=='fault':required.append('serial_number')
 return {'warranty_expired':date.fromisoformat(expiry)<date.today() if expiry else None,'reported_fault_checks_complete':claims.get('troubleshooting_completed') is True and claims.get('issue_persists') is True,'required_materials':required,'claims_verified':False,'can_execute_remedy':False}

def advance(root,session,message,intent,context,event=None,trace_id=None):
 event=validate(event or {});kind=event.get('event','continue')
 with connect(root) as c:
  c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT payload FROM cases WHERE session=?',(session,)).fetchone()
  case=json.loads(row[0]) if row else {'id':'case-'+uuid.uuid4().hex[:12],'session_id':session,'state':'QA','claims':{},'consent':False,'revision':0}
  if 'expected_revision' in event and event['expected_revision']!=case['revision']:raise ValueError('案件已更新，请使用最新回复中的操作按钮')
  old=case['state'];case['classification']=intent;claims=case['claims'];case['issue_type']=intent['issue_type'];case['requested_remedy']=intent['requested_remedy']
  if event.get('issue_type'):case['issue_type']=event['issue_type']
  for k in ['country','seller','serial_number','address','troubleshooting_completed','issue_persists','customer_received']:
   if k in event:claims[k]=event[k]
  for k in ['country','seller']:
   if context.get(k):claims[k]=context[k]
  if event.get('remedy') and event['remedy']!='none':case['requested_remedy']=event['remedy']
  order_number=context.get('order_number') or next(iter(re.findall(r'\bAnker\d{3}\b',message,re.I)),None)
  if order_number:case['order_number']=order_number[0].upper()+order_number[1:].lower() if order_number.islower() else 'Anker'+order_number[-3:]
  case.setdefault('claim_evidence',{})
  for field,value in observed_claims(message).items():
   key='troubleshooting_completed' if field=='checks_completed' else field
   if key not in event:claims[key]=value['value'];case['claim_evidence'][key]=value
  for key in event:
   if key in claims:case['claim_evidence'][key]={'status':'CUSTOMER_REPORTED','source':'workflow_form'}
  explicit_request=bool(re.search(r'我(?:要|想|需要).{0,8}(退款|退货|换货|补发)|申请.{0,4}(退款|换货|补发)|request.{0,8}(refund|replacement|reship)',message,re.I))
  if re.search(r'不想|不要|暂不|不申请|do not want',message,re.I):explicit_request=False
  if kind=='consent' or explicit_request or (old=='CONSENT' and re.search(r'^(同意|确认|是的|yes)',message,re.I)):case['consent']=True
  if kind=='decline':case['consent']=False;case['requested_remedy']='none';case['state']='QA'
  if old not in {'HUMAN_PENDING','REVIEWED','DECLINED'} and (kind=='resolved' or re.search(r'^(已经解决了|问题(?:已经|已)?解决了|已解决|问题好了|resolved)',message,re.I)):
   case['state']='CLOSED';survey={'id':'survey-'+case['id'],'case_id':case['id'],'status':'PRESENTED_IN_CHAT','sent_external':False,'csat':None}
   c.execute('INSERT OR IGNORE INTO surveys VALUES(?,?,?)',(survey['id'],case['id'],json.dumps(survey)));case['survey']=survey
   for pending in c.execute('SELECT id,payload FROM tasks WHERE case_id=?',(case['id'],)).fetchall():
    task=json.loads(pending['payload']);task.update(status='CLOSED_CUSTOMER_CONFIRMED',closed_at=stamp(),approved=False);c.execute('UPDATE tasks SET payload=? WHERE id=?',(json.dumps(task),pending['id']))
  elif kind=='feedback':
   if old!='CLOSED':raise ValueError('请先确认问题解决')
   survey=json.loads(c.execute('SELECT payload FROM surveys WHERE case_id=?',(case['id'],)).fetchone()[0]);survey['csat']=event.get('csat');survey['status']='ANSWERED';c.execute('UPDATE surveys SET payload=? WHERE case_id=?',(json.dumps(survey),case['id']));case['survey']=survey
  elif old in {'HUMAN_PENDING','REVIEWED','DECLINED','CLOSED'}:case['state']=old
  elif kind=='human' or intent['issue_type']=='out_of_scope':case['human_task']=queue(c,case,'SERVICE_REVIEW');case['state']='HUMAN_PENDING'
  elif kind=='decline':case['state']='QA'
  else:
   if kind=='unresolved' and case['requested_remedy']=='none':case['state']='CONSENT'
   elif case['consent'] and case['requested_remedy']=='none':case['state']='CONSENT'
   elif case['requested_remedy']!='none' and not (not case['consent'] and not explicit_request and re.search(r'条件|政策|期限|多久|怎么退|如何退|能退吗|refund policy|return policy',message,re.I)):
    if not case['consent']:case['state']='CONSENT'
    elif case['issue_type']=='unknown':case['state']='INTENT'
    else:
     order=order_detail(case.get('order_number',''),root);case['order_status']=order['status'];item=None
     if order['status']=='FOUND_LOCAL_SNAPSHOT':
      case['items']=[{'id':i['id'],'sku':i['properties']['sku'],'warranty_end':i['properties']['warranty_end']} for i in order['items']]
      if event.get('item_id'):
       if event['item_id'] not in {i['id'] for i in order['items']}:raise ValueError('目标商品不属于该订单')
       case['item_id']=event['item_id']
      if len(order['items'])==1:case['item_id']=order['items'][0]['id']
      item=next((i for i in order['items'] if i['id']==case.get('item_id')),None)
      case['state']='ITEM' if item is None else 'MATERIALS'
      if item:
       expiry=date_value(item['properties'].get('warranty_end'));case['warranty']={'end':expiry,'basis':'LOCAL_ORDER_SNAPSHOT','verified':False}
       expired=evaluate_eligibility(case['issue_type'],case['requested_remedy'],claims,expiry)['warranty_expired']
       if expired is True and case['issue_type']!='shipping':case['state']='EXPIRED'
       elif case['issue_type']=='fault' and claims.get('troubleshooting_completed') is not True:case['state']='TROUBLESHOOT'
       elif case['issue_type']=='fault' and claims.get('issue_persists') is not True:case['state']='TROUBLESHOOT'
       if case['issue_type']=='shipping' and case['requested_remedy']=='reship':
        shipments=order['shipments'];case['shipments']=[{'id':s.get('id','single-package'),'tracking_number':s['properties'].get('tracking_number','资料未列出'),'status':s['properties']['status']} for s in shipments]
        if event.get('shipment_id'):
         if event['shipment_id'] not in {s['id'] for s in case['shipments']}:raise ValueError('目标包裹不属于该订单')
         case['shipment_id']=event['shipment_id']
        selected=next((s for s in case['shipments'] if s['id']==case.get('shipment_id')),None)
        if len(shipments)==1:selected=case['shipments'][0];case['shipment_id']=selected['id']
        case['delivery_basis']={'selected':selected,'verified':False,'contents_verified':False,'customer_received':claims.get('customer_received')}
        if len(shipments)>1 and selected is None:case['state']='SHIPMENT'
        elif selected is None or selected['status'] not in {'DELIVERED','IN_TRANSIT','RETURN_TO_SENDER'}:case['human_task']=queue(c,case,'SHIPPING_SCOPE_REVIEW');case['state']='HUMAN_PENDING'
        elif selected['status']=='DELIVERED':case['human_task']=queue(c,case,'DELIVERED_DISPUTE');case['state']='HUMAN_PENDING'
        elif claims.get('customer_received') is not False:case['state']='ORDER'

     else:
      if not claims.get('country') or not claims.get('seller'):case['state']='CHANNEL'
      else:
       case['dealer_check']=dealer(claims['country'],claims['seller'],root);case['state']='CHANNEL' if case['dealer_check']['needs_review'] else 'MATERIALS' if case['dealer_check']['authorized_by_brief'] else 'NON_AUTHORIZED'
     if case['state']=='MATERIALS' and case['issue_type']=='fault' and not evaluate_eligibility('fault',case['requested_remedy'],claims)['reported_fault_checks_complete']:case['state']='TROUBLESHOOT'
     if order['status']!='FOUND_LOCAL_SNAPSHOT' and case['issue_type']=='shipping' and case['requested_remedy']=='reship' and case['state']=='MATERIALS':case['state']='ORDER'
     if case['state']=='MATERIALS':
      receipts=[json.loads(r[0]) for r in c.execute('SELECT payload FROM materials WHERE case_id=?',(case['id'],))];case['material_receipts']=receipts
      required=evaluate_eligibility(case['issue_type'],case['requested_remedy'],claims)['required_materials']
      have={r['kind'] for r in receipts if r['status']!='REJECTED'}
      if claims.get('address'):have.add('address')
      # Fault-related refunds and replacements both require SN.
      if claims.get('serial_number'):have.add('serial_number')
      case['missing_materials']=[x for x in required if x not in have];case['material_verification']='RECEIVED_IS_NOT_VERIFIED'
      if not case['missing_materials']:
       case['state']='READY'
       if kind=='submit':
        receipt={'id':'request-'+uuid.uuid4().hex[:12],'case_id':case['id'],'type':case['requested_remedy'],'status':'PENDING_HUMAN','item_id':case.get('item_id'),'shipment_id':case.get('shipment_id'),'order_number':case.get('order_number'),'material_ids':[r['id'] for r in receipts],'customer_claims':{k:v for k,v in claims.items() if k!='address'},'address_received':bool(claims.get('address')),'requires_human_verification':True,'approved':False,'created_at':stamp()}
        old_request=c.execute('SELECT id FROM requests WHERE case_id=?',(case['id'],)).fetchone()
        if old_request:receipt['id']=old_request['id']
        c.execute('INSERT OR REPLACE INTO requests VALUES(?,?,?)',(receipt['id'],case['id'],json.dumps(receipt)));case['request']=receipt;case['human_task']=queue(c,case,'AFTERSALES_REQUEST');case['human_task']['status']='PENDING_HUMAN';c.execute('UPDATE tasks SET payload=? WHERE case_id=?',(json.dumps(case['human_task']),case['id']));case['state']='HUMAN_PENDING'
   elif intent.get('intent')=='clarification' and (case['issue_type']=='unknown' or old=='QA') and not event.get('issue_type'):case['state']='INTENT'
   elif old not in {'CONSENT','CLOSED'}:case['state']='QA'
  case['revision']+=1;case['updated_at']=stamp();case['trace_id']=trace_id;case['claim_provenance']='CUSTOMER_REPORTED_NOT_VERIFIED';case['state_label']=LABELS[case['state']]
  c.execute('INSERT OR REPLACE INTO cases VALUES(?,?,?)',(case['id'],session,json.dumps(case)))
  log={'id':uuid.uuid4().hex,'case_id':case['id'],'before':old,'after':case['state'],'event':kind,'trace_id':trace_id,'at':stamp()};c.execute('INSERT INTO events VALUES(?,?,?)',(log['id'],case['id'],json.dumps(log)))
 return public(case)

def response_text(case):
 state=case['state'];missing=case.get('missing_materials',[]);names={'purchase_proof':'订单/购买凭证','media':'相关图片或视频','address':'寄送地址（本地材料表单填写）','serial_number':'故障产品SN'}
 if state=='INTENT':return '请确认主要需要查询物流、了解产品，还是处理产品故障；意图不明确时不会自动批准售后。'
 if state=='SHIPMENT':return '该订单有多个包裹，请选择本次咨询的运单。运单出现在商品行中不代表已经确认包裹内装的商品。'
 if state=='REVIEWED':return '本地人工已完成材料与条件审核；外部退款、换货或补发仍未执行。审核意见：'+case.get('review_note','')
 if state=='DECLINED':return '本地人工审核未通过。原因：'+case.get('review_note','')
 if state=='HUMAN_PENDING':return '已创建本地人工待办 '+case['human_task']['id']+('，申请编号 '+case['request']['id'] if case.get('request') else '')+'。当前等待人工核验，尚未批准或执行退款、换货或补发。'
 if state=='CLOSED':return '已按您的确认结束本次服务。请在下方评价本次服务；调查仅在当前界面呈现，未向外部发送。'
 if state=='CONSENT':return '请确认是否进入换货、退款或补发申请流程；暂不进入也可以继续咨询。'
 if state=='CHANNEL' and case.get('dealer_check',{}).get('needs_review'):return '销售方名称与名录候选存在近似或歧义，请核对凭证上的完整销售方名称和国家代码，或提交人工复核；暂不认定授权或非授权。'
 if state=='CHANNEL':return '订单尚未在本地资料中查到。请补充购买国家代码和凭证上的销售方名称，以核对赛题授权渠道。'
 if state=='ITEM':return '该订单包含多个商品，请在下方选择本次需要处理的商品，再核对该商品的质保与材料。'
 if state=='TROUBLESHOOT':return '故障售后需要先确认适用排障是否完成、问题是否仍然存在。请如实填写；客户陈述会单独记录，仍需人工核验。'
 if state=='EXPIRED':return '按本地订单快照及本次赛题质保期限，目标商品已过保，本次质保售后流程不继续。若日期或适用政策有争议，可提交本地人工复核。'
 if state=='NON_AUTHORIZED':return '按本次赛题国家精准匹配与销售方模糊匹配规则，未命中授权渠道，请联系购买商家的售后；匹配有误时可提交本地人工复核。'
 if state=='MATERIALS':return '还需补充：'+'、'.join(names[x] for x in missing)+'。收到材料不代表核验通过，材料齐备后可确认提交本地人工审核申请。'
 if state=='READY':return '所需材料已收到，尚未核验。请确认提交申请，系统会创建本地申请号和人工待办，不直接执行售后。'
 if state=='ORDER':return '请补充订单号或确认是否收到目标包裹；多包裹或物流状态不明确时需人工核验。'
 return None

def get_case(root,session):
 with connect(root) as c:
  row=c.execute('SELECT payload FROM cases WHERE session=?',(session,)).fetchone()
 return public(json.loads(row[0])) if row else None

def graph_projection(root):
 nodes=[];links=[]
 with connect(root) as c:
  for table,typ in [('cases','ServiceCase'),('requests','AftersalesRequest'),('tasks','HumanServiceTask'),('surveys','ServiceSurvey')]:
   for row in c.execute(f'SELECT payload FROM {table}'):
    value=json.loads(row[0]);value=public(value) if table=='cases' else value
    nodes.append({'id':value['id'],'type':typ,'label':value.get('state_label') or value.get('type') or value['id'],'properties':{**value,'record_kind':'本地工作流运行记录，可能含演示/测试，不是正式售后执行'}})
    if table=='cases':
     target={'INTENT':'intent','SHIPMENT':'shipping','REVIEWED':'human','DECLINED':'human','QA':'resolved','CONSENT':'consent','ORDER':'pending','CHANNEL':'seller','ITEM':'warranty','TROUBLESHOOT':'fault-readiness','MATERIALS':'materials','READY':'request','HUMAN_PENDING':'human','CLOSED':'close','EXPIRED':'expired','NON_AUTHORIZED':'merchant'}.get(value['state'])
     if target:links.append({'source':value['id'],'target':'sop:step:'+target,'relation':'case_at_sop_step','basis':{'source':'local/customer-sop.sqlite','scope':'CURRENT_LOCAL_CASE_STATE'}})
    if table!='cases':links.append({'source':value['case_id'],'target':value['id'],'relation':'case_has_'+table,'basis':{'source':'local/customer-sop.sqlite','scope':'LOCAL_DEMO_RECEIPT'}})
  for row in c.execute('SELECT payload FROM materials'):
   v=json.loads(row[0]);nodes.append({'id':v['id'],'type':'CustomerMaterial','label':v['kind'],'properties':{k:x for k,x in v.items() if k not in {'stored_name','original_name'}}});links.append({'source':v['case_id'],'target':v['id'],'relation':'case_has_material','basis':{'source':'local/customer-sop.sqlite'}})
 return nodes,links


def register(app,root):
 from flask import request,jsonify,send_file
 root=Path(root);connect(root).close()
 def local():
  if request.remote_addr not in {'127.0.0.1','::1'} or request.headers.get('Origin',request.host_url.rstrip('/'))!=request.host_url.rstrip('/'):raise ValueError('仅允许本机同源操作')
 @app.get('/api/workflow/case/<session>')
 def read_case(session):
  if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',session):return jsonify(error='无效会话'),400
  case=get_case(root,session);return (jsonify(case),200) if case else (jsonify(error='未找到服务案例'),404)
 @app.post('/api/workflow/materials/<session>')
 def upload(session):
  try:
   local();request.max_content_length=9*1024*1024
   if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',session):raise ValueError('无效会话')
   case=get_case(root,session)
   if not case:raise ValueError('请先开始会话')
   if case['state'] in {'HUMAN_PENDING','CLOSED','REVIEWED','DECLINED'}:raise ValueError('案件已提交或结束；请由人工继续处理材料')
   kind=request.form.get('kind');file=request.files.get('file')
   if kind not in {'purchase_proof','media'} or not file:raise ValueError('请选择凭证或图片/视频材料')
   content=file.read(8*1024*1024+1)
   if not content or len(content)>8*1024*1024:raise ValueError('文件须小于8MB')
   supported=content.startswith((b'%PDF-',b'\x89PNG\r\n\x1a\n',b'\xff\xd8\xff')) or (len(content)>12 and content[4:8]==b'ftyp')
   if not supported:raise ValueError('仅接收PDF、PNG、JPEG或MP4；材料尚不自动核验')
   ident='material-'+uuid.uuid4().hex;folder=root/'local/customer-sop-materials';folder.mkdir(exist_ok=True,mode=0o700);(folder/ident).write_bytes(content);(folder/ident).chmod(0o600)
   receipt={'id':ident,'case_id':case['id'],'kind':kind,'size':len(content),'sha256':hashlib.sha256(content).hexdigest(),'stored_name':ident,'original_name':file.filename[:120],'status':'RECEIVED_UNVERIFIED','created_at':stamp()}
   with connect(root) as c:c.execute('INSERT INTO materials VALUES(?,?,?,?)',(ident,case['id'],kind,json.dumps(receipt)))
   return jsonify({k:v for k,v in receipt.items() if k not in {'stored_name','original_name'}})
  except ValueError as e:return jsonify(error=str(e)),400
 @app.get('/workflow/human')
 def human_page():return send_file(root/'web/workflow-human.html')
 @app.get('/api/workflow/tasks')
 def tasks():
  with connect(root) as c:items=[json.loads(r[0]) for r in c.execute('SELECT payload FROM tasks ORDER BY rowid DESC')]
  return jsonify(items=items,scope='LOCAL_DEMO_PENDING_QUEUE',external_human_assigned=False)
 @app.get('/api/workflow/tasks/<ident>')
 def task_detail(ident):
  with connect(root) as c:
   task=c.execute('SELECT payload FROM tasks WHERE id=?',(ident,)).fetchone()
   if not task:return jsonify(error='未找到待办'),404
   task=json.loads(task[0]);case=json.loads(c.execute('SELECT payload FROM cases WHERE id=?',(task['case_id'],)).fetchone()[0]);req=c.execute('SELECT payload FROM requests WHERE case_id=?',(task['case_id'],)).fetchone();materials=[json.loads(r[0]) for r in c.execute('SELECT payload FROM materials WHERE case_id=?',(task['case_id'],))]
  return jsonify(task=task,case=public(case),application=json.loads(req[0]) if req else None,materials=[{k:v for k,v in m.items() if k not in {'stored_name','original_name'}} for m in materials])

class WorkflowAgentMixin:
 """Wrap the reviewed answer engine; all workflow edits use bounded server code."""
 def run(self,payload,on_event=None):
  started=perf_counter()
  event=validate(payload.get('workflow',{}));previous=get_case(self.root,payload['session_id']) if payload.get('session_id') else None
  if 'expected_revision' in event and event['expected_revision']!=(previous or {}).get('revision',0):raise ValueError('案件已更新，请使用最新回复中的操作按钮')
  classification=classify(payload['message'],previous,live=payload.get('mode')=='live' and not event,root=self.root)
  core=dict(payload);core.pop('_workflow_skill',None)
  if classification['issue_type']=='shipping':core['_workflow_skill']='shipping'
  if re.search(r'我(?:要|想|需要).{0,8}(退款|退货|换货|补发)|申请.{0,4}(退款|换货|补发)|request.{0,8}(refund|replacement|reship)',payload['message'],re.I) or classification['intent'] in {'clarification','out_of_scope'} or event.get('event','continue')!='continue' or previous and previous['state'] not in {'QA','TROUBLESHOOT'}:core['mode']='offline'
  result=super().run(core,on_event=on_event)
  case=advance(self.root,result['session_id'],payload['message'],classification,payload.get('context',{}),event,result['trace_id'])
  from .type_contracts import sync_case_task
  service_task=sync_case_task(self.root,case,result.get('state',{}),self.contract_actor() if hasattr(self,'contract_actor') else None)
  if service_task:result['service_task_id']=service_task['id']
  text=response_text(case)
  if text:
   result['zh']=text;result['en']='Local service workflow: '+case['state']+'. '+('A local pending-human task has been saved; no refund, replacement or reshipment is approved or executed.' if case['state']=='HUMAN_PENDING' else 'Please complete the requested information or use the workflow controls below. Customer statements and received materials require human verification.')
   en={'INTENT':'Please clarify whether you need shipment tracking, product information or fault troubleshooting. Intent estimates are not eligibility decisions.','SHIPMENT':'Select the target tracking number. A parcel listed on an item row does not verify its contents.','REVIEWED':'Local human review is complete. No external refund, replacement or reshipment has been executed.','DECLINED':'Local human review declined the application. See the recorded review note.','CONSENT':'Please confirm whether to enter a replacement, refund or reshipment application, or continue the consultation.','CHANNEL':'The order is absent from the local snapshot. Provide the purchase country code and seller name shown on the receipt.','ITEM':'Choose the order item for this application; item warranties and package contents are distinct.','TROUBLESHOOT':'Confirm whether applicable troubleshooting is complete and whether the issue persists. These remain customer reports pending human verification.','EXPIRED':'Under the competition warranty dates in the local snapshot, the item is outside warranty. This warranty workflow stops; request local human review if the dates or policy are disputed.','NON_AUTHORIZED':'The country and seller do not match the competition dealer rule. Contact the purchasing seller, or request local human review of the match.','MATERIALS':'Please provide the missing materials: '+', '.join(case.get('missing_materials',[]))+'. Receipt is not verification.','READY':'Required materials have been received but are unverified. Confirm submission to create a local application and pending-human task.','CLOSED':'The case is closed following your confirmation. A satisfaction survey is shown in this chat; none was sent externally.','ORDER':'Provide the order number or confirm receipt of the target parcel. Missing or conflicting shipment facts need human review.'}
   if case['state'] in en:result['en']=en[case['state']]
   if case['state']=='HUMAN_PENDING':result['en']='Local pending-human task '+case['human_task']['id']+(' and application '+case['request']['id'] if case.get('request') else '')+' saved. No refund, replacement or reshipment is approved or executed.'
   result['sections']={lang:{'summary':result[lang],'actions':[],'questions':[],'limits':'本地演示，非正式售后执行' if lang=='zh' else 'Local demo, not an executed remedy'} for lang in ['zh','en']};result['model_status']='workflow_contract';result['decision']='workflow_'+case['state'].lower()
  result['workflow']=case;result['workflow_function_calls']=[{'name':'classifyServiceIntent','result':classification},{'name':'evaluateServiceEligibility','result':evaluate_eligibility(case['issue_type'],case['requested_remedy'],case['claims'],case.get('warranty',{}).get('end'))},{'name':'advanceServiceCase','state':case['state'],'revision':case['revision']}]
  if event.get('event')=='submit' and case.get('request') and not (previous or {}).get('request'):result['workflow_function_calls'].append({'name':'submitAftersalesRequest','receipt':case['request']})
  result['latency_ms']=round((perf_counter()-started)*1000,2)
  result['intent_model_calls']=classification.get('model_calls',[])
  from .data import connect as service_connect
  with service_connect(self.root) as conn:
   conn.execute('UPDATE traces SET payload=? WHERE id=?',(json.dumps(result,ensure_ascii=False),result['trace_id']))
   history=conn.execute('SELECT id,payload FROM conversations WHERE session_id=? ORDER BY id DESC LIMIT 1',(result['session_id'],)).fetchone()
   if history:
    h=json.loads(history['payload']);h['assistant']={'zh':result['zh'],'en':result['en']};conn.execute('UPDATE conversations SET payload=? WHERE id=?',(json.dumps(h,ensure_ascii=False),history['id']))
  if on_event:on_event('tool_completed',{'name':'advance_service_workflow'})
  return result
