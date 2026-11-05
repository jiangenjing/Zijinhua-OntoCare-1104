const $=id=>document.getElementById(id);
let session=null,semantic=null,language='zh',pending=false;
const conversation=[];
function fallbackStatus(reply){
 if(reply.model_status==='offline_not_requested')return '离线回放回复';
 const reasons={cross_product_answer:'回复中混入其他型号',invalid_citations:'引用校验未通过',unsafe_business_claim:'业务承诺校验未通过',invalid_structured_answer:'回复格式校验未通过',secret_in_answer:'敏感内容校验未通过'};
 if(reasons[reply.model_status])return '模型回复未通过校验：'+reasons[reply.model_status]+'；以下为有依据的保底回复。';
 return '模型调用未完成（'+reply.model_status+'）；以下为离线保底。';
}
const get=async path=>{const r=await fetch(path);const d=await r.json();if(!r.ok)throw Error(d.error||'请求失败 '+r.status);return d};
const node=(tag,text,className)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(className)n.className=className;return n};
function showPage(name){document.querySelectorAll('.page').forEach(p=>p.hidden=p.id!==name);document.querySelectorAll('[data-page]').forEach(n=>n.classList.toggle('selected',n.dataset.page===name));if(name==='ontology')loadSemantic();if(name==='library')loadCatalog()}
document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>showPage(b.dataset.page));
document.querySelectorAll('[data-prompt]').forEach(b=>b.onclick=()=>{$('message').value=b.dataset.prompt;$('message').focus()});

function renderConversation(){
 const log=$('conversation'),busy=$('busy');log.replaceChildren();
 if(!conversation.length){const welcome=node('div',undefined,'message assistant welcome');welcome.append(node('span','小克','avatar'),node('div',language==='zh'?'你好，我是安小克。请告诉我产品型号、遇到的现象，以及已经尝试过的操作。我会先查询适用资料，再给出有依据的建议。':'Hello, I am Anka. Please share the model, issue and checks already attempted. I will look up applicable evidence before suggesting the next step.','message-body'));log.append(welcome)}
 for(const item of conversation){
  const row=node('div',undefined,'message '+item.role),body=node('div',undefined,'message-body');
  if(item.role==='user'){body.textContent=item.text;row.append(body)}
  else{
   row.append(node('span','小克','avatar'));
   if(item.error){body.append(node('p',item.error,'error-notice'))}
   else{
    const r=item.reply;
    if(r.mode!=='live')body.append(node('div',fallbackStatus(r),'reply-badge offline'));
    else body.append(node('div','DeepSeek 实际回复 · '+(r.model_calls.at(-1)?.model||'DeepSeek-V4.1-Flash'),'reply-badge'));
    const sections=r.sections?.[language];
    if(sections){body.append(node('p',sections.summary,'reply-summary'));if(sections.actions.length){body.append(node('h4',language==='zh'?'处理建议':'Suggested steps'));const list=node('ol');for(const action of sections.actions)list.append(node('li',action));body.append(list)}if(sections.questions.length){body.append(node('h4',language==='zh'?'还需要确认':'Please confirm'));const list=node('ul');for(const question of sections.questions)list.append(node('li',question));body.append(list)}if(sections.limits)body.append(node('p',sections.limits,'reply-limits'))}
    else body.append(node('div',r[language],'reply-text'));
    if(r.citations.length){const cites=node('div',undefined,'inline-citations');for(const [i,c] of r.citations.entries()){const a=node('a',`[${i+1}] ${c.source.sheet} · 第 ${c.source.row} 行`);a.href='/library?kind=qa&q='+encodeURIComponent(c.id);a.target='_blank';a.rel='noopener';cites.append(a)}body.append(cites)}
    body.append(node('small',r.mode==='live'?`${r.latency_ms} ms · 本体 ${r.timings?.ontology_ms??'—'} ms · 来源与范围检查${r.checks.every(c=>c.passed)?'通过':'未通过'}`:`${r.latency_ms} ms · 离线流程，不代表模型质量`,'reply-footer'));
   }
   row.append(body);
  }
  log.append(row);
 }
 log.append(busy);busy.hidden=!pending;log.scrollTop=log.scrollHeight;
}

function renderGraph(reply){
 const graph=reply.retrieval,wrap=$('graphPreview');wrap.replaceChildren();
 if(!graph?.nodes.length){wrap.append(node('span',reply.state.pn?'此问题暂无适用的知识节点':'请先确认产品型号'));$('nodeCount').textContent='0';return}
 const chosen=[];for(const [type,limit]of [['product_model',1],['error_code',1],['knowledge_topic',2],['check_action',2]])chosen.push(...graph.nodes.filter(n=>n.type===type).slice(0,limit));
 const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 400 250');svg.setAttribute('role','img');svg.setAttribute('aria-label',`实际命中的 ${graph.nodes.length} 个本体节点`);
 const positions=new Map(),columns={product_model:55,error_code:140,knowledge_topic:240,check_action:345},seen={};
 for(const n of chosen){const index=seen[n.type]||0;seen[n.type]=index+1;positions.set(n.id,{x:columns[n.type],y:n.type==='knowledge_topic'||n.type==='check_action'?75+index*105:125})}
 for(const edge of graph.edges){const a=positions.get(edge.source),b=positions.get(edge.target);if(!a||!b)continue;const line=document.createElementNS(ns,'line');for(const [k,v]of Object.entries({x1:a.x,y1:a.y,x2:b.x,y2:b.y,stroke:'#b5c9e6','stroke-width':1.5}))line.setAttribute(k,String(v));svg.append(line)}
 const colors={product_model:'#3975ef',error_code:'#ba8a3a',knowledge_topic:'#5577b6',check_action:'#2c957c'};
 for(const n of chosen){const p=positions.get(n.id),group=document.createElementNS(ns,'g'),rect=document.createElementNS(ns,'rect');for(const [k,v]of Object.entries({x:p.x-43,y:p.y-27,width:86,height:54,rx:9,fill:'#fff',stroke:colors[n.type]}))rect.setAttribute(k,String(v));group.append(rect);const title=document.createElementNS(ns,'title');title.textContent=n.name;group.append(title);for(const [i,text]of [n.type==='knowledge_topic'?'知识资料':n.type==='check_action'?'检查动作':n.type==='error_code'?'故障码':'产品型号',n.name.length>13?n.name.slice(0,12)+'…':n.name].entries()){const label=document.createElementNS(ns,'text');label.setAttribute('x',p.x);label.setAttribute('y',p.y-4+i*17);label.setAttribute('text-anchor','middle');label.setAttribute('font-size',i?'10':'9');label.setAttribute('fill',i?'#223c60':'#8090a8');label.textContent=text;group.append(label)}svg.append(group)}
 wrap.append(svg);$('nodeCount').textContent=String(graph.nodes.length);$('graphHint').textContent=`${reply.state.pn} · ${graph.contract.max_hops} 跳图搜索 · 本次 ${graph.nodes.length} 个节点、${graph.edges.length} 条关系；图中展示其中 ${chosen.length} 个节点。`;
}

function renderTrace(reply){
 renderGraph(reply);$('answerMeta').textContent=`${reply.version} · ${reply.prompt.skill} Skill · ${reply.citations.length} 条引用${reply.ontology_cache?.snapshot_hit?' · 本体缓存复用':''}`;
 $('currentGraph').href='/ontology/native?pn='+encodeURIComponent(reply.state.pn||'all');
 $('sources').replaceChildren();for(const [i,s]of reply.citations.entries()){const d=node('details',undefined,'source');d.append(node('summary',`[${i+1}] ${s.title}`),node('small',`${s.source.file} / ${s.source.sheet} / 第 ${s.source.row} 行`),node('p',s.quote));$('sources').append(d)}if(!reply.citations.length)$('sources').append(node('p','未找到适用引用；不会把相似型号的资料作为依据。','note'));
 const names={resolve_semantics:'查询本体概念与关系',skill_state:'读取 Skill 与已完成动作',search_evidence:'检索适用原始资料',graph_search:'执行同型号两跳图搜索',lookup_order:'查询本地订单快照'};$('processSteps').replaceChildren();for(const tool of reply.tools){let label=names[tool.name]||tool.name;if(tool.name==='graph_search')label+=`：${tool.result.nodes.length} 个节点、${tool.result.edges.length} 条关系`;if(tool.cache_hit)label+='（缓存复用）';$('processSteps').append(node('li',label))}
 $('trace').textContent=JSON.stringify({state:reply.state,prompt:reply.prompt,tools:reply.tools,checks:reply.checks,ontology_cache:reply.ontology_cache,timings:reply.timings,model_validation:reply.model_validation,model_calls:reply.model_calls,trace_id:reply.trace_id},null,2);
 if(reply.mode==='live'){$('connectionStatus').textContent='DeepSeek 已实际回复';$('modelPill').textContent=reply.model_calls.at(-1)?.model||'DeepSeek-V4.1-Flash'}else if(reply.model_status!=='offline_not_requested')$('connectionStatus').textContent=fallbackStatus(reply);
}

$('newSession').onclick=()=>{session=null;conversation.length=0;renderConversation();$('graphPreview').replaceChildren(node('span','等待一条新的问题'));$('nodeCount').textContent='0';$('graphHint').textContent='提问后，这里会显示本次实际命中的型号、知识与检查动作。';$('currentGraph').href='/ontology/native?pn=all';$('sources').replaceChildren();$('trace').textContent='等待处理记录';$('answerMeta').textContent='';$('processSteps').replaceChildren()};
$('chatForm').onsubmit=async event=>{
 event.preventDefault();const text=$('message').value.trim();if(!text||pending)return;
 pending=true;$('send').disabled=true;$('newSession').disabled=true;$('version').disabled=true;conversation.push({role:'user',text});$('message').value='';renderConversation();
 try{const payload={message:text,version:$('version').value,mode:$('mode').value};if(session)payload.session_id=session;const response=await fetch($('mail').checked?'/api/mail/draft':'/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const reply=await response.json();if(!response.ok)throw Error(reply.error||'请求失败');session=reply.session_id;conversation.push({role:'assistant',reply});renderTrace(reply)}catch(error){conversation.push({role:'assistant',error:'请求未完成：'+error.message});if(!$('message').value)$('message').value=text}finally{pending=false;$('send').disabled=false;$('newSession').disabled=false;$('version').disabled=false;renderConversation()}
};
$('message').onkeydown=event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();if(!pending)$('chatForm').requestSubmit()}};
$('toolsToggle').onclick=()=>{const hidden=!$('processPanel').hidden;$('processPanel').hidden=hidden;$('chatWorkspace').classList.toggle('tools-hidden',hidden);$('toolsToggle').setAttribute('aria-expanded',String(!hidden))};
document.querySelectorAll('[data-language]').forEach(button=>button.onclick=()=>{language=button.dataset.language;document.querySelectorAll('[data-language]').forEach(b=>b.classList.toggle('selected',b===button));renderConversation()});

async function loadSemantic(){semantic=await get('/api/ontology?version='+encodeURIComponent($('version').value)+'&query='+encodeURIComponent($('semanticQuery').value));const pn=$('semanticQuery').value.trim().toUpperCase();if(/^T[0-9][A-Z0-9]{3}$/.test(pn))$('graphLink').href='/ontology/native?pn='+encodeURIComponent(pn);showLayer('content')}
async function showLayer(name){if(!semantic)return;let value;if(name==='content')value={manifest:semantic.manifest,records:semantic.browse,policies:semantic.bundle.policies};if(name==='schema')value=semantic.bundle.domain_schema;if(name==='tools')value=semantic.bundle.tools;if(name==='skills')value=semantic.bundle.skills;if(name==='diff'){const base=await get('/api/ontology?version=v0');value={parent:base.bundle.version,selected:semantic.bundle.version,changes:Object.keys(semantic.bundle).filter(k=>JSON.stringify(semantic.bundle[k])!==JSON.stringify(base.bundle[k])).map(k=>({field:k,before:base.bundle[k],after:semantic.bundle[k]}))}}$('semanticOutput').textContent=JSON.stringify(value,null,2)}
document.querySelectorAll('[data-layer]').forEach(b=>b.onclick=()=>showLayer(b.dataset.layer));$('resolve').onclick=loadSemantic;$('version').onchange=()=>{$('newSession').click();loadSemantic()};
(async()=>{const d=await get('/api/status');d.versions.forEach(v=>{const o=node('option',v+(v===d.active?' · 当前发布':''));o.value=v;$('version').append(o)});$('version').value=d.active;$('mode').value=d.model.configured?'live':'offline';$('modelPill').textContent=d.model.model||'离线回放';$('connectionStatus').textContent=d.model.configured?'API 已配置 · 等待实际回复':'API 未配置 · 离线回放';const a=d.data;for(const [label,count]of [['原始 Q&A',a.qa_total],['可见知识',a.qa_customer_visible],['订单 / 商品',a.orders+' / '+a.order_items],['去重经销商',a.dealers_unique]]){const div=node('div',undefined,'card');div.append(node('span',label),node('b',String(count)));$('counts').append(div)}$('audit').textContent=JSON.stringify({audit:a,vector:d.vector},null,2);$('report').textContent=JSON.stringify(await get('/api/report'),null,2)})().catch(error=>{$('connectionStatus').textContent='工作台连接未完成：'+error.message});
