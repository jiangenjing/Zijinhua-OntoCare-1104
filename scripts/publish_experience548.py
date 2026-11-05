"""Export observed paired outcomes; preserve regressions and evaluation limits."""
import sys,json,csv,random,statistics
from pathlib import Path
from collections import Counter,defaultdict
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from ontocare.data import load_json,write_json
from ontocare.service_eval_dashboard import score_run,task_verdict,percentile
import evaluate_experience548 as harness
from analyze_experience548 import diagnostic
LOCAL=harness.LOCAL;OUT=harness.OUT;LABELS=harness.LABELS;CASES=harness.CASES

def paired_interval(pairs):
 groups=defaultdict(list)
 for c,old,new in pairs:
  if old is not None and new is not None:groups[c['group']].append(int(new)-int(old))
 members=list(groups.values());rng=random.Random(20261103);sample=[]
 for _ in range(2000):
  rows=[v for group in rng.choices(members,k=len(members)) for v in group];sample.append(sum(rows)/len(rows))
 sample.sort();return {'groups':len(members),'delta_95_interval_pp':[100*sample[50],100*sample[1949]],'method':'paired source-group bootstrap, query-weighted; includes stochastic judge/generator uncertainty only imperfectly'}

def main():
 d=harness.publish('finalizing');metrics={};answers={};judges={};bad={};rows=[]
 for label in LABELS:
  answers[label]={c['id']:load_json(LOCAL/'answers'/label/(c['id']+'-r0.json')) for c in CASES}
  judges[label]={c['id']:load_json(LOCAL/'judges'/label/(c['id']+'-r0.json')) for c in CASES}
  bad[label]=[diagnostic(answers[label][c['id']],judges[label][c['id']]) for c in CASES if task_verdict(c,answers[label][c['id']],judges[label][c['id']]) is not True]
  hits={k:0 for k in [1,3,6]};n=0;wait=[];chunks=[]
  for c in CASES:
   a=answers[label][c['id']];r=a['turns'][-1].get('reply',{})
   if c['kind']=='knowledge':
    n+=1;ranked=[v for t in r.get('tools',[]) if t['name']=='search_evidence' for v in t['result'].get('ids',[])]
    for k in hits:hits[k]+=bool(set(ranked[:k])&set(c['gold_ids']))
   for t in a['turns']:
    if t.get('first_status_ms') is not None:wait.append(t['first_status_ms'])
    if t.get('first_validated_answer_chunk_ms') is not None:chunks.append(t['first_validated_answer_chunk_ms'])
  metrics[label]={'knowledge_first_hit':{f'at_{k}':{'passed':v,'n':n,'value':v/n} for k,v in hits.items()},'by_split':{split:score_run(ROOT,label,{c['id'] for c in CASES if c['split']==split},True)['task_pass'] for split in ['development','validation','holdout']},'first_status_latency':percentile(wait),'first_validated_answer_chunk_latency':percentile(chunks),'by_kind':d['runs'][label]['task_by_kind'],'http_latency':d['runs'][label]['latency_http'],'graph_latency':d['runs'][label]['latency_graph'],'retrieval_latency':d['runs'][label]['latency_retrieval'],'answer_tokens':d['runs'][label]['answer_tokens'],'judge_tokens':d['runs'][label]['judge_tokens'],'model_status_counts':d['runs'][label]['model_status_counts'],'policy_flags':d['runs'][label]['judge_safety_flags'],'failed_validators':d['runs'][label]['failed_validators'],'note':'HTTP includes validated chunk delivery for SSE; not raw model TTFT. Knowledge first-hit uses accepted equivalent-source Gold IDs.'}
 for c in CASES:
  row={'id':c['id'],'kind':c['kind'],'split':c['split'],'questions':'\n'.join(c['turns'])}
  for label in LABELS:
   a=answers[label][c['id']];j=judges[label][c['id']];row[label+'_answer']=a['turns'][-1].get('reply',{}).get('zh','');row[label+'_pass']=task_verdict(c,a,j);row[label+'_reason']=j.get('reason','');row[label+'_all_turns']=json.dumps([{'question':t['question'],'zh':t.get('reply',{}).get('zh'),'en':t.get('reply',{}).get('en'),'decision':t.get('reply',{}).get('decision'),'model_status':t.get('reply',{}).get('model_status')} for t in a['turns']],ensure_ascii=False)
  rows.append(row)
 with (OUT/'experience548-answers.csv').open('w',newline='',encoding='utf-8-sig') as f:
  writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
 baseline=d['runs'][LABELS[1]]
 eligible=[label for label in LABELS[2:] if d['runs'][label]['task_pass']['value']>=baseline['task_pass']['value'] and d['runs'][label]['faithfulness']['value']>=baseline['faithfulness']['value'] and d['runs'][label]['judge_safety_flags']<=baseline['judge_safety_flags'] and not d['runs'][label]['failed_validators']]
 selected=max(eligible,key=lambda label:(d['runs'][label]['task_pass']['value'],d['runs'][label]['faithfulness']['value'])) if eligible else LABELS[1]
 d['selected_candidate']=selected
 d['selection_rule']='Pass task/faithfulness/policy/validator gates versus v1, then maximize task passing, faithfulness tie-break. Selection uses seen548; not independent validation.'
 transitions={k:[] for k in ['fixed','regressed','still_failed']};paired=[];prompt_pairs=[]
 for c in CASES:
  verdict={label:task_verdict(c,answers[label][c['id']],judges[label][c['id']]) for label in LABELS};old,new=verdict[LABELS[1]],verdict[selected];paired.append((c,old,new));prompt_pairs.append((c,verdict[LABELS[0]],old))
  category='fixed' if old is False and new is True else 'regressed' if old is True and new is False else 'still_failed' if new is False else None
  if category:transitions[category].append(c['id'])
 d['metrics']=metrics;d['bad_cases']=bad;d['transitions']=transitions;d['paired_bootstrap']={'prompt_v1_vs_control':paired_interval(prompt_pairs),'selected_vs_v1':paired_interval(paired)}
 analysis=OUT/'experience548-analysis.json'
 if analysis.exists():
  d['baseline_analysis']=load_json(analysis)
  reviewed={r['id']:r for r in d['baseline_analysis']['bad_cases']['experience-v1-stream548']}
  d['bad_cases']['experience-v1-stream548']=[reviewed.get(r['id'],r) for r in d['bad_cases']['experience-v1-stream548']]
 guard=OUT/'experience548-guard-pilot.json'
 if guard.exists():d['rejected_guard_pilot']=load_json(guard)
 d['candidate_changes']=load_json(LOCAL/('experience548/v4-changes.json' if selected==LABELS[-1] else 'experience548/candidate-changes.json'))
 d['phase']='complete';d['complete']=all(v['unique_cases']==548 and v.get('judged')==548 for v in d['runs'].values())
 control,v1,v2=[d['runs'][label] for label in [LABELS[0],LABELS[1],selected]]
 d['gates']={'task_not_worse':v2['task_pass']['value']>=v1['task_pass']['value'],'faithfulness_not_worse':v2['faithfulness']['value']>=v1['faithfulness']['value'],'no_increased_policy_flags':v2['judge_safety_flags']<=v1['judge_safety_flags'],'no_failed_validators':not v2['failed_validators'],'all_548_judged':d['complete']}
 deployment=LOCAL/'experience548/deployment.json'
 d['deployment']='已切换5120到 '+load_json(deployment)['label'] if deployment.exists() else '候选隔离评测，未切换5120'
 if deployment.exists():d['deployment_record']=load_json(deployment)
 d['summary']=f"新版v1相对同代码控制组任务通过率差值：{100*(v1['task_pass']['value']-control['task_pass']['value']):+.2f}个百分点；选择候选{selected}相对v1：{100*(v2['task_pass']['value']-v1['task_pass']['value']):+.2f}个百分点。修复{len(transitions['fixed'])}题，退步{len(transitions['regressed'])}题，仍失败{len(transitions['still_failed'])}题。"
 ragas={}
 for label in LABELS:
  p=OUT/f'ragas-{label}.json'
  if p.exists():ragas[label]=load_json(p)['metrics']
 if ragas:
  d['ragas_fixed12']=ragas
  d['ragas_context_note']='All retrieved QA texts plus official bodies on cited sources; same fixed12 IDs across arms; not548-wide Ragas.'
 write_json(OUT/'experience548-comparison.json',d);write_json(OUT/'experience548-progress.json',d);write_json(ROOT/'web/experience548-progress.json',d)
 lines=['# 5120新版客服：548题Prompt/Skill评测与改进','',d['summary'],'','|版本|任务通过|声明忠实度|首条知识命中|HTTP P50/P99|','|---|---|---|---|---|']
 for label in LABELS:
  r=d['runs'][label];m=metrics[label];lines.append(f"|{label}|{r['task_pass']['passed']}/548 ({r['task_pass']['value']:.2%})|{r['faithfulness']['value']:.2%}|{m['knowledge_first_hit']['at_1']['value']:.2%}|{r['latency_http']['p50_ms']/1000:.2f}s / {r['latency_http']['p99_ms']/1000:.2f}s|")
 lines+=['', '## 分项与改进','',json.dumps(metrics,ensure_ascii=False,indent=2),'','## 修复、退步、仍失败','',json.dumps(transitions,ensure_ascii=False,indent=2),'','## 统计与部署边界','',json.dumps(d['paired_bootstrap'],ensure_ascii=False,indent=2),'', '548题均为已见回归；同模型家族LLM Judge；离线任务通过不等于真实问题解决。控制组与v1只改变体验Prompt/Skill，v4保留v1表达，另含业务路由与有来源证明的配件角色修正。对官方正文未进入主Judge造成的疑点做独立诊断，不改主评分。版本快照与逐题实际回答保留。','', '方法参考：https://www.palantir.com/docs/foundry/aip-evals/analyze-run-results ，https://www.palantir.com/docs/foundry/aip-evals/experiments ，https://arxiv.org/abs/2408.08067','', '详见 docs/5120客服评测与BadCase改进方法.md，实际修改见独立冻结候选清单。']
 lines+=['', '所选候选：'+selected, '选用规则：'+d['selection_rule'], '', json.dumps(d['candidate_changes'],ensure_ascii=False,indent=2), '', '延迟受不同阶段并发负载与缓存影响，不把本轮P50/P99差异直接当作算法性能提升。']
 if ragas:lines+=['','固定同题12题Ragas（非548题全量）：',json.dumps(ragas,ensure_ascii=False,indent=2)]
 (OUT/'5120新版548题评测与改进.md').write_text('\n'.join(lines)+'\n')
 import shutil
 shutil.copyfile(OUT/'experience548-answers.csv',ROOT/'web/experience548-answers.csv');shutil.copyfile(OUT/'5120新版548题评测与改进.md',ROOT/'web/experience548-report.md')
 print(d['summary'],d['gates'],flush=True)
if __name__=='__main__':main()
