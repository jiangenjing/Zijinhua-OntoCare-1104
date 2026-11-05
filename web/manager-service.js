(()=>{
'use strict';
const $=id=>document.getElementById(id),el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
let generation=0;
async function call(name,args={}){const r=await fetch('/api/ontology-service/call',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,arguments:args})});const v=await r.json();if(!r.ok)throw Error(v.error||'读取失败');return v;}
function button(text,run){const b=el('button',text);b.onclick=run;return b;}
function notice(box,text){const p=el('p',text);p.className='notice';box.append(p);}
function table(box,heads,rows,values,click){const t=el('table'),h=el('thead'),tr=el('tr');heads.forEach(x=>tr.append(el('th',x)));h.append(tr);t.append(h);const body=el('tbody');rows.forEach(row=>{const r=el('tr');values(row).forEach(x=>r.append(el('td',String(x??''))));if(click){r.tabIndex=0;r.onclick=()=>click(row);r.onkeydown=e=>{if(e.key==='Enter')click(row);};}body.append(r);});t.append(body);box.append(t);}
async function render({view,onInspect,onNode}){
const token=++generation,box=$('content');box.append(el('p','正在读取交付数据…'));
try{
if(view==='source-coverage'){
 const c=await call('get_source_coverage');if(token!==generation)return;box.replaceChildren(el('h2','五个 sheet：来源全部保留，按业务含义纳入'));
 notice(box,'管理视图保留原始资料，可能包含联系信息。原始行用于核查；客服工具会限制隐藏知识和敏感字段。附件链接仅登记，尚未理解内容。');
 table(box,['工作表','原始行数','字段数','纳入方式'],c.sheets,s=>[s.sheet,s.rows,s.fields.length,s.decision],s=>{onInspect(s.sheet,s);showSheet(s.sheet,1);});
 if(c.competition_brief){box.append(el('h3','赛题 Word 与业务 SOP'));notice(box,c.competition_brief.file+' · '+c.competition_brief.rule_count+' 条有来源规则 · '+c.competition_brief.boundary);const rules=await call('search_instances',{class_id:'ServiceRule',page_size:20});if(token!==generation)return;table(box,['服务规则','规则含义','实现边界'],rules.items,n=>[n.label,n.properties.statement,'条件评估与建议；不执行售后'],n=>onNode(n.id));}
 const rows=el('section');box.append(rows);
 async function showSheet(sheet,page){
  const r=await fetch('/api/ontology-service/source-rows?'+new URLSearchParams({sheet,page}));const v=await r.json();if(token!==generation)return;if(!r.ok)throw Error(v.error);
  rows.replaceChildren(el('h3',sheet+' · 原始来源行 · '+v.total+' 条'));notice(rows,'点击行查看全部字段。排版序号、空列和重复文件保留为来源信息，无需各建一个业务对象。');
  table(rows,['Excel 行号','原始内容摘要','查看'],v.items,x=>[x.source_row,Object.values(x.fields).filter(Boolean).join(' · ').slice(0,170),'全部字段 JSON →'],x=>onInspect(sheet+' · Excel 行 '+x.source_row,x));
  const nav=el('div');if(page>1)nav.append(button('上一页',()=>showSheet(sheet,page-1)));nav.append(el('span',' 第 '+page+' 页 '));if(page*20<v.total)nav.append(button('下一页',()=>showSheet(sheet,page+1)));rows.append(nav);
 }
 await showSheet(c.sheets[0].sheet,1);return;
}
const report=await call('get_delivery_report');if(token!==generation)return;box.replaceChildren(el('h2','客服试运行与外部 Agent 接入'));
notice(box,'当前连接使用本地资料快照，默认只读。下面是已实现的证据与下一步规划工具；完整多轮客服请使用「返回客服工作台」。正式退款、发信和真人转接尚未接通。');
const form=el('form');form.className='service-form';
const inputs={};for(const [key,label,value] of [['message','客户问题','Anker008 的包裹发货了吗？'],['pn','确认 PN（可留空）',''],['order_number','订单号（可留空）',''],['country','购买国家（核对销售方时填写）',''],['seller','销售方（核对名录时填写）','']]){const l=el('label',label),i=el(key==='message'?'textarea':'input');i.name=key;i.value=value;i.setAttribute('aria-label',label);l.append(i);form.append(l);inputs[key]=i;}
const submit=el('button','运行客服证据规划');submit.type='submit';form.append(submit);box.append(form);const output=el('section');box.append(output);
form.onsubmit=async e=>{e.preventDefault();submit.disabled=true;output.replaceChildren(el('p','查询中…'));try{const result=await call('plan_customer_service',Object.fromEntries(Object.entries(inputs).map(([k,v])=>[k,v.value])));if(token!==generation)return;output.replaceChildren(el('h3','查询结果 · '+result.intent));notice(output,result.next_step);output.append(button('查看返回 JSON',()=>onInspect('客服规划 · 实际返回',result)));
 if(result.result?.order){const o=result.result;table(output,['对象','当前资料状态','详情'],[o.order,...o.items,...o.shipments],n=>[n.label,window.OntoCareLabels.value(n.properties.fulfillment_status||n.properties.source_status||n.properties.status),'查看对象 →'],n=>onNode(n.id));}
 if(result.result?.candidates){notice(output,result.result.reason||'请补充购买国家与销售方');table(output,['销售方','国家','当前边界'],result.result.candidates,n=>[n.label,n.properties.country,'名录出现；授权范围未知'],n=>onNode(n.id));}
 if(result.evidence){table(output,['依据 ID','适用型号','原文'],result.evidence.documents,d=>[d.id,d.pns.join(' / '),d.title],d=>onInspect(d.title,d));if(!result.evidence.documents.length)notice(output,'未找到适用原文，请补充症状或交由复核。');}
 if(result.candidates)notice(output,'型号候选：'+(result.candidates.join('、')||'尚未确认'));
 }catch(err){output.textContent=err.message;}finally{submit.disabled=false;}};
box.append(el('h3','MCP：'+Object.keys(report.tools).length+' 个已注册工具 · stdio 本地连接'));
notice(box,'项目 .mcp.json 已生成。外部客户端启动 .venv/bin/python -m ontocare.service_mcp；工作目录指向本项目。当前 API 面向可信本地演示，远程开放前需补身份验证与订单归属检查。');
const cfg=el('pre');cfg.textContent='配置文件：项目根目录 .mcp.json\n联通检查：.venv/bin/python scripts/external_agent.py --message "Anker008 物流怎么样？"\n模型驱动：同上追加 --live（复用现有模型配置）';box.append(cfg);
table(box,['工具','业务用途','当前状态'],Object.entries(report.tools),([name,desc])=>[name,desc,name==='submit_for_review'?'已实现，本连接禁写':name==='generate_report'?'已实现，写入本地报告归档':'已实现，本地查询'],async([name,description])=>{try{const manifest=await(await fetch('/static/service-tools.json')).json();onInspect(name,{description,...manifest.tools.find(t=>t.name===name)});}catch(e){onInspect(name,{description});}});
box.append(el('h3','正式对接仍需补充'));report.production_gaps.forEach(x=>box.append(el('p','• '+x)));
}catch(err){if(token===generation)box.replaceChildren(el('p',err.message));}
}
window.OntoCareService={render};
})();
