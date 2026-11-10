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
