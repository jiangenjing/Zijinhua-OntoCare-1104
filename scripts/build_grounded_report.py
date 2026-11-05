"""Recompute every displayed number from saved runs; unavailable is never zero."""
from collections import Counter,defaultdict
from pathlib import Path
import json
import csv
import random
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ontocare.data import load_json,write_json,digest
from ontocare.benchmark_metrics import latency

OUT=ROOT/'reports/grounded-eval'


def run_summary(arm):
    folder=ROOT/'local/eval-v2/live'/arm;rows=[];times=[];graph=[];retrieval=[];calls=[];judges=[];scored=[];bad=Counter();dims=defaultdict(list);supported=total=manual=0;turns=0;judge_calls=[]
    for path in sorted(folder.glob('*.json')):
        if path.name.endswith('-judge.json'):continue
        row=load_json(path);jp=path.with_name(path.stem+'-judge.json');j=load_json(jp) if jp.exists() else {}
        rows.append(row)
        if j.get('status')=='completed':
            judges.append(j);scored.append(j['passed']);supported+=j.get('supported_claims',0);total+=j.get('total_claims',0)
            for k,v in j['dimensions'].items():dims[k].append(v['score'])
            if not j['passed']:
                status=row['turns'][-1].get('reply',{}).get('model_status')
                category='validator' if status and status!='completed' else j.get('attribution','unknown')
                bad[category]+=1
        judge_calls+=j.get('model_calls',[])
        for turn in row['turns']:
            turns+=1;times.append(turn['http_ms']);r=turn.get('reply',{});t=r.get('timings',{})
            if r.get('retrieval') and t.get('graph_ms') is not None:graph.append(t['graph_ms'])
            if t.get('retrieval_ms') is not None:retrieval.append(t['retrieval_ms'])
            calls+=r.get('model_calls',[])+r.get('retrieval_model_calls',[])
            manual+=r.get('decision')=='manual_review'
    def tokens(cs):return {k:sum((c.get('usage') or {}).get(k,0) for c in cs) for k in ['prompt_tokens','completion_tokens','total_tokens']}
    complete=sum(r['turns'][-1].get('reply',{}).get('model_status')=='completed' for r in rows)
    return {'arm':arm,'scenarios':len(rows),'turns':turns,'main_model_completed':complete,'judge_completed':len(judges),'pass_n':sum(scored),'pass_denominator':len(scored),'task_pass':sum(scored)/len(scored) if scored else None,'task_pass_scope':'Reply/process pass on sampled synthetic and boundary scenarios; not real issue resolution. Model completion and hard checks are required. Unjudged items are pending.','dimension_means':{k:sum(v)/len(v) for k,v in dims.items()},'faithfulness':supported/total if total else None,'supported_claims':supported,'total_claims':total,'latency_http':latency(times),'latency_graph':latency(graph),'latency_retrieval':latency(retrieval),'answer_tokens':tokens(calls),'judge_tokens':tokens(judge_calls),'manual_review_recommendation_rate':manual/turns if turns else None,'bad_case_attribution':dict(bad),'money_cost':None,'money_cost_reason':'No verified gateway unit prices. Recorded tokens include query rewrite, evidence rerank, answer generation and retries where returned by provider.'}


def main():
    history=load_json(OUT/'selection-history.json');manifest=load_json(ROOT/'evaluation/grounded-1200/manifest.json')
    optional=lambda name:load_json(OUT/name) if (OUT/name).exists() else None
    runs=[run_summary(a) for a in ['baseline','candidate','candidate-v2','release']]
    ragas=optional('ragas-grounded-context.json');ragas_summary={}
    if ragas:
        extra=optional('ragas-release-context.json')
        ragas_cases=ragas['cases']+(extra['cases'] if extra else [])
        for arm in ['baseline','candidate','candidate-v2','release']:
            cases=[c for c in ragas_cases if c['arm']==arm];metrics={}
            for metric in ['faithfulness','context_recall','context_precision','answer_relevancy']:
                vals=[c['metrics'].get(metric) for c in cases if c['metrics'].get(metric) is not None]
                metrics[metric]={'n':len(vals),'value':sum(vals)/len(vals) if vals else None,'failed':len(cases)-len(vals)}
            ragas_summary[arm]=metrics
    summary={'updated_at':time.time(),'dataset':manifest,'selection':{k:v for k,v in history.items() if k!='benchmark'},'v1_final':optional('final-comparison.json'),'v2_validation':optional('verify-validation.json'),'v2_final':optional('reserve-comparison.json'),'release':optional('active-release.json'),'runs':runs,'ragas':{'library':'ragas 0.4.3 collections','scope':'24 responses / 12 bilingual questions / 6 source families, fixed paired subset. English actual response evaluated against actual retrieved full-source contexts; same-model judge; no official composite score.','results':ragas_summary},'business':{'actual_resolution_rate':None,'actual_handoff_rate':None,'csat':None,'repeat_contact_rate':None,'reason':'Source first emails lack confirmed closure/transfer receipts/surveys/customer-linked repeat outcomes. Manual-review recommendation is a proxy, not actual handoff.'},'calibration':optional('judge-calibration.json'),'human_review':'pending; model judging and assistant checks are not human verification','limitations':['问题与来源标签由模型生成，尚未完成独立人工标准答案复核。','正文与规范化标题重复来源不跨集合；更广泛的语义近似仍可能存在。','首条有效资料命中率 Hit@1 与全部标准资料的集合 Recall@1 分母不同，分别报告。','首次最终测试为 88%，结果保留；新增预留集仅覆盖剩余五种型号，不能代替全产品结论。','有限候选曲线不能证明长期收敛。出题、客服和裁判使用同一网关模型，存在同源偏差。','小样本本机 HTTP 的 P99 不稳定，不包含外网浏览器耗时，未测首 token 时间。']}
    audit=optional('top-evidence-audit.json')
    summary.update(workflow_state=optional('workflow-state.json'),cache_latency=optional('cache-latency.json'),paired_effect=optional('paired-effect.json'),top_evidence_audit={k:v for k,v in audit.items() if k!='cases'} if audit else None,source_review_notes=optional('source-review-notes.json'),seen_ticket_regression=optional('seen-ticket-regression.json'))
    write_json(OUT/'summary.json',summary)
    allcases=[c for split in ['development','validation','final'] for c in load_json(ROOT/'evaluation/grounded-1200'/(split+'.json'))['cases']]
    reserve=ROOT/'evaluation/grounded-reserve-v2'
    extra=load_json(reserve/'final.json')['cases'] if (reserve/'final.json').exists() else []
    write_json(OUT/'dataset-export.json',{'manifest':manifest,'cases':allcases,'reserve_manifest':load_json(reserve/'manifest.json') if extra else None,'reserve_cases':extra,'total_semantic_cases':len(allcases)+len(extra),'total_query_forms':2*(len(allcases)+len(extra))})
    # Blinded paired audit. No automatic approval is placed in the reviewer fields.
    sample=load_json(OUT/'live-sampling.json')['cases'];rng=random.Random(20261103);pack=[];audit_key=[]
    for case in sorted(sample,key=lambda c:digest(['audit',c['id']]))[:20]:
        arms=['baseline','release' if (ROOT/'local/eval-v2/live/release').exists() else 'candidate-v2' if (ROOT/'local/eval-v2/live/candidate-v2').exists() else 'candidate'];rng.shuffle(arms);entries=[]
        for arm in arms:
            p=ROOT/'local/eval-v2/live'/arm/(case['id'].replace(':','-')+'.json')
            if p.exists():
                row=load_json(p);label='AB'[len(entries)];audit_key.append({'id':case['id'],'blind_label':label,'arm':arm});entries.append({'blind_label':label,'turns':[{'question':t['question'],'zh':t.get('reply',{}).get('zh'),'en':t.get('reply',{}).get('en'),'citation_ids':t.get('reply',{}).get('citation_ids')} for t in row['turns']]})
        if len(entries)==2:pack.append({'id':case['id'],'reference':case.get('reference'),'versions':entries,'reviewer':None,'reviewed_at':None,'preferred':None,'factual_error':None,'boundary_error':None,'reason':None})
    write_json(OUT/'manual-audit.json',{'status':'pending human review','sampling':'20 preselected cases, version-blind randomized pair order; unavailable pairs remain absent until both finish','cases':pack})
    write_json(ROOT/'local/eval-v2/manual-audit-key.json',audit_key)
    with (OUT/'manual-audit.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['案例','问题','标准来源参考','A中文','A英文','B中文','B英文','更好版本','是否事实错误','是否边界错误','审核理由','审核人','审核时间'])
        for c in pack:
            a,b=c['versions'];writer.writerow([c['id'],'\n'.join(t['question'] for t in a['turns']),c.get('reference'),'\n'.join(t.get('zh') or '' for t in a['turns']),'\n'.join(t.get('en') or '' for t in a['turns']),'\n'.join(t.get('zh') or '' for t in b['turns']),'\n'.join(t.get('en') or '' for t in b['turns']),None,None,None,None,None,None])
    # Actual measured candidates; missing validation points stay missing.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    rounds=[{'candidate':'baseline','development':history['baseline']['development'],'validation':history['baseline']['validation']}]+history['rounds']
    for name in ['rerank','verify']:
        p=optional(name+'-validation.json')
        if p:rounds.append({'candidate':name,'validation':p['metrics']})
    fig,ax=plt.subplots(figsize=(11,4.2));xs=list(range(len(rounds)))
    for split,color in [('development','#9087fd'),('validation','#27b89f')]:
        ys=[100*r.get(split,{}).get('hit_at_1',float('nan')) for r in rounds];ax.plot(xs,ys,'o-',label=split,color=color)
    ax.axhline(90,color='#ea9d50',linestyle='--',label='target 90%');ax.set_xticks(xs,[r['candidate'].replace('_','\n') for r in rounds],fontsize=8);ax.set_ylim(0,100);ax.set_ylabel('Query-level first-hit @1 (%)');ax.set_xlabel('Candidate attempts (not wall-clock convergence)');ax.grid(axis='y',alpha=.2);ax.legend();fig.tight_layout();fig.savefig(OUT/'evolution.svg');plt.close(fig)
    print(json.dumps({'runs':[(r['arm'],r['scenarios'],r['task_pass']) for r in runs],'ragas':ragas_summary},ensure_ascii=False))

if __name__=='__main__':main()
