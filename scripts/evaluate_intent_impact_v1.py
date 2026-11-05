"""Frozen paired diagnostics for the actual classifier and local SOP wrapper.
Does not tune prompts, read final questions, or change historical evaluation rules.
"""
from concurrent.futures import ThreadPoolExecutor,as_completed
from contextlib import ExitStack
from pathlib import Path
import json,os,random,shutil,sqlite3,sys,time,urllib.request
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
os.environ.setdefault('ONTOCARE_LLM_CONFIG',str(ROOT/'local/deepseek-config.json'))
from ontocare.data import digest,load_json,write_json
from ontocare.agent import intent as legacy_intent
from ontocare.customer_workflow import classify
from ontocare.reference_agent import SourceActionAgent
from ontocare.customer_workflow_agent import CustomerWorkflowAgent
from ontocare.app import create_app
from ontocare.evaluation import http_server
from ontocare.benchmark_metrics import latency
from ontocare.provider import Provider,ModelUnavailable
from live_grounded_eval import RUBRIC,parse
from ontocare.judge import DIMENSIONS
OUT=ROOT/'reports/intent-impact-v1';LOCAL=ROOT/'local/intent-impact-v1';OUT.mkdir(exist_ok=True);LOCAL.mkdir(exist_ok=True)
dataset=load_json(ROOT/'evaluation/intent-impact-v1/cases.json');assert digest(dataset['cases'])==dataset['sha256']

def route(value):
 if value['intent']=='shipping':return 'shipping'
 if value['intent'] in {'refund','replacement','warranty','dealer_check'}:return 'aftersales'
 if value['intent'] in {'troubleshooting','product_inquiry'}:return 'troubleshooting'
 return 'clarification' if value['intent']=='clarification' else 'handoff'


def one_route(case):
 p=LOCAL/'routing'/f"{case['id']}.json";p.parent.mkdir(exist_ok=True)
 if p.exists():return load_json(p)
 start=time.perf_counter();before=legacy_intent(case['message']);before_ms=(time.perf_counter()-start)*1000
 start=time.perf_counter();after=classify(case['message'],live=True,root=ROOT);after_ms=(time.perf_counter()-start)*1000
 result={'case':case,'before':{'route':before,'elapsed_ms':before_ms,'passed':before==case['expected_route']},'after':{'route':route(after),'elapsed_ms':after_ms,'passed':route(after)==case['expected_route'],'classification':after}}
 write_json(p,result);return result


def runtime_root(name):
 root=LOCAL/('runtime-'+name);root.mkdir(exist_ok=True);(root/'local').mkdir(exist_ok=True)
 for directory in ['data','ontology','evaluation','web','prompts','actions']:
  dest=root/directory
  if not dest.exists():dest.symlink_to(ROOT/directory,target_is_directory=True)
 for name in ['business.sqlite','vectors.json','vectors.npz','ranking-title-vectors.json','ranking-title-vectors.npz','reference-snapshots.json','deepseek-config.json']:
  src=ROOT/'local'/name;dest=root/'local'/name
  if src.exists() and not dest.exists():
   if name.endswith('.sqlite'):shutil.copyfile(src,dest)
   else:dest.symlink_to(src)
 database=root/'local/service.sqlite'
 if not database.exists():
  source=sqlite3.connect((ROOT/'local/service.sqlite').resolve().as_uri()+'?mode=ro',uri=True);target=sqlite3.connect(database)
  for table,sql in source.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
   if table in {'sessions','traces','conversations','faq_cache'}:continue
   target.execute(sql);records=source.execute('SELECT * FROM "'+table+'"').fetchall()
   if records:target.executemany('INSERT INTO "'+table+'" VALUES('+','.join('?' for _ in records[0])+')',records)
  target.commit();source.close();target.close()
 return root


def evaluate_judge(row):
 # Unchanged five-dimension rubric. Both arms expose only their actual facts.
 reply=row['reply'];workflow=reply.get('workflow');facts=dict(reply.get('business_context',{}))
 if workflow:
  facts['local_workflow_receipt']={k:workflow[k] for k in ['id','state','state_label','claim_provenance','missing_materials','request','human_task'] if k in workflow}
 packet={'questions':[row['case']['message']],'reference':None,'expected_decision':None,'answer':{k:reply.get(k) for k in ['zh','en','decision']},'retrieved_contexts':reply.get('citations',[]),'tool_facts':facts,'history':[]}
 provider=Provider(config_path=ROOT/'local/deepseek-config.json');errors=[]
 for _ in range(2):
  try:
   j=parse(provider.chat([{'role':'system','content':RUBRIC},{'role':'user','content':json.dumps(packet,ensure_ascii=False)}])['content'].strip());dims=j['dimensions']
   if set(dims)!=set(DIMENSIONS) or any(type(v['score']) is not int or v['score'] not in [0,1,2] or not v.get('reason') for v in dims.values()):raise ValueError('rubric')
   if type(j['task_satisfied']) is not bool or not 0<=j['supported_claims']<=j['total_claims']:raise ValueError('claims')
   total=sum(v['score'] for v in dims.values());hard=all(c['passed'] for c in reply.get('checks',[]))
   strict=total>=8 and hard and j['task_satisfied'] and reply.get('model_status')=='completed' and all(dims[k]['score']>0 for k in ['factual_model_accuracy','evidence_support','business_boundaries'])
   return {**j,'total':total,'status':'completed','historical_strict_gate_passed':strict,'model_calls':provider.calls,'rubric_sha256':digest(RUBRIC),'human_review':'not_performed','same_model_bias':True}
  except (ModelUnavailable,ValueError,KeyError,TypeError) as e:errors.append(type(e).__name__)
 return {'status':'not_evaluated','errors':errors,'model_calls':provider.calls}


def main():
 protocol={'dataset_sha256':dataset['sha256'],'routing_cases':40,'families':20,'end_to_end_cases_per_arm':12,'repeats':1,'workers':3,'model':Provider(config_path=ROOT/'local/deepseek-config.json').public_status(),'judge_rubric_sha256':digest(RUBRIC),'scope':'constructed bilingual paired diagnostic, not independent blind data or actual issue resolution','route_ablation':'legacy agent.intent versus customer_workflow.classify; same input, shared three-way labels; no tuning after freezing','e2e_comparison':'SourceActionAgent versus CustomerWorkflowAgent on the same retrieval/knowledge/model; measures combined router+SOP wrapper, not pure classifier attribution','judge_packet':'same old rubric; add actual local workflow receipts as tool facts for any arm that returns them; historical strict completed-model gate is also preserved separately','frozen_source_hashes':{name:digest((ROOT/name).read_bytes()) for name in ['ontocare/intent_router.py','ontocare/customer_workflow.py','ontocare/reference_agent.py','prompts/intent-router.md']}}
 path=OUT/'protocol.json'
 if path.exists():assert load_json(path)==protocol,'Protocol changed; use a new experiment version'
 else:write_json(path,protocol)
 routing=[]
 with ThreadPoolExecutor(max_workers=3) as pool:
  for f in as_completed([pool.submit(one_route,c) for c in dataset['cases']]):
   routing.append(f.result())
   if len(routing)%10==0:print('routing',len(routing),'/40',flush=True)
 roots={a:runtime_root(a) for a in ['before','after']};agents={'before':SourceActionAgent(roots['before']),'after':CustomerWorkflowAgent(roots['after'])}
 agents['before'].retriever._encoder(agents['before'].retriever.vector_meta['revision']);agents['after'].retriever.encoder=agents['before'].retriever.encoder
 apps={a:create_app(roots[a],agents[a]) for a in agents};protocol['runtime_ids']={a:app.test_client().get('/api/runtime').json['id'] for a,app in apps.items()};write_json(OUT/'runtimes.json',protocol['runtime_ids'])
 def one(base,arm,case):
  p=LOCAL/arm/(case['id']+'.json');p.parent.mkdir(exist_ok=True)
  if p.exists():row=load_json(p)
  else:
   start=time.perf_counter()
   try:
    body={'message':case['message'],'context':case['context'],'mode':'live'}
    with urllib.request.urlopen(urllib.request.Request(base+'/api/chat',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'}),timeout=180) as response:reply=json.load(response)
    row={'case':case,'arm':arm,'reply':reply,'http_ms':(time.perf_counter()-start)*1000}
   except Exception as e:row={'case':case,'arm':arm,'reply':{},'http_ms':(time.perf_counter()-start)*1000,'error':type(e).__name__}
   write_json(p,row)
  if 'judge' not in row:row['judge']=evaluate_judge(row) if row['reply'] else {'status':'not_evaluated'};write_json(p,row)
  return row
 rows=[];live=[c for c in dataset['cases'] if c['id'] in dataset['live_ids']]
 with ExitStack() as stack:
  bases={a:stack.enter_context(http_server(app,threaded=True)) for a,app in apps.items()};jobs=[(a,c) for c in live for a in apps];random.Random(20261103).shuffle(jobs)
  with ThreadPoolExecutor(max_workers=3) as pool:
   for f in as_completed([pool.submit(one,bases[a],a,c) for a,c in jobs]):
    row=f.result();rows.append(row);print('live+judge',len(rows),'/24',row['arm'],row['case']['id'],row['reply'].get('model_status',row.get('error')),flush=True)
    write_json(OUT/'progress.json',{'completed':len(rows),'planned':24,'status':'running'})
 def summarize(arm):
  selected=[r for r in rows if r['arm']==arm];judged=[r['judge'] for r in selected if r['judge']['status']=='completed'];supported=sum(j['supported_claims'] for j in judged);claims=sum(j['total_claims'] for j in judged)
  calls=[c for r in selected for c in r['reply'].get('model_calls',[])+r['reply'].get('intent_model_calls',[])+r['reply'].get('retrieval_model_calls',[])]
  return {'planned':12,'returned':sum(bool(r['reply']) for r in selected),'judge_completed':len(judged),'judge_task_satisfied_n':sum(j['task_satisfied'] for j in judged),'judge_task_satisfied_rate_all_planned':sum(j['task_satisfied'] for j in judged)/12,'historical_strict_gate_pass_n':sum(j.get('historical_strict_gate_passed',False) for j in judged),'supported_claims':supported,'total_claims':claims,'faithfulness':supported/claims if claims else None,'mean_judge_score':sum(j['total'] for j in judged)/len(judged) if judged else None,'latency_http':latency([r['http_ms'] for r in selected]),'hard_check_failures':sum(any(not c['passed'] for c in r['reply'].get('checks',[])) for r in selected),'main_model_completed':sum(r['reply'].get('model_status')=='completed' for r in selected),'local_workflow_receipts':sum(r['reply'].get('model_status')=='workflow_contract' for r in selected),'total_tokens':sum((c.get('usage') or {}).get('total_tokens',0) for c in calls)}
 summary={'protocol':protocol,'routing':{a:{'correct':sum(r[a]['passed'] for r in routing),'n':40,'accuracy':sum(r[a]['passed'] for r in routing)/40,'latency':latency([r[a]['elapsed_ms'] for r in routing])} for a in ['before','after']},'routing_paired':{'improved':sum(not r['before']['passed'] and r['after']['passed'] for r in routing),'regressed':sum(r['before']['passed'] and not r['after']['passed'] for r in routing),'both_wrong':sum(not r['before']['passed'] and not r['after']['passed'] for r in routing)},'end_to_end':{a:summarize(a) for a in ['before','after']},'actual_resolution_rate':None,'independent_test':False,'github_uploaded':False}
 write_json(LOCAL/'routing-all.json',sorted(routing,key=lambda r:r['case']['id']));write_json(OUT/'summary.json',summary);write_json(OUT/'progress.json',{'completed':24,'planned':24,'status':'complete'});print(json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
