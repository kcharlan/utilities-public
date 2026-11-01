import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const window={preact:{h(){}},preactHooks:{},htm:{bind(){}}};
vm.runInNewContext(readFileSync(new URL('../frontend_vendor/svg_charts.js',import.meta.url),'utf8'),{window});
const g=window.svgCharts.geometry;
const plain=x=>JSON.parse(JSON.stringify(x));
test('stack accumulates values and sign separates positive and negative',()=>{
 assert.deepEqual(plain(g.stack([{a:2,b:3}],['a','b'],'none')),[[[0,2]],[[2,5]]]);
 assert.deepEqual(plain(g.stack([{a:2,b:-3,c:-1}],['a','b','c'],'sign')),[[[0,2]],[[0,-3]],[[-3,-4]]]);
});
test('nice ticks cover domain with round values and handle equal bounds',()=>{
 const t=g.niceTicks(1.1,9.1,5);assert.ok(t[0]<=1.1&&t.at(-1)>=9.1);assert.ok(t.length>=2);assert.ok(g.niceTicks(0,0,5).every(Number.isFinite));
});
test('zero width scale returns midpoint',()=>assert.equal(g.linearScale([2,2],[10,20])(2),15));
test('monotone path includes points and keeps a flat segment flat',()=>{
 const p=g.monotonePath([[0,0],[1,1],[2,1],[3,0]]);assert.match(p,/1[, ]1/);assert.match(p,/2[, ]1/);assert.match(p,/C[^C]*1[^C]*1[^C]*2[, ]1/);
 assert.equal(g.monotonePath([]),'');assert.match(g.monotonePath([[1,2]]),/^M\s*1[, ]2/);
});
const curveSegments=path=>[...path.matchAll(/C([^ ]+) ([^ ]+) ([^CL]+)/g)].map(match=>match.slice(1).map(pair=>pair.split(',').map(Number)));
test('monotone curve control points never overshoot their segment',()=>{
 const cases=[[[0,0],[1,1],[2,1],[3,0]],[[0,0],[1,10],[2,10.5],[3,30],[4,30],[5,2]],[[0,5],[2,1],[3,9],[7,9],[8,0]]];
 for(const points of cases) {
  const segments=curveSegments(g.monotonePath(points));assert.equal(segments.length,points.length-1);
  segments.forEach(([c1,c2,end],i)=>{
   const lo=Math.min(points[i][1],end[1]),hi=Math.max(points[i][1],end[1]);
   for(const control of [c1,c2]) assert.ok(control[1]>=lo-1e-9&&control[1]<=hi+1e-9,`segment ${i} control ${control[1]} outside ${lo}..${hi}`);
  });
 }
});
test('monotone curve matches the old d3 monotoneX tangents and draws two points straight',()=>{
 assert.equal(g.monotonePath([[0,0],[3,3]]),'M0,0L3,3');
 const [first]=curveSegments(g.monotonePath([[0,0],[3,3],[6,0]]));
 assert.deepEqual(first,[[1,1.5],[2,3],[3,3]]);
});
test('full circular arcs and degenerate geometry remain finite',()=>{
 const arc=g.arcPath(0,0,4,8,0,Math.PI*2);assert.ok((arc.match(/A/g)||[]).length>=4);
 const results=[g.monotonePath([]),g.monotonePath([[0,0]]),g.areaPath([],[]),g.arcPath(0,0,0,0,0,0),JSON.stringify(g.stack([{}],['x'],'sign')),JSON.stringify(g.niceTicks(0,0,5))];
 for(const r of results)assert.doesNotMatch(r,/NaN|Infinity/);
});
test('components expose selectors, selection keys and tooltip payloads',()=>{
 let state=[],cursor=0,effects=[];const h=(tag,props,...children)=>({tag,props:props||{},children:children.flat(Infinity).filter(Boolean)});
 const hooks={useRef:()=>({current:null}),useState(initial){const i=cursor++;return [state[i]??initial,value=>{state[i]=value;}];},useEffect:fn=>effects.push(fn)};
 const w={preact:{h},preactHooks:hooks};vm.runInNewContext(readFileSync(new URL('../frontend_vendor/svg_charts.js',import.meta.url),'utf8'),{window:w});
 const find=(tree,predicate)=>{if(predicate(tree))return tree;for(const child of tree.children||[])if(typeof child==='object'){const result=find(child,predicate);if(result)return result;}return null;};
 let selected=null,payload=null;const item={label:'A very long synthetic label',value:7,color:'var(--demo)'};
 const render=()=>{cursor=0;return w.svgCharts.HBarChart({items:[item],labelMaxChars:6,onSelect:value=>selected=value,tooltip:value=>{payload=value;return 'tip';}});};
 let tree=render(),bar=find(tree,n=>n.props?.class==='svgc-bar');assert.equal(bar.props.role,'button');let prevented=false;bar.props.onKeyDown({key:' ',preventDefault(){prevented=true;}});assert.equal(selected,item);assert.equal(prevented,true);
 const title=find(tree,n=>n.tag==='title');assert.equal(title.children[0],item.label);
 find(tree,n=>n.props?.class==='svgc-wrapper').props.onMouseMove({clientX:300,clientY:100,currentTarget:{getBoundingClientRect:()=>({left:0,top:0})}});tree=render();assert.equal(payload.label,item.label);assert.equal(payload.payload[0].payload,item);assert.equal(payload.payload[0].value,7);
 const donut=w.svgCharts.DonutChart({items:[item],onSelect:value=>selected=value});assert.equal(find(donut,n=>n.props?.class==='svgc-sector').props.role,'button');
});
test('cartesian plot renders references, curves and nearest-row tooltip',()=>{
 let state=[],cursor=0,payload;const h=(tag,props,...children)=>({tag,props:props||{},children:children.flat(Infinity).filter(x=>x!=null&&x!==false)});
 const hooks={useRef:()=>({current:null}),useState(initial){const i=cursor++;return [state[i]??initial,value=>state[i]=value];},useEffect(){}};
 const w={preact:{h},preactHooks:hooks};vm.runInNewContext(readFileSync(new URL('../frontend_vendor/svg_charts.js',import.meta.url),'utf8'),{window:w});
 const find=(tree,predicate)=>{if(predicate(tree))return tree;for(const child of tree.children||[])if(typeof child==='object'){const result=find(child,predicate);if(result)return result;}return null;};
 const data=[{bucket:'a',v:1},{bucket:'b',v:2}];const render=()=>{cursor=0;return w.svgCharts.CartesianChart({data,xKey:'bucket',series:[{key:'v',color:'var(--demo)'}],width:300,referenceX:'b',plotClass:'plot',tooltip:p=>{payload=p;return 'tip';}});};
 let tree=render();assert.ok(find(tree,n=>n.props?.class==='svgc-area'));assert.ok(find(tree,n=>n.props?.class==='plot'));assert.equal(find(tree,n=>n.props?.class==='svgc-reference-line').props.x,'b');
 find(tree,n=>n.props?.class==='svgc-wrapper').props.onMouseMove({clientX:290,clientY:30,currentTarget:{getBoundingClientRect:()=>({left:0,top:0})}});tree=render();assert.equal(payload.label,'b');assert.equal(payload.payload[0].payload,data[1]);
});
test('bar charts group independent series and share a slot for stacked series',()=>{
 const h=(tag,props,...children)=>({tag,props:props||{},children:children.flat(Infinity).filter(Boolean)});
 const w={preact:{h},preactHooks:{useRef:()=>({current:null}),useState:value=>[value,()=>{}],useEffect(){}}};
 vm.runInNewContext(readFileSync(new URL('../frontend_vendor/svg_charts.js',import.meta.url),'utf8'),{window:w});
 const bars=series=>{const root=w.svgCharts.CartesianChart({kind:'bar',data:[{a:3,b:5,c:2}],series,width:300});const out=[];const visit=n=>{if(n.props?.class==='svgc-bar')out.push(n.props);for(const c of n.children||[])if(typeof c==='object')visit(c);};visit(root);return out;};
 const grouped=bars([{key:'a'},{key:'b'}]);assert.ok(grouped[0].x+grouped[0].width<=grouped[1].x);
 const mixed=bars([{key:'a',stack:true},{key:'b',stack:true},{key:'c'}]);assert.equal(mixed[0].x,mixed[1].x);assert.equal(mixed[0].width,mixed[1].width);assert.ok(mixed[1].x+mixed[1].width<=mixed[2].x);
});
test('bar charts forward series stroke styling',()=>{
 const h=(tag,props,...children)=>({tag,props:props||{},children:children.flat(Infinity).filter(Boolean)});
 const w={preact:{h},preactHooks:{useRef:()=>({current:null}),useState:value=>[value,()=>{}],useEffect(){}}};
 vm.runInNewContext(readFileSync(new URL('../frontend_vendor/svg_charts.js',import.meta.url),'utf8'),{window:w});
 const root=w.svgCharts.CartesianChart({kind:'bar',data:[{a:3}],series:[{key:'a',color:'var(--demo)',strokeWidth:4,strokeOpacity:.5,strokeDasharray:'5 3'}],width:300});
 let bar;const visit=n=>{if(n.props?.class==='svgc-bar')bar=n.props;for(const c of n.children||[])if(typeof c==='object')visit(c);};visit(root);
 assert.equal(bar.stroke,'var(--demo)');assert.equal(bar['stroke-width'],4);assert.equal(bar['stroke-opacity'],.5);assert.equal(bar['stroke-dasharray'],'5 3');
});
function renderCartesian(props) {
 const h=(tag,attrs,...children)=>({tag,props:attrs||{},children:children.flat(Infinity).filter(x=>x!==null&&x!==undefined&&x!==false)});
 const w={preact:{h},preactHooks:{useRef:()=>({current:null}),useState:value=>[value,()=>{}],useEffect(){}}};
 vm.runInNewContext(readFileSync(new URL('../frontend_vendor/svg_charts.js',import.meta.url),'utf8'),{window:w});
 const root=w.svgCharts.CartesianChart({data:[{x:'a',v:0},{x:'b',v:11},{x:'c',v:7}],xKey:'x',series:[{key:'v'}],width:300,height:200,...props});
 const nodes=[];const visit=n=>{nodes.push(n);for(const c of n.children||[])if(typeof c==='object')visit(c);};visit(root);return nodes;
}
test('grid directions align with displayed x ticks and carry configured stroke',()=>{
 const nodes=renderCartesian({tickEvery:2,grid:{horizontal:false,vertical:true,stroke:'var(--grid)',strokeDasharray:'2 4'}});
 assert.equal(nodes.filter(n=>n.props.class==='svgc-grid-horizontal').length,0);
 const vertical=nodes.filter(n=>n.props.class==='svgc-grid-vertical');assert.equal(vertical.length,2);
 const xLabels=nodes.filter(n=>n.tag==='text'&&n.props['text-anchor']==='middle');assert.deepEqual(vertical.map(n=>n.props.x1),xLabels.map(n=>n.props.x));
 assert.ok(vertical.every(n=>n.props.stroke==='var(--grid)'&&n.props['stroke-dasharray']==='2 4'));
 const horizontal=renderCartesian({grid:true}).filter(n=>n.props.class==='svgc-grid-horizontal');assert.ok(horizontal.length>0);
 assert.equal(renderCartesian({grid:false}).filter(n=>String(n.props.class).startsWith('svgc-grid-')).length,0);
 assert.equal(renderCartesian({grid:{horizontal:true,vertical:false}}).filter(n=>n.props.class==='svgc-grid-vertical').length,0);
});
test('optional x axis line uses requested stroke and defaults off',()=>{
 assert.equal(renderCartesian({}).filter(n=>n.props.class==='svgc-x-axis-line').length,0);
 const line=renderCartesian({xAxisLine:'var(--border)'}).find(n=>n.props.class==='svgc-x-axis-line');
 assert.equal(line.props.stroke,'var(--border)');assert.equal(line.props.y1,line.props.y2);
 assert.ok(renderCartesian({xAxisLine:true}).some(n=>n.props.class==='svgc-x-axis-line'));
});
test('explicit numeric y domains bound ticks and retain endpoints including degenerate domains',()=>{
 for(const [lo,hi] of [[0,11],[0,24],[-3,7],[4,4]]) {
  const labels=renderCartesian({yDomain:[lo,hi],data:[{x:'a',v:lo},{x:'b',v:hi}]}).filter(n=>n.tag==='text'&&n.props['text-anchor']==='end');
  const values=labels.map(n=>Number(n.children[0]));assert.ok(values.includes(lo));assert.ok(values.includes(hi));
  assert.ok(values.every(v=>Number.isFinite(v)&&v>=lo&&v<=hi));
  assert.ok(labels.every(n=>Number.isFinite(n.props.y)&&n.props.y>=10&&n.props.y<=175));
 }
});
test('tooltip placement flips and clamps to the chart and viewport intersection',()=>{
 const place=g.tooltipPosition;
 const chart={left:100,top:100,right:500,bottom:400};
 const viewport={left:0,top:0,right:450,bottom:350};
 const size={width:120,height:80};
 const right=place({x:390,y:220},size,chart,viewport);
 assert.ok(right.left>=0 && right.left+size.width<=350);
 assert.ok(right.top>=0 && right.top+size.height<=250);
 assert.ok(right.left<390);
 const corner=place({x:2,y:2},size,chart,viewport);
 assert.ok(corner.left>=0 && corner.top>=0);
 // Tall tooltips may leave the chart, as the old page's did, so a viewport-height
 // tooltip starts at the top of the viewport rather than the top of the chart.
 const oversized=place({x:50,y:50},{width:600,height:350},chart,viewport);
 assert.equal(oversized.left,0);assert.equal(oversized.top,-100);
});
test('all charts use a shared measured tooltip container with intrinsic width',()=>{
 const source=readFileSync(new URL('../frontend_vendor/svg_charts.js',import.meta.url),'utf8');
 const css=readFileSync(new URL('../frontend_vendor/svg_charts.css',import.meta.url),'utf8');
 assert.match(source,/useLayoutEffect/);assert.match(source,/function Tooltip\(/);
 assert.match(source,/getBoundingClientRect\(\)/);assert.match(css,/width:\s*max-content/);
 assert.equal((source.match(/tooltipNode\(tooltip,/g)||[]).length,4);
});
test('donut tooltip sits at the sector midpoint and horizontal bars track the pointer row',()=>{
 let state=[],cursor=0;const h=(tag,props,...children)=>({tag,props:props||{},children:children.flat(Infinity).filter(Boolean)});
 const hooks={useRef:()=>({current:null}),useState(initial){const i=cursor++;return [state[i]??initial,value=>state[i]=value];},useEffect(){}};
 const w={preact:{h},preactHooks:hooks};vm.runInNewContext(readFileSync(new URL('../frontend_vendor/svg_charts.js',import.meta.url),'utf8'),{window:w});
 const all=root=>{const nodes=[];const visit=n=>{nodes.push(n);for(const c of n.children||[])if(typeof c==='object')visit(c);};visit(root);return nodes;};
 const tip=root=>all(root).find(n=>typeof n.tag==='function');
 state=[];let render=()=>{cursor=0;return w.svgCharts.DonutChart({items:[{label:'synthetic',value:1},{label:'other',value:1}],height:200,cy:90,startAngle:0,tooltip:()=>null});};
 all(render()).find(n=>n.props.class==='svgc-sector').props.onMouseMove();
 let position=tip(render()).props.position;assert.ok(Math.abs(position.x-200)<1e-6);assert.equal(position.y,90+67.5);
 state=[];render=()=>{cursor=0;return w.svgCharts.HBarChart({items:[{label:'a',value:1},{label:'b',value:0}],height:205,tooltip:()=>null});};
 const wrapper=all(render()).find(n=>n.props.class==='svgc-wrapper');
 wrapper.props.onMouseMove({clientX:300,clientY:140,currentTarget:{getBoundingClientRect:()=>({left:0,top:0})}});
 const tooltip=tip(render());assert.equal(tooltip.props.position.x,300);assert.equal(tooltip.props.position.y,128.75);
});
test('constrained tooltip permits scrolling and keeps hover stable while interacting',()=>{
 let state=[],cursor=0,effect;const h=(tag,props,...children)=>({tag,props:props||{},children:children.flat(Infinity).filter(x=>x!=null&&x!==false)});
 const attrs={};const chart={getBoundingClientRect:()=>({left:0,top:0,right:200,bottom:60})};
 const node={parentElement:chart,style:{},scrollWidth:100,clientWidth:100,scrollHeight:120,clientHeight:60,
  getBoundingClientRect:()=>({width:100,height:60}),setAttribute:(k,v)=>attrs[k]=v,removeAttribute:k=>delete attrs[k]};
 const hooks={useRef:()=>({current:node}),useState(initial){const i=cursor++;return [state[i]??initial,value=>state[i]=value];},useEffect(){},useLayoutEffect:fn=>effect=fn};
 const focused={};const w={preact:{h},preactHooks:hooks,document:{activeElement:focused},innerWidth:400,innerHeight:400,addEventListener(){},removeEventListener(){}};
 vm.runInNewContext(readFileSync(new URL('../frontend_vendor/svg_charts.js',import.meta.url),'utf8'),{window:w});
 const find=(n,p)=>{if(p(n))return n;for(const c of n.children||[])if(typeof c==='object'){const result=find(c,p);if(result)return result;}return null;};
 const render=()=>{cursor=0;return w.svgCharts.CartesianChart({data:[{x:'synthetic',v:1}],xKey:'x',series:[{key:'v'}],width:200,height:60,tooltip:()=>h('div',null,'content')});};
 let root=render(),wrapper=find(root,n=>n.props.class==='svgc-wrapper');
 wrapper.props.onMouseMove({clientX:120,clientY:30,currentTarget:chart});
 root=render();const tooltip=find(root,n=>typeof n.tag==='function');const box=tooltip.tag({...tooltip.props,children:tooltip.children});effect();
 assert.equal(node.style.pointerEvents,'auto');assert.equal(attrs.tabindex,'0');assert.equal(attrs.role,'region');
 node.scrollHeight=60;effect();assert.equal(node.style.pointerEvents,'none');assert.equal(attrs.tabindex,undefined);
 node.scrollHeight=120;effect();
 let stopped=false;box.props.onMouseMove({stopPropagation(){stopped=true;}});assert.equal(stopped,true);
 wrapper=find(root,n=>n.props.class==='svgc-wrapper');wrapper.props.onMouseLeave({currentTarget:{contains:()=>true,querySelector:()=>({contains:value=>value===focused})}});
 root=render();assert.ok(find(root,n=>typeof n.tag==='function'));
 wrapper.props.onMouseLeave({currentTarget:{contains:()=>true,querySelector:()=>({contains:()=>false})}});
 root=render();assert.equal(find(root,n=>typeof n.tag==='function'),null);
});
function renderItemChart(name,props) {
 const h=(tag,attrs,...children)=>({tag,props:attrs||{},children:children.flat(Infinity).filter(x=>x!==null&&x!==undefined&&x!==false)});
 const w={preact:{h},preactHooks:{useRef:()=>({current:null}),useState:value=>[value,()=>{}],useEffect(){}}};
 vm.runInNewContext(readFileSync(new URL('../frontend_vendor/svg_charts.js',import.meta.url),'utf8'),{window:w});
 const nodes=[];const visit=n=>{nodes.push(n);for(const c of n.children||[])if(typeof c==='object')visit(c);};visit(w.svgCharts[name](props));return nodes;
}
test('selectable SVG marks expose lowercase tabindex and activate with Enter and Space',()=>{
 for(const [chart,cls] of [['DonutChart','svgc-sector'],['HBarChart','svgc-bar']]) {
  const item={label:'synthetic',value:4};let selected;const mark=renderItemChart(chart,{items:[item],onSelect:value=>selected=value}).find(n=>n.props.class===cls);
  assert.equal(mark.props.tabindex,0);assert.equal(mark.props.tabIndex,undefined);assert.equal(mark.props.role,'button');
  for(const key of ['Enter',' ']){let prevented=false;selected=null;mark.props.onKeyDown({key,preventDefault(){prevented=true;}});assert.equal(selected,item);assert.equal(prevented,true);}
 }
});
test('horizontal bar axis formats visible numeric ticks below bars for empty and populated charts',()=>{
 for(const items of [[],[{label:'a',value:0}],[{label:'a',value:12},{label:'b',value:4}]]) {
  const nodes=renderItemChart('HBarChart',{items,height:200,valueFormat:v=>`v=${v}`});
  const ticks=nodes.filter(n=>n.props.class==='svgc-hbar-tick');assert.ok(ticks.length>0);assert.ok(ticks.every(n=>String(n.children[0]).startsWith('v=')));
  const bars=nodes.filter(n=>n.props.class==='svgc-bar');assert.ok(bars.every(b=>ticks.every(t=>b.props.y+b.props.height<t.props.y)));
  assert.doesNotMatch(JSON.stringify(nodes),/NaN|Infinity/);
 }
});
test('donut supports configurable start, direction and sector outline without changing defaults',()=>{
 const items=[{label:'a',value:1},{label:'b',value:1}];
 const sectors=opts=>renderItemChart('DonutChart',{items,height:200,...opts}).filter(n=>n.props.class==='svgc-sector');
 const defaults=sectors({});assert.equal(defaults[0].props.d,g.arcPath(200,100,50,85,-Math.PI/2,Math.PI/2));assert.equal(defaults[0].props.stroke,undefined);
 const custom=sectors({startAngle:0,clockwise:false,stroke:'var(--edge)',strokeWidth:1});
 assert.equal(custom[0].props.d,g.arcPath(200,100,50,85,0,-Math.PI));assert.equal(custom[0].props.stroke,'var(--edge)');assert.equal(custom[0].props['stroke-width'],1);
 const full=renderItemChart('DonutChart',{items:[{label:'a',value:1}],startAngle:0,clockwise:false}).find(n=>n.props.class==='svgc-sector').props.d;assert.ok((full.match(/A/g)||[]).length>=4);assert.doesNotMatch(full,/NaN|Infinity/);
});
test('horizontal axis uses round ticks without crowding a near-maximum endpoint',()=>{
 const nodes=renderItemChart('HBarChart',{items:[{label:'synthetic',value:11}],height:200});
 const ticks=nodes.filter(n=>n.props.class==='svgc-hbar-tick');
 assert.deepEqual(ticks.map(n=>Number(n.children[0])),[0,3,6,9,12]);
 assert.ok(ticks.every(n=>n.props['text-anchor']==='middle'));
 const bar=nodes.find(n=>n.props.class==='svgc-bar');assert.ok(bar.props.x+bar.props.width<ticks.at(-1).props.x);
});
test('single-point area and line series expose finite visible and hidden value dots',()=>{
 for(const kind of ['area','line']) {
  const nodes=renderCartesian({kind,data:[{x:'only',a:1,b:0}],series:[{key:'a',color:'var(--value)',strokeOpacity:.8},{key:'b',color:'var(--hidden)',strokeOpacity:0}]});
  const dots=nodes.filter(n=>n.props.class==='svgc-point');assert.equal(dots.length,2);
  assert.equal(dots[0].tag,'circle');assert.equal(dots[0].props.fill,'var(--value)');assert.equal(dots[0].props.opacity,.8);
  assert.equal(dots[1].props.opacity,0);assert.ok(dots.every(n=>Number.isFinite(n.props.cx)&&Number.isFinite(n.props.cy)&&n.props.r>0));
 }
 assert.equal(renderCartesian({kind:'bar',data:[{x:'only',v:1}]}).filter(n=>n.props.class==='svgc-point').length,0);
 assert.equal(renderCartesian({kind:'line',data:[]}).filter(n=>n.props.class==='svgc-point').length,0);
});
test('rendered y ticks keep explicit bounds and adequate pixel separation',()=>{
 for(const height of [150,200,300]) {
  const labels=renderCartesian({height,yDomain:[0,1.05],data:[{x:'only',v:1}]}).filter(n=>n.tag==='text'&&n.props['text-anchor']==='end');
  const values=labels.map(n=>Number(n.children[0]));assert.ok(values.includes(0));assert.ok(values.includes(1.05));
  const ys=labels.map(n=>n.props.y).sort((a,b)=>a-b);for(let i=1;i<ys.length;i++)assert.ok(ys[i]-ys[i-1]>=20);
 }
 const tiny=renderCartesian({height:45,yDomain:[0,1.05]}).filter(n=>n.tag==='text'&&n.props['text-anchor']==='end');assert.ok(tiny.length<=1);
});
test('default formatted x tick selection adapts to width while explicit interval stays fixed',()=>{
 const data=Array.from({length:60},(_,i)=>({x:`item-${i}`,v:i}));
 const render=(width,extra={})=>renderCartesian({width,data,xFormat:(_,i)=>i, ...extra});
 const opts={xFormat:value=>`12:${String(Number(value.split('-')[1])).padStart(2,'0')}`,grid:{horizontal:false,vertical:true}};
 const labels=nodes=>nodes.filter(n=>n.tag==='text'&&n.props['text-anchor']==='middle');
 const wide=render(800,opts),narrow=render(320,opts);assert.ok(labels(wide).length<60);assert.ok(labels(narrow).length<labels(wide).length);
 for(const nodes of [wide,narrow]) {
  const x=labels(nodes).map(n=>n.props.x);for(let i=1;i<x.length;i++)assert.ok(x[i]-x[i-1]>=38);
  const grid=nodes.filter(n=>n.props.class==='svgc-grid-vertical').map(n=>n.props.x1);
  assert.equal(grid[0],55);assert.equal(grid.at(-1),nodes===wide?790:310);assert.ok(grid.length<x.length+2);
 }
 assert.equal(labels(render(600,{...opts,tickEvery:6})).length,10);
});
test('legend renders decorative type symbols and retains button toggling and hidden state',()=>{
 const h=(tag,props,...children)=>({tag,props:props||{},children:children.flat(Infinity).filter(x=>x!=null&&x!==false)});
 const w={preact:{h},preactHooks:{}};vm.runInNewContext(readFileSync(new URL('../frontend_vendor/svg_charts.js',import.meta.url),'utf8'),{window:w});
 let toggled;const series=[{key:'a',label:'Alpha',color:'var(--a)',strokeDasharray:'5 3'}];
 const line=w.svgCharts.Legend({series,kind:'line',hidden:new Set(['a']),onToggle:key=>toggled=key});
 const button=line.children[0],symbol=button.children[0];assert.equal(button.tag,'button');assert.equal(button.props['aria-pressed'],false);button.props.onClick();assert.equal(toggled,'a');
 assert.equal(symbol.tag,'svg');assert.equal(symbol.props['aria-hidden'],'true');assert.equal(symbol.children[0].tag,'path');assert.equal(symbol.children[0].props.stroke,'var(--a)');assert.equal(symbol.children[0].props['stroke-dasharray'],'5 3');
 for(const kind of ['area','line']) {const mark=w.svgCharts.Legend({series,kind}).children[0].children[0].children[0];assert.equal(mark.tag,'path');assert.equal(mark.props.fill,'none');assert.equal(mark.props['stroke-width'],4);}
 {const mark=w.svgCharts.Legend({series,kind:'bar'}).children[0].children[0].children[0];assert.equal(mark.tag,'path');assert.equal(mark.props.fill,'var(--a)');assert.equal(mark.props.stroke,'none');}
 assert.ok(button.children.includes('Alpha'));
});
test('optional y axis line and reference opacity preserve default behavior',()=>{
 const base=renderCartesian({referenceX:'a',referenceY:0});assert.equal(base.filter(n=>n.props.class==='svgc-y-axis-line').length,0);
 assert.ok(base.filter(n=>n.props.class==='svgc-reference-line').every(n=>n.props['stroke-opacity']===1));
 const custom=renderCartesian({referenceX:'a',referenceY:0,yAxisLine:'var(--axis)',referenceOpacity:.5});
 const line=custom.find(n=>n.props.class==='svgc-y-axis-line');assert.equal(line.props.stroke,'var(--axis)');assert.equal(line.props.x1,line.props.x2);
 assert.ok(custom.filter(n=>n.props.class==='svgc-reference-line').every(n=>n.props['stroke-opacity']===.5));
 assert.ok(renderCartesian({yAxisLine:true}).some(n=>n.props.class==='svgc-y-axis-line'));
});
function chartHarness(component,props) {
 let state=[],cursor=0;const h=(tag,attrs,...children)=>({tag,props:attrs||{},children:children.flat(Infinity).filter(x=>x!==null&&x!==undefined&&x!==false)});
 const hooks={useRef(initial=null){const i=cursor++;return state[i]??={current:initial};},useState(initial){const i=cursor++;return [i in state?state[i]:initial,value=>{state[i]=value;}];},useEffect(){}};
 const w={preact:{h},preactHooks:hooks};vm.runInNewContext(readFileSync(new URL('../frontend_vendor/svg_charts.js',import.meta.url),'utf8'),{window:w});
 const nodes=()=>{cursor=0;const out=[];const visit=n=>{out.push(n);for(const c of n.children||[])if(typeof c==='object')visit(c);};visit(w.svgCharts[component](props));return out;};
 const pick=cls=>nodes().filter(n=>n.props.class===cls);
 const moveTo=(x,y)=>pick('svgc-wrapper')[0].props.onMouseMove({clientX:x,clientY:y,currentTarget:{getBoundingClientRect:()=>({left:0,top:0}),querySelector:()=>null}});
 return {nodes,pick,moveTo,svg:()=>nodes().find(n=>n.tag==='svg')};
}
const rows=[{x:'a',p:2,q:3},{x:'b',p:4,q:1},{x:'c',p:1,q:6}];
const stackedSeries=[{key:'p',stack:true,color:'#111'},{key:'q',stack:true,color:'#222'}];
const finite=nodes=>assert.doesNotMatch(JSON.stringify(nodes.map(n=>n.props),(k,v)=>typeof v==='number'&&!Number.isFinite(v)?String(v):v),/NaN|Infinity/);
test('a series beyond the spread argument limit renders without a stack overflow',()=>{
 const data=Array.from({length:130000},(_,i)=>({x:`b${i}`,a:i%7,b:i%5}));
 const nodes=renderCartesian({data,kind:'line',series:[{key:'a'},{key:'b'}]});
 assert.equal(nodes.filter(n=>n.props.class==='svgc-curve').length,2);
 assert.ok(renderItemChart('HBarChart',{items:Array.from({length:130000},(_,i)=>({label:`i${i}`,value:i%3})),height:400}).length>0);
});
test('cartesian surface is keyboard reachable and arrow keys move the tooltip and active marks',()=>{
 let payload;const chart=chartHarness('CartesianChart',{data:rows,xKey:'x',series:stackedSeries,width:300,height:200,tooltip:p=>{payload=p;return 'tip';}});
 const surface=()=>chart.svg().props;assert.equal(surface().tabindex,0);assert.equal(surface().role,'application');
 surface().onFocus({currentTarget:{matches:()=>true}});chart.nodes();assert.equal(payload.label,'a');
 const key=name=>{let prevented=false,stopped=false;surface().onKeyDown({key:name,currentTarget:{matches:()=>true},preventDefault(){prevented=true;},stopPropagation(){stopped=true;}});return {prevented,stopped};};
 assert.deepEqual(key('ArrowRight'),{prevented:true,stopped:true});chart.nodes();assert.equal(payload.label,'b');
 assert.equal(chart.pick('svgc-active-dot').length,2);assert.equal(chart.pick('svgc-cursor').length,1);
 key('ArrowRight');key('ArrowRight');chart.nodes();assert.equal(payload.label,'c');
 key('ArrowLeft');chart.nodes();assert.equal(payload.label,'b');
 surface().onFocus({currentTarget:{matches:()=>false}});
 assert.deepEqual(key('ArrowRight'),{prevented:true,stopped:false});chart.nodes();assert.equal(payload.label,'c');
 surface().onFocus({currentTarget:{matches:()=>true}});
 key('ArrowLeft');chart.nodes();assert.equal(payload.label,'b');
 assert.deepEqual(key('a'),{prevented:false,stopped:false});
 key('Escape');assert.equal(chart.pick('svgc-active-dot').length,0);
 surface().onFocus({currentTarget:{matches:()=>false}});assert.equal(chart.pick('svgc-cursor').length,0);
 surface().onFocus({currentTarget:{matches:()=>true}});assert.equal(chart.pick('svgc-cursor').length,1);
 surface().onBlur({currentTarget:{parentElement:{contains:()=>false}},relatedTarget:null});assert.equal(chart.pick('svgc-cursor').length,0);
 assert.equal(chartHarness('CartesianChart',{data:rows,xKey:'x',series:stackedSeries,width:300}).svg().props.tabindex,undefined);
});
test('hover draws a cursor line and active dots at the stacked value, or a band behind bars',()=>{
 const chart=chartHarness('CartesianChart',{data:rows,xKey:'x',series:stackedSeries,width:300,height:200,yDomain:[0,8],tooltip:()=>'tip'});
 assert.equal(chart.pick('svgc-cursor').length,0);chart.moveTo(150,80);
 const line=chart.pick('svgc-cursor')[0];assert.equal(line.tag,'line');assert.equal(line.props.stroke,'#ccc');assert.equal(line.props.x1,line.props.x2);
 const dots=chart.pick('svgc-active-dot');assert.equal(dots.length,2);
 assert.equal(dots[0].props.fill,'#111');assert.equal(dots[0].props.r,4);assert.equal(dots[0].props.stroke,'#fff');
 assert.ok(dots[1].props.cy<dots[0].props.cy,'second dot sits on the stacked total');
 const bars=chartHarness('CartesianChart',{kind:'bar',data:rows,xKey:'x',series:stackedSeries,width:300,height:200,tooltip:()=>'tip'});
 bars.moveTo(150,80);const band=bars.pick('svgc-cursor')[0];assert.equal(band.tag,'rect');assert.equal(bars.pick('svgc-active-dot').length,0);
 const paint=bars.svg().children.map(n=>n.props?.class);
 assert.ok(paint.indexOf("svgc-cursor")<paint.indexOf("svgc-bar"),"band is painted behind the bars");
 assert.equal(chartHarness('CartesianChart',{data:rows,xKey:'x',series:stackedSeries,width:300,height:200}).pick('svgc-cursor').length,0);
});
test('tooltip appears only inside the plot and clears outside it',()=>{
 const chart=chartHarness('CartesianChart',{data:rows,xKey:'x',series:stackedSeries,width:300,height:200,tooltip:()=>'tip'});
 const shown=()=>chart.nodes().some(n=>typeof n.tag==='function');
 chart.moveTo(150,80);assert.ok(shown());
 chart.moveTo(30,80);assert.ok(!shown(),'Y gutter');
 chart.moveTo(150,80);chart.moveTo(150,190);assert.ok(!shown(),'X labels');
 chart.moveTo(150,80);chart.moveTo(150,3);assert.ok(!shown(),'above the plot');
});
test('tall tooltips are limited by the viewport, not the chart, and stay on screen',()=>{
 const chart={left:0,top:400,right:800,bottom:700},viewport={left:0,top:0,right:1000,bottom:900};
 const placed=g.tooltipPosition({x:100,y:150},{width:200,height:560},chart,viewport);
 assert.ok(chart.top+placed.top>=0);assert.ok(chart.top+placed.top+560<=900);
 const fits=g.tooltipPosition({x:100,y:20},{width:200,height:100},chart,viewport);assert.equal(fits.top,30);
 const source=readFileSync(new URL('../frontend_vendor/svg_charts.js',import.meta.url),'utf8');
 assert.match(source,/maxHeight=`\$\{viewport\.bottom-viewport\.top\}px`/);
});
test('domains always contain the data and non-finite bounds fall back to the data',()=>{
 const yLabels=nodes=>nodes.filter(n=>n.tag==='text'&&n.props['text-anchor']==='end');
 const data=[{x:'a',v:-2},{x:'b',v:83}];
 for(const yDomain of [[0,5],['auto','auto'],[0,'auto'],[null,null],[NaN,Infinity]]) {
  const nodes=renderCartesian({kind:'line',data,yDomain});finite(nodes);
  const labels=yLabels(nodes);assert.ok(labels.every(n=>n.props.y>=10&&n.props.y<=175),String(yDomain));
  const values=labels.map(n=>Number(n.children[0]));assert.ok(Math.min(...values)<=-2&&Math.max(...values)>=83,String(yDomain));
  const curve=nodes.find(n=>n.props.class==='svgc-curve').props.d.match(/-?[\d.]+/g).map(Number).filter((_,i)=>i%2);
  assert.ok(curve.every(v=>v>=10-1e-6&&v<=175+1e-6),String(yDomain));
 }
 assert.deepEqual(plain(g.axisDomain(["auto","auto"],5,9).ticks),[5,6,7,8,9]);
 const fixed=renderCartesian({kind:'bar',data:[{x:'a',v:5}],yDomain:[2,8]}).find(n=>n.props.class==='svgc-bar');
 assert.equal(fixed.props.y+fixed.props.height,175);
});
test('tick rules match the old axis on the cases the reviewers measured',()=>{
 assert.deepEqual(plain(g.niceTicks(-100,130,5)),[-130,-65,0,65,130]);
 assert.deepEqual(plain(g.niceTicks(0,74,5)),[0,20,40,60,80]);
 assert.deepEqual(plain(g.niceTicks(0,0,5)),[0,1,2,3,4]);
 assert.deepEqual(plain(g.fixedTicks(0,12.6,5)),[0,4,8,12,12.6]);
 assert.deepEqual(plain(g.fixedTicks(0,21.35,5)),[0,6,12,18,21.35]);
 assert.deepEqual(plain(g.fixedTicks(-2,6.31,5)),[-2,1,4,6.31]);
 assert.deepEqual(plain(g.fixedTicks(4,4,5)),[4]);
 assert.deepEqual(plain(g.niceTicks(0,.36,5)),[0,.09,.18,.27,.36]);
});
test('negative horizontal bars draw from zero and stay hoverable',()=>{
 const chart=chartHarness('HBarChart',{items:[{label:'loss',value:-4},{label:'gain',value:8}],height:200,tooltip:p=>p.payload[0].value});
 const [loss,gain]=chart.pick('svgc-bar');assert.ok(loss.props.width>0);assert.ok(gain.props.width>0);
 assert.equal(loss.props.x+loss.props.width,gain.props.x);finite(chart.nodes());
 const values=chart.pick('svgc-hbar-tick').map(n=>Number(n.children[0]));assert.ok(Math.min(...values)<=-4);
 chart.moveTo(loss.props.x+1,40);assert.equal(chart.nodes().find(n=>typeof n.tag==='function').props.position.y,5+40);
});
test('horizontal bars round only the far end, keep axis lines and label rule, and clear outside rows',()=>{
 const label='a'.repeat(20),longer='b'.repeat(21);
 const chart=chartHarness('HBarChart',{items:[{label,value:4},{label:longer,value:1},{label:'zero',value:0}],height:200,labelMaxChars:20,tooltip:()=>'tip'});
 assert.equal(g.barPath(10,50,0,10),'M10,0L46,0A4,4 0 0 1 50,4L50,6A4,4 0 0 1 46,10L10,10Z');
 assert.equal(chart.pick('svgc-hbar-axis').length,1);assert.equal(chart.pick('svgc-hbar-category-axis').length,1);
 assert.ok(chart.pick('svgc-tick-line').length>=8);
 const labels=chart.nodes().filter(n=>n.tag==='text'&&n.props['text-anchor']==='end').map(n=>n.children.at(-1));
 assert.deepEqual(labels,[label,`${'b'.repeat(18)}…`,'zero']);
 chart.moveTo(300,130);assert.equal(chart.pick('svgc-cursor').length,1);
 chart.moveTo(60,130);assert.equal(chart.pick('svgc-cursor').length,0);
});
test('leaving a donut sector hides its tooltip and unselectable sectors are not buttons',()=>{
 const items=[{label:'a',value:1},{label:'Other (2)',value:1,selectable:false}];
 const chart=chartHarness('DonutChart',{items,height:200,onSelect(){},tooltip:()=>'tip'});
 const [first,other]=chart.pick('svgc-sector');assert.equal(first.props.role,'button');assert.equal(other.props.role,undefined);assert.equal(other.props.tabindex,undefined);assert.equal(other.props.onClick,undefined);
 first.props.onMouseMove();assert.ok(chart.nodes().some(n=>typeof n.tag==='function'));
 chart.pick('svgc-sector')[0].props.onMouseLeave();assert.ok(!chart.nodes().some(n=>typeof n.tag==='function'));
});
test('x labels keep the last label, stay inside the svg and respect width with a fixed interval',()=>{
 const data=Array.from({length:30},(_,i)=>({x:`2026-10-${String(i+1).padStart(2,'0')}`,v:i}));
 const labels=nodes=>nodes.filter(n=>n.tag==='text'&&n.props['text-anchor']==='middle');
 for(const width of [320,600,1200]) {
  const shown=labels(renderCartesian({width,data,margin:{right:5}}));
  assert.equal(shown.at(-1).children[0],'2026-10-30');
  const half=shown.at(-1).children[0].length*11*.6/2;assert.ok(shown.at(-1).props.x+half<=width);
 }
 const dense=labels(renderCartesian({width:320,data,tickEvery:2}));
 for(let i=1;i<dense.length;i++)assert.ok(dense[i].props.x-dense[i-1].props.x>=66);
});
test('all-zero series use the old zero to four axis with the baseline at the bottom',()=>{
 const nodes=renderCartesian({data:[{x:'a',v:0},{x:'b',v:0}],yFormat:String});
 assert.deepEqual(nodes.filter(n=>n.tag==='text'&&n.props['text-anchor']==='end').map(n=>n.children[0]),['0','1','2','3','4']);
 const spark=renderCartesian({compact:true,height:28,margin:{top:0,right:0,bottom:0,left:0},data:[{x:'a',v:0},{x:'b',v:0}]});
 assert.match(spark.find(n=>n.props.class==='svgc-curve').props.d,/^M0,28/);
 assert.ok(renderItemChart('HBarChart',{items:[{label:'a',value:0}],height:200}).filter(n=>n.props.class==='svgc-hbar-tick').length>=2);
});
test('grouped bars keep the four pixel gap, zero bars draw nothing and y labels centre on gridlines',()=>{
 const nodes=renderCartesian({kind:'bar',width:800,data:[{x:'a',p:3,q:5,r:0}],series:[{key:'p'},{key:'q'},{key:'r'}]});
 const bars=nodes.filter(n=>n.props.class==='svgc-bar');assert.equal(bars.length,2);
 assert.equal(bars[1].props.x-(bars[0].props.x+bars[0].props.width),4);
 const tick=nodes.find(n=>n.tag==='text'&&n.props['text-anchor']==='end');assert.equal(tick.props.dy,'.355em');
 const marks=renderCartesian({tickLine:'var(--tick)'}).filter(n=>n.props.class==='svgc-tick-line');assert.ok(marks.length>0&&marks.every(n=>n.props.stroke==='var(--tick)'));
 assert.equal(renderCartesian({}).filter(n=>n.props.class==='svgc-tick-line').length,0);
});
test('chart wrapper is out of flow so the svg cannot hold a shrinking parent open',()=>{
 for(const nodes of [renderCartesian({}),renderItemChart('DonutChart',{items:[]}),renderItemChart('HBarChart',{items:[]})]) {
  assert.equal(nodes.find(n=>n.props.class==='svgc-wrapper').props.style.position,'absolute');
  assert.equal(nodes.find(n=>n.props.class==='svgc-responsive').props.style.position,'relative');
 }
});
test('axis labels move inward at the chart edge while their marks and gridlines stay on the data',()=>{
 const data=[0,1,2,3].map(i=>({x:`synthetic-category-${i}`,v:[0,3,6,24.94][i]}));
 const nodes=renderCartesian({width:400,data,margin:{top:5,right:5,left:70,bottom:35},yDomain:[0,24.94],tickLine:'#123',
  grid:{horizontal:true,vertical:true}});
 const yLabels=nodes.filter(n=>n.tag==='text'&&n.props['text-anchor']==='end');
 const horizontal=nodes.filter(n=>n.props.class==='svgc-grid-horizontal').map(n=>n.props.y1);
 assert.equal(yLabels.at(-1).children.join(''),'24.94');assert.ok(yLabels.at(-1).props.y>5);assert.ok(horizontal.includes(5));
 const xLabels=nodes.filter(n=>n.tag==='text'&&n.props['text-anchor']==='middle');
 const marks=nodes.filter(n=>n.props.class==='svgc-tick-line'&&n.props.x1===n.props.x2).map(n=>n.props.x1);
 assert.equal(marks.at(-1),395);assert.ok(xLabels.at(-1).props.x<395);
});
test('tooltips flip inside the plot, not the whole chart',()=>{
 const viewport={left:0,top:0,right:2000,bottom:2000},chart={left:0,top:0,right:1000,bottom:380};
 const plot={left:75,top:5,right:995,bottom:320};
 assert.equal(g.tooltipPosition({x:500,y:190,plot},{width:176,height:131},chart,viewport).top,49);
 assert.equal(g.tooltipPosition({x:500,y:60,plot},{width:176,height:131},chart,viewport).top,70);
 assert.equal(g.tooltipPosition({x:500,y:60,plot},{width:176,height:300},chart,viewport).top,5);
});
