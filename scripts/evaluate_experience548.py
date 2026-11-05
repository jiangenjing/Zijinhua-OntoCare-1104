"""Frozen 5120 experience/control comparison through real HTTP + unchanged judge."""
import sys,os,json,time,sqlite3,shutil,subprocess,urllib.request,argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from ontocare.data import load_json,write_json,digest,redact
from ontocare.service_eval_dashboard import score_run,task_verdict
import live_service_eval_v2 as ev
LOCAL=ROOT/'local/customer-service-v2';RUN=LOCAL/'experience548';OUT=ROOT/'reports/customer-service-v2'
CASES=[c for c in load_json(ROOT/'evaluation/customer-service-v2/cases.json')['cases'] if c['kind']!='seen_ticket'];assert len(CASES)==548
LABELS=['experience-core-control548','experience-v1-stream548','experience-v2-stream548','experience-v4-stream548']

def snapshot(name):
 dest=RUN/name
 if dest.exists():return dest
 dest.mkdir(parents=True)
 for name in ['ontocare','prompts','data','ontology']:
  shutil.copytree(ROOT/name,dest/name,ignore=shutil.ignore_patterns('__pycache__'))
 for name in ['web','actions','skills','evaluation']:(dest/name).symlink_to(ROOT/name,target_is_directory=True)
 (dest/'local').mkdir()
 for p in (ROOT/'local').iterdir():
  if p.is_file() and p.suffix=='.sqlite':
   with sqlite3.connect(p) as src,sqlite3.connect(dest/'local'/p.name) as target:src.backup(target)
  elif p.is_file() and not p.name.endswith(('-wal','-shm')):(dest/'local'/p.name).symlink_to(p)
 return dest

def request(case,label,base,stream,repeat=0):
 path=LOCAL/'answers'/label/(case['id']+f'-r{repeat}.json')
 if path.exists():return load_json(path)
 turns=[];session=None
 for question in case['turns']:
  body={'message':question,'context':case.get('context',{}),'mode':'live','version':'candidate-1'}
  if session:body['session_id']=session
  started=time.perf_counter();first_status=None;first_delta=None;result=None;done=False;chunks=''
  try:
   req=urllib.request.Request(base+('/api/chat/stream' if stream else '/api/chat'),data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
   with urllib.request.urlopen(req,timeout=240) as response:
    if not stream:result=json.load(response)
    else:
     event=''
     for raw in response:
      line=raw.decode().strip()
      if line.startswith('event: '):event=line[7:]
      elif line.startswith('data: '):
       v=json.loads(line[6:])
       if event=='error':raise ValueError('stream_error')
       if event=='status' and first_status is None:first_status=(time.perf_counter()-started)*1000
       if event=='evidence':result=v
       if event=='delta':
        if first_delta is None:first_delta=(time.perf_counter()-started)*1000
        chunks+=v['text']
       if event=='done':done=True
   if stream and (not done or result is None or chunks!=result['zh']):raise ValueError('incomplete_stream')
   session=result['session_id'];turns.append({'question':redact(question),'http_ms':(time.perf_counter()-started)*1000,'first_status_ms':first_status,'first_validated_answer_chunk_ms':first_delta,'reply':result})
  except Exception as exc:
   turns.append({'question':redact(question),'http_ms':(time.perf_counter()-started)*1000,'error_type':type(exc).__name__});break
 answer={'id':case['id'],'label':label,'repeat':repeat,'kind':case['kind'],'split':case['split'],'group':case['group'],'case':case,'transport':'validated_SSE' if stream else 'JSON','turns':turns}
 write_json(path,answer);return answer

def publish(phase):
 ids={c['id'] for c in CASES};runs={label:score_run(ROOT,label,ids,True) for label in LABELS}
 d={'protocol':'experience548-v1','phase':phase,'n':548,'dataset_sha256':digest(CASES),'runs':runs,'historical':{label:score_run(ROOT,label,ids,True) for label in ['parent-full548','candidate-improved548']},'limits':['All548 are seen regression cases after diagnosis, not new holdout','Same-model-family LLM judge, not independent human review','Offline task passing is not production resolution'],'judge_source_sha256':digest((ROOT/'scripts/live_service_eval_v2.py').read_bytes())}
 write_json(OUT/'experience548-progress.json',d);write_json(ROOT/'web/experience548-progress.json',d)
 return d

def run_jobs(jobs,phase):
 def one(job):
  case,label,base,stream=job;a=request(case,label,base,stream);jp=LOCAL/'judges'/label/(case['id']+'-r0.json')
  if not jp.exists():write_json(jp,ev.judge_row(a))
  return label,case['id']
 with ThreadPoolExecutor(max_workers=12) as pool:
  fs=[pool.submit(one,j) for j in jobs]
  for i,f in enumerate(as_completed(fs),1):
   print(phase,i,'/',len(jobs),*f.result(),flush=True)
   if i%20==0:publish(phase)
 publish(phase+'-complete')

def start(root,port):
 env={**os.environ,'ONTOCARE_LLM_CONFIG':str(ROOT/'local/deepseek-config.json'),'PYTHONPATH':str(root)}
 log=(RUN/f'server-{port}.log').open('a')
 p=subprocess.Popen([str(ROOT/'.venv/bin/python'),'-m','ontocare.cli','serve','--port',str(port)],cwd=root,env=env,stdout=log,stderr=log)
 for _ in range(120):
  try:
   with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/runtime',timeout=2) as r:return p,json.load(r)
  except Exception:
   if p.poll() is not None:raise RuntimeError('frozen_server_failed')
   time.sleep(.5)
 raise RuntimeError('frozen_server_timeout')

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--candidate',action='store_true');parser.add_argument('--release',default='v2');parser.add_argument('--label',default=LABELS[2]);args=parser.parse_args()
 RUN.mkdir(parents=True,exist_ok=True)
 if not args.candidate:
  root=snapshot('v1');p,runtime=start(root,5121)
  with urllib.request.urlopen('http://127.0.0.1:5120/api/runtime') as r:live=json.load(r)
  for key in ['code_sha256','prompt_sha256','data_sha256','reference_snapshot_sha256','agent','retriever']:assert runtime[key]==live[key],key
  write_json(RUN/'manifest.json',{'live_runtime':live,'snapshot_runtime':runtime,'case_ids':[c['id'] for c in CASES],'dataset_sha256':digest(CASES),'judge_sha256':digest((ROOT/'scripts/live_service_eval_v2.py').read_bytes()),'control':'same frozen code/data/model; only customer-experience Prompt+Skill enabled/disabled','transport':'v1 uses real SSE exactly as5120 UI; control uses JSON'})
  jobs=[]
  for c in sorted(CASES,key=lambda c:digest([c['id'],'exp548'])):
   pair=[(c,LABELS[0],'http://127.0.0.1:5121',False),(c,LABELS[1],'http://127.0.0.1:5121',True)]
   jobs.extend(pair if int(digest(c['id'])[:2],16)%2 else pair[::-1])
  try:run_jobs(jobs,'baseline-and-control')
  finally:p.terminate();p.wait()
 else:
  root=RUN/args.release;assert root.exists();p,runtime=start(root,5122);write_json(RUN/'candidate-runtime.json',runtime)
  try:run_jobs([(c,args.label,'http://127.0.0.1:5122',True) for c in CASES],'candidate-'+args.release)
  finally:p.terminate();p.wait()
 print('EXPERIENCE548 RUN COMPLETE',flush=True)
