"""Rebuild the workbench handoff from recorded results, keeping missing metrics null."""
from collections import Counter
from pathlib import Path
import csv
import math
import random
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ontocare.data import load_json,write_json,digest

OUT=ROOT/'reports/workbench-v4'
def optional(name):
    p=OUT/name
    return load_json(p) if p.exists() else None
def pct(value):return '待测' if value is None else f'{value:.2%}'
def sec(value):return '待测' if value is None else f'{value/1000:.3f}秒'


def main():
    allcases=[c for split in ['development','validation','final'] for c in load_json(ROOT/'evaluation/grounded-1200'/(split+'.json'))['cases']]+load_json(ROOT/'evaluation/grounded-reserve-v2/final.json')['cases']
    coverage=Counter(c['pn'] for c in allcases)
    write_json(OUT/'dataset-coverage.json',{'semantic_cases':len(allcases),'source_families':len({c['family_id'] for c in allcases}),'query_forms':sum(len(c['questions']) for c in allcases),'case_families_by_pn':dict(coverage),'knowledge_catalog_visible_to_retrieval':True,'warning':'Question/source-label groups are split. The retrieval catalog remains available; this is not a claim that all test document text was unseen by every model.'})
    ragas=optional('ragas-raw.json')
    if ragas:
        arms={}
        for arm in ['before','after']:
            rows=[r for r in ragas['cases'] if r['arm']==arm];m={}
            for key in ['faithfulness','context_recall','context_precision','answer_relevancy']:
                vals=[r['metrics'][key] for r in rows if r['metrics'].get(key) is not None]
                m[key]={'value':sum(vals)/len(vals) if vals else None,'n':len(vals),'planned':12,'failed_or_pending':12-len(vals)}
            m['custom_geometric_mean']=math.prod(v['value'] for v in m.values())**.25 if all(v['n']==12 for v in m.values()) else None
            arms[arm]=m
        write_json(OUT/'ragas-summary.json',{'arms':arms,'input_sha256':load_json(ROOT/'local/workbench-v4/ragas-input.json')['input_sha256'],'scope':'12 fixed requests / 6 source families per arm; English responses; same gateway evaluator; geometric mean is project-defined, not an official Ragas aggregate.'})
    if (OUT/'faithfulness-review.json').exists():shutil.copyfile(OUT/'faithfulness-review.json',ROOT/'web/workbench-faithfulness-review.json')
    live=optional('summary.json');ablation=optional('ablation.json');rscore=load_json(ROOT/'reports/reranker-v3/local-status.json')['best_regression']['metrics']
    if live:
        if not (OUT/'summary-initial-aggregation.json').exists():write_json(OUT/'summary-initial-aggregation.json',live)
        from evaluate_workbench_v4 import summarize
        for arm in ['before','after']:
            rows=[load_json(p) for p in (ROOT/'local/workbench-v4'/arm).glob('*/*.json')]
            if len(rows)!=live['protocol']['scenarios_per_repeat']*3:raise ValueError('Incomplete planned arm')
            live['arms'][arm]={'pooled':summarize(rows),'repeats':[summarize([r for r in rows if r['repeat']==i]) for i in range(1,4)]}
        live['aggregation_note']='Graph/retrieval latency include actual invocations only, not artificial zeros for requests that never invoked them. All planned scenarios remain in task denominator.'
        old_retrieval=optional('title-profile-legacy.json');current_retrieval=optional('current-profile-legacy.json')
        if old_retrieval and current_retrieval:
            before={c['id']:c for c in old_retrieval['cases']};groups={}
            for row in current_retrieval['cases']:
                previous=before[row['id']]
                if row['original_query']!=previous['original_query'] or row['pn']!=previous['pn'] or set(row['gold_ids'])!=set(previous['gold_ids']):raise ValueError('Large retrieval comparison inputs/gold differ')
                delta=int(bool(row['ranked_ids']) and row['ranked_ids'][0] in row['gold_ids'])-int(bool(previous['ranked_ids']) and previous['ranked_ids'][0] in previous['gold_ids'])
                groups.setdefault(row['family_id'],[]).append(delta)
            values=[sum(v)/len(v) for v in groups.values()];rng=random.Random(20261103)
            boot=sorted(sum(rng.choices(values,k=len(values)))/len(values) for _ in range(5000))
            comparison={'before':old_retrieval['metrics'],'after':current_retrieval['metrics'],'cluster_hit_delta_95_interval':[boot[125],boot[4874]],'scope':'same exposed 300 queries /150 source families, supplied PN, unchanged gold; source-only query/rerank caches may be reused; not fresh confirmation'}
            live['large_retrieval']=comparison;write_json(OUT/'retrieval-comparison.json',comparison)
        write_json(OUT/'summary.json',live)
    lines=['# 工作台评测与客服改进交付','','本轮所有改动留在本机。严格 Recall@1 门槛尚未通过，不上传 GitHub。结果来自保存的实际接口记录；未测指标保持待测。','','## 入口','','- 智能客服：http://127.0.0.1:5112/service','- 本体工作台：http://127.0.0.1:5112/ontology/manager#topology','- 评测证据台：http://127.0.0.1:5112/quality','','## 评测集怎么构建','','迁移 Palantir AIP Evals 的对象集案例、手工边界、预期输出、评测器和固定套件版本比较方法；不是在本机运行 Palantir 商业产品。官方流程没有要求必须凑满千题。','', '[Palantir 官方套件方法](https://www.palantir.com/docs/foundry/aip-evals/create-suite)说明可混用对象集与手工边界，并配置 Boolean、数值或 LLM Judge 等评测器。', '',
    '| 数据层 | 数量与用途 |','|---|---|','| 原始邮件 | 63封首封邮件，已见回归，缺少结案标签 |','| Q&A | 875条，872条允许客服召回；3条隐藏 |','| 知识基准 | 750来源案例、1500问题形式；中英文不翻倍算来源 |','| 分组 | 原始开发300/验证150/首次最终150来源，另预留150来源；历史最终题现均为已见回归 |','| 当前全流程 | 60知识问题形式＋5边界＋5业务＋2多轮＝72场景；每版本重复3次 |','| 新措辞确认 | 已知来源300案例、600问题形式，保持未测；不声称新来源盲测 |','',
    '每个案例绑定输入、适用型号、来源位置、gold资料ID、预期业务决策或禁止动作。按来源家族划分；运行时知识库包含可检索文档，不能宣称测试FAQ正文从未被模型见过。标签尚未完成独立业务人工复核。','',
    '知识基准实际覆盖9种PN，分布如下；不据此宣称19种产品都完成质量认证。T8162仅1个案例、T2353仅7个，长尾结论尤其有限。','', '| PN | 来源案例数 |','|---|---:|']
    lines += [f'| {pn} | {n} |' for pn,n in sorted(coverage.items())]
    lines += ['', '## 三类指标与判定', '',
    '- 效果：所有计划案例的任务通过率、模型完成率、首条命中Hit@1、资料集合Recall@K、MRR、五维Judge和Ragas四分项。',
    '- 效率：实际HTTP发送至完整JSON的平均/P50/P99、图遍历耗时、输入/输出token；推理与裁判成本分开。未测TTFT；无核实价格所以金额成本待测。',
    '- 业务：生产解决率、实际转接率、CSAT、重复咨询率缺少结果标签，不能由Judge替代。新增本机自愿反馈采集，按会话最新反馈去重，作为演示反馈单独展示。', '',
    '五维Judge各0—2分：事实与型号、证据支持、步骤与历史、业务条件与边界、中英文清晰度。通过需≥8/10、任务满足、关键维度非零、所有轮次模型完成与硬检查通过；失败和通过都有理由。裁判与客服同为DeepSeek网关标识DeepSeek-V4.1-Flash，独立调用仍有同源偏差。', '',
    'Hit@1判断第一条是否属于任一接受来源；资料集合Recall@1计算第一条覆盖全部gold资料集合的比例，多个标准来源时不同于Hit@1。本轮保留两个口径，不因失分放宽旧标签。', '',
    '## 当前工作台前后实测', '']
    if live:
        lines+=['固定72场景，每版本216次场景执行；重复不增加独立案例数。工作台运行指纹与实际回复绑定，页面检查是否匹配。','', '| 指标 | 改进前 | 改进后 |','|---|---:|---:|']
        a=live['arms']['before']['pooled'];b=live['arms']['after']['pooled']
        metrics=[('机器判定流程通过率',pct(a['task_pass_rate']),pct(b['task_pass_rate'])),('通过/计划场景',f"{a['passed']}/{a['scenarios']}",f"{b['passed']}/{b['scenarios']}"),('模型完成',str(a['model_completed']),str(b['model_completed'])),('HTTP平均',sec(a['http_latency']['mean_ms']),sec(b['http_latency']['mean_ms'])),('HTTP P50',sec(a['http_latency']['p50_ms']),sec(b['http_latency']['p50_ms'])),('HTTP P99',sec(a['http_latency']['p99_ms']),sec(b['http_latency']['p99_ms'])),('图搜索平均(ms)',str(a['graph_latency']['mean_ms']),str(b['graph_latency']['mean_ms'])),('推理总token',str(a['inference_tokens']['total_tokens']),str(b['inference_tokens']['total_tokens'])),('裁判总token',str(a['judge_tokens']['total_tokens']),str(b['judge_tokens']['total_tokens']))]
        lines += [f'| {name} | {x} | {y} |' for name,x,y in metrics]
        if live.get('large_retrieval'):
            r=live['large_retrieval'];lines+=['','同一300题的实际检索配置对比（PN已给定、已见回归、gold不变、缓存可能命中）：','','| 指标 | 旧工作台标题配置 | 当前正文＋证据核验 |','|---|---:|---:|']
            for key in ['hit_at_1','recall_at_1','hit_at_3','hit_at_5','mrr']:lines.append(f"| {key} | {pct(r['before'][key])} | {pct(r['after'][key])} |")
            ci=r['cluster_hit_delta_95_interval'];lines+=['',f'首条命中提升的来源聚类95%区间为{pct(ci[0])}至{pct(ci[1])}。这支持在该回归集上的检索改进，但当前集合Recall@1仍低于90%，不替代独立确认。']
        lines += ['', '三次通过率：'+str({arm:[pct(r['task_pass_rate']) for r in result['repeats']] for arm,result in live['arms'].items()}),'', '以上为已见验证场景与构造边界的流程通过率，不是真实客户问题解决率。HTTP与Ragas/候选评测曾共享网关负载，时延仅作本机混合负载描述，不能解释为算法隔离因果收益或生产SLA。']
        lines+=['','按场景拆分：'+str({arm:result['pooled'].get('pass_by_kind') for arm,result in live['arms'].items()}),'','主要通过率增益来自边界校验修复；不能把它全部归因于知识能力或自主进化。缓存未清空，首轮两种实现历史缓存不同，后两轮属于重复问题热缓存观察。']
        # Version-blind review package: 20 distinct source/scenario families, fixed by hash.
        cases=load_json(ROOT/'reports/grounded-eval/live-sampling.json')['cases'];byfamily={}
        for c in sorted(cases,key=lambda c:(c.get('language')!='zh',c['id'])):byfamily.setdefault(c['family_id'],c)
        rng=random.Random(20261103);pack=[];audit_key=[]
        for family in sorted(byfamily,key=digest)[:20]:
            c=byfamily[family];order=['before','after'];rng.shuffle(order);entries=[]
            for arm in order:
                row=load_json(ROOT/'local/workbench-v4'/arm/'1'/(c['id'].replace(':','-')+'.json'))
                audit_key.append({'id':c['id'],'blind_label':'AB'[len(entries)],'arm':arm})
                entries.append({'label':'AB'[len(entries)],'turns':[{'question':t['question'],'zh':t.get('reply',{}).get('zh'),'en':t.get('reply',{}).get('en'),'citation_ids':t.get('reply',{}).get('citation_ids')} for t in row['turns']]})
            pack.append({'id':c['id'],'family_id':family,'reference':c.get('reference'),'versions':entries,'reviewer':None,'reviewed_at':None,'preferred':None,'reason':None})
        write_json(OUT/'manual-audit.json',{'status':'pending human review','distinct_families':20,'cases':pack})
        write_json(ROOT/'local/workbench-v4/manual-audit-key.json',audit_key)
        with (OUT/'manual-audit.csv').open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.writer(f);writer.writerow(['案例','问题','参考来源','A中文','A英文','B中文','B英文','偏好','审核理由','审核人','审核日期'])
            for c in pack:
                first,second=c['versions'];writer.writerow([c['id'],'\n'.join(t['question'] for t in first['turns']),c.get('reference'),*[ '\n'.join(t[k] or '' for t in v['turns']) for v in [first,second] for k in ['zh','en']],None,None,None,None])
        shutil.copyfile(OUT/'manual-audit.csv',ROOT/'web/workbench-audit.csv')
        verified=optional('independent-verification.json')
        if verified:
            ci=verified['cluster_bootstrap_task_delta_95_interval']
            lines+=['',f"配对复算：{verified['paired_improved']}次执行改善、{verified['paired_regressed']}次退步，按{verified['source_or_scenario_families']}个来源/场景家族聚类后的任务通过率差异95%区间为{pct(ci[0])}至{pct(ci[1])}。区间包含零，不宣称统计显著提升或长期收敛。",'', '实际返回的195个图上下文（每版本）均通过两跳路径结构检查；这证明调用与路径可查，不证明图事实无误或图层单独带来因果收益。']
    else:lines+=['三轮实际接口测试正在运行，完整结果尚未生成，不使用部分成功样本作为最终通过率。']
    rs=optional('ragas-summary.json')
    if rs:
        lines+=['','## Ragas实测','','固定12请求、6来源案例，每版本12个英文答复；双语请求都保留。','', '| 版本 | Faithfulness | Context Recall | Context Precision | Answer Relevancy | 自定义几何平均 |','|---|---:|---:|---:|---:|---:|']
        for arm,m in rs['arms'].items():lines.append('| '+arm+' | '+' | '.join(pct(m[k]['value'])+f" (n={m[k]['n']}/12)" for k in ['faithfulness','context_recall','context_precision','answer_relevancy'])+' | '+pct(m['custom_geometric_mean'])+' |')
        lines+=['','几何平均是本项目自定义汇总，不是Ragas官方综合分；四项全部完成才计算，不隐藏分项或缺测。']
    if ablation:
        write_json(ROOT/'web/workbench-ablation.json',ablation)
        lines+=['','## 消融','','固定18个已见场景，各消融一次，对照改进后第一轮同样场景。','','| 处理 | 通过/场景 | 通过率 |','|---|---:|---:|']
        for name in ['full','no_skill','no_ontology']:
            m=ablation[name];lines.append(f"| {name} | {m['passed']}/{m['scenarios']} | {pct(m['task_pass_rate'])} |")
        lines+=['','no_skill在隔离副本中同时清空Skill文字并关闭状态继承；仅切换原有no_skill标记并不等于去掉所有Skill Prompt。no_ontology移除范围/图上下文/本体工具的组合能力，并非单独BFS因果消融。小样本不能证明本体或Skill普遍有效。']
        lines+=['','本轮去Skill的两项失败均为多轮流程决策：内容Judge仍给10分并认为答复满足，但预期应建议人工核查，实际返回普通answer，因此程序门控不通过。去本体在这18题没有降低通过率，本体的问答质量增益在该小样本未得到证明。']
    lines+=['','## 改了什么，如何构成改进闭环','','| 层 | 本轮实际变化 |','|---|---|','| 工作台接线 | 默认客服由旧customer_agent切到已测agent实现；真实页面与评测目标对齐 |','| 检索 | 默认采用此前的中文保真改写＋E5标题/正文/BM25加权＋保守证据核验；新FAQ问题匹配候选验证不佳被拒绝 |','| Prompt和校验 | 沿用已测Skill、未知型号澄清与一次结构修复重试；并非每次回答另训练模型 |','| 页面 | 新增运行版本、图路径/约束、最新候选记录、三次重复结果、五维理由和自愿反馈 |','| 模型参数 | 本轮未执行RLHF、未训练DeepSeek权重。此前小型重排训练失败记录保留 |','','当前图搜索为型号范围内两跳BFS，最多30概念/6证据，从检索知识节点出发，产品中心不继续扩散。返回路径、映射、约束给模型；不是社区检索，也不是通用OWL逻辑推理。售后条件判断仍由代码规则校验。','','失败轨迹→检索/规则/Skill/来源归因→局部候选→开发验证→配对回归→独立确认→采纳或拒绝。当前属于工程协助的受控改进，不声称主模型、Schema或改进器已能全面自主递归修改。','','## 当前门槛与下一处本体缺口','',f"同一300题已见回归中的最佳本地候选Hit@1={pct(rscore['hit_at_1'])}，集合Recall@1={pct(rscore['recall_at_1'])}；均未满足上传验收。新候选验证Hit@1=91.00%，集合Recall@1=87.78%，未采纳。没有用验证高分替代确认成绩。",'','[官方水痕说明](https://service.eufy.com/article-description/What-should-I-do-if-there-are-water-stains-on-the-floor-after-my-S1-Pro-finishes-mopping)区分条状水痕与残留水分，应补“症状—条件—动作”关系并让Skill先追问。[官方序列号说明](https://service.eufy.com/article-description/How-to-Find-Your-Product-s-Serial-Number-SN-and-Product-Number-PN)给出T2080尘盒下方这一特例。已记录内容/Skill提案，尚未激活或完成独立验证；原始Excel和旧gold未回写。','','优先级为正确性＞速度＞成本。增加检测通常增加耗时。改进曲线不平稳、区间包含零、或回归增加时应拒绝候选，不能为了达到90%删题、换口径或虚构结案。']
    lines+=['','## 为什么98.15%仍不能当作真实正确率','','该数值是按既定规则计算的机器裁判流程通过率，尚未经过独立人工校准。T2071多楼层案例原表第123行只有外部参考链接；同一来源6次执行被判2次通过、4次未通过，一条通过回复补充了当前可见正文未支持的操作。原分保留，同时标为来源正文不足、工具访问缺口与裁判一致性待复核。不能用强迫生成步骤的Prompt补齐证据。','','若仅将这一家族全部视为未确认，敏感性计算为210/216＝97.22%；这不是完整人工纠偏，也不是真实解决率。其他未审案例仍可能有误判。人工20组抽检与6组忠实度争议保持待复核。']
    (ROOT/'docs/工作台评测与客服改进交付.md').write_text('\n'.join(lines)+'\n')
    print({'live_complete':bool(live),'ragas_rows':len(ragas['cases']) if ragas else 0,'ablation_complete':bool(ablation)})


if __name__=='__main__':main()
