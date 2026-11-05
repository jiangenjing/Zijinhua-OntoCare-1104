(()=>{
 'use strict';
 const L=window.OntoCareLabels;
 const $=id=>document.getElementById(id), el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const titles={'dual-ontology':'双本体地图',sop:'业务SOP流程与本体绑定','source-coverage':'全 sheet 来源覆盖','service-tools':'客服与 MCP 接入','object-types':'Object Type 对象声明','link-types':'Link Type 关联声明','action-types':'Action Type 行为契约','function-types':'Function Type 计算逻辑',topology:'拓扑 Topology',classes:'类 Classes',relations:'关系 Relations',properties:'属性 Properties',instances:'实例 Instances',validation:'关系校验',actions:'工具与动作边界',legacy:'旧版关联审计'};
 const descriptions={'dual-ontology':'从操作、数据对象到真实实例，查看本项目双本体的关联与边界。',sop:'来源明确的流程节点、条件分支、材料与动作声明；接入状态单独展示，不把流程图当作已执行的业务。',topology:'查看对象之间的实际关联；点击实例可查看局部拓扑和连线依据。',classes:'按业务领域展开本体类，查看每个类的属性、关系和实例。',relations:'查看关系的起点类、终点类、方向、基数与实际数据。',properties:'查看字段所属的类及实际数据类型。',instances:'搜索全部真实记录，查看原始属性及关联对象。'};
 const classGroups=[
  {id:'products',label:'产品与交易',description:'产品、部件、订单商品与销售主体',classes:['ProductModel','Component','Order','OrderItem','ProductOffering','Shipment','Dealer','Country']},
  {id:'service',label:'服务与诊断',description:'客诉、来源范围内的故障及检查步骤',classes:['SupportTicket','ErrorCode','CheckStep','ReviewTask','ExternalMaterial']},
  {id:'knowledge',label:'知识与证据',description:'知识原文、来源依据及数据映射',classes:['KnowledgeArticle','Evidence','Mapping','KnowledgeCategory']},
  {id:'decision',label:'决策与约束',description:'资格条件及业务边界',classes:['Condition','Constraint','DealerCheck','ServiceRule','ServiceProcess','SOPStep','RequiredMaterial','SOPAction','SOPDataBinding','ServiceCase','AftersalesRequest','HumanServiceTask','CustomerMaterial','ServiceSurvey']},
 ];
 let typeCatalog;
 const topologyPresets={sop:['业务SOP流程',null],all:['全部类型',null],orders:['订单与物流',['Order','OrderItem','ProductOffering','Shipment','ProductModel']],dealers:['国家与销售方',['Country','Dealer','DealerCheck','Order']],knowledge:['知识目录与来源',['KnowledgeCategory','KnowledgeArticle','Evidence','ProductModel']],service:['产品与排障',['SupportTicket','ProductModel','ErrorCode','CheckStep','ReviewTask','ExternalMaterial','KnowledgeArticle']]};
 let topologyPreset='all', showFullTopology=false;
 const overviewClasses=['SupportTicket','Order','OrderItem','Shipment','ProductModel','ErrorCode','KnowledgeArticle','CheckStep','Evidence','Constraint','ServiceRule','ServiceCase'];
 const overviewPairs=new Set(['SupportTicket|Order','SupportTicket|ProductModel','Order|OrderItem','Order|Shipment','OrderItem|ProductModel','ProductModel|KnowledgeArticle','ProductModel|ErrorCode','ErrorCode|KnowledgeArticle','KnowledgeArticle|CheckStep','KnowledgeArticle|Evidence','KnowledgeArticle|Constraint','ProductModel|ServiceRule','ServiceCase|ServiceRule']);
 let data,byId,view='topology',page=1,focus=null,legacy=null,selectedRelation=null,classMode='hierarchy';
 const collapsedGroups=new Set();
 const typeLabel=t=>data.classes.find(c=>c.id===t)?.label||t, relationLabel=r=>data.relations.find(x=>x.id===r)?.label||r;
 const json=v=>JSON.stringify(v,null,2), matches=x=>json(x).toLowerCase().includes($('search').value.toLowerCase());
 const button=(text,fn)=>{const b=el('button',text);b.onclick=fn;return b;};
 function inspect(title,value){const floating=$('detail').classList.contains('graph-inspector');$('detail').replaceChildren(el('small','INSPECTOR · 详情'),el('h2',title),el('pre',json(L.annotate(value))));if(floating){const close=button('收起详情 ×',()=>$('detail').classList.remove('graph-inspector'));close.className='close-inspector';$('detail').prepend(close);}}
 function showNode(id){
  const n=byId.get(id);if(!n)return;
  inspect(n.zh,{原始名称:n.label,中文解释:n.zh,ID:n.id,类型:typeLabel(n.type),属性:n.properties});
  $('detail').append(button('查看这个实例的局部关系图',()=>{focus=id;$('search').value='';$('kind').value='';switchView('topology');}));
  if(n.type==='KnowledgeArticle'){
   const a=el('a','查看原始 Q&A ↗');a.href='/library?kind=qa';a.target='_blank';$('detail').append(a);
  }
  const links=data.links.filter(l=>l.source===id||l.target===id);
  $('detail').append(el('h3',`直接关联 · ${links.length}`));
  for(const link of links.slice(0,40)){
   const other=byId.get(link.source===id?link.target:link.source);
   $('detail').append(button(`${relationLabel(link.relation)} → ${other.zh.slice(0,65)}`,()=>{
    inspect(relationLabel(link.relation),link);$('detail').append(button('查看目标对象',()=>showNode(other.id)),button('返回当前对象',()=>showNode(id)));
   }));
  }
  if(links.length>40)$('detail').append(el('p','详情列出前 40 条；局部图可筛选查看，完整关联数如上。'));
 }
 function table(headers,rows,values,onClick){
  const container=el('div',undefined,'table-wrap'),table=el('table'),thead=el('thead'),tr=el('tr');headers.forEach(h=>tr.append(el('th',h)));thead.append(tr);table.append(thead);
  const body=el('tbody');const total=rows.length;page=Math.max(1,Math.min(page,Math.ceil(total/20)||1));
  rows.slice((page-1)*20,page*20).forEach(row=>{const tr=el('tr');values(row).forEach(v=>tr.append(el('td',String(v??'—'))));if(onClick){tr.tabIndex=0;tr.onclick=()=>onClick(row);tr.onkeydown=e=>{if(e.key==='Enter')onClick(row);};}body.append(tr);});
  table.append(body);container.append(table);$('content').append(container);
  if(!total)$('content').append(el('p','没有匹配记录。','empty'));
  const pager=el('div',undefined,'pager'),controls=el('div');pager.append(el('span',`共 ${total} 条 · 第 ${page} / ${Math.ceil(total/20)||1} 页`));
  const prev=button('上一页',()=>{page--;render();}),next=button('下一页',()=>{page++;render();});prev.disabled=page===1;next.disabled=page*20>=total;controls.append(prev,next);pager.append(controls);$('content').append(pager);
 }
 function showClass(cls){
  const counts=new Map();for(const link of data.links)if(byId.get(link.source).type===cls.id||byId.get(link.target).type===cls.id)counts.set(link.relation,(counts.get(link.relation)||0)+1);
  inspect(cls.label,{类名:cls.id,实例数:cls.count,属性:data.properties.filter(p=>p.owner===cls.id),实际关联关系:data.relations.filter(r=>counts.has(r.id)).map(r=>({...r,count:counts.get(r.id)}))});
  $('detail').append(button('查看 '+cls.label+' 的全部实例',()=>{$('kind').value=cls.id;$('search').value='';switchView('instances');}));
 }
 function drawClasses(){
  const toolbar=el('div',undefined,'class-toolbar'),modes=el('div',undefined,'mode-switch');
  for(const [mode,label]of [['hierarchy','层级图'],['list','列表']]){
   const b=button(label,()=>{classMode=mode;page=1;render();});b.setAttribute('aria-pressed',String(classMode===mode));modes.append(b);
  }
  toolbar.append(modes);
  if(classMode==='hierarchy')toolbar.append(button('展开全部',()=>{collapsedGroups.clear();render();}),button('收起全部',()=>{classGroups.forEach(g=>collapsedGroups.add(g.id));render();}));
  $('content').append(toolbar);
  const visibleClasses=data.classes.filter(c=>(!$('kind').value||c.id===$('kind').value)&&matches(c));
  if(classMode==='list'){
   table(['类名（英文标识）','中文解释','实例数'],visibleClasses,r=>[r.id,r.label,r.count],r=>showClass(r));return;
  }
  $('content').append(el('p','实线层级用于业务分组，不表示 subclass / is-a 继承。当前版本未声明类继承；实例数量和属性来自所选版本的实际数据。','graph-note'));
  const canvas=el('div',undefined,'class-hierarchy'),root=el('div',undefined,'hierarchy-root');
  root.append(el('small','ONTOLOGY · 本体'),el('strong','OntoCare · 客服本体'),el('span',`${visibleClasses.length} / ${data.classes.length} 个类 · ${data.version}`));canvas.append(root);
  const branches=el('div',undefined,'hierarchy-branches');
  for(const group of classGroups){
   const children=visibleClasses.filter(c=>group.classes.includes(c.id));if(!children.length)continue;
   const branch=el('section',undefined,'hierarchy-branch'),head=button('',()=>{collapsedGroups.has(group.id)?collapsedGroups.delete(group.id):collapsedGroups.add(group.id);render();});
   head.className='hierarchy-group';head.title=group.description;head.setAttribute('aria-expanded',String(!collapsedGroups.has(group.id)));head.setAttribute('aria-label',group.label+' 分组');head.append(el('small','业务分组'),el('strong',(collapsedGroups.has(group.id)?'▸ ':'▾ ')+group.label),el('span',children.length+' 个类'));
   branch.append(head);const list=el('div',undefined,'hierarchy-children');list.hidden=collapsedGroups.has(group.id);
   for(const cls of children){
    const card=button('',()=>showClass(cls));card.className='hierarchy-class';card.setAttribute('aria-label',cls.label+' 类详情');
    card.append(el('strong',cls.label),el('code',cls.id),el('span',cls.count.toLocaleString()+' 个实例'));list.append(card);
   }
   branch.append(list);branches.append(branch);
  }
  canvas.append(branches);if(!visibleClasses.length)canvas.append(el('p','没有匹配的本体类。','empty'));$('content').append(canvas);
 }
 function drawGraph(){
  if(topologyPreset==='sop'&&!focus){$('content').append(button('返回类关系总览',()=>{topologyPreset='all';render();}));drawSOP();return;}
  let controller;
  const toolbar=el('div',undefined,'graph-toolbar');const preset=el('select');preset.setAttribute('aria-label','业务拓扑');for(const [id,[label]] of Object.entries(topologyPresets))preset.add(new Option(label,id));preset.value=topologyPreset;preset.onchange=()=>{topologyPreset=preset.value;focus=null;render();};toolbar.append(preset);toolbar.append(button('类关系总览',()=>{focus=null;$('detail').classList.remove('graph-inspector');render();}));
  if(!focus&&topologyPreset==='all')toolbar.append(button(showFullTopology?'返回核心关系':'显示全部类和关系',()=>{showFullTopology=!showFullTopology;render();}));
  if(focus)toolbar.append(button('返回所选对象',()=>showNode(focus)));
  toolbar.append(button('重置布局',()=>controller?.reset()),el('span','拖动节点移动位置 · 拖动边／标签调整走线 · 点击查看内容 · 滚轮缩放'));$('content').append(toolbar);
  let ns,ls;
  if(focus){
   const root=byId.get(focus),edges=data.links.filter(l=>(l.source===focus||l.target===focus)&&matches({target:byId.get(l.source===focus?l.target:l.source),relation:l.relation})&&(!$('kind').value||byId.get(l.source===focus?l.target:l.source).type===$('kind').value));
   ls=edges.slice(0,50);const ids=new Set([focus,...ls.flatMap(l=>[l.source,l.target])]);ns=[...ids].map(id=>({...byId.get(id),display:byId.get(id).zh.slice(0,18)}));
   $('content').append(el('p',`实例：${root.zh} · 匹配 ${edges.length} 条直接关联，当前图显示 ${ls.length} 条。其余可用搜索或类型筛选定位。`,'graph-note'));
  }else{
   const overview=topologyPreset==='all'&&!showFullTopology&&!$('kind').value&&!$('search').value;
   ns=data.classes.filter(c=>(!overview||overviewClasses.includes(c.id))&&(!topologyPresets[topologyPreset][1]||topologyPresets[topologyPreset][1].includes(c.id))&&(!$('kind').value||c.id===$('kind').value)&&matches(c)).map(c=>({...c,display:c.label+' · '+c.count}));
   const ids=new Set(ns.map(n=>n.id)),map=new Map();
   for(const edge of data.links){const a=byId.get(edge.source).type,b=byId.get(edge.target).type;if(!ids.has(a)||!ids.has(b))continue;const key=[a,b,edge.relation].join('|');if(!map.has(key))map.set(key,{source:a,target:b,relation:edge.relation,count:0});map.get(key).count++;}
   ls=[...map.values()];if(overview)ls=ls.filter(l=>overviewPairs.has(l.source+'|'+l.target));$('content').append(el('p',overview?'核心关系总览：只展示主要对象和已存在的实际关系；选择上方“显示全部类和关系”可查看完整图，也可切换业务主题。数字为关系记录数；悬停横向连线可显示名称，点击节点或连线查看详情。':'当前是类结构图：每条边按实际实例关系聚合，数字表示关系记录数。点击节点查看类的内容与实例入口，点击边查看关联依据。拖动只调整布局，不改变业务关系。','graph-note'));
  }
  const overview=!focus&&topologyPreset==='all'&&!showFullTopology&&!$('kind').value&&!$('search').value;
  const box=el('div',undefined,'graph'),svg=document.createElementNS('http://www.w3.org/2000/svg','svg');if(overview)box.classList.add('overview-graph');svg.setAttribute('viewBox',!focus&&topologyPreset==='all'&&!overview?'0 0 1200 960':'0 0 1000 680');svg.setAttribute('aria-label',focus?'实例关系图':'业务本体类关系图');
  const group=document.createElementNS(svg.namespaceURI,'g');svg.append(group);box.append(svg);$('content').append(box);
  const make=(tag,attrs,text)=>{const n=document.createElementNS(svg.namespaceURI,tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text)n.textContent=text;return n;};
  const defs=make('defs',{}),marker=make('marker',{id:'edgeArrow',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:6,markerHeight:6,orient:'auto'});marker.append(make('path',{d:'M 0 0 L 10 5 L 0 10 Z',fill:'#a482c8'}));defs.append(marker);svg.prepend(defs);
  const points=new Map();const positions={ProductModel:[470,140],SupportTicket:[130,115],Order:[130,330],OrderItem:[320,390],KnowledgeArticle:[680,290],ErrorCode:[690,95],CheckStep:[880,140],Evidence:[860,490],Mapping:[650,555],Constraint:[455,570],Component:[465,310],Condition:[300,220],Dealer:[135,560]};
  Object.assign(positions,{ServiceCase:[1050,35],AftersalesRequest:[1050,180],HumanServiceTask:[1050,330],CustomerMaterial:[1050,480],ServiceSurvey:[1050,630],DealerCheck:[300,650],ReviewTask:[90,35],ProductOffering:[320,510],Shipment:[100,445],Country:[110,655],KnowledgeCategory:[820,650],ExternalMaterial:[300,35],ServiceRule:[880,360],ServiceProcess:[130,800],SOPStep:[365,800],RequiredMaterial:[600,800],SOPAction:[835,800],SOPDataBinding:[600,915]});
  if(overview)Object.assign(positions,{SupportTicket:[120,100],Order:[120,280],Shipment:[120,490],OrderItem:[340,280],ProductModel:[340,100],ErrorCode:[560,100],KnowledgeArticle:[560,280],CheckStep:[790,100],Evidence:[790,280],Constraint:[560,490],ServiceRule:[790,490],ServiceCase:[340,490]});
  if(!focus){const layouts={orders:{Order:[160,290],OrderItem:[440,240],ProductOffering:[720,290],Shipment:[400,500],ProductModel:[720,100]},dealers:{Dealer:[680,330],Country:[280,330]},knowledge:{ProductModel:[160,170],KnowledgeArticle:[480,250],Evidence:[800,250],KnowledgeCategory:[480,490]}};Object.assign(positions,layouts[topologyPreset]||{});}
  ns.forEach((n,i)=>{const angle=(i-1)*2*Math.PI/Math.max(ns.length-1,1);points.set(n.id,focus?(i===0?[500,340]:[500+360*Math.cos(angle),340+270*Math.sin(angle)]):(positions[n.id]||[500,340]));});
  const floatDetail=()=>{
   $('detail').querySelector('.close-inspector')?.remove();
   $('detail').classList.add('graph-inspector');
   const close=button('收起详情 ×',()=>$('detail').classList.remove('graph-inspector'));close.className='close-inspector';$('detail').prepend(close);
  };
  controller=window.OntoCareTopology.mount({svg,group,nodes:ns,edges:ls,points,layoutKey:data.version+':'+(focus||'classes:'+topologyPreset+':'+(overview?'overview':'full')),nodeLabel:n=>n.display,
   edgeLabel:l=>relationLabel(l.relation)+(l.count?' '+l.count:''),
   onNode:n=>{if(focus)showNode(n.id);else showClass(n);floatDetail();},
   onEdge:l=>{
    const definition=data.relations.find(r=>r.id===l.relation);
    inspect(relationLabel(l.relation),{关系类型:l.relation,中文解释:definition?.label,起点:focus?byId.get(l.source).zh:typeLabel(l.source),终点:focus?byId.get(l.target).zh:typeLabel(l.target),基数:definition?L.cardinality(definition.cardinality):'见原始记录',匹配规则:definition?.rule,...l});
    if(focus)$('detail').append(button('查看起点',()=>{showNode(l.source);floatDetail();}),button('查看终点',()=>{showNode(l.target);floatDetail();}));
    else $('detail').append(button('查看该关系的实例',()=>{switchView('relations');selectedRelation=l.relation;render();}));
    floatDetail();
   }});
 }
 function showRelation(id){
  const definition=data.relations.find(x=>x.id===id),links=data.links.filter(l=>l.relation===id&&matches({source:byId.get(l.source),target:byId.get(l.target),basis:l.basis}));inspect(definition.label,definition);
  $('content').replaceChildren();table(['起点实例','关系','终点实例','中文解释','依据'],links,l=>[byId.get(l.source).label,definition.label,byId.get(l.target).label,'起点：'+byId.get(l.source).zh+' → 终点：'+byId.get(l.target).zh,typeof l.basis==='string'?l.basis:json(L.annotate(l.basis))],l=>{inspect(definition.label,l);$('detail').append(button('查看起点',()=>showNode(l.source)),button('查看终点',()=>showNode(l.target)));});
 }
 function drawSOP(){window.OntoCareSOP.render({data,onNode:showNode,onInspect:inspect,query:$('search').value});}
 function render(){
  if(!data)return;
  $('content').replaceChildren();$('status').textContent=`${data.version} · ${data.nodes.length.toLocaleString()} 个实例 · ${data.links.length.toLocaleString()} 条关系`;
  const kind=$('kind').value;
  document.querySelector('.workspace').classList.toggle('sop-workspace',view==='sop'||view==='dual-ontology'||(view==='topology'&&topologyPreset==='sop'&&!focus));
  if(view==='dual-ontology'){window.OntoCareDual.render({data,catalog:typeCatalog,query:$('search').value,onClass:c=>{$('detail').classList.add('graph-inspector');showClass(c);},onNode:id=>{$('detail').classList.add('graph-inspector');showNode(id);},onOperation:e=>{$('detail').classList.add('graph-inspector');inspect(e.label,e);}});return;}
  if(view==='sop'){drawSOP();return;}
  if(['source-coverage','service-tools'].includes(view)){window.OntoCareService.render({view,onInspect:inspect,onNode:showNode});return;}
  if(view.endsWith('-types')){window.OntoCareTypeBrowser.render({view,catalog:typeCatalog,data,query:$('search').value,onNavigate:next=>{$('search').value='';switchView(next);},onNode:showNode,onInstanceGraph:id=>{focus=id;$('search').value='';$('kind').value='';switchView('topology');},onInspect:(title,value)=>{$('detail').replaceChildren(el('small','TYPE JSON · 原始定义'),el('h2',title),el('pre',json(value)));}});return;}
  if(view==='topology')drawGraph();
  if(view==='classes')drawClasses();
  if(view==='relations'){
   if(selectedRelation)showRelation(selectedRelation);
   else table(['关系','起点类','基数','终点类','实际关系数'],data.relations.filter(matches),r=>[r.label+' / '+r.id,r.source+'（'+(r.source==='*'?'多种对象类':typeLabel(r.source))+'）',L.cardinality(r.cardinality),r.target+'（'+typeLabel(r.target)+'）',r.count],r=>{selectedRelation=r.id;page=1;render();});
  }
  if(view==='properties')table(['所属类','字段名','中文解释','实际数据类型'],data.properties.filter(r=>(!kind||r.owner===kind)&&matches(r)),r=>[typeLabel(r.owner),r.name,r.zh,r.types.map(L.value).join(' / ')],r=>inspect(r.zh,r));
  if(view==='instances'){
   $('content').append(el('p','中文解释用于阅读对照；FAQ 中文标题来自既有中文对照表，已核对原始标题、正文和型号。原文及业务规则保持不变。','graph-note'));
   const degrees=new Map();for(const l of data.links)for(const id of [l.source,l.target])degrees.set(id,(degrees.get(id)||0)+1);
   table(['实例（原始名称）','中文解释','类','关系数'],data.nodes.filter(n=>(!kind||n.type===kind)&&matches(n)),n=>[n.label,n.zh,typeLabel(n.type),degrees.get(n.id)||0],n=>showNode(n.id));
  }
  if(view==='validation'){
   $('content').append(el('p','检查断开的端点、未解析的型号、快照中缺失的订单。待核查记录不强行连线；缺少来源的关联不会自动补造。','notice'));
   table(['级别','检查项','对象','说明'],data.diagnostics.filter(matches),r=>[r.level==='error'?'错误':'待核查',L.value(r.code),r.node||r.source||'—',typeof r.detail==='string'?r.detail:json(L.annotate(r.detail))],r=>{inspect(L.value(r.code),r);if(r.node)$('detail').append(button('查看对象',()=>showNode(r.node)));});
  }
  if(view==='actions'){
   $('content').append(el('p','这里显示实际工具契约。查询本体和订单属于只读工具；skill_state 只更新本地会话。检查步骤节点表示建议操作，不代表机器人已执行；当前没有退款、换货或发信执行器。','notice'));
   table(['工具','中文解释','执行边界'],data.actions.filter(matches),r=>[r.name,L.value(r.name),r.status],r=>inspect(L.value(r.name),r.definition));
  }
  if(view==='legacy'){
   if(!legacy){$('content').append(el('p','正在读取旧版核查报告…'));fetch('/api/ontology-manager/legacy-audit').then(r=>r.json()).then(r=>{legacy=r;if(view==='legacy')render();}).catch(()=>{$('content').textContent='旧版审计报告读取失败';});return;}
   $('content').append(el('p','核查对象：anker-OntoCare-RSI/OntoCare。旧代码仅做只读核查；本界面展示的是 Rebuild 版本实际数据。','notice'));
   table(['结论','问题','影响'],legacy.findings.filter(matches),r=>[r.status,r.title,r.impact],r=>inspect(r.title,r));
  }
 }
 function switchView(next){$('detail').classList.remove('graph-inspector');view=next;$('kind').disabled=view.endsWith('-types')||view==='sop';page=1;selectedRelation=null;document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===view));$('title').textContent=titles[view];$('heading').textContent=view==='topology'?'从业务对象，到有据可查的关系。':titles[view];$('subtitle').textContent=descriptions[view]||'检查来源、数据关联和当前版本的能力边界。';history.replaceState(null,'','#'+view);render();}
 async function load(){
  $('status').textContent='正在读取真实数据…';const response=await fetch('/api/ontology-manager?version='+encodeURIComponent($('version').value));if(!response.ok)throw Error('本体数据读取失败');data=await response.json();
  const typeResponse=await fetch('/api/ontology-manager/types?version='+encodeURIComponent(data.version));if(!typeResponse.ok)throw Error('类型契约读取失败');typeCatalog=await typeResponse.json();window.OntoCareTypeBrowser.reset();
  const translated=await fetch('/static/manager-titles-zh.json');if(!translated.ok)throw Error('中文对照资料读取失败');const titles=(await translated.json()).titles;
  data.nodes=data.nodes.map(n=>({...n,zh:L.explain(n,titles)}));data.properties=data.properties.map(p=>({...p,zh:L.field(p.name)}));byId=new Map(data.nodes.map(n=>[n.id,n]));
  $('stats').replaceChildren();for(const [value,label]of [[data.classes.length,'对象类'],[data.nodes.length,'全部对象记录'],[data.links.length,'数据与定义关联'],[data.diagnostics.length,'待核查 / 校验记录']]){const card=el('div',undefined,'stat');card.append(el('strong',value.toLocaleString()),el('small',label));$('stats').append(card);}
  const selected=$('kind').value;$('kind').replaceChildren(new Option('全部对象类型',''),...data.classes.map(c=>new Option(c.label+' · '+c.count,c.id)));$('kind').value=selected;focus=null;switchView(view);
 }
 document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>switchView(b.dataset.view));$('search').oninput=()=>{page=1;render();};$('kind').onchange=()=>{page=1;render();};$('clear').onclick=()=>{$('search').value='';$('kind').value='';focus=null;page=1;render();};$('version').onchange=()=>load().catch(e=>$('status').textContent=e.message);
 for(const [selector,text]of [['.brand small','本体管理工作台'],['.current small','CURRENT ONTOLOGY · 当前本体'],['.eyebrow','业务知识网络 · BUSINESS KNOWLEDGE NETWORK'],['.badge','READ ONLY · 只读'],['#detail>small','INSPECTOR · 详情']])document.querySelector(selector).textContent=text;
 document.querySelectorAll('.sidebar .group').forEach((n,i)=>n.textContent=['ONTOLOGY · 本体结构','TYPE CONTRACTS · 类型契约','DELIVERY · 交付','INSPECTION · 核查'][i]);
 (async()=>{const status=await(await fetch('/api/status')).json();$('version').replaceChildren(...status.versions.map(v=>new Option(v+(v===status.active?' · 当前激活':''),v)));$('version').value=status.active;view=Object.hasOwn(titles,location.hash.slice(1))?location.hash.slice(1):'topology';await load();})().catch(e=>{$('status').textContent=e.message;$('content').append(el('p','读取失败，请确认本地服务与数据版本可用。','notice'));});
})();
