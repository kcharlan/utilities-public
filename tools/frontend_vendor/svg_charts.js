(function () {
  'use strict';
  const {h} = window.preact;
  const {useState, useRef, useEffect, useLayoutEffect} = window.preactHooks;
  const number = value => Number.isFinite(Number(value)) ? Number(value) : 0;
  function linearScale(domain, range) {
    const [a,b]=domain.map(number), [c,d]=range.map(number);
    return value => a===b ? (c+d)/2 : c+(number(value)-a)*(d-c)/(b-a);
  }
  // The tick helpers through fixedTicks are adapted from recharts-scale (MIT License,
  // (c) the recharts-scale authors, https://github.com/recharts/recharts-scale).
  const roundTick=value=>Number(value.toPrecision(14));
  const digitCount=value=>value===0?1:Math.floor(Math.log10(Math.abs(value)))+1;
  function tickStep(rough,correction=0) {
    if(!(rough>0)) return 0;
    const digits=digitCount(rough), unit=10**digits, ratioScale=digits===1?.1:.05;
    return roundTick((Math.ceil(roundTick(rough/unit/ratioScale))+correction)*ratioScale*unit);
  }
  function singleValueTicks(value,count) {
    const middleIndex=Math.floor((count-1)/2);
    let step=1, middle=value;
    if(!Number.isInteger(value)) {
      if(Math.abs(value)<1) {step=10**(digitCount(value)-1);middle=Math.floor(value/step)*step;}
      else middle=Math.floor(value);
    } else if(value===0) middle=middleIndex;
    return Array.from({length:count},(_,i)=>roundTick(middle+(i-middleIndex)*step));
  }
  function niceTicks(min,max,count=5) {
    min=number(min); max=number(max); count=Math.max(2,Math.floor(number(count)));
    if(min>max) [min,max]=[max,min];
    if(min===max) return singleValueTicks(min,count);
    if(!Number.isFinite(max-min)) return [min,max];
    for(let correction=0;correction<1000;correction++) {
      const step=tickStep((max-min)/(count-1),correction);
      let middle=0;
      if(min>0||max<0) {const centre=(min+max)/2;middle=roundTick(centre-centre%step);}
      let below=Math.ceil(roundTick((middle-min)/step)), above=Math.ceil(roundTick((max-middle)/step));
      const used=below+above+1;
      if(used>count) continue;
      if(max>0) above+=count-used; else below+=count-used;
      return Array.from({length:below+above+1},(_,i)=>roundTick(middle+(i-below)*step));
    }
    return [min,max];
  }
  function fixedTicks(min,max,count=5) {
    min=number(min); max=number(max); count=Math.max(2,Math.floor(number(count)));
    if(min>max) [min,max]=[max,min];
    if(min===max) return [min];
    const step=tickStep((max-min)/(count-1)), result=[];
    for(let i=0;i<1000;i++) {const tick=roundTick(min+i*step);if(tick>=max)break;result.push(tick);}
    return [...result,max];
  }
  function axisDomain(spec,dataMin,dataMax) {
    const bound=value=>typeof value==='number'&&Number.isFinite(value);
    let [first,second]=Array.isArray(spec)?spec:[0,'auto'];
    if(bound(first)&&bound(second)&&first>second) [first,second]=[second,first];
    const min=bound(first)?Math.min(first,dataMin):dataMin;
    const max=bound(second)?Math.max(second,dataMax):dataMax;
    if(bound(first)&&bound(second)) return {ticks:fixedTicks(min,max),lo:min,hi:max};
    const ticks=niceTicks(min,max);
    return {ticks,lo:ticks[0],hi:ticks.at(-1)};
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
  // Adapted from d3-shape's curveMonotoneX (ISC License, (c) Mike Bostock, https://github.com/d3/d3-shape).
  function monotonePath(points) {
    const p=points.map(xy);if(!p.length)return '';
    let path=`M${p[0][0]},${p[0][1]}`;if(p.length===1)return path;
    if(p.length===2)return `${path}L${p[1][0]},${p[1][1]}`;
    const slope=(a,b)=>b[0]===a[0]?0:(b[1]-a[1])/(b[0]-a[0]);
    const tangents=p.map((point,i)=>{
      if(i===0||i===p.length-1) return 0;
      const before=slope(p[i-1],point), after=slope(point,p[i+1]);
      const h0=point[0]-p[i-1][0], h1=p[i+1][0]-point[0];
      const mean=h0+h1?(before*h1+after*h0)/(h0+h1):0;
      return (Math.sign(before)+Math.sign(after))*Math.min(Math.abs(before),Math.abs(after),.5*Math.abs(mean))||0;
    });
    const edge=(a,b,tangent)=>{const h=b[0]-a[0];return h?(3*(b[1]-a[1])/h-tangent)/2:tangent;};
    tangents[0]=edge(p[0],p[1],tangents[1]);
    tangents[p.length-1]=edge(p[p.length-2],p[p.length-1],tangents[p.length-2]);
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
  function barPath(start,end,y,height,radius=4) {
    const sign=end<start?-1:1, r=Math.min(radius,Math.abs(end-start)/2,height/2), sweep=sign>0?1:0;
    return `M${start},${y}L${end-sign*r},${y}A${r},${r} 0 0 ${sweep} ${end},${y+r}L${end},${y+height-r}A${r},${r} 0 0 ${sweep} ${end-sign*r},${y+height}L${start},${y+height}Z`;
  }
  function useWidth(width) {
    const ref=useRef(null), [measured,setMeasured]=useState(number(width)||400);
    useEffect(()=>{if(width || !ref.current)return;const node=ref.current;const update=()=>setMeasured(Math.round(node.getBoundingClientRect().width)||400);update();if(typeof ResizeObserver==='undefined')return;const observer=new ResizeObserver(update);observer.observe(node);return()=>observer.disconnect();},[width]);
    return [ref,number(width)||measured];
  }
  const selectable=(item,onSelect)=>onSelect&&item.selectable!==false?{role:'button',tabindex:0,onClick:()=>onSelect(item),onKeyDown:event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();onSelect(item);}}}:{};
  const style={position:'relative',width:'100%'};
  const wrapperStyle={position:'absolute',top:0,left:0,width:'100%'};
  const keyboardFocus=event=>event.currentTarget.matches?.(':focus-visible')!==false;
  function tooltipPosition(point,size,chart,viewport) {
    const plot=point.plot||{left:0,top:0,right:chart.right-chart.left,bottom:chart.bottom-chart.top};
    const left=Math.max(plot.left,viewport.left-chart.left);
    const top=Math.max(plot.top,viewport.top-chart.top);
    const right=Math.max(left,Math.min(plot.right,viewport.right-chart.left));
    const bottom=Math.max(top,Math.min(plot.bottom,viewport.bottom-chart.top));
    const forward=value=>value+10, flipped=(value,extent)=>value-10-extent;
    const x=forward(point.x)+size.width<=right?forward(point.x):flipped(point.x,size.width);
    const y=forward(point.y)+size.height<=bottom?forward(point.y):Math.max(top,flipped(point.y,size.height));
    return {left:Math.max(left,Math.min(x,Math.max(left,right-size.width))),
      top:Math.max(viewport.top-chart.top,Math.min(y,viewport.bottom-chart.top-size.height))};
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
        node.style.maxWidth=`${availableWidth}px`;
        node.style.maxHeight=`${viewport.bottom-viewport.top}px`;
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
      onFocusOut:event=>{if(!event.currentTarget.parentElement?.contains(event.relatedTarget)) onDismiss();}
    },children);
  }
  function tooltipNode(tooltip,payload,position,onDismiss) {
    if(!tooltip||!payload) return null;
    return h(Tooltip,{position,onDismiss},typeof tooltip==='function'?tooltip(payload):tooltip);
  }
  const leaveChart=(event,setHover)=>{
    const tooltip=event.currentTarget.querySelector('.svgc-tooltip');
    if(!tooltip?.contains(window.document?.activeElement)) setHover(null);
  };
  const measuredText=new Map();
  let measureContext;
  const textContext=()=>measureContext??=window.document?.body
    ?window.document.createElement('canvas').getContext('2d'):undefined;
  function textWidth(text,fontSize,family) {
    const value=String(text??''), key=`${family}|${fontSize}|${value}`, known=measuredText.get(key);
    if(known!==undefined) return known;
    const context=textContext();
    if(!context) return Array.from(value).length*fontSize*.6;
    context.font=`${fontSize}px ${family}`;
    const width=context.measureText(value).width;
    if(window.document.fonts?.status==='loaded') {
      if(measuredText.size>200000) measuredText.clear();
      measuredText.set(key,width);
    }
    return width;
  }
  function pageFont() {
    const body=window.document?.body, style=body&&window.getComputedStyle(body);
    const family=style?.fontFamily||'sans-serif', size=(style&&parseFloat(style.fontSize))||16;
    const ratio=style?parseFloat(style.lineHeight)/size:NaN, context=textContext();
    const line=fontSize=>{
      if(Number.isFinite(ratio)) return ratio*fontSize;
      if(!context) return fontSize*1.2;
      context.font=`${fontSize}px ${family}`;
      const metrics=context.measureText('x');
      return Math.round(metrics.fontBoundingBoxAscent)+Math.round(metrics.fontBoundingBoxDescent);
    };
    return {family,size,line};
  }
  const labelFamily=(node,page)=>{
    const label=node?.querySelector?.('svg text');
    return label?window.getComputedStyle(label).fontFamily:page.family;
  };
  const withEdges=(lines,low,high)=>[low,...lines.filter(line=>Math.abs(line-low)>1e-6&&Math.abs(line-high)>1e-6),high];
  function preserveEndTicks(ticks,start,end,gap=5) {
    const shown=[];
    let limit=end;
    for(let i=ticks.length-1;i>=0;i--) {
      const tick=ticks[i], half=tick.size/2;
      const at=i===ticks.length-1?Math.min(tick.x,end-half):tick.x;
      if(at-half>=start&&at+half<=limit) {shown.push({...tick,at});limit=at-half-gap;}
    }
    return shown.reverse();
  }
  function intervalTicks(ticks,every,start,end) {
    return ticks.filter(({i})=>i%every===0).map(tick=>({...tick,
      at:Math.max(start+tick.size/2,Math.min(tick.x,end-tick.size/2))}));
  }
  function CartesianChart({
    kind='area', data=[], xKey, series=[], stackOffset='none', height=300,
    width, margin={}, yFormat=String, xFormat=String, tickEvery, yDomain,
    referenceX, referenceY, referenceOpacity=1, grid=true, xAxisLine=false,
    yAxisLine=false, tickLine=false, plotClass='', tooltip, ariaLabel='Chart',
    compact=false
  }) {
    const [ref,w]=useWidth(width), [hover,setHover]=useState(null), keyboardReading=useRef(false);
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
    let dataMin=Infinity, dataMax=-Infinity;
    const include=value=>{if(value<dataMin)dataMin=value;if(value>dataMax)dataMax=value;};
    bands.forEach((band,j)=>band.forEach(pair=>{include(pair[1]);if(series[j].stack)include(pair[0]);}));
    if(dataMin>dataMax) dataMin=dataMax=0;
    const {ticks,lo,hi}=axisDomain(yDomain,dataMin,dataMax);
    const y=linearScale([lo,hi],[bottom,top]);
    const base=Math.max(lo,Math.min(hi,0));
    const yLabelTicks=size=>preserveEndTicks(ticks.map(tick=>({tick,x:height-y(tick),size})),0,height)
      .map(({tick,at})=>({tick,at:height-at}));
    const page=pageFont(), axisFamily=labelFamily(ref.current,page);
    const shownY=compact?[]:yLabelTicks(page.line(11));
    const x=i=>data.length<=1?(left+right)/2:kind==='bar'
      ?left+(i+.5)*pw/data.length:left+i*pw/(data.length-1);
    const band=data.length?pw/data.length:0, bandOffset=band*.1;
    const barGap=slotCount>1&&band-2*bandOffset-(slotCount-1)*4>0?4:0;
    const rawBarWidth=slotCount?(band-2*bandOffset-(slotCount-1)*barGap)/slotCount:0;
    const barWidth=rawBarWidth>1?Math.round(rawBarWidth):rawBarWidth;
    const marks=series.map((s,j)=>{
      const b=bands[j], color=s.color||'currentColor';
      const low=pair=>s.stack?pair[0]:base;
      if(kind==='bar') {
        return b.map((pair,i)=>{
          const barHeight=Math.abs(y(pair[1])-y(low(pair)));
          return barHeight>0&&h('rect',{
            class:'svgc-bar',x:x(i)-band/2+bandOffset+(barWidth+barGap)*slots[j],
            y:Math.min(y(low(pair)),y(pair[1])),width:barWidth,
            height:barHeight,fill:s.fill||color,
            'fill-opacity':s.fillOpacity??1,stroke:color,
            'stroke-opacity':s.strokeOpacity??1,'stroke-width':s.strokeWidth??2,
            'stroke-dasharray':s.strokeDasharray
          });
        });
      }
      const upper=b.map((v,i)=>[x(i),y(v[1])]);
      const lower=b.map((v,i)=>[x(i),y(low(v))]);
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
      if(!data.length||!tooltip) return;
      const rect=e.currentTarget.getBoundingClientRect();
      const local=e.clientX-rect.left, localY=e.clientY-rect.top;
      if(local<left||local>right||localY<top||localY>bottom) {leaveChart(e,setHover);return;}
      const fraction=pw?(local-left)/pw:0;
      const index=data.length===1?0:kind==='bar'
        ?Math.min(data.length-1,Math.floor(fraction*data.length))
        :Math.round(fraction*(data.length-1));
      setHover({index,x:x(index),y:localY});
    };
    const keyHover=index=>({index,x:x(index),y:(top+bottom)/2});
    const surface=tooltip?{tabindex:0,role:'application','aria-label':ariaLabel,
      onFocus:event=>{
        keyboardReading.current=keyboardFocus(event);
        if(data.length&&!hover&&keyboardReading.current)setHover(keyHover(0));
      },
      onBlur:event=>{if(!event.currentTarget.parentElement?.contains(event.relatedTarget))setHover(null);},
      onKeyDown:event=>{
        if(!data.length) return;
        if(event.key==='Escape') {setHover(null);return;}
        const step=event.key==='ArrowRight'?1:event.key==='ArrowLeft'?-1:0;
        if(!step) return;
        event.preventDefault();
        // A page shortcut keeps these keys after a mouse click. Judged at focus, because
        // Chromium also matches :focus-visible on a mouse-focused element once a key is down.
        if(keyboardReading.current) event.stopPropagation();
        const index=hover?hover.index+step:step>0?0:data.length-1;
        setHover(keyHover(Math.max(0,Math.min(data.length-1,index))));
      }}:{};
    const row=hover&&data[hover.index];
    const payload=row&&{
      active:true,label:row[xKey],row,index:hover.index,
      payload:series.map(s=>({dataKey:s.key,name:s.label||s.key,
        value:row[s.key],color:s.color,payload:row}))
    };
    const cursorX=payload?x(hover.index):0;
    const refIndex=data.findIndex(row=>row[xKey]===referenceX);
    const options=typeof grid==='object' && grid!==null?grid:{};
    const horizontal=typeof grid==='object'?options.horizontal!==false:!!grid;
    const vertical=typeof grid==='object'&&options.vertical===true;
    const gridStroke=options.stroke??'var(--border-default, #334155)';
    const gridDash=options.strokeDasharray??'3 3';
    const tickStroke=typeof tickLine==='string'?tickLine:'var(--border-default, #334155)';
    const xLabels=compact?[]:data.map((row,i)=>{
      const label=xFormat(row[xKey]);
      return {i,label,x:x(i),size:textWidth(label,11,axisFamily)};
    });
    let widestLabel=0;
    for(const {size} of xLabels) if(size>widestLabel) widestLabel=size;
    const categoryGap=data.length>1?pw/(kind==='bar'?data.length:data.length-1):pw;
    const shownX=Number.isFinite(tickEvery)
      ?intervalTicks(xLabels,Math.max(1,Math.floor(tickEvery),categoryGap>0?Math.ceil((widestLabel+5)/categoryGap):1),0,w)
      :preserveEndTicks(xLabels,0,w);
    const gridX=vertical&&!compact?withEdges((Number.isFinite(tickEvery)?shownX
      :preserveEndTicks(xLabels.map(tick=>({...tick,size:textWidth(tick.label,page.size,page.family)})),0,w)).map(tick=>tick.x),left,right):[];
    const gridY=horizontal&&!compact?withEdges(yLabelTicks(page.line(page.size)).map(({tick})=>y(tick)),bottom,top):[];
    return h('div',{ref,class:'svgc-responsive',style:{...style,height,width:width||'100%'}},
      h('div',{class:'svgc-wrapper',style:{...wrapperStyle,height},
        onMouseMove:move,onMouseLeave:event=>leaveChart(event,setHover)},
        h('svg',{width:w,height,viewBox:`0 0 ${w} ${height}`,...surface},
          h('rect',{class:plotClass,x:left,y:top,width:pw,height:bottom-top,fill:'transparent'}),
          gridY.map(line=>h('line',{class:'svgc-grid-horizontal',x1:left,x2:right,
            y1:line,y2:line,stroke:gridStroke,'stroke-dasharray':gridDash})),
          gridX.map(lineX=>h('line',{
            class:'svgc-grid-vertical',x1:lineX,x2:lineX,y1:top,y2:bottom,
            stroke:gridStroke,'stroke-dasharray':gridDash
          })),
          payload&&kind==='bar'&&h('rect',{class:'svgc-cursor',x:cursorX-band/2,y:top+.5,
            width:band,height:Math.max(0,bottom-top-1),fill:'#ccc','pointer-events':'none'}),
          marks,
          refIndex>=0&&h('line',{class:'svgc-reference-line',x:referenceX,
            x1:x(refIndex),x2:x(refIndex),y1:top,y2:bottom,
            stroke:'#94a3b8','stroke-opacity':referenceOpacity,'stroke-dasharray':'3 3'}),
          referenceY!=null&&h('line',{class:'svgc-reference-line',x:referenceY,
            x1:left,x2:right,y1:y(referenceY),y2:y(referenceY),
            stroke:'var(--border-default, #94a3b8)','stroke-opacity':referenceOpacity}),
          !compact&&xAxisLine&&h('line',{
            class:'svgc-x-axis-line',x1:left,x2:right,y1:bottom,y2:bottom,
            stroke:typeof xAxisLine==='string'?xAxisLine:'var(--border-default, #334155)'
          }),
          !compact&&yAxisLine&&h('line',{
            class:'svgc-y-axis-line',x1:left,x2:left,y1:top,y2:bottom,
            stroke:typeof yAxisLine==='string'?yAxisLine:'var(--border-default, #334155)'
          }),
          !compact&&tickLine&&shownX.map(({x:tickX})=>h('line',{class:'svgc-tick-line',
            x1:tickX,x2:tickX,y1:bottom,y2:bottom+6,stroke:tickStroke})),
          tickLine&&shownY.map(({tick})=>h('line',{class:'svgc-tick-line',
            x1:left-6,x2:left,y1:y(tick),y2:y(tick),stroke:tickStroke})),
          payload&&kind!=='bar'&&h('line',{class:'svgc-cursor',x1:cursorX,x2:cursorX,y1:top,y2:bottom,
            stroke:'#ccc','pointer-events':'none'}),
          payload&&kind!=='bar'&&series.map((s,j)=>h('circle',{class:'svgc-active-dot',cx:cursorX,
            cy:y(bands[j][hover.index][1]),r:4,fill:s.color||'currentColor',stroke:'#fff','stroke-width':2,
            'pointer-events':'none'})),
          shownY.map(({tick,at})=>h('text',{x:left-8,y:at,dy:'.355em',
            fill:'var(--text-muted, #94a3b8)','text-anchor':'end','font-size':11},yFormat(tick))),
          !compact&&shownX.map(({label,at})=>h('text',{
            x:at,y:bottom+8,dy:'.71em',fill:'var(--text-muted, #94a3b8)',
            'text-anchor':'middle','font-size':11
          },label))
        ),
        tooltipNode(tooltip,payload,{...hover,plot:{left,top,right,bottom}},()=>setHover(null))
      )
    );
  }
  const itemPayload=hover=>hover&&{active:true,label:hover.item.label,payload:[{dataKey:'value',
    name:hover.item.label,value:hover.item.value,color:hover.item.color,payload:hover.item}]};
  function DonutChart({items=[],height=250,innerRadius=50,outerRadius=85,tooltip,onSelect,
    startAngle=-Math.PI/2,clockwise=true,stroke,strokeWidth,cy}) {
    const [ref,w]=useWidth(),[hover,setHover]=useState(null);
    const centreY=number(cy)||height/2;
    const total=items.reduce((sum,item)=>sum+Math.max(0,number(item.value)),0);
    let angle=number(startAngle);
    const sectors=items.map(item=>{
      const start=angle;
      angle+=total?(clockwise?1:-1)*Math.max(0,number(item.value))/total*2*Math.PI:0;
      const middle=(start+angle)/2, radius=(innerRadius+outerRadius)/2;
      const show=()=>setHover({item,x:w/2+radius*Math.cos(middle),y:centreY+radius*Math.sin(middle)});
      const hide=()=>setHover(null);
      return h('path',{class:'svgc-sector',d:arcPath(w/2,centreY,innerRadius,outerRadius,start,angle),
        fill:item.color,stroke,'stroke-width':strokeWidth,...selectable(item,onSelect),
        onMouseMove:show,onMouseLeave:hide,
        onFocus:event=>{if(keyboardFocus(event))show();},onBlur:hide},h('title',null,item.label));
    });
    return h('div',{ref,class:'svgc-responsive',style:{...style,height}},
      h('div',{class:'svgc-wrapper',style:{...wrapperStyle,height},onMouseLeave:event=>leaveChart(event,setHover)},
        h('svg',{width:w,height},sectors),
        tooltipNode(tooltip,itemPayload(hover),hover||{},()=>setHover(null))));
  }
  function HBarChart({items=[],height=250,valueFormat=String,labelWidth=130,labelMaxChars=Infinity,onSelect,tooltip}) {
    const [ref,w]=useWidth(),[hover,setHover]=useState(null);
    const left=5+labelWidth, right=Math.max(left,w-5), top=5, bottom=Math.max(top,height-35);
    let dataMin=0, dataMax=0;
    for(const item of items) {const value=number(item.value);if(value<dataMin)dataMin=value;if(value>dataMax)dataMax=value;}
    const ticks=niceTicks(dataMin,dataMax), position=linearScale([ticks[0],ticks.at(-1)],[left,right]);
    const rowHeight=(bottom-top)/Math.max(1,items.length), zero=position(0);
    const axisStroke='var(--border-default, #475569)';
    const rowHover=(index,x)=>({index,item:items[index],x,y:top+(index+.5)*rowHeight});
    const move=event=>{
      if(!tooltip||!items.length) return;
      const rect=event.currentTarget.getBoundingClientRect();
      const localX=event.clientX-rect.left, localY=event.clientY-rect.top;
      if(localX<left||localX>right||localY<top||localY>bottom) {leaveChart(event,setHover);return;}
      setHover(rowHover(Math.min(items.length-1,Math.floor((localY-top)/rowHeight)),localX));
    };
    const page=pageFont(), axisFamily=labelFamily(ref.current,page);
    const shownRows=new Set(preserveEndTicks(items.map((_,i)=>({i,x:top+(i+.5)*rowHeight,size:page.line(page.size)})),0,height).map(({i})=>i));
    const bars=items.map((item,i)=>{
      const label=String(item.label??''), value=number(item.value), end=position(value);
      const short=label.length>labelMaxChars?label.slice(0,Math.max(0,labelMaxChars-2))+'…':label;
      const barY=top+i*rowHeight+rowHeight*.1, barHeight=rowHeight*.8;
      return h('g',null,
        shownRows.has(i)&&h('text',{x:left-12,y:top+(i+.5)*rowHeight,dy:4,'text-anchor':'end',
          fill:'var(--text-muted, #94a3b8)','font-size':10},h('title',null,label),short),
        shownRows.has(i)&&h('line',{class:'svgc-tick-line',x1:left-6,x2:left,y1:top+(i+.5)*rowHeight,y2:top+(i+.5)*rowHeight,stroke:axisStroke}),
        h('path',{class:'svgc-bar',d:barPath(zero,end,barY,barHeight),x:Math.min(zero,end),y:barY,
          width:Math.abs(end-zero),height:barHeight,
          fill:item.color,'aria-label':item.ariaLabel||`${label}: ${valueFormat(value)}`,
          ...selectable(item,onSelect),
          onFocus:event=>{if(keyboardFocus(event))setHover(rowHover(i,Math.max(zero,end)));},
          onBlur:()=>setHover(null)})
      );
    });
    const tickLabels=preserveEndTicks(ticks.map((value,i)=>{
      const label=valueFormat(value);
      return {i,value,label,x:position(value),size:textWidth(label,11,axisFamily)};
    }),0,w);
    return h('div',{ref,class:'svgc-responsive',style:{...style,height}},
      h('div',{class:'svgc-wrapper',style:{...wrapperStyle,height},onMouseMove:move,onMouseLeave:event=>leaveChart(event,setHover)},
        h('svg',{width:w,height},
          hover&&h('rect',{class:'svgc-cursor',x:left+.5,y:top+hover.index*rowHeight,
            width:Math.max(0,right-left-1),height:rowHeight,fill:'#ccc','pointer-events':'none'}),
          bars,
          h('line',{class:'svgc-hbar-axis',x1:left,x2:right,y1:bottom,y2:bottom,stroke:axisStroke}),
          h('line',{class:'svgc-hbar-category-axis',x1:left,x2:left,y1:top,y2:bottom,stroke:axisStroke}),
          tickLabels.map(({x:tickX,at,label})=>[
            h('line',{class:'svgc-tick-line',x1:tickX,x2:tickX,y1:bottom,y2:bottom+6,stroke:axisStroke}),
            h('text',{class:'svgc-hbar-tick',x:at,y:bottom+8,dy:'.71em','text-anchor':'middle',
              fill:axisStroke,'font-size':11},label)
          ])
        ),
        tooltipNode(tooltip,itemPayload(hover),{...hover,plot:{left,top,right,bottom}},()=>setHover(null))));
  }
  function Legend({series=[],hidden=new Set(),onToggle,kind='area'}) {
    return h('div',{class:'svgc-legend'},series.map(s=>{
      const color=s.color||'currentColor';
      const symbol=kind==='bar'
        ?h('path',{d:'M0,4h32v24h-32z',fill:color,stroke:'none'})
        :h('path',{d:'M0,16h10.67A5.33,5.33,0,1,1,21.33,16H32M21.33,16A5.33,5.33,0,1,1,10.67,16',
          fill:'none',stroke:color,'stroke-width':4,'stroke-dasharray':s.strokeDasharray});
      return h('button',{type:'button',class:'svgc-legend-item',
        'aria-pressed':!hidden.has(s.key),onClick:()=>onToggle?.(s.key),
        style:{color:s.color,opacity:hidden.has(s.key)?.45:1}},
        h('svg',{'aria-hidden':'true',width:14,height:14,viewBox:'0 0 32 32'},symbol),s.label||s.key);
    }));
  }
  window.svgCharts={geometry:{linearScale,niceTicks,fixedTicks,axisDomain,preserveEndTicks,barPath,stack,monotonePath,areaPath,arcPath,tooltipPosition},CartesianChart,DonutChart,HBarChart,Legend};
})();
