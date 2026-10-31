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
 bar.props.onMouseMove({offsetX:12,offsetY:8});tree=render();assert.equal(payload.label,item.label);assert.equal(payload.payload[0].payload,item);assert.equal(payload.payload[0].value,7);
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
  const labels=renderCartesian({yDomain:[lo,hi]}).filter(n=>n.tag==='text'&&n.props['text-anchor']==='end');
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
 const oversized=place({x:50,y:50},{width:600,height:500},chart,viewport);
 assert.equal(oversized.left,0);assert.equal(oversized.top,0);
});
test('all charts use a shared measured tooltip container with intrinsic width',()=>{
 const source=readFileSync(new URL('../frontend_vendor/svg_charts.js',import.meta.url),'utf8');
 const css=readFileSync(new URL('../frontend_vendor/svg_charts.css',import.meta.url),'utf8');
 assert.match(source,/useLayoutEffect/);assert.match(source,/function Tooltip\(/);
 assert.match(source,/getBoundingClientRect\(\)/);assert.match(css,/width:\s*max-content/);
 assert.equal((source.match(/tooltipNode\(tooltip,/g)||[]).length,4);
});
test('item chart pointer coordinates are relative to the chart wrapper',()=>{
 let state=[],cursor=0;const h=(tag,props,...children)=>({tag,props:props||{},children:children.flat(Infinity).filter(Boolean)});
 const hooks={useRef:()=>({current:null}),useState(initial){const i=cursor++;return [state[i]??initial,value=>state[i]=value];},useEffect(){}};
 const w={preact:{h},preactHooks:hooks};vm.runInNewContext(readFileSync(new URL('../frontend_vendor/svg_charts.js',import.meta.url),'utf8'),{window:w});
 for(const [component,selector] of [['HBarChart','svgc-bar'],['DonutChart','svgc-sector']]) {
  state=[];const render=()=>{cursor=0;return w.svgCharts[component]({items:[{label:'synthetic',value:1}],tooltip:()=>null});};
  const all=root=>{const nodes=[];const visit=n=>{nodes.push(n);for(const c of n.children||[])if(typeof c==='object')visit(c);};visit(root);return nodes;};
  const mark=all(render()).find(n=>n.props.class===selector);
  mark.props.onMouseMove({clientX:155,clientY:220,offsetX:5,offsetY:6,currentTarget:{ownerSVGElement:{parentElement:{getBoundingClientRect:()=>({left:100,top:200})}}}});
  const tooltip=all(render()).find(n=>typeof n.tag==='function');assert.equal(tooltip.props.position.x,55);assert.equal(tooltip.props.position.y,20);
 }
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
 assert.deepEqual(ticks.map(n=>Number(n.children[0])),[0,5,10,15]);
 assert.equal(ticks[0].props['text-anchor'],'start');assert.equal(ticks.at(-1).props['text-anchor'],'end');
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
  const x=labels(nodes).map(n=>n.props.x);for(let i=1;i<x.length;i++)assert.ok(x[i]-x[i-1]>=52);
  assert.deepEqual(nodes.filter(n=>n.props.class==='svgc-grid-vertical').map(n=>n.props.x1),x);
 }
 assert.equal(labels(render(320,{...opts,tickEvery:6})).length,10);
});
test('legend renders decorative type symbols and retains button toggling and hidden state',()=>{
 const h=(tag,props,...children)=>({tag,props:props||{},children:children.flat(Infinity).filter(x=>x!=null&&x!==false)});
 const w={preact:{h},preactHooks:{}};vm.runInNewContext(readFileSync(new URL('../frontend_vendor/svg_charts.js',import.meta.url),'utf8'),{window:w});
 let toggled;const series=[{key:'a',label:'Alpha',color:'var(--a)',strokeDasharray:'5 3'}];
 const line=w.svgCharts.Legend({series,kind:'line',hidden:new Set(['a']),onToggle:key=>toggled=key});
 const button=line.children[0],symbol=button.children[0];assert.equal(button.tag,'button');assert.equal(button.props['aria-pressed'],false);button.props.onClick();assert.equal(toggled,'a');
 assert.equal(symbol.tag,'svg');assert.equal(symbol.props['aria-hidden'],'true');assert.equal(symbol.children[0].tag,'line');assert.equal(symbol.children[0].props.stroke,'var(--a)');assert.equal(symbol.children[0].props['stroke-dasharray'],'5 3');
 for(const kind of ['area','line']) {const marks=w.svgCharts.Legend({series,kind}).children[0].children[0].children;assert.deepEqual(marks.map(mark=>mark.tag),['line','circle']);assert.equal(marks[1].props.fill,'var(--a)');}
 assert.equal(w.svgCharts.Legend({series,kind:'bar'}).children[0].children[0].children[0].tag,'rect');
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
