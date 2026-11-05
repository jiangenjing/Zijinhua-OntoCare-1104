(()=>{
 'use strict';
 // Also provides an isolated navigation entry without replacing the manager UI.
 const form=document.getElementById('actionForm');
 if(!form){const nav=document.querySelector('.sidebar');if(nav){const a=document.createElement('a');a.textContent='↗ 执行本地 ActionType';a.href='/ontology/actions';a.className='back';nav.insertBefore(a,nav.querySelector('.back'));}return;}
 const $=id=>document.getElementById(id),el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
 const labels={OPEN:'待处理',WAITING_CUSTOMER:'等待客户',PENDING_REVIEW:'待复核',CustomerServiceAgent:'客服操作员',CustomerServiceSupervisor:'客服主管'};
 const pretty=value=>JSON.stringify(value,null,2);
 let requestKey=crypto.randomUUID(),previousParameters='',lastResult;
 async function get(url){const response=await fetch(url);if(!response.ok)throw Error('读取失败，请检查本地服务');return response.json();}
 function showResult(result){
  lastResult=result;$('result').hidden=false;$('result').replaceChildren(el('h2',result.committed?'动作已提交':'动作未提交'),el('p',result.message));
  $('result').className='panel '+(result.committed?'success':'failure');
  if(result.committed){
   const effects=el('ul');effects.className='effects';
   for(const text of ['工单：'+result.after.ticket_id,'状态：'+labels[result.before.workflow_status]+' → '+labels[result.after.workflow_status],'复核任务：'+result.review_task.id,'关联：工单 → 复核任务','事件：REVIEW_REQUESTED（已记录在本地，未投递外部）','审计编号：'+result.action_id,...result.checks.map(c=>'✓ '+c.reason)])effects.append(el('li',text));
   $('result').append(effects);const links=el('div');links.className='result-actions';
   const graph=el('a','查看更新后的本体与复核任务 ↗');graph.href='/ontology/manager#instances';graph.target='_blank';links.append(graph);$('result').append(links);
  }
  const details=el('details'),summary=el('summary','完整执行回执（含参数校验理由）');details.append(summary,el('pre',pretty(result)));$('result').append(details);
 }
 async function refresh(){
  const [graph,history]=await Promise.all([get('/api/ontology-manager'),get('/api/actions/history')]);
  const selected=$('ticket').value;$('ticket').replaceChildren(new Option('请选择工单',''));
  for(const n of graph.nodes.filter(n=>n.type==='SupportTicket')){$('ticket').append(new Option(n.label+' · '+(labels[n.properties.workflow_status||'OPEN']||n.properties.workflow_status),n.properties.id));}
  $('ticket').value=selected;$('history').replaceChildren();
  for(const receipt of history.records){const b=el('button',new Date(receipt.created_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+' · '+(receipt.committed?'已提交':'拒绝／回滚')+'\n'+receipt.message);b.type='button';b.onclick=()=>showResult(receipt);$('history').append(b);}
  if(!history.records.length)$('history').append(el('p','尚无动作执行记录。'));
 }
 form.onsubmit=async e=>{
  e.preventDefault();if(!form.reportValidity())return;
  const parameters={ticket:{objectType:'SupportTicket',id:$('ticket').value},reason:$('reason').value.trim()};
  if(pretty(parameters)!==previousParameters){requestKey=crypto.randomUUID();previousParameters=pretty(parameters);}
  $('submit').disabled=true;$('status').textContent='正在检查权限、前提并提交事务…';
  try{
   const response=await fetch('/api/actions/submit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({actionType:'submitForReview',parameters,idempotency_key:requestKey})});
   const result=await response.json();showResult(result);$('status').textContent=result.committed?(result.replayed?'已返回原提交回执，没有重复创建任务。':'已完成本地事务。'):result.message;await refresh();
  }catch(error){$('status').textContent='连接中断，可以重试同一次提交；相同幂等键不会重复建单。';}
  finally{$('submit').disabled=false;}
 };
 (async()=>{const meta=await get('/api/action-types');$('definition').textContent=pretty(meta.types[0]);$('operator').textContent='服务端操作员：'+meta.actor.id+' · '+meta.actor.roles.map(r=>labels[r]||r).join('／')+'。本机演示身份，未接入生产登录认证。';await refresh();$('submit').disabled=false;$('status').textContent='请选择工单并填写理由。';})().catch(error=>$('status').textContent=error.message);
})();
