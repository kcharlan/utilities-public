import test from 'node:test';
import assert from 'node:assert/strict';
import {Renderer} from '../dist/game/render.js';
import {createRun} from '../dist/game/simulation.js';
import {buildWorld} from '../dist/game/world.js';
import {TIERS} from '../dist/game/tiers.js';
import {cameraFor} from '../dist/game/session.js';

test('pickup tokens and attached tags stay inside viewport and reserve their footprint',()=>{
  for(const tier of Object.values(TIERS))for(const [w,h] of [[1440,900],[1280,720],[844,390],[390,844]]){
    const run=createRun('standard',buildWorld(undefined,tier));
    let seen=0;for(const pk of run.world.pickups){
      run.plane.x=pk.x-150;run.plane.y=pk.y;
      const ctx=new Proxy({measureText:s=>({width:s.length*6}),drawImage(){}},{get:(o,k)=>k in o?o[k]:()=>{}});
      const renderer=Object.assign(Object.create(Renderer.prototype),{w,h,ctx,washer:{complete:false},reduced:true,cache:[{},{}],sprite:()=>{}});
      let footprint;const original=renderer.drawPickup;renderer.drawPickup=function(...args){const result=original.apply(this,args);if(args[0].id===pk.id)footprint=result;return result;};
      renderer.draw(run,false,1);
      if(footprint?.token){seen++;assert.ok(footprint.radius>=13);assert.ok(footprint.rect.left>=0&&footprint.rect.right<=w&&footprint.rect.top>=0&&footprint.rect.bottom<=h);assert.ok(renderer.labelRects.some(r=>r===footprint.rect));}
    }
    assert.ok(seen>0,`${tier.id} ${w} has visible pickups`);
  }
});

test('pickup tags, label clearance, sizing and offscreen markers across viewports',()=>{
  for(const tier of Object.values(TIERS))for(const [w,h] of [[1440,900],[1280,720],[844,390],[390,844]])for(const distance of [350,250,150,60]){
    const run=createRun('standard',buildWorld(undefined,tier));
    for(const pk of run.world.pickups){
      run.plane.x=pk.x-distance;run.plane.y=pk.y;run.announced.add(pk.id);
      const ctx=new Proxy({measureText:s=>({width:s.length*6}),drawImage(){}},{get:(o,k)=>k in o?o[k]:()=>{}});
      const renderer=Object.assign(Object.create(Renderer.prototype),{w,h,ctx,washer:{complete:false},reduced:true,cache:[{},{}],sprite:()=>{}}),labels=[],layouts=[];
      const label=renderer.label;renderer.label=function(...args){const before=this.labelRects.length;label.apply(this,args);if(this.labelRects.length>before)labels.push(this.labelRects.at(-1));};
      const draw=renderer.drawPickup;renderer.drawPickup=function(item,layout,...rest){layouts.push({item,layout});return draw.call(this,item,layout,...rest);};
      renderer.draw(run,false,1);
      const found=layouts.find(v=>v.item.id===pk.id);if(!found||!found.layout.token)continue;
      const l=found.layout;assert.ok(l.radius>=13);if(w>=1280){const collect=pk.r*cameraFor(w,h,run.plane).scale;assert.ok(Math.abs(l.radius-collect)/collect<=.15,`${tier.id} ${w} collect size`);}assert.ok(Math.min(Math.abs(l.left+l.width-l.x),Math.abs(l.left-l.x))<=l.radius+40);
      assert.ok(l.left>=0&&l.left+l.width<=w&&l.top>=0&&l.top+22<=h);
      for(const r of labels)assert.ok(!(r.left<l.rect.right&&r.right>l.rect.left&&r.top<l.rect.bottom&&r.bottom>l.rect.top),`${tier.id} ${w} ${pk.id} label overlaps`);
    }
  }
});

test('announced pickups use an offscreen marker only on assisted tiers',()=>{
  for(const tier of Object.values(TIERS)){
    const run=createRun('standard',buildWorld(undefined,tier)),pk=run.world.pickups[0];run.plane.x=pk.x-tier.notice.lead+10;run.plane.y=pk.y;run.announced.add(pk.id);
    const ctx=new Proxy({measureText:s=>({width:s.length*6}),drawImage(){}},{get:(o,k)=>k in o?o[k]:()=>{}}),found=[];
    const renderer=Object.assign(Object.create(Renderer.prototype),{w:390,h:844,ctx,washer:{complete:false},reduced:true,cache:[{},{}],sprite:()=>{}}),draw=renderer.drawPickup;
    renderer.drawPickup=function(item,layout,...rest){if(item.id===pk.id)found.push(layout);return draw.call(this,item,layout,...rest);};renderer.draw(run,false,1);
    if(tier.id==='overtime')assert.ok(found.every(layout=>layout.token));else {assert.equal(found.length,1);assert.equal(found[0].token,false);}
  }
});

test('offscreen marker does not cover real Rush warning labels',async()=>{
  const {referenceInput}=await import('../dist/game/bot.js'),{stepRun}=await import('../dist/game/simulation.js');const run=createRun('standard',buildWorld(undefined,TIERS.rush));for(let i=0;i<643;i++)stepRun(run,referenceInput(run));
  const markers=[],labels=[],ctx=new Proxy({measureText:s=>({width:s.length*6}),drawImage(){},fillRect(x,y,w,h){if(this.fillStyle==='#303149e8')markers.push({left:x,right:x+w,top:y,bottom:y+h});if(this.fillStyle==='#303149d9')labels.push({left:x,right:x+w,top:y,bottom:y+h});}},{get:(o,k)=>k in o?o[k]:()=>{}});
  const renderer=Object.assign(Object.create(Renderer.prototype),{w:390,h:844,ctx,washer:{complete:false},reduced:true,cache:[{},{}],sprite:()=>{}});renderer.draw(run,false,1);assert.ok(markers.length);assert.ok(labels.length);
  for(const a of markers)for(const b of labels)assert.ok(!(a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top),'marker overlaps label');
});

test('visible pickup paints its token and tag without label overlap in every required frame',async()=>{
  const {pickupPos}=await import('../dist/game/world.js');
  for(const tier of Object.values(TIERS))for(const [w,h] of [[1440,900],[1280,720],[844,390],[390,844]])for(const distance of [350,250,150,60]){
    const run=createRun('standard',buildWorld(undefined,tier));
    for(const base of run.world.pickups){
      run.plane.x=base.x-distance;run.plane.y=base.y;run.announced.add(base.id);
      const pk=pickupPos(run.world,base,0),cam=cameraFor(w,h,run.plane),x=(pk.x-cam.left)*cam.scale,y=h-(pk.y-cam.bottom)*cam.verticalScale;
      const tokens=[],texts=[],labels=[];let arc;
      const ctx=new Proxy({measureText:s=>({width:s.length*6}),drawImage(){},arc(x,y,r){arc={x,y,r};},fill(){if(this.fillStyle==='#ffe3a8'&&arc)tokens.push({...arc});},fillText(t,x,y){texts.push({t,x,y,style:this.fillStyle});},fillRect(x,y,w,h){if(this.fillStyle==='#303149d9')labels.push({left:x,right:x+w,top:y,bottom:y+h});}},{get:(o,k)=>k in o?o[k]:()=>{}});
      const renderer=Object.assign(Object.create(Renderer.prototype),{w,h,ctx,washer:{complete:false},reduced:true,cache:[{},{}],sprite:()=>{}});renderer.draw(run,false,1);
      if(x<0||x>w||y<0||y>h)continue;
      const token=tokens.find(v=>Math.abs(v.x-x)<.001&&Math.abs(v.y-y)<.001);assert.ok(token,`${tier.id} ${w} ${distance} ${base.id} missing token`);assert.ok(token.r>=13);
      if(w>=1280)assert.ok(Math.abs(token.r-pk.r*cam.scale)/(pk.r*cam.scale)<=.15);
      const tag=texts.find(v=>v.t.startsWith(`−${pk.rewardTicks/60}s`)&&v.style==='#fff0d3'&&Math.abs(v.y-y)<=26);assert.ok(tag,`${tier.id} ${w} ${distance} ${base.id} missing tag`);
      const tagWidth=tag.t.length*6;assert.ok(tag.x>=0&&tag.x+tagWidth<=w&&tag.y-15>=0&&tag.y+7<=h);assert.ok(Math.min(Math.abs(tag.x-x),Math.abs(tag.x+tagWidth-x))<=token.r+40);
      const rect={left:Math.min(x-token.r,tag.x-6),right:Math.max(x+token.r,tag.x+tagWidth+6),top:Math.min(y-token.r,tag.y-15),bottom:Math.max(y+token.r,tag.y+7)};for(const b of labels)assert.ok(!(rect.left<b.right&&rect.right>b.left&&rect.top<b.bottom&&rect.bottom>b.top),`${tier.id} ${w} ${base.id} covered`);
    }
  }
});

test('quiet-tier announced pickups stay absent when independently projected offscreen at every size',()=>{
  for(const [w,h] of [[1440,900],[1280,720],[844,390],[390,844]]){
    const run=createRun('standard',buildWorld(undefined,TIERS.overtime));
    for(const pk of run.world.pickups){
      run.collected=new Set(run.world.pickups.filter(p=>p!==pk).map(p=>p.id));run.plane.x=pk.x-1000;run.plane.y=pk.y;run.announced.add(pk.id);const cam=cameraFor(w,h,run.plane);assert.ok((pk.x-cam.left)*cam.scale>w);
      const texts=[],painted=[],ctx=new Proxy({measureText:s=>({width:s.length*6}),drawImage(){},fillText:t=>texts.push(t)},{get:(o,k)=>k in o?o[k]:()=>{}});const renderer=Object.assign(Object.create(Renderer.prototype),{w,h,ctx,washer:{complete:false},reduced:true,cache:[{},{}],sprite:()=>{}}),draw=renderer.drawPickup;
      renderer.drawPickup=function(item,...args){painted.push(item.id);return draw.call(this,item,...args);};renderer.draw(run,false,1);
      assert.ok(!painted.includes(pk.id),`${w} ${pk.id} offscreen pickup rendered`);assert.ok(!texts.some(t=>t.startsWith(`−${pk.rewardTicks/60}s`)));
    }
  }
});

test('each assisted pickup paints its announced offscreen marker on portrait',async()=>{
  const {pickupPos}=await import('../dist/game/world.js');
  for(const tier of [TIERS.casual,TIERS.rush]){
    const run=createRun('standard',buildWorld(undefined,tier));for(const base of run.world.pickups){
      run.collected=new Set(run.world.pickups.filter(p=>p!==base).map(p=>p.id));run.announced.add(base.id);run.plane.x=base.x-tier.notice.lead+10;run.plane.y=base.y;
      const pk=pickupPos(run.world,base,0),cam=cameraFor(390,844,run.plane);assert.ok((pk.x-cam.left)*cam.scale>390,`${tier.id} ${base.id} must be offscreen`);
      const texts=[],arcs=[],ctx=new Proxy({measureText:s=>({width:s.length*6}),drawImage(){},fillText:t=>texts.push(t),arc:(x,y,r)=>arcs.push({x,y,r})},{get:(o,k)=>k in o?o[k]:()=>{}});const renderer=Object.assign(Object.create(Renderer.prototype),{w:390,h:844,ctx,washer:{complete:false},reduced:true,cache:[{},{}],sprite:()=>{}});renderer.draw(run,false,1);
      assert.ok(texts.some(t=>t.startsWith(`−${pk.rewardTicks/60}s`)&&t.includes(pk.hint)),`${tier.id} ${base.id} marker text`);assert.ok(arcs.some(a=>a.r===8&&a.x>0&&a.x<=390),'marker token');
    }
  }
});
