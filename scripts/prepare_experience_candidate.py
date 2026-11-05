"""Small, source-grounded fixes based on observed v1 failure patterns."""
import sys,shutil,sqlite3,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from ontocare.data import load_json,write_json,digest
BASE=ROOT/'local/customer-service-v2/experience548';src=BASE/'v1';dst=BASE/'v2'
assert not dst.exists(),'Do not overwrite a frozen candidate'
dst.mkdir()
for name in ['ontocare','prompts','data','ontology']:shutil.copytree(src/name,dst/name,ignore=shutil.ignore_patterns('__pycache__'))
for name in ['web','actions','skills','evaluation','reports']:(dst/name).symlink_to(ROOT/name,target_is_directory=True)
(dst/'local').mkdir()
for p in (src/'local').iterdir():
 if p.is_file() and p.suffix=='.sqlite':
  with sqlite3.connect(p) as source,sqlite3.connect(dst/'local'/p.name) as target:source.backup(target)
 elif p.is_file() and not p.name.endswith(('-wal','-shm')):(dst/'local'/p.name).symlink_to(p.resolve())
(dst/'local/customer-service-v2').symlink_to(ROOT/'local/customer-service-v2',target_is_directory=True)
p=dst/'ontocare/agent.py';s=p.read_text();old="dealer_only = skill == 'aftersales' and bool(re.search(r'dealer|seller|经销商|销售方|卖家|购买渠道|授权', text, re.I))";new="dealer_only = skill == 'aftersales' and bool(business_context.get('dealer_check') or re.search(r'dealer|seller|经销商|销售方|卖家|购买渠道|授权', text, re.I))";assert old in s;s=s.replace(old,new);p.write_text(s)
p=dst/'prompts/customer-experience.md';s=p.read_text()+'''

## Evidence-first correction · v2
For a factual FAQ or app setting question, answer exactly what was asked and stop after necessary conditions. A short factual answer is complete when the requested fact and its limitations are covered; do not attach general maintenance, prevention, extra diagnostics, warranties or a closing follow-up unless necessary for this task.
Use the source whose question/body most directly answers the request. Do not blend adjacent FAQs into a larger answer. Supplementary official article bodies may support a requested missing detail only when their product scope and conditions are explicit; merely being linked or nearby is not enough. Never add an instruction solely because it appears somewhere in a broad article. If the requested steps are absent, state that precise evidence gap.
For diagnostic instructions preserve the exact test setup, order, conditions and conditional outcomes. A noise disappearing after removing a component does not prove which component is faulty unless the source explicitly states that inference. A source-listed possibility is not a confirmed diagnosis. Do not present an unverified cause or an electrical/mechanical intervention as established.
For a known component, acknowledge it rather than asking which component again. Use 泵主机 (pump hub) consistently. Answer only the latest turn after a product switch. Reuse the resolved state and keep genuinely conflicting product/part identifiers pending clarification.
Before finalizing, remove every sentence that adds an unrequested fact, unsupported benefit, likely cause, prevention claim or speculative step. Keep all requested source-supported facts and caveats. Never change binding workflow restrictions to satisfy a user request.
''';p.write_text(s)
p=dst/'prompts/skills/customer-experience/SKILL.md';s=p.read_text()+'''

## v2：按证据缺口选择处理
- 事实问答：先给直接结论，完整保留被问到的数字、条件和例外；没有诊断需求时不追加维修流程。
- 排障：只保留直接匹配问题的原文步骤，不把官方长文里其他型号或其他症状的步骤拼进来；噪音对比等测试的条件、先后和结论按原文表达。
- 已有销售方核验结果应进入购买凭证/适用政策核查路径，不能退回无关的型号识别；此项由代码执行，不让模型绕过代码限制。
- 官方正文存在不等于任何补充建议都适用；引用必须与问题、型号和证据条件同时匹配。
- 型号或配件冲突保留澄清，不通过弱化作用域规则改善测试分数。
''';p.write_text(s)
p=dst/'ontocare/prompting.py';s=p.read_text().replace('"customer-experience-v1" if customer_experience','"customer-experience-v2" if customer_experience');p.write_text(s)
analysis=ROOT/'reports/customer-service-v2/experience548-analysis.json';observed=load_json(analysis) if analysis.exists() else {}
write_json(BASE/'candidate-changes.json',{'name':'experience-v2','observed_baseline_cases_at_freeze':len(list((ROOT/'local/customer-service-v2/answers/experience-v1-stream548').glob('*-r0.json'))),'observed_failure_ids':[r['id'] for r in observed.get('bad_cases',{}).get('experience-v1-stream548',[])],'changes':['Prompt/Skill: factual focus and remove unrequested article extras','Prompt/Skill: preserve conditional diagnostic steps and conclusions','Prompt/Skill: latest turn and known component wording','Code: verified dealer context participates in purchase-evidence routing'],'unchanged':['knowledge sources','ontology links and product scope','retrieval/reranking algorithm','gold labels','primary judge/rubric'],'files':{str(p.relative_to(dst)):digest(p.read_bytes()) for p in [dst/'ontocare/agent.py',dst/'ontocare/prompting.py',dst/'prompts/customer-experience.md',dst/'prompts/skills/customer-experience/SKILL.md']}})
print('FROZEN V2 CANDIDATE',flush=True)
