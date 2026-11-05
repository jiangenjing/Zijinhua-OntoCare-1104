/* Type contracts are a read-only view; design records never enter business data. */
window.OntoCareTypeBrowser=(()=>{
 'use strict';
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const button=(text,fn)=>{const b=el('button',text);b.onclick=fn;return b;};
 const kindFor={'object-types':'ObjectType','link-types':'LinkType','action-types':'ActionType','function-types':'FunctionType'};
 let selected=null,tab='definition',page=1,options,lastInspected=null;
 const reset=()=>{selected=null;tab='definition';page=1;lastInspected=null;};
 const badge=e=>el('span',e.statusLabel,'type-status '+e.status);
 function select(id,keepTab=false){selected=id;if(!keepTab)tab='definition';page=1;lastInspected=null;const entry=options.catalog.entries.find(e=>e.id===id),view=Object.keys(kindFor).find(key=>kindFor[key]===entry.kind);if(view!==options.view){options.onNavigate(view);return;}draw();}
 function article(kind,parent){
  const a=options.catalog.articles[kind];parent.append(el('h2',a.title),el('p',a.summary));
  for(const section of a.sections)parent.append(el('h3',section.title),el('p',section.text));
  const link=el('a','下载本类深度剖析文档 ↓');link.href='/static/type-guides/'+kind+'.md';link.download=kind+'.md';parent.append(link);
 }
 function list(headers,records,values,click,parent){
  if(!records.length){parent.append(el('p','当前版本没有对应真实记录。','empty'));return;}
  const wrap=el('div',undefined,'table-wrap'),t=el('table'),head=el('tr');headers.forEach(h=>head.append(el('th',h)));const thead=el('thead');thead.append(head);t.append(thead);const body=el('tbody');
  page=Math.min(page,Math.ceil(records.length/20));
  for(const r of records.slice((page-1)*20,page*20)){const row=el('tr');values(r).forEach(v=>row.append(el('td',String(v??'—'))));row.tabIndex=0;row.onclick=()=>click(r);row.onkeydown=e=>{if(e.key==='Enter')click(r);};body.append(row);}
  t.append(body);wrap.append(t);parent.append(wrap);const pager=el('div',undefined,'pager');pager.append(el('span',`共 ${records.length} 条 · 第 ${page} / ${Math.ceil(records.length/20)} 页`));const controls=el('div');const prev=button('上一页',()=>{page--;draw();}),next=button('下一页',()=>{page++;draw();});prev.disabled=page===1;next.disabled=page*20>=records.length;controls.append(prev,next);pager.append(controls);parent.append(pager);
 }
 function instances(entry,parent){
  const {data,onNode,onInspect,onInstanceGraph,catalog}=options;
  if(entry.classId){
   const rows=data.nodes.filter(n=>n.type===entry.classId);parent.append(el('p',`真实实例 · ${rows.length} 条；点击查看属性，或进入该实例的实际拓扑。`));
   list(['实例标识','名称 / 中文说明'],rows,r=>[r.id,r.zh||r.label],r=>{onNode(r.id);document.getElementById('detail').append(button('打开实际实例拓扑',()=>onInstanceGraph(r.id)));},parent);
  }else if(entry.relationId){
   const byId=new Map(data.nodes.map(n=>[n.id,n]));const rows=data.links.filter(l=>l.relation===entry.relationId);parent.append(el('p',`真实关联实例 · ${rows.length} 条；点击查看边的完整依据与两端对象。`));
   list(['起点','关系','终点'],rows,r=>[byId.get(r.source).zh||r.source,entry.label,byId.get(r.target).zh||r.target],r=>{onInspect(entry.label,r);document.getElementById('detail').append(button('起点实例拓扑',()=>onInstanceGraph(r.source)),button('终点实例拓扑',()=>onInstanceGraph(r.target)));},parent);
  }else{
   parent.append(el('p',catalog.traceWindow,'graph-note'),el('p','记录已区分本地工具轨迹与本地动作审计；可能来自评测。COMMITTED 仅表示本地事务提交，不是外部办理回执。','notice'));
   list(['记录标识','工具','模式 / 结果'],entry.records,r=>[r.id,r.tool,[r.mode,r.decision].filter(Boolean).join(' / ')],r=>onInspect('本地调用轨迹摘要',r),parent);
  }
  if(entry.examples.length){parent.append(el('h3','演示实例 / 输入输出（未执行）'),el('p','以下是设计讲解材料，不计入真实实例或调用记录。'));for(const example of entry.examples)parent.append(el('pre',JSON.stringify(example,null,2),'type-json'));}
 }
 function topology(entry,parent){
  const all=new Map(options.catalog.entries.map(e=>[e.id,e]));
  const refs=[...new Set([...entry.references,...options.catalog.entries.filter(e=>e.references.includes(entry.id)).map(e=>e.id)])];
  parent.append(el('p','类型契约拓扑：实线表示已实现类型的结构引用，虚线表示部分实现或设计引用；连线不表示已调用或业务已执行。查看真实业务边请进入“实例 / 记录”。','graph-note'));
  const box=el('div',undefined,'graph type-graph'),svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 1000 640');svg.setAttribute('aria-label','四类类型关联拓扑');
  const make=(tag,attrs,text)=>{const n=document.createElementNS(svg.namespaceURI,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text)n.textContent=text;return n;};
  const visible=refs.slice(0,12);const points=new Map([[entry.id,[500,320]]]);visible.forEach((id,i)=>{const angle=i*2*Math.PI/visible.length;points.set(id,[500+345*Math.cos(angle),320+245*Math.sin(angle)]);});
  for(const id of visible){const n=all.get(id),[x,y]=points.get(id);const line=make('line',{x1:500,y1:320,x2:x,y2:y,stroke:n.status==='implemented'&&entry.status==='implemented'?'#9a7fcc':'#b89655','stroke-width':2,'stroke-dasharray':n.status==='implemented'&&entry.status==='implemented'?'none':'6 5'});line.append(make('title',{},'类型结构引用（非执行）'));line.onclick=()=>options.onInspect('类型结构引用',{source:entry.id,target:id,meaning:'涉及/输入/输出/关联类型，非执行证明'});svg.append(line);}
  for(const id of [entry.id,...visible]){const e=all.get(id),[x,y]=points.get(id),g=make('g',{role:'button',tabindex:0,class:'node','aria-label':e.label+' '+e.name,transform:`translate(${x},${y})`});g.append(make('rect',{x:-100,y:-31,width:200,height:62,rx:10,fill:id===entry.id?'#48305f':'#211c2d',stroke:e.status==='implemented'?'#68c6ad':e.status==='partial'?'#d8b66c':'#b09bd5','stroke-dasharray':e.status==='design'?'5 3':'none'}),make('text',{y:-5,'text-anchor':'middle',fill:'#eee8fa','font-size':13},e.label),make('text',{y:17,'text-anchor':'middle',fill:'#c8bbd6','font-size':10},e.kind+' · '+e.statusLabel));const click=()=>select(id,true);g.onclick=click;g.onkeydown=ev=>{if(ev.key==='Enter')click();};svg.append(g);}
  box.append(svg);parent.append(box);if(refs.length>visible.length)parent.append(el('p',`图中展示前 ${visible.length} 个直接引用；全部 ${refs.length} 个引用如下，可点击查看。`));
  const links=el('div',undefined,'type-ref-list');for(const id of refs)links.append(button(all.get(id).label+' · '+all.get(id).kind,()=>select(id,true)));parent.append(links);
 }
 function draw(){
  const {catalog,view,query,onInspect}=options,content=document.getElementById('content');content.replaceChildren();
  const kind=kindFor[view],entries=catalog.entries.filter(e=>e.kind===kind&&JSON.stringify(e).toLowerCase().includes(query.toLowerCase()));
  content.append(el('p',catalog.schemaNote,'notice'));
  const counts=el('div',undefined,'type-counts');for(const [status,label]of [['implemented','已实现'],['partial','部分实现'],['design','设计示例']])counts.append(el('span',label+' '+entries.filter(e=>e.status===status).length,'type-status '+status));content.append(counts);
  const cards=el('div',undefined,'type-cards');for(const e of entries){const b=button('',()=>select(e.id));b.className='type-card'+(selected===e.id?' selected':'');b.append(badge(e),el('strong',e.label),el('code',e.name));const count=e.classId?e.instanceIds.length:e.relationId?e.relationCount:e.recordCount;b.append(el('small',`${e.classId?'真实实例':e.relationId?'真实关联':'本地调用记录'} ${count}${e.executionUrl?(e.kind==='FunctionType'?' · 可调用查看结果':e.kind==='ActionType'?' · 可执行查看回执':' · 可打开执行台'):''}`));cards.append(b);}content.append(cards);
  // A topology click can navigate across families without changing sidebar selection.
  let entry=selected&&catalog.entries.find(e=>e.id===selected);
  if(!entry||(!entries.some(e=>e.id===entry.id)&&tab!=='topology'))entry=entries[0];
  if(!entry){content.append(el('p','没有匹配类型。','empty'));return;}selected=entry.id;
  const inspectionKey=options.catalog.version+':'+entry.id;if(lastInspected!==inspectionKey){onInspect(entry.label,entry.definition);lastInspected=inspectionKey;}
  const panel=el('section',undefined,'type-panel');panel.append(badge(entry),el('h2',entry.label+' · '+entry.kind),el('p',entry.statusDetail));
  if(entry.executionUrl){const run=el('a',entry.kind==='FunctionType'?'调用函数 / 查看结果 ↗':entry.kind==='ActionType'?'执行本地动作 / 查看审计 ↗':'打开对象与关系执行台 ↗');run.href=entry.executionUrl;run.target='_blank';panel.append(run);}
  const tabs=el('div',undefined,'type-tabs');tabs.setAttribute('role','tablist');
  for(const [id,label]of [['definition','JSON 定义'],['instances','实例 / 记录'],['topology','关联拓扑'],['article','深度剖析']]){const b=button(label,()=>{tab=id;page=1;draw();});b.setAttribute('role','tab');b.setAttribute('aria-selected',String(tab===id));tabs.append(b);}panel.append(tabs);
  if(tab==='definition'){panel.append(el('p','定义来源：'+entry.source.map(s=>s.replace('{version}',catalog.version)).join('；'),'graph-note'));panel.append(el('pre',JSON.stringify(entry.definition,null,2),'type-json'));panel.append(button('在右侧查看原始 JSON',()=>onInspect(entry.label,entry.definition)));}
  if(tab==='instances')instances(entry,panel);
  if(tab==='topology')topology(entry,panel);
  if(tab==='article')article(entry.kind,panel);
  content.append(panel);
 }
 return {render:o=>{options=o;draw();},reset};
})();
