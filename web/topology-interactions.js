/* SVG layout interactions. No edits to objects, relationships or source data. */
window.OntoCareTopology=(()=>{
 const layouts=new Map();
 function mount({svg,group,nodes,edges,points,layoutKey,nodeLabel,edgeLabel,onNode,onEdge}){
  const make=(tag,attrs,text)=>{const n=document.createElementNS(svg.namespaceURI,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;return n;};
  const defaults=new Map([...points].map(([id,p])=>[id,[...p]]));
  if(!layouts.has(layoutKey))layouts.set(layoutKey,{points:new Map(),bends:new Map(),scale:1,tx:0,ty:0});
  const layout=layouts.get(layoutKey),nodeViews=new Map(),edgeViews=[];
  for(const[id,p]of layout.points)if(points.has(id))points.set(id,[...p]);
  const edgeLayer=make('g',{'aria-label':'关系连线'}),nodeLayer=make('g',{'aria-label':'对象节点'});group.append(edgeLayer,nodeLayer);
  let drag=null,selected=null;
  const point=(event,target)=>{
   const p=svg.createSVGPoint();p.x=event.clientX;p.y=event.clientY;
   return p.matrixTransform(target.getScreenCTM().inverse());
  };
  const transform=()=>group.setAttribute('transform',`translate(${layout.tx},${layout.ty}) scale(${layout.scale})`);
  const boundary=(center,toward)=>{
   const dx=toward[0]-center[0],dy=toward[1]-center[1],denom=Math.max(Math.abs(dx)/86,Math.abs(dy)/27);
   if(!denom)return [...center];
   const t=Math.min(1,1/denom);return [center[0]+dx*t,center[1]+dy*t];
  };
  function update(){
   for(const[id,g]of nodeViews){const[x,y]=points.get(id);g.setAttribute('transform',`translate(${x},${y})`);}
   for(const v of edgeViews){
    const a=points.get(v.edge.source),b=points.get(v.edge.target),bend=layout.bends.get(v.key)||[0,0];
    const middle=[(a[0]+b[0])/2,(a[1]+b[1])/2],control=[middle[0]+2*bend[0],middle[1]+2*bend[1]];
    const start=boundary(a,control),end=boundary(b,control),label=[(start[0]+2*control[0]+end[0])/4,(start[1]+2*control[1]+end[1])/4];
    const loop=v.edge.source===v.edge.target;
    if(loop){label[0]=a[0]+bend[0];label[1]=a[1]-88+bend[1];}
    const d=loop?`M ${a[0]-40} ${a[1]-24} C ${a[0]-130+bend[0]} ${a[1]-135+bend[1]}, ${a[0]+130+bend[0]} ${a[1]-135+bend[1]}, ${a[0]+40} ${a[1]-24}`:`M ${start[0]} ${start[1]} Q ${control[0]} ${control[1]} ${end[0]} ${end[1]}`;
    v.path.setAttribute('d',d);v.hit.setAttribute('d',d);v.label.setAttribute('transform',`translate(${label[0]},${label[1]-7})`);
   }
  }
  function select(kind,id,value){
   if(selected)selected.classList.remove('selected');
   selected=kind==='node'?nodeViews.get(id):edgeViews.find(v=>v.key===id)?.element;
   selected?.classList.add('selected');kind==='node'?onNode(value):onEdge(value);
  }
  const begin=(event,kind,id,value)=>{
   if(event.button!==0)return;
   event.preventDefault();event.stopPropagation();
   const local=point(event,group),root=point(event,svg);
   drag={kind,id,value,start:local,root,startClient:[event.clientX,event.clientY],origin:kind==='node'?[...points.get(id)]:kind==='edge'?[...(layout.bends.get(id)||[0,0])]:[layout.tx,layout.ty],moved:false};
   svg.setPointerCapture(event.pointerId);svg.classList.add('is-dragging');
  };
  for(const edge of edges){
   if(!points.has(edge.source)||!points.has(edge.target))continue;
   const key=JSON.stringify([edge.source,edge.relation,edge.target]);
   const a=points.get(edge.source),b=points.get(edge.target);
   const g=make('g',{class:'topology-edge'+(Math.abs(a[1]-b[1])<60?' edge-horizontal':''),'data-edge-key':key,tabindex:0,role:'button','aria-label':edgeLabel(edge)});
   const path=make('path',{class:'edge-line',fill:'none','marker-end':'url(#edgeArrow)'}),hit=make('path',{class:'edge-hit',fill:'none',stroke:'transparent','stroke-width':18});
   const label=make('g',{class:'edge-label'}),text=make('text',{'text-anchor':'middle','font-size':12},edgeLabel(edge));
   const labelWidth=Math.max(66,[...edgeLabel(edge)].length*10+14);label.append(make('rect',{x:-labelWidth/2,y:-15,width:labelWidth,height:23,rx:5}),text);
   g.append(make('title',{},'点击查看关系；拖动连线或标签调整走线'),path,hit,label);edgeLayer.append(g);
   g.onpointerdown=e=>begin(e,'edge',key,edge);g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select('edge',key,edge);}};
   g.onclick=e=>{if(e.detail===0)select('edge',key,edge);};edgeViews.push({key,edge,element:g,path,hit,label});
  }
  for(const node of nodes){
   const g=make('g',{class:'node topology-node','data-node-id':node.id,tabindex:0,role:'button','aria-label':nodeLabel(node)});
   g.append(make('title',{},'点击查看内容；拖动调整节点位置'),make('rect',{x:-83,y:-24,width:166,height:48,rx:10}),make('text',{x:0,y:5,'text-anchor':'middle','font-size':12},nodeLabel(node)));
   g.onpointerdown=e=>begin(e,'node',node.id,node);g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select('node',node.id,node);}};
   g.onclick=e=>{if(e.detail===0)select('node',node.id,node);};nodeLayer.append(g);nodeViews.set(node.id,g);
  }
  svg.onpointerdown=e=>begin(e,'canvas',null,null);
  svg.onpointermove=e=>{
   if(!drag)return;
   if(Math.hypot(e.clientX-drag.startClient[0],e.clientY-drag.startClient[1])>4)drag.moved=true;
   if(!drag.moved)return;
   const p=point(e,drag.kind==='canvas'?svg:group),start=drag.kind==='canvas'?drag.root:drag.start;
   const next=[drag.origin[0]+p.x-start.x,drag.origin[1]+p.y-start.y];
   if(drag.kind==='node'){points.set(drag.id,next);layout.points.set(drag.id,next);update();}
   else if(drag.kind==='edge'){layout.bends.set(drag.id,next);update();}
   else{[layout.tx,layout.ty]=next;transform();}
  };
  const end=(e,cancel=false)=>{
   if(!drag)return;const last=drag;drag=null;svg.classList.remove('is-dragging');
   if(svg.hasPointerCapture(e.pointerId))svg.releasePointerCapture(e.pointerId);
   if(!cancel&&!last.moved&&last.kind!=='canvas')select(last.kind,last.id,last.value);
  };
  svg.onpointerup=e=>end(e);svg.onpointercancel=e=>end(e,true);svg.onlostpointercapture=()=>{drag=null;svg.classList.remove('is-dragging');};
  svg.onwheel=e=>{
   e.preventDefault();if(drag)return;
   const local=point(e,group),root=point(e,svg);layout.scale=Math.max(.35,Math.min(3,layout.scale*(e.deltaY>0?.9:1.1)));
   layout.tx=root.x-local.x*layout.scale;layout.ty=root.y-local.y*layout.scale;transform();
  };
  transform();update();
  return {reset(){layout.points.clear();layout.bends.clear();layout.scale=1;layout.tx=layout.ty=0;for(const[id,p]of defaults)points.set(id,[...p]);transform();update();}};
 }
 return {mount};
})();
