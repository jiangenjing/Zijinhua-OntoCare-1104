"""Pilot existing evidence guard; preserve primary evaluation rubric."""
import sys,shutil,sqlite3
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import evaluate_experience548 as ev
from ontocare.data import write_json,load_json,digest
from ontocare.service_eval_dashboard import task_verdict,score_run
BASE=ev.RUN;src=BASE/'v1';dst=BASE/'v3'
if not dst.exists():
 dst.mkdir()
 for folder in ['ontocare','prompts','data','ontology']:shutil.copytree(src/folder,dst/folder,ignore=shutil.ignore_patterns('__pycache__'))
 for folder in ['web','actions','skills','evaluation','reports','docs']:(dst/folder).symlink_to(ROOT/folder,target_is_directory=True)
 (dst/'local').mkdir()
 for p in (src/'local').iterdir():
  if p.is_file() and p.suffix=='.sqlite':
   with sqlite3.connect(p) as source,sqlite3.connect(dst/'local'/p.name) as target:source.backup(target)
  elif p.is_file() and not p.name.endswith(('-wal','-shm')):(dst/'local'/p.name).symlink_to(p.resolve())
 (dst/'local/customer-service-v2').symlink_to(ev.LOCAL,target_is_directory=True)
 p=dst/'ontocare/app.py';s=p.read_text().replace('from .reference_agent import SourceActionAgent as Agent','from .reference_agent import VerifiedReferenceAgent as Agent');p.write_text(s)
 p=dst/'ontocare/agent.py';s=p.read_text().replace("dealer_only = skill == 'aftersales' and bool(re.search(","dealer_only = skill == 'aftersales' and bool(business_context.get('dealer_check') or re.search(");p.write_text(s)
 p=dst/'ontocare/prompting.py';s=p.read_text().replace('"customer-experience-v1" if customer_experience','"customer-experience-v3-guard" if customer_experience');p.write_text(s)
 ids=[]
 for c in ev.CASES:
  a=ev.LOCAL/'answers/experience-v1-stream548'/(c['id']+'-r0.json');j=ev.LOCAL/'judges/experience-v1-stream548'/a.name
  if j.exists() and task_verdict(c,load_json(a),load_json(j)) is False:ids.append(c['id'])
 # Include deterministic success cases to detect guard false-rejection.
 for c in sorted(ev.CASES,key=lambda c:digest([c['id'],'guard-pilot'])):
  a=ev.LOCAL/'answers/experience-v1-stream548'/(c['id']+'-r0.json');j=ev.LOCAL/'judges/experience-v1-stream548'/a.name
  if j.exists() and c['id'] not in ids:ids.append(c['id'])
  if len(ids)>=40:break
 write_json(BASE/'guard-pilot-ids.json',ids)
 write_json(BASE/'guard-changes.json',{'baseline':'v1','changes':['existing GroundedProvider checks cited evidence including official bodies, conditions and scope','at most one existing generation retry after unsupported claim review','dealer context routes to purchase evidence'],'prompt':'v1 wording retained; v2 long correction prompt rejected pending result review','pilot_ids':ids,'gold_and_primary_judge':'unchanged'})
ids=set(load_json(BASE/'guard-pilot-ids.json'));cases=[c for c in ev.CASES if c['id'] in ids];p,runtime=ev.start(dst,5123)
def run(c):
 a=ev.request(c,'experience-v3-pilot','http://127.0.0.1:5123',True);jp=ev.LOCAL/'judges/experience-v3-pilot'/(c['id']+'-r0.json')
 if not jp.exists():write_json(jp,ev.ev.judge_row(a))
 return c['id']
try:
 with ThreadPoolExecutor(max_workers=8) as pool:
  for i,c in enumerate(pool.map(run,cases),1):print('GUARD PILOT',i,'/',len(cases),c,flush=True)
finally:p.terminate();p.wait()
write_json(ev.OUT/'experience548-guard-pilot.json',{'runs':{label:score_run(ROOT,label,ids,True) for label in ['experience-v1-stream548','experience-v2-stream548','experience-v3-pilot']},'selection':'failure-focused + deterministic successes; not population performance'})
print('GUARD PILOT COMPLETE',flush=True)
