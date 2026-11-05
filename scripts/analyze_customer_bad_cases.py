"""Attribute recorded failures without changing frozen labels or held-out answers."""
from collections import Counter
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ontocare.data import load_json,write_json
from ontocare.service_eval_dashboard import task_verdict
LOCAL=ROOT/'local/customer-service-v2';OUT=ROOT/'reports/customer-service-v2'


def analyze():
    flags={r['id']:r for r in load_json(OUT/'reference-quality-flags.json')['cases']}
    failures=[];degraded=[]
    for p in sorted((LOCAL/'answers/candidate-final').glob('*.json')):
        a=load_json(p);jp=LOCAL/'judges/candidate-final'/p.name
        j=load_json(jp) if jp.exists() else {};c=a['case'];r=a['turns'][-1].get('reply',{})
        verdict=task_verdict(c,a,j)
        status=r.get('model_status','http_error')
        if verdict is not False and status=='completed':continue
        ids=[k for t in r.get('tools',[]) if t['name']=='search_evidence' for k in t['result'].get('ids',[])]
        gold=c.get('gold_ids',[]);cause='generation';proposal='逐条核对回答与原文，保留例外条件；在新的开发集验证更具体的答复约束。'
        if not r:cause='infrastructure';proposal='检查服务/网关错误和超时；不把基础设施错误作为知识训练材料。'
        elif c['id'] in flags:cause='reference_scope_conflict';proposal='人工核实原文适用PN与题干型号；当前保留原分数，修复标签时发布新题集并重新建立基线。'
        elif c.get('expected_decision') and r.get('decision')!=c['expected_decision']:cause='workflow';proposal='核对意图、所需条件和期望状态；不要仅增加相似问答来掩盖流程错误。'
        elif j.get('policy_safe') is False:cause='policy';proposal='人工复核越权/不支持的承诺；检查Action授权与答复校验。'
        elif j.get('history_ok') is False:cause='history';proposal='核查会话中的型号切换、已做步骤和用户报告/工具验证的区分。'
        elif gold and not set(gold)&set(ids):cause='retrieval';proposal='检查适用范围与召回；如使用本留出失败题改进，必须建立新的留出来源组。'
        elif status=='cross_product_answer':cause='generation_scope_guard';proposal='检查共享资料中的其他型号是否被误抄入答复；保留型号校验，优先修正表述。'
        elif status=='unsafe_business_claim':cause='promise_guard';proposal='区分真实执行承诺与被否定的承诺；保持安全保底，并以正反例验证校验器。'
        elif status=='invalid_citations':cause='citation_contract';proposal='检查缺失或无效引用；不放宽引用验证来提高生成成功率。'
        entry={'id':a['id'],'repeat':a['repeat'],'split':a['split'],'kind':a['kind'],'question':c['question'],'strict_task_pass':verdict,'model_status':status,'judge_category':j.get('bad_case_category'),'judge_reason':j.get('reason'),'derived_root_cause':cause,'grounding':{'retrieved_ids':ids,'gold_ids':gold,'gold_in_retrieved':bool(set(gold)&set(ids)) if gold else None},'proposal_not_applied':proposal,'policy':'No edit to source, frozen gold or historical score; proposal requires a separate candidate and new holdout if current holdout is used for tuning'}
        if verdict is False:failures.append(entry)
        if status!='completed':degraded.append(entry)
    result={'task_failure_attempts':len(failures),'task_failure_unique_cases':len({r['id'] for r in failures}),'degraded_attempts':len(degraded),'failure_causes':dict(Counter(r['derived_root_cause'] for r in failures)),'failures':failures,'degraded':degraded,'reference_quality_flags':len(flags),'score_policy':'Raw judge decisions and strict scores preserved; this is evidence-led attribution, not relabelling or new model training'}
    write_json(OUT/'bad-case-attribution.json',result)
    lines=['# Bad Case 归因与后续回归队列','',f"有标签任务失败{len(failures)}次、涉及{result['task_failure_unique_cases']}题；模型输出保底/调用降级{len(degraded)}次。两者分别统计。",'','| 根因 | 失败次数 |','|---|---|']
    lines.extend(f'| {k} | {v} |' for k,v in result['failure_causes'].items())
    lines+=['','本文件的建议尚未应用到冻结版本。保留当前留出集的评测效力，不在看过留出失败题后继续调它的分数。','', '| 题目 | 划分 | 根因 | 下一步 |','|---|---|---|']
    seen=set()
    for r in failures:
        if r['id'] in seen:continue
        seen.add(r['id']);lines.append(f"| {r['id']} | {r['split']} | {r['derived_root_cause']} | {r['proposal_not_applied']} |")
    (OUT/'BadCase归因.md').write_text('\n'.join(lines)+'\n');print({k:result[k] for k in ['task_failure_attempts','task_failure_unique_cases','degraded_attempts','failure_causes']})
if __name__=='__main__':analyze()
