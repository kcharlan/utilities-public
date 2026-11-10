import test from 'node:test';
import assert from 'node:assert/strict';
import {createRun} from '../dist/game/simulation.js';
import {Renderer} from '../dist/game/render.js';
import {createEffects,spawnEffects} from '../dist/game/effects.js';

test('finished picnic table, bowl and group fit desktop and phone viewports',()=>{
  for(const [w,h] of [[1280,800],[390,844],[844,390]]){
    const run=createRun();run.status='finished';run.plane.x=run.world.length;run.plane.y=25;
    run.world={...run.world,buildings:[],airs:[],winds:[],hazards:[],pickups:[]};
    const rects=[],ellipses=[],text=[];let offset=[0,0];const stack=[];
    const ctx=new Proxy({fillRect:(...v)=>rects.push(v),ellipse:(x,y,rx,ry)=>ellipses.push([x+offset[0],y+offset[1],rx,ry]),fillText:(...v)=>text.push(v),drawImage(){},save:()=>stack.push([...offset]),restore:()=>{offset=stack.pop();},translate:(x,y)=>{offset=[offset[0]+x,offset[1]+y];}},{get:(o,k)=>k in o?o[k]:()=>{}});
    const renderer=Object.assign(Object.create(Renderer.prototype),{w,h,ctx,washer:{complete:false},reduced:true,cache:[{},{}],sprite:()=>{},label:(s)=>text.push([s])});
    const fx=createEffects();spawnEffects(fx,run,['landing'],{reduced:true});renderer.draw(run,false,1,fx);
    const z=Math.min(3.2,w/210,h/130),cx=w/2,cy=h*.55;
    const table=rects.find(([x,y,width,height])=>Math.abs(x-(cx-70*z))<.001&&Math.abs(width-140*z)<.001);
    assert.ok(table,`${w} table`);assert.ok(table[0]>=0&&table[0]+table[2]<=w&&table[1]>=0&&table[1]+table[3]<=h);
    if(w===1280)assert.ok(table[2]>=120);
    assert.ok(ellipses.some(([x,y,rx,ry])=>Math.abs(x-cx)<.001&&Math.abs(rx-16*z)<.001&&x-rx>=0&&x+rx<=w&&y-ry>=0&&y+ry<=h),`${w} bowl`);
    assert.ok(rects.filter(([x,y,width,height])=>Math.abs(width-10*z)<.001&&Math.abs(height-17*z)<.001&&x>=0&&x+width<=w&&y>=0&&y+height<=h).length===4,`${w} colleagues`);
    assert.ok(cy>=0&&cy<=h);assert.ok(text.some(([s])=>s==='Office Picnic'));
    assert.ok(text.every(([s])=>!s.toLowerCase().includes('potato salad')));
  }
});
