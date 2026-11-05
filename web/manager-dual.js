/* Read-only projection of existing type contracts and workbench objects. */
window.OntoCareDual=(()=>{
 'use strict';
 let selectedClass='ProductModel',selectedOperation=null,limit=30,showAll=true;
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 function render({data,catalog,query,onClass,onNode,onOperation}){
  const content=document.getElementById('content');content.replaceChildren();
  const classes=data.classes.filter(c=>!query||JSON.stringify(c).toLowerCase().includes(query.toLowerCase()));
  if(!data.classes.some(c=>c.id===selectedClass))selectedClass=data.classes[0]?.id;
  const entries=catalog.entries.filter(e=>['ActionType','FunctionType'].includes(e.kind)).filter(e=>!query||JSON.stringify(e).toLowerCase().includes(query.toLowerCase()));
  const valid=new Set(data.classes.map(c=>c.id));
  // Only project explicit references, object-typed inputs, and declared link endpoints.
  function connections(entry){
   const found=new Map();
   function add(id,reason){if(!valid.has(id))return;if(!found.has(id))found.set(id,new Set());found.get(id).add(reason);}
   for(const ref of entry.references||[]){
    if(ref.startsWith('object:'))add(ref.slice(7),'契约对象引用');
    if(ref.startsWith('link:')){const link=catalog.entries.find(e=>e.id===ref);for(const side of ['from','to'])if(link?.definition?.[side])add(link.definition[side],`关联类型 ${link.name} 的${side==='from'?'起点':'终点'}（间接）`);}
   }
   function inspectSchema(value,path){if(!value||typeof value!=='object')return;if(value.properties?.objectType?.const)add(value.properties.objectType.const,`输入参数 ${path} 的对象类型`);for(const [key,v] of Object.entries(value.properties||{}))inspectSchema(v,path?path+'.'+key:key);for(const option of value.oneOf||[])inspectSchema(option,path);if(value.items)inspectSchema(value.items,path+'[]');}
   inspectSchema(entry.definition?.inputSchema,'');
   return found;
  }
  const links=new Map(entries.map(e=>[e.id,connections(e)]));
  const cls=data.classes.find(c=>c.id===selectedClass);
  const records=data.nodes.filter(n=>n.type===selectedClass);
  const area=el('div',undefined,'dual-view');
  const intro=el('div',undefined,'dual-intro');intro.append(el('span','ONTOCARE · DUAL ONTOLOGY','dual-eyebrow'),el('h2','从数据对象到服务决策'),el('p','以 Service 和 Decision 两个视图理解同一业务底座：选择操作查看契约引用；选择数据类查看真实实例与来源。'));
  const note=el('div','连线依据：契约对象引用、对象类型输入参数，及所引用关联类型的两端（间接）。连线表示声明或结构依赖，不表示已执行、已授权或已核实业务事实；外部退款和换货未接入。','dual-note');
  const controls=el('div',undefined,'dual-controls');const toggle=el('button',showAll?'显示全部关联':'只显示选中操作','dual-toggle');toggle.type='button';toggle.onclick=()=>{showAll=!showAll;render({data,catalog,query,onClass,onNode,onOperation});};controls.append(toggle,el('span','点击操作查看关联依据；滚动列表可查看其他连线。','dual-hint'));
  const grid=el('div',undefined,'dual-grid');
  function column(title,subtitle){const c=el('section',undefined,'dual-column');const h=el('div',undefined,'dual-heading');h.append(el('small',subtitle),el('h3',title));c.append(h);grid.append(c);return c;}
  const operations=column('操作与决策','DECISION ONTOLOGY');
  const objects=column('业务数据对象','SERVICE ONTOLOGY');
  const instances=column('实例与资料来源','SOURCE DATA · CURRENT VERSION');
  operations.append(el('p','函数读取或判断数据；动作只表示契约及其实际能力状态。','dual-description'));
  const oplist=el('div',undefined,'dual-list');
  for(const e of entries){const b=el('button',undefined,'dual-row operation'+(selectedOperation===e.id?' active':''));b.type='button';b.dataset.operationId=e.id;b.append(el('span',e.label,'dual-name'),el('small',e.kind==='ActionType'?'动作':'函数','dual-tag '+(e.kind==='ActionType'?'action':'query')),el('small',e.statusLabel||e.status,'dual-status'));b.title=e.name+' · '+e.id;b.onclick=()=>{selectedOperation=e.id;const ref=links.get(e.id).keys().next().value;if(ref)selectedClass=ref;limit=30;render({data,catalog,query,onClass,onNode,onOperation});onOperation({...e,objectConnections:[...links.get(e.id)].map(([objectType,basis])=>({objectType,basis:[...basis]}))});};oplist.append(b);}
  if(!entries.length)oplist.append(el('p','没有匹配的操作。','dual-empty'));operations.append(oplist);
  objects.append(el('p',selectedOperation?'高亮对象为所选操作在类型契约中声明引用的对象。':'选择对象后，右侧展示该类的实际实例。','dual-description'));
  const refs=new Set(links.get(selectedOperation)?.keys()||[]);
  const objectlist=el('div',undefined,'dual-list');
  for(const c of classes){const b=el('button',undefined,'dual-row object'+(c.id===selectedClass?' active':'')+(refs.has(c.id)?' referenced':''));b.type='button';b.dataset.classId=c.id;b.append(el('span',c.label,'dual-name'),el('code',c.id),el('small',String(c.count),'dual-count'));b.onclick=()=>{selectedClass=c.id;selectedOperation=null;limit=30;render({data,catalog,query,onClass,onNode,onOperation});};objectlist.append(b);}
  if(!classes.length)objectlist.append(el('p','没有匹配的对象类。','dual-empty'));objects.append(objectlist);
  const sourceHead=el('div',undefined,'dual-source-head');sourceHead.append(el('strong',cls?.label||'选择对象'),el('span',records.length+' 个实例'));instances.append(sourceHead,el('p','数据来自当前工作台版本；点击查看属性、来源与关联。','dual-description'));
  if(cls){const detail=el('button','查看类定义与全部实例','dual-detail-button');detail.type='button';detail.onclick=()=>onClass(cls);instances.append(detail);}
  const list=el('div',undefined,'dual-list dual-records');
  for(const n of records.slice(0,limit)){const b=el('button',undefined,'dual-record');b.type='button';b.append(el('span',n.zh||n.label,'dual-record-name'),el('small',n.id,'dual-record-id'));b.onclick=()=>onNode(n.id);list.append(b);}
  if(!records.length)list.append(el('p','此类当前没有实例。','dual-empty'));instances.append(list);
  if(records.length>limit){const more=el('button','显示更多实例','dual-more');more.type='button';more.onclick=()=>{limit+=30;render({data,catalog,query,onClass,onNode,onOperation});};instances.append(more);}
  const foot=el('p','数据本体与操作本体是业务视图：部分条件、规则和操作共同约束服务流程。具体执行和可用性以契约状态及工具回执为准。','dual-footer');
  area.append(intro,window.OntoCareReturnCase.render({catalog,data,onClass,onOperation}),note,controls,grid,foot);content.append(area);
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('class','dual-connectors');svg.setAttribute('aria-hidden','true');grid.append(svg);
  function connect(){
   svg.replaceChildren();const bounds=grid.getBoundingClientRect();if(!bounds.width)return;
   svg.setAttribute('viewBox',`0 0 ${bounds.width} ${bounds.height}`);
   function line(a,b,color){if(!a||!b)return;const x=a.getBoundingClientRect(),y=b.getBoundingClientRect(),ac=a.closest('.dual-list')?.getBoundingClientRect(),bc=b.closest('.dual-list')?.getBoundingClientRect();if(ac&&(x.bottom<ac.top||x.top>ac.bottom)||bc&&(y.bottom<bc.top||y.top>bc.bottom))return;const sx=x.right-bounds.left,sy=x.top+x.height/2-bounds.top,ex=y.left-bounds.left,ey=y.top+y.height/2-bounds.top;const path=document.createElementNS(ns,'path');path.setAttribute('d',`M ${sx} ${sy} C ${sx+30} ${sy}, ${ex-30} ${ey}, ${ex} ${ey}`);path.setAttribute('stroke',color);path.setAttribute('fill','none');path.setAttribute('stroke-width','2');svg.append(path);}
   for(const operation of oplist.querySelectorAll('.operation')){
    if(!showAll&&operation.dataset.operationId!==selectedOperation)continue;
    for(const target of objectlist.querySelectorAll('.object'))if(links.get(operation.dataset.operationId)?.has(target.dataset.classId))line(operation,target,operation.dataset.operationId===selectedOperation?'#59e5d3':'#675589');
   }
   line(objectlist.querySelector('.object.active'),sourceHead,'#ad8bef');
  }
  requestAnimationFrame(connect);for(const scrollList of [oplist,objectlist,list])scrollList.addEventListener('scroll',connect);if(typeof ResizeObserver!=='undefined'){const observer=new ResizeObserver(()=>{if(!grid.isConnected){observer.disconnect();return;}connect();});observer.observe(grid);}

 }
 return {render};
})();
