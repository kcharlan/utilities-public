import {airEffect} from './world.js';
const colors=['#b9d5e5','#f1b39b','#f2cd8c','#bbd9d0','#d9d5ad'];
const names=['AC · steady upward push','Vent · pulsing steam','Roof heat · gentle upward push','Tailwind · forward + upward push','Thermal · weaker higher up'];

export function drawAir(renderer,a,run,X,Y,s,v){
  const ctx=renderer.ctx,w=renderer.w,h=renderer.h,left=X(a.x),right=X(a.x+a.w);
  if(right<0||left>w)return;
  const time=run.worldTicks/60,top=Y(a.top),bottom=Y(a.y),color=colors[a.type];
  const effect=airEffect(a,run.plane.y,time),active=run.plane.x>=a.x&&run.plane.x<=a.x+a.w;
  const phase=renderer.reduced?0:(time*14)%28;
  ctx.fillStyle=color;ctx.globalAlpha=a.type===1?.035+effect.activity*.13:.065;
  ctx.fillRect(left,top,right-left,bottom-top);ctx.globalAlpha=1;
  ctx.strokeStyle=color+(active?'aa':'55');ctx.lineWidth=active?1.5:1;ctx.setLineDash([4,8]);
  ctx.strokeRect(left,top,right-left,bottom-top);ctx.setLineDash([]);
  ctx.lineWidth=Math.max(1,s*.75);
  if(a.type===0){
    // Narrow, orderly blue chevrons identify constant mechanical lift.
    ctx.strokeStyle=color+'bb';
    for(let xx=a.x+18;xx<a.x+a.w;xx+=38)for(let yy=a.y+12;yy<a.top-20;yy+=28){
      const x=X(xx),y=Y(yy+phase);ctx.beginPath();ctx.moveTo(x-5,y+5);ctx.lineTo(x,y);ctx.lineTo(x+5,y+5);ctx.stroke();
    }
  }else if(a.type===1){
    // Steam occupies the full influence region; its opacity/width tracks physical power.
    ctx.fillStyle=color;
    for(let i=0;i<3;i++)for(let j=0;j<7;j++){
      const yy=a.y+12+j*(a.top-a.y-25)/7+phase;
      if(yy>a.top-6)continue;
      const x=X(a.x+a.w*(i+1)/4)+Math.sin(j*1.9+i)*6;
      ctx.globalAlpha=.025+effect.activity*.24;
      ctx.beginPath();ctx.ellipse(x,Y(yy),(9+effect.activity*10)*s,Math.max(5,7*v),0,0,Math.PI*2);ctx.fill();
    }ctx.globalAlpha=1;
    ctx.strokeStyle=color;ctx.lineWidth=2;
    for(let i=0;i<4;i++){
      const x=X(a.x+a.w*(i+1)/5),y=Y(a.y+10+(renderer.reduced?0:phase));
      ctx.beginPath();ctx.moveTo(x-5,y);ctx.quadraticCurveTo(x+8,y-12,x,y-24);ctx.stroke();
    }
  }else if(a.type===2){
    // Broad warm arches distinguish a thermal from the straight AC arrows.
    ctx.strokeStyle=color+'a0';
    for(let yy=a.y+15;yy<a.top-10;yy+=30){
      const y=Y(yy+phase);ctx.beginPath();ctx.moveTo(left+12,y+9);ctx.quadraticCurveTo((left+right)/2,y-15,right-12,y+9);ctx.stroke();
    }
  }else if(a.type===3){
    ctx.strokeStyle=color+'cc';ctx.lineWidth=1.6;
    const shift=renderer.reduced?0:(time*32)%44;
    for(let yy=a.y+18;yy<a.top-6;yy+=26)for(let xx=a.x+12;xx<a.x+a.w-30;xx+=55){
      const x=X(xx+shift),y=Y(yy);ctx.beginPath();ctx.moveTo(x-16,y+2);ctx.quadraticCurveTo(x,y-6,x+17,y);ctx.lineTo(x+12,y-4);ctx.moveTo(x+17,y);ctx.lineTo(x+12,y+4);ctx.stroke();
      ctx.beginPath();ctx.moveTo(x-4,y+4);ctx.lineTo(x,y-4);ctx.lineTo(x+4,y);ctx.stroke();
    }
  }else{
    // The same height falloff used by the simulation fades the visible rings.
    ctx.strokeStyle=color;
    for(let yy=a.y+15;yy<a.top-10;yy+=25){
      ctx.globalAlpha=airEffect(a,yy,time).activity*.7;
      ctx.beginPath();ctx.ellipse((left+right)/2,Y(yy+phase),(right-left)*.38,Math.max(3,3*v),0,0,Math.PI*2);ctx.stroke();
    }ctx.globalAlpha=1;
  }
  const mx=left+18*s,my=Y(a.y-4);
  ctx.fillStyle='#7b8191';ctx.fillRect(mx,my-7*s,16*s,8*s);ctx.fillStyle='#343e55';ctx.fillRect(mx+3*s,my-5*s,10*s,4*s);
  if(a.type===0){ctx.strokeStyle='#c9c4ca';ctx.beginPath();ctx.arc(mx+8*s,my-3*s,3*s,0,Math.PI*2);ctx.stroke();}
  const name=a.type===1?(effect.activity>.35?'Vent · steam burst ↑':'Vent · lull · save speed'):names[a.type];
  renderer.label(name,Math.max(10,Math.min(w-185,left+8)),Math.max(155,top-12),color,11);
  if(active){
    const explanation=['AC adds upward push','Steam gusts push upward','Warm roof: gentle upward push','Wind pushes forward and upward','Higher means less upward push'];
    const direction=a.gapId?.endsWith('.1')?'Hold early · climb over the flock':a.gapId?.endsWith('.3')?'Release to dive · then level out':explanation[a.type];
    renderer.label(direction,Math.max(10,Math.min(w-218,left+10)),Math.max(185,Math.min(h-115,Y(190))),'#ffe3a8',11);
  }
}
