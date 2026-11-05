"""Source-backed tables and per-case reasons; do not rewrite historical scores."""
from collections import defaultdict
from pathlib import Path
import csv,json,random,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ontocare.data import load_json,write_json
from ontocare.benchmark_metrics import retrieval_scores
OUT=ROOT/'reports/intent-impact-v1';LOCAL=ROOT/'local/intent-impact-v1'
s=load_json(OUT/'summary.json');rows=load_json(LOCAL/'routing-all.json')
groups=defaultdict(list)
for r in rows:groups[r['case']['family']].append(int(r['after']['passed'])-int(r['before']['passed']))
means=[sum(x)/len(x) for x in groups.values()];rng=random.Random(20261103)
boot=sorted(sum(rng.choices(means,k=len(means)))/len(means) for _ in range(5000))
s['routing_paired']['family_bootstrap_delta_95']=[boot[125],boot[4874]]
s['routing_paired']['families']=len(means)
# Validate historical comparisons on case ID, original question and gold, never just summaries.
history=[]
for filename in ['reports/grounded-eval/baseline-validation.json','reports/grounded-eval/body_hybrid-validation.json','reports/reranker-v3/intent-validation.json']:
 x=load_json(ROOT/filename);cases=x['cases'];index={c['id']:c for c in cases}
 if not history:initial=index
 else:
  assert set(initial)==set(index)
  assert all(initial[k]['query']==index[k].get('original_query',index[k]['query']) and set(initial[k]['gold_ids'])==set(index[k]['gold_ids']) for k in initial)
 metrics=[retrieval_scores(c['gold_ids'],c['ranked_ids']) for c in cases]
 history.append({'file':filename,'n':len(cases),'hit_at_1':sum(m['hit_at_1'] for m in metrics)/len(metrics),'recall_at_1':sum(m['recall_at_1'] for m in metrics)/len(metrics),'scope':'historical 300 bilingual validation queries /150 source families; not the new router or independent confirmation'})
write_json(OUT/'historical-audit.json',history)
with (OUT/'routing-cases.csv').open('w',newline='',encoding='utf-8-sig') as f:
 w=csv.writer(f);w.writerow(['ID','问题','预期路由','旧版路由','当前路由','旧版正确','当前正确','识别方法','当前判定理由'])
 for r in rows:w.writerow([r['case']['id'],r['case']['message'],r['case']['expected_route'],r['before']['route'],r['after']['route'],r['before']['passed'],r['after']['passed'],r['after']['classification']['method'],r['after']['classification']['reason']])
replies=[]
for arm in ['before','after']:
 for p in sorted((LOCAL/arm).glob('*.json')):
  r=load_json(p);j=r['judge'];replies.append({'id':r['case']['id'],'arm':arm,'question':r['case']['message'],'reply':{k:r['reply'].get(k) for k in ['zh','en','decision','model_status','trace_id']},'judge':{k:v for k,v in j.items() if k!='model_calls'}})
write_json(OUT/'reply-reasons.json',replies)
a=s['end_to_end']['before'];b=s['end_to_end']['after']
percent=lambda x:'待测' if x is None else f'{x*100:.2f}%'
lines=['# 新增意图识别之后，效果有没有改善？','',
'结论按本轮实测填写；没有修改客服代码、提示词、历史评测口径或错误标签来提高分数。原公开仓库未修改，未上传 GitHub。','',
'## 1. 新旧识别器配对诊断','',
'先冻结 20 个构造场景的中英文问法，共 40 条。共同标签仅为物流、知识/排障、售后三级业务路由；这不是细粒度意图准确率或真实工单解决率。旧版调用 agent.intent，当前版调用客服实际使用的 customer_workflow.classify；同题评测且不使用最终盲测集。','',
'| 指标 | 旧版 | 当前版 | 差值 |','|---|---:|---:|---:|',
f"| 路由命中 | {s['routing']['before']['correct']}/40 | {s['routing']['after']['correct']}/40 | +{s['routing']['after']['correct']-s['routing']['before']['correct']} 条 |",
f"| 路由准确率 | {percent(s['routing']['before']['accuracy'])} | {percent(s['routing']['after']['accuracy'])} | {(s['routing']['after']['accuracy']-s['routing']['before']['accuracy'])*100:+.2f} 个百分点 |",'',
f"同题变化：{s['routing_paired']['improved']} 条改善，{s['routing_paired']['regressed']} 条回归，{s['routing_paired']['both_wrong']} 条两版均未命中。按场景族重采样的差值95%区间：{[round(v*100,2) for v in s['routing_paired']['family_bootstrap_delta_95']]} 个百分点；20个场景族的小样本不能证明生产泛化。",'',
'主要未命中包括否定表达（“不要退款，只查物流”）、隐含换货（“想换一台新的”），还有1条保守追问。保守追问不等于危险误执行，但在冻结的三类精确命中口径下仍计未命中；没有删除或改标。','',
'## 2. 真实模型回复配对诊断','',
'预先选择6个场景族的中英文版本，共12题；旧版与当前版各答一次，共24份回复。同一模型、知识、检索实现与五维裁判Rubric。此对比包含意图识别和SOP包装层，不能把差值全部归因于分类器。裁判独立调用但仍为同一模型，未人工复核。','',
'| 指标 | 旧版 | 当前版 |','|---|---:|---:|',
f"| 裁判任务满足 | {a['judge_task_satisfied_n']}/12（{percent(a['judge_task_satisfied_rate_all_planned'])}） | {b['judge_task_satisfied_n']}/12（{percent(b['judge_task_satisfied_rate_all_planned'])}） |",
f"| 平均五维总分 | {a['mean_judge_score']:.2f}/10 | {b['mean_judge_score']:.2f}/10 |",
f"| 裁判估计忠实度（支持断言/总断言） | {a['supported_claims']}/{a['total_claims']}（{percent(a['faithfulness'])}） | {b['supported_claims']}/{b['total_claims']}（{percent(b['faithfulness'])}） |",
f"| 原有严格模型完成门控通过 | {a['historical_strict_gate_pass_n']}/12 | {b['historical_strict_gate_pass_n']}/12 |",
f"| 模型生成完成 / 本地流程回执 | {a['main_model_completed']} / {a['local_workflow_receipts']} | {b['main_model_completed']} / {b['local_workflow_receipts']} |",
f"| 端到端平均耗时 | {a['latency_http']['mean_ms']/1000:.2f} 秒 | {b['latency_http']['mean_ms']/1000:.2f} 秒 |",'',
'原严格门控仍要求 model_status=completed，本地 workflow_contract 回执不会被偷偷改成模型生成成功。任务满足是裁判原始语义判断，单独列出。端到端时延为本机 HTTP 发出至完整 JSON 返回，已加载模型权重；包含检索、意图和模型调用，不含裁判，也不是TTFT。一次小样本运行不足以稳定估计P99或判断忠实度不回归。','',
'暴露出的实际问题：当前售后固定回复可能覆盖原来的详细建议，只提示确认排障，没有说明足够具体的申请路径。个别裁判还会把信息不完整与不忠实混在一起，需要另行复核；本报告保留原始评分，没有事后翻分。','',
'## 3. 历史检索结果不能冒充本轮效果','',
'已逐条核对以下300条验证问法的ID、原问题和gold一致，但这组比较包含检索翻译、排序与FAQ意图对齐等变化，与本轮业务路由不是同一个实验。','',
'| 历史方法 | Hit@1 | 严格集合 Recall@1 |','|---|---:|---:|']
for label,h in zip(['原始检索','正文混合检索','FAQ意图对齐'],history):lines.append(f"| {label} | {percent(h['hit_at_1'])} | {percent(h['recall_at_1'])} |")
lines+=['','Hit@1表示第一条命中任一正确资料；严格Recall@1表示第一条覆盖全部gold资料的比例。不能把91%的Hit@1写成87.78%的严格Recall@1，也不能称为真实问题解决率。','',
'## 4. 证据与复现','',
'- evaluation/intent-impact-v1/cases.json：执行前冻结的题目、标签和哈希。','- reports/intent-impact-v1/protocol.json：固定协议与比较范围。','- reports/intent-impact-v1/summary.json：本轮指标与运行标识。','- reports/intent-impact-v1/routing-cases.csv：40条配对结果和识别理由。','- reports/intent-impact-v1/reply-reasons.json：24份回复及裁判逐维理由。','- local/intent-impact-v1/：模型消耗、完整轨迹和隔离运行数据库，不入公开代码。','',
'复现：在模型配置可用时运行 `.venv/bin/python scripts/evaluate_intent_impact_v1.py`，再运行 `.venv/bin/python scripts/report_intent_impact_v1.py`。已完成记录会被读取；重新独立运行需使用新实验版本，不能覆盖本轮。','',
'当前没有新增真实结案标签；真实问题解决率仍未知。本轮不是独立最终测试，也没有证明严格Recall@1超过90%或忠实度不下降，因此不上传仓库。']
write_json(OUT/'summary.json',s);(OUT/'结果说明.md').write_text('\n'.join(lines)+'\n')
print({'routing':s['routing'],'paired':s['routing_paired'],'end_to_end':s['end_to_end']})
