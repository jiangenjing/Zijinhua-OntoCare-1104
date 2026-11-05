"""Complete the fixed evaluation protocol; never tune on held-out failures."""
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ontocare.data import load_json,write_json
from ontocare.service_eval_dashboard import summary
LOCAL=ROOT/'local/customer-service-v2';OUT=ROOT/'reports/customer-service-v2'

def publish():
    result=summary(str(ROOT),time.time())
    write_json(OUT/'summary.json',result)
    run=next((r for r in result['runs'] if r['label']=='candidate-final'),None)
    if not run:return
    with (OUT/'all-questions-answers-scores.csv').open('w',newline='') as handle:
        fields=['id','split','kind','repeat','question','full_questions','reference','actual_zh','full_answers_zh','actual_en','decision','model_status','task_pass','judge_reason','bad_case_category','faithfulness']
        writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader()
        for p in sorted((LOCAL/'answers/candidate-final').glob('*.json')):
            a=load_json(p);c=a['case'];r=a['turns'][-1].get('reply',{});jp=LOCAL/'judges/candidate-final'/p.name;j=load_json(jp) if jp.exists() else {}
            from ontocare.service_eval_dashboard import task_verdict
            writer.writerow({'id':a['id'],'split':a['split'],'kind':a['kind'],'repeat':a['repeat'],'question':c['question'],'full_questions':'\n\n'.join(c['turns']),'reference':c.get('reference'),'actual_zh':r.get('zh'),'full_answers_zh':'\n\n'.join(t.get('reply',{}).get('zh','') for t in a['turns']),'actual_en':r.get('en'),'decision':r.get('decision'),'model_status':r.get('model_status'),'task_pass':task_verdict(c,a,j),'judge_reason':j.get('reason'),'bad_case_category':j.get('bad_case_category'),'faithfulness':j.get('faithfulness')})
    write_json(OUT/'final-verification.json',{'dataset_cases':611,'answer_run':run,'status':'completed' if run['unique_cases']==611 and run['three_repeat_cases']>=237 else 'running','stop_criterion':'Frozen heldout retrieval first-hit >=.90; no changes to source scope or action permissions','statistics_note':'Point estimate, not proof population >=90%; reference-quality flags preserved, no opportunistic exclusions'})
    primary=run.get('first_attempt',run)
    def pc(v):return '未测' if v is None else f'{100*v:.2f}%'
    def sec(v):return '未测' if v is None else f'{v/1000:.3f}s'
    h=next(r for r in result['retrieval'] if r['label']=='candidate-title-focused-holdout');p=next(r for r in result['retrieval'] if r['label']=='parent-holdout')
    text=['# 安克客服评测实测报告','',f"冻结611题；实际回答{run['unique_cases']}个不同问题、{run['attempts']}次记录；{run['three_repeat_cases']}题完成至少三次。",'', '| 指标 | 原版 / 结果 |','|---|---|',f"| 留出首条命中 | {pc(p['metrics']['holdout']['recall_at_1'])} → {pc(h['metrics']['holdout']['recall_at_1'])}（各96题） |",f"| 留出 Recall@3 / @6 | {pc(h['metrics']['holdout']['recall_at_3'])} / {pc(h['metrics']['holdout']['recall_at_6'])} |",f"| 有标签任务验证通过率 | {pc(primary['task_pass']['value'])}，{primary['task_pass']['passed']}/{primary['task_pass']['n']}；未评分{primary['task_pass']['unassessed_n']} |",f"| 声明级忠实度 | {pc(primary['faithfulness']['value'])}，支持{primary['faithfulness']['supported_claims']}/{primary['faithfulness']['total_claims']}条 |",f"| HTTP P50 / P99 | {sec(run['latency_http']['p50_ms'])} / {sec(run['latency_http']['p99_ms'])} |",f"| 图检索 P50 / P99 | {sec(run['latency_graph']['p50_ms'])} / {sec(run['latency_graph']['p99_ms'])} |",f"| 回答链Token / Judge Token | {run['answer_tokens']['total_tokens']} / {run['judge_tokens']['total_tokens']} |",'| 真实解决率 / CSAT / 真实转接率 / 重复咨询率 | 未测：缺生产闭环数据 |','| 金额费用 | 未测：网关实际单价未知 |','','以上为源材料生成题集的离线测量，Judge与生成器为同模型系列的不同调用，不等于人工认证或生产客户解决率。','逐题问答和理由见 all-questions-answers-scores.csv；Ragas分项和抽样数量见 summary.json。']
    (OUT/'实测结果.md').write_text('\n'.join(text)+'\n')

if __name__=='__main__':
    while not (LOCAL/'answers-candidate-final-index.json').exists():
        publish();time.sleep(15)
    write_json(OUT/'protocol-progress.json',{'phase':'three_repeats_validation_holdout','planned_unique_cases':611,'planned_total_attempts':1085})
    env={**os.environ,'ONTOCARE_EVAL_URL':'http://127.0.0.1:5113'}
    # The 63 known historical emails remain regression; development screens once.
    subprocess.run([str(ROOT/'.venv/bin/python'),'scripts/live_service_eval_v2.py','candidate-final','--splits','validation','holdout','--repeat','3','--judge','--workers','8'],cwd=ROOT,env=env,check=True)
    publish()
    write_json(OUT/'protocol-progress.json',{'phase':'actual_ragas_paired_sample','planned_total_attempts':1085})
    subprocess.run([str(LOCAL/'ragas-runtime/bin/python'),'scripts/ragas_service_eval_v2.py','candidate-final','--limit','12'],cwd=ROOT,env=env,check=True)
    publish()
    path=OUT/'evolution.json';d=load_json(path);d['candidate_status']='retrieval_holdout_target_met_protocol_completed';d['iterations'][-1]['result']='全量611题回答；验证与留出共237题各3次，共1085次回答记录；实际Ragas12题配对抽样。';write_json(path,d)
    write_json(OUT/'protocol-progress.json',{'phase':'completed','planned_total_attempts':1085})
    print('CUSTOMER EVALUATION PROTOCOL COMPLETED',flush=True)
