import {cameraFor} from './session.js';
import {hazardBox,hazardParts,hazardAdvice,upcomingHazard,hazardKey} from './world.js';
import {drawAir,drawWind} from './air-render.js';
const C={ink:'#302f48',shadow:'#4f4b64',sky:'#9b8cbb',warm:'#f1a290',paper:'#fff0d3',window:'#f3bd86',green:'#7d887d'};
const hash=n=>{const x=Math.sin(n*127.1+311.7)*43758.5453;return x-Math.floor(x);};
export class Renderer{
  constructor(canvas){
    this.canvas=canvas;this.ctx=canvas.getContext('2d',{alpha:false});this.reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.plane=new Image();this.plane.src='./assets/plane-sheet.png';this.pigeon=new Image();this.pigeon.src='./assets/pigeon-sheet.png';this.washer=new Image();this.washer.src='./assets/washer-v1.png';this.cache=[];this.resize();
  }
  resize(){
    this.w=this.canvas.clientWidth;this.h=this.canvas.clientHeight;const ratio=Math.min(devicePixelRatio||1,2);
    this.canvas.width=Math.round(this.w*ratio);this.canvas.height=Math.round(this.h*ratio);this.ctx.setTransform(ratio,0,0,ratio,0,0);
    this.gradient=this.ctx.createLinearGradient(0,0,0,this.h);this.gradient.addColorStop(0,'#777fa5');this.gradient.addColorStop(.52,C.sky);this.gradient.addColorStop(.83,C.warm);this.gradient.addColorStop(1,'#e6b59f');
    this.cache=[this.skyline(0),this.skyline(1)];
  }
  skyline(layer){
    const tile=document.createElement('canvas');tile.width=1200;tile.height=500;const c=tile.getContext('2d');
    for(let i=0;i<32;i++){
      const x=i*39,w=30+hash(i+layer*32)*35,h=60+hash(i+7+layer*81)*300,y=500-h;
      c.fillStyle=layer?'#5b607b':'#7e7d9b';c.fillRect(x,y,w,h);
      c.fillStyle=layer?'#efb79580':'#ecc0ac50';
      for(let xx=x+6;xx<x+w-4;xx+=10)for(let yy=y+12;yy<490;yy+=16)if(hash(xx+yy)> .54)c.fillRect(xx,yy,3,5);
      if(i%5===0){c.strokeStyle=layer?'#5b607b':'#7e7d9b';c.lineWidth=2;c.beginPath();c.moveTo(x+w/2,y);c.lineTo(x+w/2,y-18);c.stroke();}
    }return tile;
  }
  draw(run,held,alpha=0){
    const ctx=this.ctx,w=this.w,h=this.h,p=run.plane;
    const display={...p};if(run.previous&&run.status==='flying'){display.x=run.previous.x+(p.x-run.previous.x)*alpha;display.y=run.previous.y+(p.y-run.previous.y)*alpha;}
    const cam=cameraFor(w,h,display),s=cam.scale;
    const X=x=>(x-cam.left)*s,Y=y=>h-(y-cam.bottom)*cam.verticalScale;
    ctx.fillStyle=this.gradient;ctx.fillRect(0,0,w,h);
    // Cached city layers, painted once on resize.
    for(let layer=0;layer<2;layer++){
      const tw=1200*(h/850),th=h*(layer?.57:.43),offset=this.reduced?0:((p.x*(layer?.17:.075))%tw);
      ctx.globalAlpha=layer?.75:.65;
      for(let x=-offset-tw;x<w;x+=tw)ctx.drawImage(this.cache[layer],x,h-th,tw,th);
    }ctx.globalAlpha=1;
    if(p.x>run.world.finishStart-550)this.park(ctx,X,Y,s,run);
    for(const b of run.world.buildings){
      if(X(b.x+b.w)<-10||X(b.x)>w+10)continue;
      const bx=X(b.x),by=Y(b.y),bw=b.w*s;
      ctx.fillStyle=b.district%2?'#44495f':'#41485e';ctx.fillRect(bx,by,bw,h-by);
      ctx.fillStyle='#77758a';ctx.fillRect(bx,by,bw,4*s);
      ctx.fillStyle='#2f384e';ctx.fillRect(bx,by+4*s,bw,3*s);
      const step=16*s;
      for(let xx=Math.max(bx+9*s,Math.floor(-bx/step)*step+bx+9*s);xx<Math.min(w,bx+bw-6*s);xx+=step){
        for(let yy=by+16*s;yy<h;yy+=24*s){ctx.fillStyle=hash(Math.round(xx-bx)+Math.round(yy-by)+b.x)>.52?'#e8b58c':'#7c82973b';ctx.fillRect(xx,yy,5*s,9*s);}
      }
      // Rooftop railings mark the solid top; lift machinery below.
      ctx.strokeStyle='#9c9aaa';ctx.lineWidth=Math.max(1,s*.6);ctx.beginPath();ctx.moveTo(bx,Y(b.y+4));ctx.lineTo(bx+bw,Y(b.y+4));ctx.stroke();
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
    // Label a squeeze once, at its shared window rather than on each member.
    if(run.world.tier.prompts!=='quiet')for(const hazard of run.world.hazards.filter(h=>h.squeeze&&h.kind==='platform')){
      const b=hazardBox(hazard,run.worldTicks/60),flock=run.world.hazards.find(h=>h.squeeze&&h.district===hazard.district&&h.slot===hazard.slot&&h.kind==='pigeon');
      const f=hazardBox(flock,run.worldTicks/60),dx=b.x-p.x;
      if(X(b.x)<w&&X(b.x+b.w)>0&&dx>-b.w&&dx<hazard.warningDistance){
        this.label(hazardAdvice(hazard),Math.max(10,X(b.x)-65),Y((b.y+f.y+f.h)/2)-20,'#ffe3a8',12);
      }
    }
    // If a warning source is outside the camera vertically, keep its direction legible.
    const incoming=upcomingHazard(run.world,p.x);
    const squeeze=run.world.hazards.find(h=>h.squeeze&&run.warned.has(hazardKey(h))&&hazardBox(h,run.worldTicks/60).x+h.w+8>p.x);
    const marker=squeeze||incoming;
    if(marker){
      const b=hazardBox(marker,run.worldTicks/60);
      if(marker.squeeze){
        const pair=run.world.hazards.filter(h=>h.squeeze&&hazardKey(h)===hazardKey(marker)).map(h=>hazardBox(h,run.worldTicks/60));
        b.x=Math.min(...pair.map(h=>h.x));b.y=(Math.max(...pair.map(h=>h.y))+Math.min(...pair.map(h=>h.y+h.h)))/2;
      }
      const offscreen=X(b.x)>w-15;if(offscreen||Y(b.y)<155)this.label((run.world.tier.prompts==='full'?(offscreen?'→ ':''):'→ ')+(run.world.tier.prompts==='quiet'?'':hazardAdvice(marker)),Math.max(10,Math.min(w-218,w*.35)),182,'#ffe3a8',12);}
    if(p.x<70){
      const bx=X(-34),by=Y(138);ctx.fillStyle='#384459';ctx.fillRect(bx,by,30*s,h-by);ctx.fillStyle='#f4c68d';ctx.fillRect(bx+5*s,by+7*s,20*s,29*s);ctx.strokeStyle='#aeb2bd';ctx.strokeRect(bx+5*s,by+7*s,20*s,29*s);this.label('40th floor',Math.max(8,bx),by-10,'#fff0d3',11);
    }
    const finished=run.status==='finished';
    const planeX=X(display.x),planeY=Y(display.y);
    if(run.status!=='respawning'||run.respawnTicks%10<5){
      const size=Math.max(58,21*s),frame=p.stalled?3:held?1:0;
      this.sprite(this.plane,frame,planeX,planeY,size,size*.77,finished?-.12:-p.pitch);
      if(p.stalled)this.label('Stall · release to recover',Math.max(12,Math.min(w-190,planeX-45)),planeY-32,'#ffe3a8',12);
    }
    if(p.y>cam.bottom+h/s-25)this.label('↑ Plane above view',20,190,C.paper,12);
  }
  label(text,x,y,color,size){
    const ctx=this.ctx;ctx.font=`${size}px -apple-system, BlinkMacSystemFont, sans-serif`;
    const lines=[];let line='';const limit=Math.max(30,this.w-32);
    for(const word of text.split(' ')){const next=line?line+' '+word:word;if(line&&ctx.measureText(next).width>limit){lines.push(line);line=word;}else line=next;}
    if(line)lines.push(line);const width=Math.max(...lines.map(part=>ctx.measureText(part).width));
    x=Math.max(6,Math.min(x,this.w-width-6));
    ctx.fillStyle='#303149d9';ctx.fillRect(x-6,y-size-4,width+12,lines.length*(size+4)+7);ctx.fillStyle=color;
    lines.forEach((part,i)=>ctx.fillText(part,x,y+i*(size+4)));
  }
  sprite(img,frame,x,y,w,h,rotation){
    const ctx=this.ctx;ctx.save();ctx.translate(x,y);ctx.rotate(rotation);
    if(img.complete&&img.naturalWidth){const cell=img.naturalWidth/2;ctx.drawImage(img,(frame%2)*cell,Math.floor(frame/2)*cell,cell,cell,-w/2,-h/2,w,h);}
    else{ctx.fillStyle=C.paper;ctx.beginPath();ctx.moveTo(w/2,0);ctx.lineTo(-w/2,-h/4);ctx.lineTo(-w/3,0);ctx.lineTo(-w/2,h/4);ctx.closePath();ctx.fill();}ctx.restore();
  }
  park(ctx,X,Y,s,run){
    const start=X(run.world.finishStart),ground=Y(4);ctx.fillStyle='#697f79';ctx.fillRect(start,ground,this.w-start,this.h-ground);
    for(let i=0;i<12;i++){
      const x=X(run.world.finishStart+i*36),y=Y(18);ctx.fillStyle='#485e67';ctx.fillRect(x-2*s,y,4*s,15*s);ctx.fillStyle=i%2?'#74877b':'#8b977d';ctx.beginPath();ctx.arc(x,y-12*s,18*s,0,Math.PI*2);ctx.fill();
    }
    const x=X(run.world.length),y=Y(18);ctx.fillStyle='#bd947f';ctx.fillRect(x-30*s,y,60*s,4*s);ctx.fillStyle='#ddd1bb';ctx.fillRect(x-23*s,y,46*s,3*s);ctx.fillStyle='#665e68';ctx.fillRect(x-23*s,y+4*s,3*s,14*s);ctx.fillRect(x+20*s,y+4*s,3*s,14*s);
    ctx.fillStyle='#e9c7ae';ctx.beginPath();ctx.ellipse(x,Y(22),11*s,5*s,0,0,Math.PI);ctx.fill();ctx.fillStyle='#f5dfad';ctx.beginPath();ctx.ellipse(x,Y(23),11*s,3*s,0,0,Math.PI*2);ctx.fill();
    ctx.fillStyle='#77927f';for(let i=0;i<5;i++)ctx.fillRect(x+(i*3-6)*s,Y(24)+(i%2)*s,1.5*s,1.5*s);
    if(x<this.w+100)this.label('Office picnic · potato salad',Math.min(this.w-180,Math.max(12,x-90)),Y(40),'#fff0d3',12);
    if(run.plane.x>run.world.finishStart)this.label('The park. Release to descend home.',Math.max(16,this.w*.38),this.h-112,'#fff0d3',12);
  }
}
