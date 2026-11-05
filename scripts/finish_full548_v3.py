"""Publish full comparison progress and evaluate source-disjoint reserve after freeze."""
import time,json,sys,runpy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from ontocare.data import load_json,write_json,digest
from ontocare.service_eval_dashboard import score_run
OUT=ROOT/'reports/customer-service-v2';LOCAL=ROOT/'local/customer-service-v2';RUN=LOCAL/'comparison-v3'
while True:
 try:
  result=load_json(OUT/'full548-comparison.json');write_json(ROOT/'web/full548-progress.json',result)
  if result['completed']:break
 except (FileNotFoundError,ValueError):pass
 time.sleep(10)
import service_eval_v2 as builder
builder.LOCAL=RUN/'reserve-generation';builder.LOCAL.mkdir(parents=True,exist_ok=True)
used={c['group'] for c in load_json(ROOT/'evaluation/customer-service-v2/cases.json')['cases']}
docs=[d for d in load_json(ROOT/'data/knowledge.json') if d['visible'] and d['content_hash'] not in used]
selected=[];seen=set()
for d in sorted(docs,key=lambda d:digest([d['content_hash'],'full548-reserve-v3'])):
 if d['content_hash'] in seen:continue
 seen.add(d['content_hash']);selected.append({'group':d['content_hash'],'pn':d['pns'][0],'document':d,'gold_ids':[x['id'] for x in docs if x['content_hash']==d['content_hash'] and d['pns'][0] in x['pns']]})
 if len(selected)==40:break
path=RUN/'reserve80.json'
if not path.exists():
 from concurrent.futures import ThreadPoolExecutor
 with ThreadPoolExecutor(max_workers=4) as pool:
  list(pool.map(lambda i:builder.generate_batch(i//4,selected[i:i+4]),range(0,len(selected),4)))
 cases=[]
 for i in range(0,len(selected),4):
  batch=selected[i:i+4];items={x['id']:x for x in builder.generate_batch(i//4,batch)['items']}
  for g in batch:
   item=items[g['document']['id']]
   for lang in ['zh','en']:
    q=g['pn']+' '+item[lang];cases.append({'id':'reserve3-'+g['document']['id']+'-'+lang,'kind':'knowledge','group':g['group'],'split':'new_holdout','language':lang,'pn':g['pn'],'question':q,'turns':[q],'context':{'sku':g['pn']},'gold_ids':g['gold_ids'],'reference':item['reference'],'support_quote':item['support_quote'],'source':g['document']['source']})
 write_json(path,{'cases':cases,'sha256':digest(cases),'scope':'40 source families excluded from prior611, synthetic gold, not independently human-labelled; other experiments not excluded'})
cases=load_json(path)['cases'];import run_full_comparison_v3 as harness
harness.CASES=[c for c in load_json(ROOT/'evaluation/customer-service-v2/cases.json')['cases'] if c['kind']!='seen_ticket']
import os;os.environ['ONTOCARE_LLM_CONFIG']=str(ROOT/'local/deepseek-config.json')
m=harness.load_module('reserve_candidate_v3',(RUN/'candidate-agent.py').read_text());agent=m.Agent(harness.prepare('candidate',(RUN/'candidate-prompt.md').read_text()))
harness.run_arm('candidate-v3-reserve80',agent,5118,cases)
result=load_json(OUT/'full548-comparison.json');result['new_unseen_holdout']=score_run(ROOT,'candidate-v3-reserve80');result['reserve_definition']='source-disjoint from611 only; synthetic, n80; frozen candidate unchanged after reserve';write_json(OUT/'full548-comparison.json',result);write_json(ROOT/'web/full548-progress.json',result)
print('FULL548 AND RESERVE COMPLETE',flush=True)
