/* Guided explanation of the implemented workflow; no actions are executed. */
window.OntoCareReturnCase=(()=>{
 'use strict';
 let step=0;
 const steps=[
  {title:'识别诉求',state:'识别与澄清',summary:'示例：客户说“我的订单是 Anker003，我想退货”。系统识别订单号和退款／退货意愿；如果问题类型未知，先追问物流、产品还是故障。',op:'function:classifyServiceIntent',objects:['ServiceCase'],basis:'类型契约声明 classifyServiceIntent → ServiceCase；classify() 将问题类型和售后诉求分别识别。此处是流程关联，不代表分类函数直接读取案件节点。',source:'ontocare/type_catalog.py；ontocare/customer_workflow.py:29、116'},
  {title:'查询订单',state:'本地快照',summary:'问题类型明确并进入申请流程后，按订单号查本地快照，读取订单商品和包裹；客户与订单归属尚未核验，物流也不是实时信息。',op:'function:lookup_order',objects:['Order','OrderItem'],basis:'lookup_order 契约引用 Order、OrderItem；order_detail() 按订单 ID 找订单，再按订单号读取商品。客服状态机实际直接调用 order_detail()，不是声称一定调用了该契约接口。',source:'web/type-definitions.json；ontocare/business.py:184；ontocare/customer_workflow.py:120'},
  {title:'选择商品',state:'ITEM / MATERIALS',summary:'订单有多条商品时先选择商品；只有一条时自动选中。所选商品必须属于该订单，然后读取该商品的质保日期。',op:'function:advanceServiceCase',objects:['ServiceCase','Order','OrderItem'],basis:'advanceServiceCase 的契约引用 ServiceCase；其实现调用 order_detail，并验证商品属于订单。Order → OrderItem 依据商品行的订单号；后两条是代码读取依赖，不是该函数契约直接引用。',source:'ontocare/type_catalog.py；ontocare/customer_workflow.py:120–131；ontocare/business.py:184'},
  {title:'核对条件与材料',state:'EXPIRED / TROUBLESHOOT / MATERIALS',summary:'按本地流程检查所选商品的质保日期及材料缺口；故障还需排障状态和 SN。缺少订单时询问购买国家与卖家并匹配渠道。收到材料和客户陈述均待核验。',op:'function:evaluateServiceEligibility',objects:['ServiceCase','OrderItem'],basis:'evaluateServiceEligibility 的契约引用 ServiceCase；实际输入是问题类型、请求方式、客户陈述和质保日期。质保日期由状态机从 OrderItem 读取并传入，是代码数据依赖，不是函数的对象引用参数。',source:'ontocare/type_catalog.py；ontocare/customer_workflow.py:53–75、130–163'},
  {title:'确认并交人工',state:'READY → HUMAN_PENDING',summary:'材料齐全后等待客户确认；提交时保存本地售后申请及待人工任务。仅为本地流程示例，未批准或执行真实退货、退款，也不代表外部人工已接单。',op:'action:submitAftersalesRequest',objects:['ServiceCase','AftersalesRequest','HumanServiceTask'],basis:'动作契约引用 ServiceCase、AftersalesRequest、HumanServiceTask；advance() 在 READY 且收到 submit 事件时保存申请并创建本地人工待办。',source:'ontocare/type_catalog.py；ontocare/customer_workflow.py:163–168'}
 ];
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 function render({catalog,data,onClass,onOperation}){
  const section=el('section',undefined,'case-guide');section.setAttribute('aria-label','查询订单并申请退货案例');
  const head=el('div',undefined,'case-head');const title=el('div');title.append(el('small','GUIDED CASE · 场景演示','case-eyebrow'),el('h3','查询订单并申请退货'),el('p','沿着操作、数据对象和关联依据，一步步理解客服流程。'));
  head.append(title,el('span','示意案例 · 不执行操作','case-badge'));section.append(head);
  const nav=el('div',undefined,'case-steps');nav.setAttribute('aria-label','案例步骤');
  steps.forEach((s,i)=>{const button=el('button',`${i+1}  ${s.title}`,'case-step'+(i===step?' active':''));button.type='button';button.setAttribute('aria-current',i===step?'step':'false');button.onclick=()=>{step=i;replace();};nav.append(button);});section.append(nav);
  const s=steps[step];const body=el('div',undefined,'case-body');body.append(el('div',`步骤 ${step+1} / ${steps.length}  ·  ${s.state}`,'case-state'),el('p',s.summary,'case-summary'));
  const op=catalog.entries.find(e=>e.id===s.op);const flow=el('div',undefined,'case-flow');
  const operation=el('button',undefined,'case-node case-operation');operation.type='button';operation.append(el('small','操作 · DECISION'),el('strong',op?.label||s.op),el('code',s.op));operation.onclick=()=>{if(op)onOperation(op);};flow.append(operation);
  const connector=el('div','关联 / 数据依赖 →','case-arrow');flow.append(connector);
  const targets=el('div',undefined,'case-targets');for(const id of s.objects){const cls=data.classes.find(c=>c.id===id);const b=el('button',undefined,'case-node case-object');b.type='button';b.append(el('small','对象 · SERVICE'),el('strong',cls?.label||id),el('code',id));b.onclick=()=>{if(cls)onClass(cls);};targets.append(b);}flow.append(targets);body.append(flow);
  const basis=el('div',undefined,'case-basis');basis.append(el('strong','连线依据'),el('p',s.basis),el('small','代码位置：'+s.source));body.append(basis);
  const actions=el('div',undefined,'case-actions');const prev=el('button','← 上一步');prev.disabled=step===0;prev.onclick=()=>{step--;replace();};const next=el('button',step===steps.length-1?'已到最后一步':'下一步 →');next.disabled=step===steps.length-1;next.onclick=()=>{step++;replace();};actions.append(prev,next);body.append(actions);section.append(body);
  function replace(){const next=render({catalog,data,onClass,onOperation});section.replaceWith(next);next.querySelector('.case-step.active')?.focus({preventScroll:true});}
  return section;
 }
 return {render};
})();
