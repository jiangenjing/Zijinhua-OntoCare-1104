"""Wait for all honest runs, score fixed paired Ragas samples, export auditable results."""
import sys,time,subprocess,csv
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from ontocare.data import load_json,write_json
from ontocare.service_eval_dashboard import score_run,task_verdict
OUT=ROOT/'reports/customer-service-v2';LOCAL=ROOT/'local/customer-service-v2'
while True:
 try:
  d=load_json(OUT/'full548-comparison.json')
  if isinstance(d.get('new_unseen_holdout'),dict) and d['new_unseen_holdout']['unique_cases']==80:break
 except (FileNotFoundError,ValueError):pass
 time.sleep(10)
for label in ['parent-full548','candidate-improved548']:
 subprocess.run([str(LOCAL/'ragas-runtime/bin/python'),'scripts/ragas_service_eval_v2.py',label,'--limit','12'],cwd=ROOT,check=True)
# Explicitly repeat all four multi-turn scenarios three times on the frozen candidate.
import os,threading
from concurrent.futures import ThreadPoolExecutor
from werkzeug.serving import make_server
import run_full_comparison_v3 as harness
import live_service_eval_v2 as evaluator
os.environ['ONTOCARE_LLM_CONFIG']=str(ROOT/'local/deepseek-config.json')
runroot=LOCAL/'comparison-v3';module=harness.load_module('v3_multiturn_candidate',(runroot/'candidate-agent.py').read_text());agent=module.Agent(harness.prepare('candidate',(runroot/'candidate-prompt.md').read_text()))
server=make_server('127.0.0.1',5119,harness.create_app(agent.root,agent),threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();evaluator.BASE='http://127.0.0.1:5119'
multi=[c for c in load_json(ROOT/'evaluation/customer-service-v2/cases.json')['cases'] if c['kind']=='multi_turn']
def repeat_one(pair):
 c,r=pair;a=evaluator.request(c,'candidate-v3-multi3',r);jp=LOCAL/'judges/candidate-v3-multi3'/(c['id']+f'-r{r}.json')
 if not jp.exists():write_json(jp,evaluator.judge_row(a))
try:
 with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(repeat_one,[(c,r) for c in multi for r in range(3)]))
finally:server.shutdown()
d=load_json(OUT/'full548-comparison.json');d['ragas']={label:load_json(OUT/f'ragas-{label}.json')['metrics'] for label in ['parent-full548','candidate-improved548']}
case_data=load_json(ROOT/'evaluation/customer-service-v2/cases.json')['cases'];byid={c['id']:c for c in case_data if c['kind']!='seen_ticket'}
with (OUT/'full548-paired-answers.csv').open('w',newline='') as f:
 fields=['id','split','kind','question','parent_zh','parent_pass','previous_zh','previous_pass','candidate_zh','candidate_pass','parent_reason','candidate_reason'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
 for ident,case in byid.items():
  row={'id':ident,'split':case['split'],'kind':case['kind'],'question':'\n'.join(case['turns'])}
  for label,prefix in [('parent-full548','parent'),('candidate-final','previous'),('candidate-improved548','candidate')]:
   a=load_json(LOCAL/'answers'/label/(ident+'-r0.json'));j=load_json(LOCAL/'judges'/label/(ident+'-r0.json'));row[prefix+'_zh']=a['turns'][-1]['reply']['zh'];row[prefix+'_pass']=task_verdict(case,a,j)
   if prefix!='previous':row[prefix+'_reason']=j.get('reason')
  w.writerow(row)
d['multi_turn_stability']=score_run(ROOT,'candidate-v3-multi3');d['by_split']={};d['by_kind']={}
for dimension in ['split','kind']:
 for value in sorted({c[dimension] for c in byid.values()}):
  ids={c['id'] for c in byid.values() if c[dimension]==value}
  d['by_'+dimension][value]={label:score_run(ROOT,label,ids,True)['task_pass'] for label in d['runs']}
transitions={'fixed':[],'regressed':[],'still_failed':[]}
for ident,case in byid.items():
 results={}
 for label in ['candidate-final','candidate-improved548']:
  a=load_json(LOCAL/'answers'/label/(ident+'-r0.json'));j=load_json(LOCAL/'judges'/label/(ident+'-r0.json'));results[label]=(task_verdict(case,a,j),j)
 old,oj=results['candidate-final'];new,nj=results['candidate-improved548']
 category='fixed' if old is False and new is True else 'regressed' if old is True and new is False else 'still_failed' if new is False else None
 if category:transitions[category].append({'id':ident,'split':case['split'],'kind':case['kind'],'question':case['question'],'old_reason':oj.get('reason'),'new_reason':nj.get('reason')})
d['transitions']=transitions;write_json(OUT/'full548-case-transitions.json',transitions)
base=d['runs']['parent-full548'];cand=d['runs']['candidate-improved548'];prev=d['runs']['candidate-final'];reserve=d['new_unseen_holdout']
d['gates']={'candidate_overall_not_worse':cand['task_pass']['value']>=prev['task_pass']['value'],'validation_improved':d['by_split']['validation']['candidate-improved548']['value']>d['by_split']['validation']['candidate-final']['value'],'multi_turn_not_worse':d['by_kind']['multi_turn']['candidate-improved548']['value']>=d['by_kind']['multi_turn']['candidate-final']['value'],'no_policy_flags':cand['judge_safety_flags']==0,'no_validator_failures':not cand['failed_validators'],'reserve_ge90':reserve['task_pass']['value']>=.90}
d['candidate_accepted']=all(d['gates'].values());d['deployment']='isolated candidate; results ready for review, not silently deployed';d['phase']='complete'
write_json(OUT/'full548-comparison.json',d);write_json(ROOT/'web/full548-progress.json',d)
lines=['# 548题真正同题对照与第二轮优化','', '| 版本 | 首次任务通过 |','|---|---|']
for label,title in [('parent-full548','还原原版'),('candidate-final','上一版'),('candidate-improved548','新候选')]:
 r=d['runs'][label]['task_pass'];lines.append(f"| {title} | {r['passed']}/548 = {r['value']:.2%} |")
lines += ['',f"原版→新候选：{100*(cand['task_pass']['value']-base['task_pass']['value']):+.2f}个百分点。",f"上一版→新候选：{100*(cand['task_pass']['value']-prev['task_pass']['value']):+.2f}个百分点。",'', '新候选验收条件：'+str(d['gates']),f"新增来源留出：{reserve['task_pass']['passed']}/80，{reserve['task_pass']['value']:.2%}。仅与本轮611来源不重叠；合成标签，需要人工复核。",'', '验证/多轮用于优化后属于已见回归，不再充当独立泛化证据。型号冲突Gold保留；同一Judge评分规则保持不变。真实客户解决率仍未测得。','', '逐题原版、上一版、新候选回答与原始评分见 full548-paired-answers.csv。']
(OUT/'548题完整对照与优化结果.md').write_text('\n'.join(lines)+'\n')
import shutil
shutil.copyfile(OUT/'full548-paired-answers.csv',ROOT/'web/full548-paired-answers.csv')
shutil.copyfile(OUT/'548题完整对照与优化结果.md',ROOT/'web/full548-report.md')
print('FULL548 FINAL REPORT READY',d['gates'],flush=True)
