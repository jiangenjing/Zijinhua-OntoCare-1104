"""Original548 baseline and candidate548, identical frozen cases and judge; isolated servers."""
import os,sys,json,types,shutil,sqlite3,threading,time,hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from ontocare.data import load_json,write_json,digest
from ontocare.service_eval_dashboard import score_run,task_verdict
import live_service_eval_v2 as evaluator
from ontocare.app import create_app
from werkzeug.serving import make_server
OUT=ROOT/'reports/customer-service-v2';LOCAL=ROOT/'local/customer-service-v2';ARCHIVE=LOCAL/'parent-runtime';RUN=LOCAL/'comparison-v3'

def load_module(name,source):
 m=types.ModuleType('ontocare.'+name);m.__package__='ontocare';sys.modules[m.__name__]=m;exec(compile(source,m.__name__,'exec'),m.__dict__);return m

def prepare(name,prompt):
 root=RUN/name;root.mkdir(parents=True,exist_ok=True)
 for folder in ['data','ontology','web','actions','skills','evaluation']:
  if (ROOT/folder).exists() and not (root/folder).exists():(root/folder).symlink_to(ROOT/folder,target_is_directory=True)
 if not (root/'prompts').exists():shutil.copytree(ROOT/'prompts',root/'prompts')
 (root/'prompts/customer-service.md').write_text(prompt)
 (root/'local').mkdir(exist_ok=True)
 for filename in ['service.sqlite','business.sqlite']:
  dest=root/'local'/filename
  if not dest.exists():
   with sqlite3.connect(ROOT/'local'/filename) as src,sqlite3.connect(dest) as dst:src.backup(dst)
 for filename in ['vectors.npz','vectors.json','ranking-title-vectors.npz','ranking-title-vectors.json','deepseek-config.json']:
  src=ROOT/'local'/filename;dst=root/'local'/filename
  if src.exists() and not dst.exists():dst.symlink_to(src)
 return root

def run_arm(label,agent,port,cases):
 server=make_server('127.0.0.1',port,create_app(agent.root,agent),threaded=True);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();evaluator.BASE=f'http://127.0.0.1:{port}'
 def one(case):
  a=evaluator.request(case,label,0);jp=LOCAL/'judges'/label/(case['id']+'-r0.json')
  if not jp.exists():write_json(jp,evaluator.judge_row(a))
  return case['id']
 try:
  with ThreadPoolExecutor(max_workers=8) as pool:
   futures=[pool.submit(one,c) for c in cases]
   for i,f in enumerate(as_completed(futures),1):
    print(label,i,'/',len(cases),f.result(),flush=True)
    if i%10==0:publish()
 finally:server.shutdown()
 publish()

def publish():
 labels=['parent-full548','candidate-final','candidate-improved548'];ids={c['id'] for c in CASES}
 runs={k:score_run(ROOT,k,ids,True) for k in labels}
 result={'protocol':'full548-v3','dataset_sha256':digest(CASES),'cases':548,'judge':'same frozen judge_row; no rubric edits','runs':runs,'completed':all(runs[k]['unique_cases']==548 and runs[k]['judged']==548 for k in ['parent-full548','candidate-improved548']),'historical_holdout':'now observed for evaluation; not claimed as new independent generalization evidence','new_unseen_holdout':'not_run; must select source-disjoint families after candidate freeze'}
 write_json(OUT/'full548-comparison.json',result)

if __name__=='__main__':
 os.environ['ONTOCARE_LLM_CONFIG']=str(ROOT/'local/deepseek-config.json')
 CASES=[c for c in load_json(ROOT/'evaluation/customer-service-v2/cases.json')['cases'] if c['kind']!='seen_ticket'];assert len(CASES)==548
 RUN.mkdir(parents=True,exist_ok=True)
 parent_prompt=(ARCHIVE/'customer-service.md').read_text();parent_source=(ARCHIVE/'agent.py').read_text();retrieval_source=(ARCHIVE/'retrieval.py').read_text()
 parent_retriever=load_module('v3_parent_retriever',retrieval_source).Retriever
 parent_module=load_module('v3_parent_agent',parent_source);parent_module.Retriever=parent_retriever
 candidate_source=(ROOT/'ontocare/customer_agent.py').read_text()
 candidate_source=candidate_source.replace("dealer_only = skill == 'aftersales' and bool(","dealer_only = skill == 'aftersales' and bool(")
 old="dealer_only = skill == 'aftersales' and bool(re.search(r'dealer|seller|经销商|销售方|卖家|购买渠道|授权', text, re.I))"
 new="dealer_only = skill == 'aftersales' and bool(business_context.get('dealer_check') or re.search(r'dealer|seller|经销商|销售方|卖家|购买渠道|授权', text, re.I))"
 assert old in candidate_source;candidate_source=candidate_source.replace(old,new)
 prompt=(ROOT/'prompts/customer-service.md').read_text()+'''\n## Candidate-v4 evidence and conversation corrections\nAnswer only the latest customer turn. When the user explicitly switches product or issue, finish the latest task using the reset state; do not also answer the old product issue. Translate pump hub consistently as 泵主机（pump hub）. If the exact component is supplied, acknowledge it without requesting it again.\nFor factual questions use the most directly matching source first. If its content only contains a URL, say that the linked instructions are the available evidence; do not import specifications, settings or procedures from adjacent FAQs or another named model. Do not label a configuration/specification for one named model as applicable to another based only on proximity. Preserve scope conflicts and request clarification.\n'''
 (RUN/'candidate-agent.py').write_text(candidate_source);(RUN/'candidate-prompt.md').write_text(prompt)
 write_json(RUN/'manifest.json',{'cases':548,'case_ids':[c['id'] for c in CASES],'dataset_sha256':digest(CASES),'original_agent_sha256':digest(parent_source),'original_retrieval_sha256':digest(retrieval_source),'original_prompt_sha256':digest(parent_prompt),'candidate_agent_sha256':digest(candidate_source),'candidate_prompt_sha256':digest(prompt),'changes':['dealer context routes to purchase evidence rather than unrelated missing-PN branch','latest-turn and product-switch wording','primary-source scope; prohibit adjacent-model advice'],'reference_conflicts':'kept for audit; gold unchanged','deployment':'candidate isolated, production unchanged until review of results'})
 publish()
 run_arm('parent-full548',parent_module.Agent(prepare('parent',parent_prompt)),5116,CASES)
 candidate_module=load_module('v3_candidate_agent',candidate_source)
 run_arm('candidate-improved548',candidate_module.Agent(prepare('candidate',prompt)),5117,CASES)
 print('FULL548 COMPARISON FINISHED',flush=True)
