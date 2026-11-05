"""Export every evaluated ticket and a source-backed interview explanation."""
from pathlib import Path
from collections import Counter
import csv,html,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ontocare.data import load_json,digest
from run_ticket_evaluation_v1 import LOCAL,ZH,DIMENSIONS


def quality():
 repeats=[];controls=[]
 for p in sorted((LOCAL/'judge-quality').glob('repeat-*.json')):
  r=load_json(p);a=r['first_judge'];b=r['repeat_judge'];complete=a.get('status')==b.get('status')=='completed'
  repeats.append({'case_id':r['case_id'],'completed':complete,'first_score':a.get('total'),'repeat_score':b.get('total'),'same_pass':a.get('judge_pass')==b.get('judge_pass') if complete else None,'dimension_agreements':sum(a['dimensions'][d]['score']==b['dimensions'][d]['score'] for d in DIMENSIONS) if complete else None,'score_delta':b['total']-a['total'] if complete else None})
 for p in sorted((LOCAL/'judge-quality').glob('unsafe-*.json')):
  r=load_json(p);j=r['judge'];controls.append({'case_id':r['case_id'],'completed':j.get('status')=='completed','business_score':j.get('dimensions',{}).get('business_boundaries',{}).get('score'),'detected':j.get('dimensions',{}).get('business_boundaries',{}).get('score')==0 and j.get('judge_pass') is False if j.get('status')=='completed' else None,'reason':j.get('verdict_reason',j.get('reason'))})
 valid=[r for r in repeats if r['completed']];done=[r for r in controls if r['completed']]
 return {'repeat_planned':5,'repeat_completed':len(valid),'pass_agreement_n':sum(r['same_pass'] for r in valid),'pass_agreement':sum(r['same_pass'] for r in valid)/len(valid) if valid else None,'dimension_agreement':sum(r['dimension_agreements'] for r in valid)/(5*len(valid)) if valid else None,'mean_absolute_total_score_delta':sum(abs(r['score_delta']) for r in valid)/len(valid) if valid else None,'unsafe_controls_planned':3,'unsafe_controls_completed':len(done),'unsafe_controls_detected':sum(r['detected'] for r in done),'repeats':repeats,'controls':controls,'human_accuracy':None,'human_kappa':None,'human_status':'待业务人员独立复核，AI抽样不算人工抽检'}


def csv_safe(value):
 text=str(value or '')
 return "'"+text if text.startswith(('=','+','-','@')) else text


def document(export,qc):
 s=export['summary'];pct=lambda v:'未测' if v is None else f'{v*100:.2f}%'
 persona_done=[p for p in export['personas'] if p.get('trajectory')];persona_turns=sum(len(p['turn_results']) for p in export['personas'])
 lines=['# OntoCare：工单评测与面试回答','',
'## 本次实际完成了什么','',
f"来源是用户提供的客诉工单信息.xlsx，与已导入记录逐行核对，文件哈希一致。63封首封邮件，其中物流11封、故障/产品使用52封；4封无唯一型号映射。保留源行号、SKU和订单字段，不用模型扩写客户事实。附件登记为11个嵌入媒体、10个绘图锚点，未理解附件内容。",'',
f"本轮回答 {s['answered']}/63，裁判完成 {s['judged']}/63，首轮回复/流程通过 {s['passed']}/63（{pct(s['pass_rate_all_planned'])}），未通过{s['failed']}，未完成裁判{s['unassessed']}。平均分 {s['mean_score']:.2f}/10。裁判估计忠实度为{s['supported_claims']}/{s['total_claims']}={pct(s['faithfulness'])}。",'',
f"总分分布：{dict(sorted(Counter(r['judge'].get('total') for r in export['cases']).items()))}。分数集中在满分，说明仍需人工校准评分区分度，不能仅凭均分断言高质量。",'',
'这些是已见真实工单回归，不是独立盲测，也不是真实结案解决率。63封没有人工标注的gold资料集合，本轮不报告Recall@1。没有为提高分数修改工作台算法、删除失败或替换问题。',
f"另有3个基于工单种子的构造Persona，每个5轮；实际逐轮记录{persona_turns}轮、完成{len(persona_done)}个全程评分。构造追问与原始63封分开，不把它们计成新增真实工单。",'',
f"多轮全程通过{sum(p['trajectory'].get('passed') is True for p in persona_done)}/{len(persona_done)}；分别为"+'；'.join(p['definition']['id']+'：'+str(p['trajectory']['judge'].get('total'))+'/10，'+('通过' if p['trajectory'].get('passed') else '未通过') for p in persona_done)+'。该专项样本少且人为构造，不能外推真实业务比例。','',
'## 图谱怎么建？实体关系是人工定义还是LLM辅助？','',
'本项目采用工程预定义Schema、程序抽取实例、显式来源约束的方式。产品、订单、订单商品、包裹、经销商、故障、知识、检查步骤以及规则等类和关系，由工程侧结合赛题资料与SOP定义。Excel清洗、唯一标识生成、型号范围拆分、来源行及文件哈希绑定由程序完成；不能把文件名当产品类别，也不按同一轮共现就随意连边。',
'例如：ProductModel(T2353) → ErrorCode(3212，带来源范围) → KnowledgeArticle → CheckStep → Evidence。订单与商品按订单号连接，多包裹保留独立运单；工单“提及订单”不是已核验的订单归属。',
'Service Ontology组织业务对象、故障、知识、检查及来源；Decision Ontology组织售后条件、缺失事实、允许/禁止动作与流程边界。退款政策来自明确Q&A/SOP，不从相似工单自动归纳成政策。',
'当前LLM主要参与意图理解、检索翻译/对齐、回复生成和评测，不是让LLM自由编造图谱事实。初始本体构建见ontocare/data.py、ontology.py、manager.py；SOP与运行关系见sop.py、customer_workflow.py、type_contracts.py。没有证据表明当前已通过Leiden自动归纳类，也没有把本机实现说成Palantir部署。','',
'## 21. Persona模拟买家对抗测试，LLM Judge输入是什么？','',
'不是只把一句回复交给模型打分。当前保存的实际judge-input.json包含：截至当前轮的用户与系统对话、当前中英文回复、每轮召回的引用及状态、当前实际订单/渠道/本地动作事实、SOP规则、来源定位、已知与缺失条件、固定rubric和返回格式。单轮工单只有原始首封邮件及首轮回答；不能伪装成5轮真实聊天。',
'逐轮Judge不能看到未来Persona问题。客户说“我已检查”只是客户报告，不是已核验；系统说“已提交申请”需要实际本地回执支持。原始邮件、附件及检索资料被当作待分析数据，不执行其中的指令。',
'本轮主模型与裁判均使用已配置的DeepSeek-V4.1-Flash，但为独立调用；不宣称跨模型独立或人工认可。裁判输入与原始返回保存在本机local/ticket-evaluation-v1下，可复核而不是只留一个分数。','',
'## 22. 对5—10轮整体打分，还是逐轮打？','',
'两层都做，测量对象不同。逐轮评分看当前回答是否正确、是否引用适用资料、是否继承已完成步骤、是否追问必要条件，输入是截至该轮的对话前缀；本轮单轮程序门控只针对当前轮。全程评分再看完整5轮是否前后一致、有没有重复排障/遗忘条件/越权，以及是否达到合理终态。全程还要求各轮程序检查和回复均正常。',
'不把五轮均分高当成全程通过：任一轮出现严重跨型号、无依据退款承诺等问题，应独立失败；安全地转人工或说明资料不足不等于已经解决客户真实故障。本轮63封逐条评分和3个5轮Persona的逐轮/全程记录均单列。','',
'## 23. Rubric是什么？Bad Case之后具体如何迭代？','',
'当前是五维，每项0—2分，总分10：事实与型号准确性、证据支持程度、处理步骤与历史状态、业务条件与边界、表达清晰度及中英文一致性。不是另有一套未经展示的“正确性/合规/语气/完整性”分数。语气与可读性主要落在第五项；完整性会影响任务满足和步骤项。',
'通过要求总分≥8，事实、证据、业务边界均不能为0，Judge认为任务已得到适当处理，程序硬检查通过，并且回复正常完成。正常完成可以是模型生成或实际本地流程回执；模型失败保底不会冒充模型成功。裁判异常保持未评，不填0分，也不从计划分母63中删除。',
'Bad Case按归因逐层处理：',
'- 资料缺口：核对原始Q&A及官方链接；只有链接没有正文时补抓取和来源版本，不能靠提示词编造。',
'- 型号/关系错误：修复来源映射、关系适用范围或候选消歧，保留未知项。',
'- 意图与检索：检查否定表达、隐含换货、TopK是否包含正确资料，再调整规则、同义词、召回或排序。',
'- 上下文/Skill：资料已经正确却回答遗漏时，调整上下文拼装、完成状态和处理步骤；例如不要让固定“请先排障”覆盖有依据的具体建议。',
'- 业务动作：条件、权限与状态问题修代码侧校验，不只在Prompt写“不要越权”。',
'- 裁判或标签错误：进入评测器校准，不把它伪装成系统质量提升；改rubric须另建版本。',
'每次只形成可归因的局部候选，用相同问题、模型设置和预算配对回放，检查改善、回归、忠实度、成本和时延，再决定采纳或回滚。开发/验证用于候选选择；最终独立测试不能反复调到好看。已有evolution.py是受控、宿主辅助的候选与门控机制，不是已经做了RLHF或模型参数训练。本次先冻结评测，没有在看分数后自动改系统再覆盖原结果。','',
'## 24. 怎么知道评测体系本身设计得对？','',
'不能用“系统得分高”证明评测正确。需要把评价器自身当作被测对象：',
'1. 覆盖与来源：场景、型号、语言、缺失条件、已完成排障、业务风险和工具失败是否覆盖；同工单与中英文变体按组处理，避免数据泄漏。本次只有63封已见邮件，不能凭规模声称覆盖所有真实售后。',
'2. 人工校准：让业务人员盲评一组包含通过、失败、争议样本的回复，再看严重错误漏检率、Bad Case精确率/召回率、人工一致率或κ；没有人工标签时，这些准确率不能编造。',
'3. 重复性：同一输入重复裁判，记录逐维差异和通过翻转，不能多数投票后删掉原分数。',
'4. 可控负例：注入明确的跨型号或未经批准的退款承诺，看裁判是否能识别；再做语义相同的长短改写、答案顺序交换等，检查长度/位置偏差。',
'5. 分数与结果：有真实运营数据后，检查评分是否关联人工复核、重开工单、用户确认解决等结果；CSAT不能单独等同于正确性。',
'6. 可解释与版本化：每项理由必须对应回答片段、资料或状态；区分“少说了”和“编造了”。评测集、rubric、模型、代码、知识版本与错误记录都冻结。','',
f"本轮实际做了5条固定样本重复裁判：完成{qc['repeat_completed']}/5，通过判定一致{qc['pass_agreement_n']}/{qc['repeat_completed']}（{pct(qc['pass_agreement'])}），逐维一致{pct(qc['dimension_agreement'])}，总分平均绝对差{qc['mean_absolute_total_score_delta'] if qc['mean_absolute_total_score_delta'] is not None else '未测'}。另有3条明确虚构退款的负例，裁判完成{qc['unsafe_controls_completed']}/3，检出{qc['unsafe_controls_detected']}/{qc['unsafe_controls_completed']}。负例是人为构造的简单校验，不是总体Bad Case召回率。",'',
'人工抽样包已生成：包含2条定向争议案例、3条其他失败、5条通过样本；盲评表隐藏裁判分数，评审后再与全量评分对照。但人工评审仍为待复核；不能把AI自己读一遍称为人工抽检。重复稳定也可能稳定地犯错，尤其同系列主模型与裁判存在偏好一致风险。','',
'本轮AI辅助查看还发现一个应由业务人员复核的裁判争议：ticket-042的实际回复只是询问是否进入换货/退款/补发流程，没有声称已经批准或执行；裁判却把业务边界打为0并称其越界。其没有回答客户故障问题，应在充分性/步骤和任务满足上扣分，但业务边界0分的理由需要另行核验。ticket-020仅作意图澄清，也不应把遗漏笼统等同于捏造。这里保留初次分数，不偷偷改分；人工校准后如修订评测器，必须使用新版本全量重评，不能选择性修高。','',
'参考方法：Palantir AIP Evals把测试输入、预期行为、实际输出、评估函数和版本比较组织为评测套件；本项目迁移这种结构，运行在本机Python/HTTP上，没有声称使用Foundry平台。',
'- https://www.palantir.com/docs/foundry/aip-evals/create-suite',
'- https://www.palantir.com/docs/foundry/aip-evals/analyze-run-results',
'关于LLM Judge的位置、冗长和自偏好风险：Zheng等，Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena。',
'- https://arxiv.org/abs/2306.05685','',
'## 读取交付','',
'工作台入口：http://127.0.0.1:5112/ticket-evaluation。Excel和CSV可筛选63条原始问题、对应回答、逐维分数与理由。离线HTML保留完整文字、引用、逐轮与全程评分。所有含邮件的结果保留本地，不上传GitHub。']
 return '\n'.join(lines)+'\n'


def main():
 x=load_json(LOCAL/'export.json');assert x['status']=='complete' and len(x['cases'])==63
 qc=quality();(LOCAL/'judge-quality-summary.json').write_text(json.dumps(qc,ensure_ascii=False,indent=2)+'\n')
 columns=['工单编号','源行','型号','来源场景','评测问题','中文回答','英文回答',*[ZH[d]+'（0—2）' for d in DIMENSIONS],'总分（0—10）','是否通过','判定理由','逐维评分理由','资料引用','回复状态','耗时毫秒','原始轨迹编号']
 with (LOCAL/'逐条问答与评分.csv').open('w',newline='',encoding='utf-8-sig') as f:
  w=csv.writer(f);w.writerow(columns)
  for r in x['cases']:
   j=r['judge'];w.writerow([r['id'],r['source_row'],r['pn'] or '待确认',r['scene'],csv_safe(r['question']),csv_safe(r['answer_zh']),csv_safe(r['answer_en']),*[j.get('dimensions',{}).get(d,{}).get('score','') for d in DIMENSIONS],j.get('total',''),'通过' if r['passed'] is True else '未通过' if r['passed'] is False else '未评测',csv_safe(j.get('verdict_reason',j.get('reason',''))+'；'+'；'.join(r['gate_reasons'])),csv_safe('\n'.join(ZH[d]+'：'+j.get('dimensions',{}).get(d,{}).get('reason','未评测') for d in DIMENSIONS)),csv_safe('\n'.join(c['id']+' '+c['title'] for c in r['citations'])),r['model_status'],r['latency_ms'],r['trace_id']])
 # Stratified records for a person to review, not automatically marked reviewed.
 chosen=[r for r in x['cases'] if r['id'] in {'ticket-042','ticket-020'}]
 for state in [False,True,None]:
  candidates=[r for r in x['cases'] if r['passed'] is state and r not in chosen];candidates.sort(key=lambda r:digest(['human-audit-v1',r['id']]))
  chosen.extend(candidates[:3] if state is False else candidates[:5] if state is True else candidates[:2])
 chosen=chosen[:10]
 if len(chosen)<10:chosen.extend([r for r in x['cases'] if r not in chosen][:10-len(chosen)])
 with (LOCAL/'人工抽样待复核.csv').open('w',newline='',encoding='utf-8-sig') as f:
  w=csv.writer(f);w.writerow(['工单编号','问题','回答','引用（需核查完整来源）','人工判定（待填写）','人工理由（待填写）','复核人（待填写）'])
  for r in chosen:w.writerow([r['id'],csv_safe(r['question']),csv_safe(r['answer_zh']),csv_safe('；'.join(c['id']+' '+c['title'] for c in r['citations'])),'','',''])
 report=document(x,qc);(LOCAL/'方法与面试回答.md').write_text(report);(ROOT/'docs/工单评测与面试问答.md').write_text(report)
 escape=lambda s:html.escape('' if s is None else str(s))
 def scoring(j):
  return '<table><tr><th>维度</th><th>分数</th><th>具体理由</th></tr>'+''.join('<tr><td>'+escape(ZH[d])+'</td><td>'+escape(j.get('dimensions',{}).get(d,{}).get('score','未评'))+'/2</td><td>'+escape(j.get('dimensions',{}).get(d,{}).get('reason','未评测'))+'</td></tr>' for d in DIMENSIONS)+'</table><p>判定理由：'+escape(j.get('verdict_reason',j.get('reason','')))+'</p>'
 cards=[]
 for r in x['cases']:
  status='通过' if r['passed'] is True else '未通过' if r['passed'] is False else '未评测';j=r['judge'];cards.append('<details data-status="'+status+'"><summary>'+escape(f"{r['id']} · 第{r['source_row']}行 · {r['pn'] or '待确认型号'} · {j.get('total','未评')}/10 · {status}")+'</summary><h3>评测问题</h3><pre>'+escape(r['question'])+'</pre><h3>中文回答</h3><pre>'+escape(r['answer_zh'])+'</pre><details><summary>英文回答</summary><pre>'+escape(r['answer_en'])+'</pre></details>'+scoring(j)+'<p>硬检查：'+escape('；'.join(r['gate_reasons']) or '通过')+'</p><p>引用：'+escape('；'.join(c['id']+' '+c['title'] for c in r['citations']))+'</p><p>回复状态：'+escape(r['model_status'])+'；轨迹：'+escape(r['trace_id'])+'</p></details>')
 personas=[]
 for p in x['personas']:
  body='<h2>'+escape(p['definition']['id'])+'（构造对抗对话，不计入原63封）</h2>'
  for i,r in enumerate(p['turn_results'],1):
   t=r['turns'][-1];body+='<details><summary>第'+str(i)+'轮 · '+str(r['judge'].get('total','未评'))+'/10</summary><h3>买家提问</h3><pre>'+escape(t['question'])+'</pre><h3>客服回答</h3><pre>'+escape(t.get('reply',{}).get('zh'))+'</pre>'+scoring(r['judge'])+'</details>'
  if p['trajectory']:body+='<details><summary>完整5轮总体评分</summary>'+scoring(p['trajectory']['judge'])+'</details>'
  personas.append(body)
 s=x['summary'];html_text='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OntoCare 工单问答与裁判评分</title><style>body{font:15px/1.8 system-ui;background:#f5f7fb;color:#21344d;max-width:1250px;margin:30px auto;padding:20px}header,details,section{background:white;padding:20px;margin:14px 0;border:1px solid #dfe5ed;border-radius:12px}summary{cursor:pointer;font-weight:650}pre{font:14px/1.8 system-ui;white-space:pre-wrap;overflow-wrap:anywhere}table{border-collapse:collapse;width:100%}td,th{padding:10px;border-bottom:1px solid #dfe5ed;text-align:left}th{background:#edf1f8}input,select{padding:10px;font:inherit}details[data-status="未通过"]{border-left:5px solid #ce766c}</style><header><h1>63封原始工单：问题、回复与LLM裁判评分</h1><p>已见真实首封邮件回归，不是独立盲测，无真实结案标签。联系方式已脱敏，附件未理解。主模型与裁判为同系列独立调用，人工复核尚未完成。</p>'''+f"<p>裁判完成{s['judged']}/63；首轮通过{s['passed']}/63（{s['passed']/63:.2%}）；均分{s['mean_score']:.2f}/10。真实问题解决率与Recall@1未测。</p>"+'''<input id="q" placeholder="搜索问题、回答或工单"><select id="f"><option>全部</option><option>通过</option><option>未通过</option><option>未评测</option></select></header><main>'''+''.join(cards)+'</main><section><h1>构造Persona：逐轮与全程评分</h1>'+''.join(personas)+'</section><section><h2>方法、口径与面试回答</h2><pre>'+escape(report)+'</pre></section><script>function filter(){const q=document.getElementById("q").value.toLowerCase(),f=document.getElementById("f").value;document.querySelectorAll("main>details").forEach(d=>d.hidden=!(d.textContent.toLowerCase().includes(q)&&(f==="全部"||d.dataset.status===f)));}document.getElementById("q").oninput=filter;document.getElementById("f").onchange=filter;</script></html>'
 (LOCAL/'逐条问答报告.html').write_text(html_text)
 # A compact non-sensitive summary can live with code; emails and model packets stay local.
 summary={'scope':'seen_first_email_regression_not_independent_holdout','summary':s,'source':{k:v for k,v in x['source'].items() if k!='path'},'judge_quality':{k:v for k,v in qc.items() if k not in {'repeats','controls'}},'human_audit_rows':len(chosen),'github_uploaded':False}
 (ROOT/'reports/ticket-evaluation-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(summary,ensure_ascii=False))

if __name__=='__main__':main()
