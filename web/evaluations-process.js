/* Matched comparisons of recorded evaluations. No model calls or changes to scores. */
(()=>{'use strict';
const make=(tag,text)=>{const e=document.createElement(tag);e.textContent=text;return e;},percent=v=>v==null?'未测':(100*v).toFixed(2)+'%';
window.renderEvaluationProcess=state=>{
 const body=document.getElementById('matched-comparison');body.replaceChildren();
 const metric=(label,split)=>state.retrieval.find(r=>r.label===label)?.metrics?.[split];
 const add=(name,before,after)=>{const row=document.createElement('tr');for(const value of [name,percent(before),percent(after),before==null||after==null?'无可比基线':(100*(after-before)>=0?'+':'')+(100*(after-before)).toFixed(2)+' 个百分点'])row.append(make('td',value));body.append(row);};
 const parent=metric('parent','development'),pv=metric('parent','validation'),ph=metric('parent-holdout','holdout'),cd=metric('candidate-title-focused','development'),cv=metric('candidate-title-focused','validation'),ch=metric('candidate-title-focused-holdout','holdout');
 const overall=rows=>rows.every(r=>r?.n)?rows.reduce((a,r)=>a+r.n*r.recall_at_1,0)/rows.reduce((a,r)=>a+r.n,0):null;
 add('知识首条命中 · 同480题诊断汇总',overall([parent,pv,ph]),overall([cd,cv,ch]));
 add('知识首条命中 · 同96题验证集',pv?.recall_at_1,cv?.recall_at_1);
 add('知识首条命中 · 同96题留出集',ph?.recall_at_1,ch?.recall_at_1);
 const pair=state.paired_answer_comparison,p=pair?.runs['parent-pilot'],c=pair?.runs['candidate-final'];
 add('任务通过 · 同'+(pair?.n||0)+'题开发调试',p?.task_pass.value,c?.task_pass.value);
 add('声明级忠实度 · 同'+(pair?.n||0)+'题开发调试',p?.faithfulness.value,c?.faithfulness.value);
 const rb=state.ragas.find(r=>r.label==='parent-pilot'),ra=state.ragas.find(r=>r.label==='candidate-final');
 for(const [key,name] of [['faithfulness','RAGAS忠实度'],['context_precision','RAGAS上下文精度'],['context_recall','RAGAS上下文召回']])add(name+' · 同12题抽样',rb?.metrics?.[key]?.value,ra?.metrics?.[key]?.value);
 const total=state.runs.find(r=>r.label==='candidate-final'),first=total?.first_attempt||total;
 if(!window.full548Status?.runs?.['parent-full548']?.judged || window.full548Status.runs['parent-full548'].judged<548)document.getElementById('comparison-boundary').textContent='同40题任务通过：'+(p?.task_pass.passed??'—')+'/'+(p?.task_pass.n??'—')+' → '+(c?.task_pass.passed??'—')+'/'+(c?.task_pass.n??'—')+'。新版全量：'+(first?.task_pass.passed??'—')+'/'+(first?.task_pass.n??'—')+'（'+percent(first?.task_pass.value)+'）。原版548题全量任务通过率未测，不能推算全量提升幅度；40题开发集100%不代表全量100%。';
};
for(const [label,id] of [['parent-pilot','example-before'],['candidate-final','example-after']]){
 fetch('/api/service-evals/cases/kb-qa-ba9360f02f65-zh?run='+label).then(r=>{if(!r.ok)throw Error('not ready');return r.json();}).then(d=>{document.getElementById(id).textContent=d.outputs?.find(o=>o.repeat===0)?.turns?.at(-1)?.zh||'此记录尚未提供';}).catch(()=>{document.getElementById(id).textContent='此记录暂时无法读取，可在逐题评测区查看。';});
}
})();
