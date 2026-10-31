(function () {
  'use strict';
  const {h} = window.preact;
  const {useState, useRef, useEffect, useLayoutEffect} = window.preactHooks;
  const number = value => Number.isFinite(Number(value)) ? Number(value) : 0;
  function linearScale(domain, range) {
    const [a,b]=domain.map(number), [c,d]=range.map(number);
    return value => a===b ? (c+d)/2 : c+(number(value)-a)*(d-c)/(b-a);
  }
  function niceTicks(min,max,count=5) {
    min=number(min); max=number(max); count=Math.max(1,number(count));
    if(min>max) [min,max]=[max,min];
    if(min===max) {const pad=Math.abs(min)*0.1||1;min-=pad;max+=pad;}
    const raw=(max-min)/count, magnitude=10**Math.floor(Math.log10(raw));
    const factor=raw/magnitude, step=(factor<=1?1:factor<=2?2:factor<=5?5:10)*magnitude;
    const start=Math.floor(min/step), end=Math.ceil(max/step), result=[];
    for(let i=start;i<=end && result.length<1000;i++) result.push(Number((i*step).toPrecision(14)));
    return result;
  }
  function stack(rows,keys,offset='none') {
    const result=keys.map(()=>[]);
    rows.forEach(row=>{let pos=0,neg=0,total=0;keys.forEach((key,i)=>{
      const value=number(row[key]);let start;
      if(offset==='sign') {start=value<0?neg:pos;if(value<0)neg+=value;else pos+=value;}
      else {start=total;total+=value;}
      result[i].push([start,start+value]);
    });});return result;
  }
  const xy=p=>Array.isArray(p)?[number(p[0]),number(p[1])]:[number(p.x),number(p.y)];
  function monotonePath(points) {
    const p=points.map(xy);if(!p.length)return '';
    let path=`M${p[0][0]},${p[0][1]}`;if(p.length===1)return path;
    const slopes=p.slice(1).map((v,i)=>v[0]===p[i][0]?0:(v[1]-p[i][1])/(v[0]-p[i][0]));
    const tangents=p.map((_,i)=>i===0?slopes[0]:i===p.length-1?slopes.at(-1):slopes[i-1]*slopes[i]<=0?0:2/(1/slopes[i-1]+1/slopes[i]));
    for(let i=0;i<p.length-1;i++) {const dx=(p[i+1][0]-p[i][0])/3;path+=`C${p[i][0]+dx},${p[i][1]+dx*tangents[i]} ${p[i+1][0]-dx},${p[i+1][1]-dx*tangents[i+1]} ${p[i+1][0]},${p[i+1][1]}`;}
    return path;
  }
  function areaPath(top,bottom) {if(!top.length||!bottom.length)return '';return monotonePath(top)+monotonePath([...bottom].reverse()).replace(/^M/,'L')+'Z';}
  function arcPath(cx,cy,inner,outer,start,end) {
    cx=number(cx);cy=number(cy);inner=Math.max(0,number(inner));outer=Math.max(0,number(outer));start=number(start);end=number(end);
    const delta=Math.max(-2*Math.PI,Math.min(2*Math.PI,end-start)), sweep=delta>=0?1:0;
    const point=(r,a)=>`${cx+r*Math.cos(a)},${cy+r*Math.sin(a)}`;
    const arcs=(r,a,d,s)=>{const n=Math.abs(d)>=2*Math.PI-1e-9?2:1;let out='';for(let i=1;i<=n;i++)out+=`A${r},${r} 0 ${Math.abs(d/n)>Math.PI?1:0} ${s} ${point(r,a+d*i/n)}`;return out;};
    return `M${point(outer,start)}${arcs(outer,start,delta,sweep)}L${point(inner,start+delta)}${arcs(inner,start+delta,-delta,1-sweep)}Z`;
  }
  function useWidth(width) {
    const ref=useRef(null), [measured,setMeasured]=useState(number(width)||400);
    useEffect(()=>{if(width || !ref.current)return;const node=ref.current;const update=()=>setMeasured(node.getBoundingClientRect().width||400);update();if(typeof ResizeObserver==='undefined')return;const observer=new ResizeObserver(update);observer.observe(node);return()=>observer.disconnect();},[width]);
    return [ref,number(width)||measured];
  }
  const selectable=(item,onSelect)=>onSelect?{role:'button',tabindex:0,onClick:()=>onSelect(item),onKeyDown:event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();onSelect(item);}}}:{};
  const style={position:'relative',width:'100%'};
  function tooltipPosition(point,size,chart,viewport) {
    const left=Math.max(chart.left,viewport.left)-chart.left;
    const top=Math.max(chart.top,viewport.top)-chart.top;
    const right=Math.max(left,Math.min(chart.right,viewport.right)-chart.left);
    const bottom=Math.max(top,Math.min(chart.bottom,viewport.bottom)-chart.top);
    const place=(value,extent,min,max)=>{
      const forward=value+10, flipped=value-10-extent;
      const preferred=forward+extent<=max?forward:flipped;
      return Math.max(min,Math.min(preferred,Math.max(min,max-extent)));
    };
    return {left:place(point.x,size.width,left,right),top:place(point.y,size.height,top,bottom)};
  }
  function Tooltip({children,position,onDismiss}) {
    const ref=useRef(null);
    useLayoutEffect(()=>{
      const node=ref.current, chart=node?.parentElement;
      if(!node||!chart) return;
      const update=()=>{
        const bounds=chart.getBoundingClientRect();
        const viewport={left:0,top:0,right:window.innerWidth,bottom:window.innerHeight};
        const availableWidth=Math.max(0,Math.min(bounds.right,viewport.right)-Math.max(bounds.left,viewport.left));
        const availableHeight=Math.max(0,Math.min(bounds.bottom,viewport.bottom)-Math.max(bounds.top,viewport.top));
        node.style.maxWidth=`${availableWidth}px`;
        node.style.maxHeight=`${availableHeight}px`;
        const size=node.getBoundingClientRect();
        const constrained=node.scrollWidth>node.clientWidth || node.scrollHeight>node.clientHeight;
        node.style.pointerEvents=constrained?'auto':'none';
        if(constrained) {
          node.setAttribute('tabindex','0');
          node.setAttribute('role','region');
          node.setAttribute('aria-label','Chart tooltip');
        } else {
          node.removeAttribute('tabindex');
          node.removeAttribute('role');
          node.removeAttribute('aria-label');
        }
        const placed=tooltipPosition(position,size,bounds,viewport);
        node.style.left=`${placed.left}px`;
        node.style.top=`${placed.top}px`;
        node.style.visibility='visible';
      };
      update();
      const observer=typeof ResizeObserver==='undefined'?null:new ResizeObserver(update);
      observer?.observe(chart);
      window.addEventListener('resize',update);
      window.addEventListener('scroll',update,true);
      return ()=>{observer?.disconnect();window.removeEventListener('resize',update);window.removeEventListener('scroll',update,true);};
    },[position.x,position.y,children]);
    return h('div',{ref,class:'svgc-tooltip',
      onMouseMove:event=>event.stopPropagation(),
      onFocusOut:event=>{if(!event.currentTarget.contains(event.relatedTarget)) onDismiss();}
    },children);
  }
  function tooltipNode(tooltip,payload,position,onDismiss) {
    if(!tooltip||!payload) return null;
    return h(Tooltip,{position,onDismiss},typeof tooltip==='function'?tooltip(payload):tooltip);
  }
  function spacedTicks(ticks,scale,minSpacing=20) {
    if(ticks.length<2) return ticks;
    const first=ticks[0], last=ticks.at(-1);
    if(Math.abs(scale(first)-scale(last))<minSpacing) return [first];
    const shown=[first];
    for(const tick of ticks.slice(1,-1)) {
      if(Math.abs(scale(tick)-scale(shown.at(-1)))>=minSpacing &&
         Math.abs(scale(tick)-scale(last))>=minSpacing) shown.push(tick);
    }
    return [...shown,last];
  }
  const leaveChart=(event,setHover)=>{
    const tooltip=event.currentTarget.querySelector('.svgc-tooltip');
    if(!tooltip?.contains(window.document?.activeElement)) setHover(null);
  };
  function itemHover(event,item) {
    const bounds=event.currentTarget?.ownerSVGElement?.parentElement?.getBoundingClientRect();
    return {item,x:bounds?event.clientX-bounds.left:event.offsetX,
      y:bounds?event.clientY-bounds.top:event.offsetY};
  }
  function CartesianChart({
    kind='area', data=[], xKey, series=[], stackOffset='none', height=300,
    width, margin={}, yFormat=String, xFormat=String, tickEvery, yDomain,
    referenceX, referenceY, referenceOpacity=1, grid=true, xAxisLine=false,
    yAxisLine=false, plotClass='', tooltip,
    compact=false
  }) {
    const [ref,w]=useWidth(width), [hover,setHover]=useState(null);
    const m={top:10,right:10,bottom:compact?0:25,left:compact?0:55,...margin};
    const left=m.left, right=Math.max(left,w-m.right), top=m.top;
    const bottom=Math.max(top,height-m.bottom), pw=right-left;
    const stacked=stack(data,series.filter(s=>s.stack).map(s=>s.key),stackOffset);
    let si=0;
    const bands=series.map(s=>s.stack?stacked[si++]:data.map(row=>[0,number(row[s.key])]));
    let slotCount=0, stackSlot;
    const slots=series.map(s=>{
      if(!s.stack) return slotCount++;
      if(stackSlot===undefined) stackSlot=slotCount++;
      return stackSlot;
    });
    const values=bands.flat(2).concat([0]);
    let lo=Math.min(...values), hi=Math.max(...values);
    const explicitDomain=Array.isArray(yDomain) && yDomain.length>=2 &&
      Number.isFinite(yDomain[0]) && Number.isFinite(yDomain[1]);
    if(Array.isArray(yDomain)) {
      if(Number.isFinite(yDomain[0])) lo=yDomain[0];
      if(Number.isFinite(yDomain[1])) hi=yDomain[1];
    }
    let ticks=niceTicks(lo,hi,4);
    if(explicitDomain) {
      const min=Math.min(lo,hi), max=Math.max(lo,hi);
      ticks=[min,...ticks.filter(t=>t>min && t<max),...(min===max?[]:[max])];
    } else if(!yDomain) {
      lo=ticks[0]; hi=ticks.at(-1);
    }
    const y=linearScale([lo,hi],[bottom,top]);
    const renderedTicks=spacedTicks(ticks,y);
    const x=i=>data.length<=1?(left+right)/2:kind==='bar'
      ?left+(i+.5)*pw/data.length:left+i*pw/(data.length-1);
    const marks=series.map((s,j)=>{
      const b=bands[j], color=s.color||'currentColor';
      if(kind==='bar') {
        const groupWidth=data.length?pw/data.length*.8:0;
        const barWidth=slotCount?groupWidth/slotCount:0;
        return b.map((pair,i)=>h('rect',{
          class:'svgc-bar',x:x(i)-groupWidth/2+slots[j]*barWidth,
          y:Math.min(y(pair[0]),y(pair[1])),width:barWidth,
          height:Math.abs(y(pair[1])-y(pair[0])),fill:s.fill||color,
          'fill-opacity':s.fillOpacity??1,stroke:color,
          'stroke-opacity':s.strokeOpacity??1,'stroke-width':s.strokeWidth??2,
          'stroke-dasharray':s.strokeDasharray
        }));
      }
      const upper=b.map((v,i)=>[x(i),y(v[1])]);
      const lower=b.map((v,i)=>[x(i),y(v[0])]);
      return h('g',null,
        kind==='area'&&s.fill!=='none'&&h('path',{
          class:'svgc-area',d:areaPath(upper,lower),fill:s.fill||color,
          'fill-opacity':s.fillOpacity??.3
        }),
        h('path',{
          class:'svgc-curve',d:monotonePath(upper),fill:'none',stroke:color,
          'stroke-opacity':s.strokeOpacity??1,'stroke-width':s.strokeWidth??2,
          'stroke-dasharray':s.strokeDasharray
        }),
        upper.length===1&&h('circle',{class:'svgc-point',cx:upper[0][0],cy:upper[0][1],
          r:3,fill:color,opacity:s.strokeOpacity??1})
      );
    });
    const move=e=>{
      if(!data.length) return;
      const rect=e.currentTarget.getBoundingClientRect(), local=e.clientX-rect.left;
      const fraction=pw?Math.max(0,Math.min(1,(local-left)/pw)):0;
      const index=data.length===1?0:kind==='bar'
        ?Math.min(data.length-1,Math.floor(fraction*data.length))
        :Math.round(fraction*(data.length-1));
      setHover({index,x:local,y:e.clientY-rect.top});
    };
    const row=hover&&data[hover.index];
    const payload=row&&{
      active:true,label:row[xKey],row,index:hover.index,
      payload:series.map(s=>({dataKey:s.key,name:s.label||s.key,
        value:row[s.key],color:s.color,payload:row}))
    };
    const refIndex=data.findIndex(row=>row[xKey]===referenceX);
    const options=typeof grid==='object' && grid!==null?grid:{};
    const horizontal=typeof grid==='object'?options.horizontal!==false:!!grid;
    const vertical=typeof grid==='object'&&options.vertical===true;
    const gridStroke=options.stroke??'var(--border-default, #334155)';
    const gridDash=options.strokeDasharray??'3 3';
    const xLabels=data.map((row,i)=>({i,label:xFormat(row[xKey])}));
    const maxLabelWidth=Math.max(0,...xLabels.map(({label})=>Array.from(String(label??'')).length*9+12));
    const categoryGap=data.length>1?pw/(kind==='bar'?data.length:data.length-1):pw;
    const interval=Number.isFinite(tickEvery)?Math.max(1,Math.floor(tickEvery)):
      Math.max(1,categoryGap>0?Math.ceil(maxLabelWidth/categoryGap):data.length);
    const shownX=xLabels.filter(({i})=>i%interval===0);
    return h('div',{ref,class:'svgc-responsive',style:{...style,height,width:width||'100%'}},
      h('div',{class:'svgc-wrapper',style:{...style,height},
        onMouseMove:move,onMouseLeave:event=>leaveChart(event,setHover)},
        h('svg',{width:w,height,viewBox:`0 0 ${w} ${height}`},
          h('rect',{class:plotClass,x:left,y:top,width:pw,height:bottom-top,fill:'transparent'}),
          !compact&&renderedTicks.map(t=>h('g',null,
            horizontal&&h('line',{class:'svgc-grid-horizontal',x1:left,x2:right,
              y1:y(t),y2:y(t),stroke:gridStroke,'stroke-dasharray':gridDash}),
            h('text',{x:left-6,y:y(t),fill:'var(--text-muted, #94a3b8)',
              'text-anchor':'end','font-size':11},yFormat(t))
          )),
          !compact&&vertical&&shownX.map(({i})=>h('line',{
            class:'svgc-grid-vertical',x1:x(i),x2:x(i),y1:top,y2:bottom,
            stroke:gridStroke,'stroke-dasharray':gridDash
          })),
          !compact&&shownX.map(({label,i})=>h('text',{
            x:x(i),y:height-4,fill:'var(--text-muted, #94a3b8)',
            'text-anchor':'middle','font-size':11
          },label)),
          !compact&&xAxisLine&&h('line',{
            class:'svgc-x-axis-line',x1:left,x2:right,y1:bottom,y2:bottom,
            stroke:typeof xAxisLine==='string'?xAxisLine:'var(--border-default, #334155)'
          }),
          !compact&&yAxisLine&&h('line',{
            class:'svgc-y-axis-line',x1:left,x2:left,y1:top,y2:bottom,
            stroke:typeof yAxisLine==='string'?yAxisLine:'var(--border-default, #334155)'
          }),
          marks,
          refIndex>=0&&h('line',{class:'svgc-reference-line',x:referenceX,
            x1:x(refIndex),x2:x(refIndex),y1:top,y2:bottom,
            stroke:'#94a3b8','stroke-opacity':referenceOpacity,'stroke-dasharray':'3 3'}),
          referenceY!=null&&h('line',{class:'svgc-reference-line',x:referenceY,
            x1:left,x2:right,y1:y(referenceY),y2:y(referenceY),
            stroke:'var(--border-default, #94a3b8)','stroke-opacity':referenceOpacity})
        ),
        tooltipNode(tooltip,payload,hover||{},()=>setHover(null))
      )
    );
  }
  function DonutChart({items=[],height=250,innerRadius=50,outerRadius=85,tooltip,onSelect,
    startAngle=-Math.PI/2,clockwise=true,stroke,strokeWidth}) {
    const [ref,w]=useWidth(),[hover,setHover]=useState(null);
    const total=items.reduce((sum,item)=>sum+Math.max(0,number(item.value)),0);
    let angle=number(startAngle);
    const sectors=items.map(item=>{
      const start=angle;
      angle+=total?(clockwise?1:-1)*Math.max(0,number(item.value))/total*2*Math.PI:0;
      return h('path',{class:'svgc-sector',d:arcPath(w/2,height/2,innerRadius,outerRadius,start,angle),
        fill:item.color,stroke,'stroke-width':strokeWidth,...selectable(item,onSelect),
        onMouseMove:e=>setHover(itemHover(e,item))},h('title',null,item.label));
    });
    return h('div',{ref,class:'svgc-responsive',style:{...style,height}},
      h('div',{class:'svgc-wrapper',style:{...style,height},onMouseLeave:event=>leaveChart(event,setHover)},
        h('svg',{width:w,height},sectors),
        tooltipNode(tooltip,hover&&{active:true,label:hover.item.label,payload:[{dataKey:'value',name:hover.item.label,value:hover.item.value,color:hover.item.color,payload:hover.item}]},hover||{},()=>setHover(null))));
  }
  function HBarChart({items=[],height=250,valueFormat=String,labelWidth=130,labelMaxChars=Infinity,onSelect,tooltip}) {
    const [ref,w]=useWidth(),[hover,setHover]=useState(null);
    const max=Math.max(0,...items.map(i=>number(i.value)));
    const plotHeight=Math.max(0,height-24), rowHeight=plotHeight/Math.max(1,items.length);
    const plotWidth=Math.max(0,w-labelWidth-8);
    const ticks=max?niceTicks(0,max,4):[0], axisMax=ticks.at(-1);
    const bars=items.map((item,i)=>{
      const label=String(item.label??'');
      const short=label.length>labelMaxChars?label.slice(0,Math.max(0,labelMaxChars-1))+'…':label;
      return h('g',null,
        h('text',{x:labelWidth-6,y:(i+.5)*rowHeight,'text-anchor':'end',
          'dominant-baseline':'middle',fill:'var(--text-muted, #94a3b8)','font-size':10},h('title',null,label),short),
        h('rect',{class:'svgc-bar',x:labelWidth,y:i*rowHeight+rowHeight*.15,
          width:axisMax?plotWidth*Math.max(0,number(item.value))/axisMax:0,height:rowHeight*.7,rx:4,
          fill:item.color,'aria-label':item.ariaLabel||`${label}: ${valueFormat(item.value)}`,
          ...selectable(item,onSelect),onMouseMove:e=>setHover(itemHover(e,item))})
      );
    });
    return h('div',{ref,class:'svgc-responsive',style:{...style,height}},
      h('div',{class:'svgc-wrapper',style:{...style,height},onMouseLeave:event=>leaveChart(event,setHover)},
        h('svg',{width:w,height},bars,
          h('line',{class:'svgc-hbar-axis',x1:labelWidth,x2:labelWidth+plotWidth,y1:plotHeight,y2:plotHeight,stroke:'var(--border-default, #475569)'}),
          ticks.map((t,i)=>h('text',{class:'svgc-hbar-tick',x:labelWidth+(axisMax?t/axisMax*plotWidth:0),y:height-4,
            'text-anchor':i===0?'start':i===ticks.length-1?'end':'middle',
            fill:'var(--text-muted, #94a3b8)','font-size':11},valueFormat(t)))
        ),
        tooltipNode(tooltip,hover&&{active:true,label:hover.item.label,payload:[{dataKey:'value',name:hover.item.label,value:hover.item.value,color:hover.item.color,payload:hover.item}]},hover||{},()=>setHover(null))));
  }
  function Legend({series=[],hidden=new Set(),onToggle,kind='area'}) {
    return h('div',{class:'svgc-legend'},series.map(s=>{
      const color=s.color||'currentColor';
      const symbol=kind==='bar'
        ?h('rect',{x:1,y:1,width:14,height:8,fill:s.fill||color,stroke:color,'stroke-dasharray':s.strokeDasharray})
        :[h('line',{x1:1,y1:5,x2:15,y2:5,stroke:color,'stroke-width':2,'stroke-dasharray':s.strokeDasharray}),
          h('circle',{cx:8,cy:5,r:3,fill:color})];
      return h('button',{type:'button',class:'svgc-legend-item',
        'aria-pressed':!hidden.has(s.key),onClick:()=>onToggle?.(s.key),
        style:{color:s.color,opacity:hidden.has(s.key)?.45:1}},
        h('svg',{'aria-hidden':'true',width:16,height:10,viewBox:'0 0 16 10'},symbol),s.label||s.key);
    }));
  }
  window.svgCharts={geometry:{linearScale,niceTicks,stack,monotonePath,areaPath,arcPath,tooltipPosition},CartesianChart,DonutChart,HBarChart,Legend};
})();
