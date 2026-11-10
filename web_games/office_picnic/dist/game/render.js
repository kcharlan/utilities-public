import {cameraFor} from './session.js';
import {hazardBox,hazardParts,hazardAdvice,upcomingHazard,hazardKey,pickupPos} from './world.js';
import {drawAir,drawWind} from './air-render.js';
const C={ink:'#302f48',shadow:'#4f4b64',sky:'#9b8cbb',warm:'#f1a290',paper:'#fff0d3',window:'#f3bd86',green:'#7d887d'};
const hash=n=>{const x=Math.sin(n*127.1+311.7)*43758.5453;return x-Math.floor(x);};
function squeezePassage(world,hazard,time){
  const pair=world.hazards.filter(h=>h.squeeze&&hazardKey(h)===hazardKey(hazard));
  const washer=pair.find(h=>h.kind==='platform'),flock=pair.find(h=>h.kind==='pigeon');
  if(!washer||!flock)return hazardBox(hazard,time);
  const a=hazardBox(washer,time),b=hazardBox(flock,time),x=Math.max(a.x,b.x),y=b.y+b.h;
  return {x,y,w:Math.max(0,Math.min(a.x+a.w,b.x+b.w)-x),h:Math.max(0,a.y-y)};
}
export class Renderer{
  constructor(canvas){
    this.canvas=canvas;this.ctx=canvas.getContext('2d',{alpha:false});this.reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.plane=new Image();this.plane.src='./assets/plane-sheet.png';this.pigeon=new Image();this.pigeon.src='./assets/pigeon-sheet.png';this.washer=new Image();this.washer.src='./assets/washer-v1.png';this.cache=[];this.resize();
  }
  resize(){
    this.w=this.canvas.clientWidth;this.h=this.canvas.clientHeight;const ratio=Math.min(devicePixelRatio||1,2);
    this.canvas.width=Math.round(this.w*ratio);this.canvas.height=Math.round(this.h*ratio);this.ctx.setTransform(ratio,0,0,ratio,0,0);
    this.scenery=this.makeScenery();this.grain=this.makeGrain();
    this.cache=[this.skyline(0),this.skyline(1)];
  }
  makeScenery(){
    const sky=document.createElement('canvas');sky.width=1;sky.height=Math.max(1,this.h);const c=sky.getContext('2d');
    const g=c.createLinearGradient(0,0,0,sky.height);for(const [p,color] of [[0,'#777fa5'],[.44,C.sky],[.72,'#d49eaa'],[.87,C.warm],[1,'#e6b59f']])g.addColorStop(p,color);
    c.fillStyle=g;c.fillRect(0,0,1,sky.height);
    const body=document.createElement('canvas');body.width=128;body.height=512;const b=body.getContext('2d');
    const wash=b.createLinearGradient(0,0,0,512);wash.addColorStop(0,'#666477');wash.addColorStop(.35,'#44495f');wash.addColorStop(1,'#333d55');b.fillStyle=wash;b.fillRect(0,0,128,512);
    for(let x=9;x<128;x+=16)for(let y=16;y<512;y+=24){b.fillStyle=hash(x+y)>.52?'#e8b58c':'#7c829750';b.fillRect(x-2,y-2,9,13);b.fillStyle=hash(x+y)>.52?'#f3bd86':'#7c829760';b.fillRect(x,y,5,9);}
    const ground=document.createElement('canvas');ground.width=1;ground.height=128;const gctx=ground.getContext('2d'),grass=gctx.createLinearGradient(0,0,0,128);
    grass.addColorStop(0,'#91a18b');grass.addColorStop(.3,'#697f79');grass.addColorStop(1,'#485e67');gctx.fillStyle=grass;gctx.fillRect(0,0,1,128);
    const tree=document.createElement('canvas');tree.width=40;tree.height=55;const tc=tree.getContext('2d');
    tc.fillStyle='#485e67';tc.fillRect(18,30,4,25);tc.fillStyle='#74877b';tc.beginPath();tc.arc(20,20,18,0,Math.PI*2);tc.fill();tc.fillStyle='#9ca68c';tc.beginPath();tc.arc(14,14,10,0,Math.PI*2);tc.fill();
    return {sky,body,ground,tree};
  }
  makeGrain(){
    const tile=document.createElement('canvas');tile.width=Math.max(1,this.w);tile.height=Math.max(1,this.h);const c=tile.getContext('2d');
    for(let i=0;i<this.w*this.h/35;i++){const x=hash(i+17)*this.w,y=hash(i+993)*this.h;c.fillStyle=i%2?'#fff0d30c':'#302f480a';c.fillRect(x,y,1,1);}
    return tile;
  }
  skyline(layer){
    const tile=document.createElement('canvas');tile.width=1200;tile.height=500;const c=tile.getContext('2d');
    for(let i=0;i<32;i++){
      const x=i*39,w=30+hash(i+layer*32)*35,h=60+hash(i+7+layer*81)*300,y=500-h;
      const wash=c.createLinearGradient(0,y,0,500);wash.addColorStop(0,layer?'#77788d':'#aaa0ac');wash.addColorStop(1,layer?'#5b607b':'#7e7d9b');c.fillStyle=wash;
      c.beginPath();c.moveTo(x,500);c.lineTo(x,y+5);c.lineTo(x+w*.25,y+5);c.lineTo(x+w*.25,y);c.lineTo(x+w*.8,y);c.lineTo(x+w*.8,y+3);c.lineTo(x+w,y+3);c.lineTo(x+w,500);c.closePath();c.fill();
      c.fillStyle=layer?'#efb79580':'#ecc0ac50';
      for(let xx=x+6;xx<x+w-4;xx+=10)for(let yy=y+12;yy<490;yy+=16)if(hash(xx+yy)> .54)c.fillRect(xx,yy,3,5);
      if(i%5===0){c.strokeStyle=layer?'#5b607b':'#7e7d9b';c.lineWidth=2;c.beginPath();c.moveTo(x+w/2,y);c.lineTo(x+w/2,y-18);c.stroke();}
    }return tile;
  }
  draw(run,held,alpha=0,effects=null){
    const ctx=this.ctx,w=this.w,h=this.h,p=run.plane;
    this.labelRects=[];
    const display={...p};if(run.previous&&run.status==='flying'){display.x=run.previous.x+(p.x-run.previous.x)*alpha;display.y=run.previous.y+(p.y-run.previous.y)*alpha;}
    const landing=run.status==='landing'||run.status==='finished',t=run.status==='finished'?1:Math.min(1,(run.landingTicks||0)/run.landingDurationTicks),ease=t*t*(3-2*t);
    const fixedLanding=run.status==='landing'&&this.reduced;
    const anchor=fixedLanding?run.landingStart:display;
    const cam=cameraFor(w,h,anchor,landing&&!fixedLanding?{focus:{x:run.world.length,y:30},zoom:Math.min(3.2,w/210,h/130),progress:ease}:{});
    if(w>0&&h>0&&(run.status==='landing'||(run.status==='flying'&&display.x>run.world.finishStart))){
      // Keep the table and plane in view through the approach. Reduced motion
      // uses the capture position for a fixed landing camera until the cut.
      const minX=Math.min(anchor.x-12,run.world.length-70),maxX=Math.max(anchor.x+12,run.world.length+70);
      const minY=Math.min(0,anchor.y),maxY=Math.max(51,anchor.y);
      const margin=Math.min(36,w/4,h/4);
      cam.scale=Math.min(cam.scale,(w-2*margin)/(maxX-minX));
      cam.verticalScale=Math.min(cam.verticalScale,(h-2*margin)/(maxY-minY));
      cam.left=Math.max(maxX-(w-margin)/cam.scale,Math.min(cam.left,minX-margin/cam.scale));
      cam.bottom=Math.max(maxY-(h-margin)/cam.verticalScale,Math.min(cam.bottom,minY-margin/cam.verticalScale));
    }
    const s=cam.scale;
    const X=x=>(x-cam.left)*s,Y=y=>h-(y-cam.bottom)*cam.verticalScale;
    // Reserve the plane's rotated, possibly stretched sprite footprint before any labels.
    const planeX=X(display.x),planeY=Y(display.y),planeRadius=Math.max(58,21*s);
    this.labelRects.push({left:planeX-planeRadius,right:planeX+planeRadius,top:planeY-planeRadius,bottom:planeY+planeRadius});
    for(const washer of run.world.hazards.filter(h=>h.squeeze&&h.kind==='platform')){
      const flock=run.world.hazards.find(h=>h.squeeze&&h.kind==='pigeon'&&hazardKey(h)===hazardKey(washer));if(!flock)continue;
      const a=hazardBox(washer,run.worldTicks/60),b=hazardBox(flock,run.worldTicks/60),margin=Math.max(17,7.5*s);
      const rect={left:Math.min(X(a.x),X(b.x))-margin,right:Math.max(X(a.x+a.w),X(b.x+b.w))+margin,top:Math.min(Y(a.y+a.h),Y(b.y+b.h))-margin,bottom:Math.max(Y(a.y),Y(b.y))+margin};
      if(rect.right>0&&rect.left<w&&rect.bottom>0&&rect.top<h)this.labelRects.push(rect);
    }
    if(this.scenery)ctx.drawImage(this.scenery.sky,0,0,w,h);else{ctx.fillStyle=this.gradient;ctx.fillRect(0,0,w,h);}
    ctx.save();if(effects?.bump&&!this.reduced)ctx.translate(Math.sin(effects.bump*2)*Math.min(4,effects.bump),0);
    // Cached city layers, painted once on resize.
    for(let layer=0;layer<2;layer++){
      const tw=1200*(h/850),th=h*(layer?.57:.43),offset=this.reduced?0:((p.x*(layer?.17:.075))%tw);
      ctx.globalAlpha=layer?.75:.65;
      for(let x=-offset-tw;x<w;x+=tw)ctx.drawImage(this.cache[layer],x,h-th,tw,th);
    }ctx.globalAlpha=1;
    if(p.x>run.world.finishStart-550)this.park(ctx,X,Y,s,run,effects);
    for(const b of run.world.buildings){
      if(X(b.x+b.w)<-10||X(b.x)>w+10)continue;
      const bx=X(b.x),by=Y(b.y),bw=b.w*s;
      if(this.scenery){
        const step=128*s,body=this.scenery.body;
        for(let xx=Math.max(0,Math.floor(-bx/step));bx+xx*step<Math.min(w,bx+bw);xx++){
          const left=bx+xx*step,right=Math.min(bx+bw,left+step),height=h-by;
          for(let yy=0;yy<height;yy+=512*s){const slice=Math.min(512*s,height-yy);if(right>0)ctx.drawImage(body,0,0,(right-left)/s,slice/s,left,by+yy,right-left,slice);}
        }
      }else{ctx.fillStyle='#41485e';ctx.fillRect(bx,by,bw,h-by);}
      ctx.fillStyle='#77758a';ctx.fillRect(bx,by,bw,4*s);
      ctx.fillStyle='#2f384e';ctx.fillRect(bx,by+4*s,bw,3*s);
      // Rooftop railings mark the solid top; lift machinery below.
      ctx.strokeStyle='#9c9aaa';ctx.lineWidth=Math.max(1,s*.6);ctx.beginPath();ctx.moveTo(bx,Y(b.y+4));ctx.lineTo(bx+bw,Y(b.y+4));ctx.stroke();
    }
    if(this.grain)ctx.drawImage(this.grain,0,0,w,h);
    if(p.x>run.world.finishStart-550){ctx.fillStyle=C.paper;ctx.font=`bold ${Math.max(9,7*s)}px sans-serif`;ctx.textAlign='center';ctx.fillText('Office Picnic',X(run.world.length),Y(54));ctx.textAlign='start';}
    if(run.mode==='standard')for(const cp of run.world.checkpoints){
      const roof=run.world.airs.find(a=>a.gapId===cp.id);if(!roof)continue;
      const x=X(Math.max(roof.x,Math.min(cp.x,roof.x+roof.w))),y=Y(roof.y-4);
      if(x<0||x>w)continue;
      ctx.beginPath();ctx.arc(x,y-4,Math.max(2,2.5*s),0,Math.PI*2);ctx.fillStyle=cp.x<=run.checkpoint.x?'#ffe3a8':'#77758a';ctx.fill();
    }
    for(const zone of run.world.winds)drawWind(this,zone,run,X,Y);
    for(const a of run.world.airs)drawAir(this,a,run,X,Y,s,cam.verticalScale);
    for(const hazard of run.world.hazards){
      const b=hazardBox(hazard,run.worldTicks/60),x=X(b.x),y=Y(b.y),dx=b.x-p.x;
      if(x<-80||x>w+80)continue;
      if(hazard.kind==='pigeon'){
        const size=Math.max(33,15*s),frame=this.reduced?0:Math.floor(run.worldTicks/9)%4;
        for(let i=0;i<2;i++)this.sprite(this.pigeon,(frame+i)%4,X(b.x+b.w*(i===0?.2:.8)),Y(b.y+b.h*(i%2?.7:.35)),size,size,0);
        if(!hazard.squeeze&&run.world.tier.prompts!=='quiet'&&x<w&&dx>-b.w&&dx<hazard.warningDistance)this.label(hazardAdvice(hazard),Math.min(w-155,Math.max(10,x-44)),Y(b.y+b.h)-25,'#ffe3a8',12);
      }else{
        for(const cable of hazardParts(hazard,run.worldTicks/60).filter(part=>part.part==='cable')){
          const cx=X(cable.x+cable.w/2);ctx.strokeStyle='#37405c';ctx.lineWidth=Math.max(2.5,cable.w*s+1);ctx.beginPath();ctx.moveTo(cx,Y(cable.y+cable.h));ctx.lineTo(cx,Y(cable.y));ctx.stroke();
          ctx.strokeStyle='#ced0da';ctx.lineWidth=Math.max(.8,cable.w*s*.5);ctx.stroke();
        }
        const image=this.washer,width=b.w*s,height=b.h*cam.verticalScale,center=X(b.x+b.w/2);
        if(image.complete&&image.naturalWidth)ctx.drawImage(image,center-width/2,y-height,width,height);
        else{ctx.fillStyle='#d5b18b';ctx.fillRect(center-width/2,y-8,width,8);}
        if(!hazard.squeeze&&run.world.tier.prompts!=='quiet'&&x<w&&dx>-b.w&&dx<hazard.warningDistance)this.label(hazardAdvice(hazard),Math.min(w-195,Math.max(10,x-65)),Math.min(h-110,y+23),'#ffe3a8',12);
      }
    }
    for(const base of run.world.pickups){
      if(run.collected.has(base.id))continue;
      const pk=pickupPos(run.world,base,run.worldTicks/60),x=X(pk.x),y=Y(pk.y);
      if(x< -40||x>w+40||y< -40||y>h+40)continue;
      ctx.beginPath();ctx.arc(x,y,Math.max(7,pk.r*s),0,Math.PI*2);ctx.fillStyle='#ffe3a8';ctx.fill();
      ctx.strokeStyle='#544457';ctx.lineWidth=2;ctx.stroke();
      this.label('−'+pk.rewardTicks/60+'s',x+10,y-9,'#fff0d3',12);
    }
    // Label a squeeze once, at its shared window rather than on each member.
    if(run.world.tier.prompts!=='quiet')for(const hazard of run.world.hazards.filter(h=>h.squeeze&&h.kind==='platform')){
      const b=hazardBox(hazard,run.worldTicks/60),flock=run.world.hazards.find(h=>h.squeeze&&h.district===hazard.district&&h.slot===hazard.slot&&h.kind==='pigeon');
      const f=hazardBox(flock,run.worldTicks/60),dx=b.x-p.x;
      if(X(b.x)<w&&X(b.x+b.w)>0&&dx>-b.w&&dx<hazard.warningDistance){
        this.label(hazardAdvice(hazard),Math.max(10,X(b.x)-65),Y((b.y+f.y+f.h)/2)-20,'#ffe3a8',12);
      }
    }
    // If a warning source is outside the camera vertically, keep its direction legible.
    const incoming=run.world.tier.prompts==='full'?upcomingHazard(run.world,p.x):run.world.hazards.find(h=>{
      const box=hazardBox(h,run.worldTicks/60);
      return box.x+box.w+8>p.x&&box.x-p.x<h.warningDistance;
    });
    const squeeze=run.world.hazards.find(h=>h.squeeze&&run.warned.has(hazardKey(h))&&hazardBox(h,run.worldTicks/60).x+h.w+8>p.x);
    const marker=squeeze||incoming;
    if(marker){
      const b=marker.squeeze?squeezePassage(run.world,marker,run.worldTicks/60):hazardBox(marker,run.worldTicks/60);
      if(marker.squeeze)b.y+=b.h/2;
      const offscreen=X(b.x)>w-15;if(offscreen||Y(b.y)<155){
        const mx=Math.max(10,Math.min(w-218,w*.35));
        this.label((run.world.tier.prompts==='full'?(offscreen?'→ ':''):'→ ')+(run.world.tier.prompts==='quiet'?'':hazardAdvice(marker)),mx,182,'#ffe3a8',12);
      }}
    if(effects)for(const cue of effects.cues)if(cue.name==='warning'&&cue.hazardKey){
      const hazard=run.world.hazards.find(h=>hazardKey(h)===cue.hazardKey);
      if(hazard)this.drawWarningCue(hazard,cue,run,X,Y);
    }
    if(p.x<70){
      const bx=X(-34),by=Y(138);ctx.fillStyle='#384459';ctx.fillRect(bx,by,30*s,h-by);ctx.fillStyle='#f4c68d';ctx.fillRect(bx+5*s,by+7*s,20*s,29*s);ctx.strokeStyle='#aeb2bd';ctx.strokeRect(bx+5*s,by+7*s,20*s,29*s);this.label('40th floor',Math.max(8,bx),by-10,'#fff0d3',11);
    }
    const finished=run.status==='finished';
    if(run.status!=='respawning'||run.respawnTicks%10<5){
      let size=Math.max(58,21*s),rotation=finished?-.48:-p.pitch,stretch=1;
      if(effects&&!this.reduced)for(const cue of effects.cues){
        if(cue.name==='respawn')size*=Math.min(1,.45+cue.age/20);
        if(cue.name==='pitch'||cue.name==='release')stretch=1+.16*(1-cue.age/cue.life);
        if(cue.name==='stall')rotation+=Math.sin(cue.age*.7)*.13*(1-cue.age/cue.life);
      }
      const frame=p.stalled?3:held?1:0;
      this.sprite(this.plane,frame,planeX,planeY,size*stretch,size*.77,rotation);
      if(p.stalled)this.label('Stall · release to recover',Math.max(12,Math.min(w-190,planeX-45)),planeY-32,'#ffe3a8',12);
    }
    if(p.y>cam.bottom+h/s-25)this.label('↑ Plane above view',20,190,C.paper,12);
    if(effects)this.drawEffects(effects,X,Y);
    ctx.restore();
  }
  drawWarningCue(hazard,cue,run,X,Y){
    const ctx=this.ctx,b=hazard.squeeze?squeezePassage(run.world,hazard,run.worldTicks/60):hazardBox(hazard,run.worldTicks/60),x=X(b.x),y=Y(b.y+b.h),right=X(b.x+b.w),bottom=Y(b.y);
    const fixed=this.reduced||cue.reduced;ctx.strokeStyle='#ffe3a8';ctx.lineWidth=2;ctx.globalAlpha=fixed?1:.55+.45*Math.sin(Math.PI*cue.age/cue.life);
    if(right>=0&&x<=this.w&&bottom>=0&&y<=this.h){if(hazard.squeeze)ctx.strokeRect(x,y,right-x,bottom-y);else ctx.strokeRect(x-5,y-5,Math.max(10,right-x+10),Math.max(10,bottom-y+10));}
    else this.label('→ '+hazardAdvice(hazard),Math.max(10,Math.min(this.w-218,this.w*.35)),215,'#ffe3a8',12);
    ctx.globalAlpha=1;
  }
  drawEffects(effects,X,Y){
    const ctx=this.ctx;
    if(!this.reduced)for(const p of effects.particles){
      const x=X(p.x),y=Y(p.y);ctx.globalAlpha=1-p.age/p.life;
      ctx.fillStyle=p.kind==='drop'?'#a9d5e6':p.kind==='sparkle'?'#ffe3a8':p.kind==='steam'?'#e8e1df':p.kind==='salad'?'#f5dfad':'#fff0d3';
      if(p.kind==='sheet')ctx.fillRect(x-3,y-2,6,4);
      else if(p.kind==='feather'){ctx.fillStyle='#e7d5c9';ctx.beginPath();ctx.ellipse(x,y,2,5,-.6,0,Math.PI*2);ctx.fill();}
      else{ctx.beginPath();ctx.arc(x,y,p.kind==='steam'?5:2.5,0,Math.PI*2);ctx.fill();}
    }
    ctx.globalAlpha=1;
    for(const cue of effects.cues){
      if(cue.name==='warning'&&cue.hazardKey)continue;
      if(cue.name==='district'){const offset=cue.reduced||this.reduced?0:(1-Math.min(1,cue.age/15))*100;this.label(cue.district,Math.max(12,this.w*.38-offset),this.h-180,'#fff0d3',16);continue;}
      if(cue.visual==='splash'){
        if(cue.reduced||this.reduced){ctx.fillStyle='#f5dfad';for(const [dx,dy] of [[-16,-12],[-8,-23],[9,-21],[18,-10]]){ctx.beginPath();ctx.ellipse(X(cue.x)+dx,Y(cue.y)+dy,4,3,0,0,Math.PI*2);ctx.fill();}}
        continue;
      }
      const fixed=cue.reduced||this.reduced,x=X(cue.x),y=Y(cue.y),radius=fixed?20:14+cue.age*.35;
      ctx.globalAlpha=fixed?1:1-cue.age/cue.life;ctx.strokeStyle='#ffe3a8';ctx.lineWidth=2;ctx.beginPath();ctx.arc(x,y,radius,0,Math.PI*2);ctx.stroke();ctx.globalAlpha=1;
      if(cue.name==='pickup')this.label('−'+cue.reward/60+'s',x+12,y-20-(fixed?0:cue.age*.4),'#fff0d3',12);
    }
  }
  label(text,x,y,color,size){
    const ctx=this.ctx;ctx.font=`${size}px -apple-system, BlinkMacSystemFont, sans-serif`;
    const lines=[];let line='';const limit=Math.max(30,this.w-32);
    for(const word of text.split(' ')){const next=line?line+' '+word:word;if(line&&ctx.measureText(next).width>limit){lines.push(line);line=word;}else line=next;}
    if(line)lines.push(line);const width=Math.max(...lines.map(part=>ctx.measureText(part).width));
    x=Math.max(6,Math.min(x,this.w-width-6));
    if(this.labelRects){
      const height=lines.length*(size+4)+7,original=y;
      let placed=false;for(let row=0;row<30&&!placed;row++){
        const candidate=original+(row%2?1:-1)*Math.ceil(row/2)*(height+3),top=candidate-size-4;
        if(top<145||top+height>this.h-5)continue;
        for(const left of [x,6,this.w-width-6])if(!this.labelRects.some(r=>left-6<r.right&&left+width+6>r.left&&top<r.bottom&&top+height>r.top)){x=left;y=candidate;placed=true;break;}
      }
      this.labelRects.push({left:x-6,right:x+width+6,top:y-size-4,bottom:y-size-4+height});
    }
    ctx.fillStyle='#303149d9';ctx.fillRect(x-6,y-size-4,width+12,lines.length*(size+4)+7);ctx.fillStyle=color;
    lines.forEach((part,i)=>ctx.fillText(part,x,y+i*(size+4)));
  }
  sprite(img,frame,x,y,w,h,rotation){
    const ctx=this.ctx;ctx.save();ctx.translate(x,y);ctx.rotate(rotation);
    if(img.complete&&img.naturalWidth){const cell=img.naturalWidth/2;ctx.drawImage(img,(frame%2)*cell,Math.floor(frame/2)*cell,cell,cell,-w/2,-h/2,w,h);}
    else{ctx.fillStyle=C.paper;ctx.beginPath();ctx.moveTo(w/2,0);ctx.lineTo(-w/2,-h/4);ctx.lineTo(-w/3,0);ctx.lineTo(-w/2,h/4);ctx.closePath();ctx.fill();}ctx.restore();
  }
  park(ctx,X,Y,s,run,effects){
    const park=run.world.park;
    if(run.world.tier.prompts!=='quiet'){
      ctx.save();ctx.strokeStyle='rgba(255,240,211,.35)';ctx.lineWidth=1;ctx.setLineDash([3,6]);ctx.beginPath();ctx.moveTo(X(run.world.finishStart),Y(175));ctx.lineTo(X(run.world.length-park.coneRange),Y(park.bowlY+park.coneSlope*park.coneRange));ctx.lineTo(X(run.world.length),Y(park.bowlY));ctx.stroke();ctx.restore();
    }
    const start=X(run.world.finishStart),ground=Y(4);if(this.scenery&&this.w>start&&this.h>ground)ctx.drawImage(this.scenery.ground,start,ground,this.w-start,this.h-ground);else{ctx.fillStyle='#697f79';ctx.fillRect(start,ground,this.w-start,this.h-ground);}
    for(let i=0;i<12;i++){
      const x=X(run.world.finishStart+i*36),y=Y(18);if(this.scenery)ctx.drawImage(this.scenery.tree,x-20*s,y-30*s,40*s,55*s);else{ctx.fillStyle='#74877b';ctx.beginPath();ctx.arc(x,y-12*s,18*s,0,Math.PI*2);ctx.fill();}
    }
    const x=X(run.world.length),y=Y(18),cue=run.status==='finished'?(effects?.cues.find(c=>c.name==='landing')?.age??45):null;
    // Blanket and cooler anchor the gathering on the grass.
    ctx.fillStyle='#b88d89';ctx.fillRect(x-83*s,Y(5),60*s,5*s);ctx.fillStyle='#d6b4a3';for(let i=0;i<5;i++)ctx.fillRect(x+(-80+i*12)*s,Y(5),2*s,5*s);
    ctx.fillStyle='#687d8c';ctx.fillRect(x+58*s,Y(14),21*s,12*s);ctx.fillStyle=C.paper;ctx.fillRect(x+57*s,Y(15),23*s,3*s);
    // Colleagues stand behind the table; the impact gives them a brief raised-arm reaction.
    const reaction=cue!==null&&!this.reduced&&cue<45?Math.sin(cue*.15)*3:0;
    for(const [dx,color] of [[-55,'#9b8cbb'],[-32,'#f1a290'],[36,'#718899'],[59,'#bc977d']]){
      ctx.fillStyle=color;ctx.fillRect(x+(dx-5)*s,Y(31),10*s,17*s);ctx.fillStyle='#e9c7ae';ctx.beginPath();ctx.arc(x+dx*s,Y(35),4.5*s,0,Math.PI*2);ctx.fill();
      ctx.strokeStyle=color;ctx.lineWidth=3*s;ctx.beginPath();ctx.moveTo(x+(dx-5)*s,Y(29));ctx.lineTo(x+(dx-10)*s,Y(24+reaction));ctx.moveTo(x+(dx+5)*s,Y(29));ctx.lineTo(x+(dx+10)*s,Y(24+reaction));ctx.stroke();
    }
    // Bunting is part of the gathering, not a label for the food.
    ctx.strokeStyle=C.paper;ctx.lineWidth=s;ctx.beginPath();ctx.moveTo(x-78*s,Y(51));ctx.lineTo(x+78*s,Y(51));ctx.stroke();
    for(let i=0;i<9;i++){ctx.fillStyle=i%2?C.warm:C.sky;ctx.beginPath();ctx.moveTo(x+(-72+i*18)*s,Y(51));ctx.lineTo(x+(-62+i*18)*s,Y(51));ctx.lineTo(x+(-67+i*18)*s,Y(46));ctx.closePath();ctx.fill();}
    ctx.fillStyle='#665e68';ctx.fillRect(x-57*s,y,4*s,15*s);ctx.fillRect(x+53*s,y,4*s,15*s);
    ctx.fillStyle='#bd947f';ctx.fillRect(x-70*s,y,140*s,4*s);ctx.fillStyle=C.paper;ctx.fillRect(x-67*s,y,134*s,8*s);
    ctx.fillStyle='#d9b5a5';for(let i=0;i<11;i++)ctx.fillRect(x+(-65+i*12)*s,y,2*s,8*s);
    const wobble=cue!==null&&!this.reduced&&cue<45?Math.sin(cue*.45)*(1-cue/45)*.12:0;
    ctx.save();ctx.translate(x,Y(23));ctx.rotate(wobble);
    ctx.fillStyle='#e9c7ae';ctx.beginPath();ctx.ellipse(0,0,16*s,7*s,0,0,Math.PI);ctx.fill();ctx.fillStyle='#f5dfad';ctx.beginPath();ctx.ellipse(0,0,16*s,4*s,0,0,Math.PI*2);ctx.fill();
    for(let i=0;i<9;i++){ctx.fillStyle=i%3?'#fff0d3':'#77927f';ctx.fillRect((i*3.5-14)*s,((i%3)-1)*s,2.5*s,2*s);}ctx.restore();
  }
}
