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
test('overhead descent keeps the plane and table in the landscape view',()=>{
  const run=createRun();run.plane.x=run.world.length+.1;run.plane.y=180;
  // Use the real simulation to enter and advance the overhead landing.
  return import('../dist/game/simulation.js').then(({stepRun})=>{
    stepRun(run,false);for(let n=0;n<Math.floor(run.landingDurationTicks*.3);n++)stepRun(run,false);
    const rects=[],sprites=[],ctx=new Proxy({fillRect:(...v)=>rects.push(v),drawImage(){}},{get:(o,k)=>k in o?o[k]:()=>{}});
    const renderer=Object.assign(Object.create(Renderer.prototype),{w:844,h:390,ctx,washer:{complete:false},reduced:false,cache:[{},{}],sprite:(...v)=>sprites.push(v),label:()=>{}});
    renderer.draw(run,false,1);const plane=sprites.at(-1);assert.ok(plane[3]>0&&plane[3]<390,'plane visible');
    const table=rects.find(([x,y,w,h])=>w>100&&h>0&&y>200&&y<390);assert.ok(table&&table[1]+table[3]<=390,'table visible');
  });
});
test('finished framing excludes buildings and hazard motion bounds at all playfield sizes',async()=>{
  const {cameraFor}=await import('../dist/game/session.js');
  const {hazardParts}=await import('../dist/game/world.js');
  for(const [w,h] of [[1440,900],[844,390],[390,844]]){
    const run=createRun(),world=run.world,p={x:world.length,y:world.park.bowlY};
    const cam=cameraFor(w,h,p,{focus:{x:world.length,y:30},zoom:Math.min(3.2,w/210,h/130),progress:1});
    const intersects=b=>b.x+b.w>=cam.left&&b.x<=cam.left+w/cam.scale&&b.y+b.h>=cam.bottom&&b.y<=cam.bottom+h/cam.verticalScale;
    for(const b of world.buildings)assert.ok(!intersects({x:b.x,y:-1000,w:b.w,h:1000+b.y}),`${w} building`);
    for(const hzd of world.hazards){
      const dx=hzd.moving?(hzd.amp?.pigeonX??0):0,dy=hzd.moving?(hzd.kind==='platform'?(hzd.amp?.platformY??0):(hzd.amp?.pigeonY??0)):0;
      for(const b of hazardParts({...hzd,moving:false},0))assert.ok(!intersects({x:b.x-dx,y:b.y-dy,w:b.w+2*dx,h:b.h+2*dy}),`${w} ${hzd.id}`);
    }
  }
});
test('finished renderer excludes buildings and hazards at all playfield sizes and tiers',async()=>{
  const {TIERS}=await import('../dist/game/tiers.js'),{buildWorld}=await import('../dist/game/world.js');
  for(const tier of Object.values(TIERS))for(const [w,h] of [[1440,900],[844,390],[390,844]]){
    const run=createRun('standard',buildWorld(undefined,tier));run.status='finished';run.plane.x=run.world.length;run.plane.y=25;
    const buildings=[],hazards=[],washer={complete:true,naturalWidth:1536,naturalHeight:1024},pigeon={complete:true,naturalWidth:1254};
    const ctx=new Proxy({fillRect(...v){if(this.fillStyle==='#41485e')buildings.push(v);},drawImage(...v){if(v[0]===washer)hazards.push(v.slice(1));}},{get:(o,k)=>k in o?o[k]:()=>{}});
    const renderer=Object.assign(Object.create(Renderer.prototype),{w,h,ctx,washer,pigeon,reduced:true,cache:[{},{}],sprite:(img,...v)=>{if(img===pigeon)hazards.push(v);},label:()=>{}});
    renderer.draw(run,false,1);
    assert.ok(buildings.every(([x,y,width,height])=>x+width<=0||x>=w||y+height<=0||y>=h),tier.id+' building '+w);
    assert.equal(hazards.length,0,tier.id+' hazard '+w);
  }
});
test('approach guidance appears only in full and warnings modes',async()=>{
  const {TIERS}=await import('../dist/game/tiers.js');const {buildWorld}=await import('../dist/game/world.js');
  for(const tier of Object.values(TIERS)){
    const run=createRun('standard',buildWorld(undefined,tier)),dashes=[];
    const ctx=new Proxy({setLineDash:v=>dashes.push(v),drawImage(){}},{get:(o,k)=>k in o?o[k]:()=>{}});
    const renderer=Object.assign(Object.create(Renderer.prototype),{w:844,h:390,ctx,washer:{complete:false},reduced:false,cache:[{},{}],sprite:()=>{},label:()=>{}});
    run.plane.x=run.world.finishStart+10;run.plane.y=175;renderer.draw(run,false,1);
    assert.equal(dashes.some(v=>v[0]===3&&v[1]===6),tier.prompts!=='quiet',tier.id);
  }
});
test('reference approaches keep the actual table and aircraft in view at every park tick',async()=>{
  const {TIERS}=await import('../dist/game/tiers.js'),{buildWorld}=await import('../dist/game/world.js');
  const {stepRun}=await import('../dist/game/simulation.js'),{referenceInput}=await import('../dist/game/bot.js');
  for(const tier of Object.values(TIERS))for(const reduced of [false,true])for(const [w,h] of [[1440,900],[844,390],[390,844]]){
    const run=createRun('standard',buildWorld(undefined,tier));
    while(run.status==='flying'&&run.plane.x<=run.world.finishStart)stepRun(run,referenceInput(run));
    while(run.status==='flying'||run.status==='landing'){
      const rects=[],sprites=[],ctx=new Proxy({fillRect(...v){if(this.fillStyle==='#bd947f')rects.push(v);},drawImage(){}},{get:(o,k)=>k in o?o[k]:()=>{}});
      const renderer=Object.assign(Object.create(Renderer.prototype),{w,h,ctx,washer:{complete:false},reduced,cache:[{},{}],sprite:(...v)=>sprites.push(v),label:()=>{}});
      renderer.draw(run,false,1);const table=rects[0],plane=sprites.at(-1);
      assert.ok(table&&table[0]>=0&&table[0]+table[2]<=w&&table[1]>=0&&table[1]+table[3]<=h,`${tier.id} reduced=${reduced} table at ${run.plane.x-run.world.finishStart}`);
      assert.ok(plane&&plane[2]-plane[4]/2>=0&&plane[2]+plane[4]/2<=w&&plane[3]-plane[5]/2>=0&&plane[3]+plane[5]/2<=h,`${tier.id} reduced=${reduced} plane`);
      stepRun(run,referenceInput(run));
    }
  }
});
test('reduced-motion overhead descent keeps actual aircraft and table in view',async()=>{
  const {stepRun}=await import('../dist/game/simulation.js');const run=createRun();run.plane.x=run.world.length+.1;run.plane.y=180;stepRun(run,false);
  let initialTable;
  while(run.status==='landing'){
    const rects=[],sprites=[],ctx=new Proxy({fillRect(...v){if(this.fillStyle==='#bd947f')rects.push(v);},drawImage(){}},{get:(o,k)=>k in o?o[k]:()=>{}});
    const renderer=Object.assign(Object.create(Renderer.prototype),{w:844,h:390,ctx,washer:{complete:false},reduced:true,cache:[{},{}],sprite:(...v)=>sprites.push(v),label:()=>{}});
    renderer.draw(run,false,1);const table=rects[0],plane=sprites.at(-1);
    assert.ok(table&&table[0]>=0&&table[0]+table[2]<=844&&table[1]>=0&&table[1]+table[3]<=390,'table');
    if(initialTable)assert.deepEqual(table,initialTable,'reduced-motion framing stays fixed');else initialTable=table;
    assert.ok(plane&&plane[3]-plane[5]/2>=0&&plane[3]+plane[5]/2<=390,`plane tick ${run.landingTicks}`);
    stepRun(run,false);
  }
});


test("painted picnic cells layer correctly and switch people rows at three viewports", async () => {
  const manifest = JSON.parse(
    (await import("node:fs")).readFileSync(
      new URL("../dist/assets/manifest.json", import.meta.url),
    ),
  );
  const { readPng } = await import('../scripts/png.mjs');
  const { measure } = await import('../scripts/asset-metrics.mjs');
  const { readFileSync } = await import('node:fs');
  const source = readPng(readFileSync(new URL('../dist/assets/picnic-people.png', import.meta.url)));
  const personGeometry = measure(source, 4, 2);
  const dimensions = Object.fromEntries(Object.entries(manifest).map(([name, meta]) => {
    const decoded = readPng(readFileSync(new URL('../dist/assets/' + meta.file, import.meta.url)));
    return [name, { width: decoded.width, height: decoded.height }];
  }));
  for (const [w, h] of [
    [1440, 900],
    [844, 390],
    [390, 844],
  ])
    for (const reduced of [false, true])
      for (const finished of [false, true]) {
        const run = createRun();
        run.plane.x = run.world.length;
        run.plane.y = run.world.park.bowlY;
        if (finished) run.status = "finished";
        const draws = [],
          ctx = new Proxy(
            {
              drawImage: (...v) => draws.push(v),
              measureText: (s) => ({ width: s.length * 6 }),
            },
            { get: (o, k) => (k in o ? o[k] : () => {}) },
          ),
          art = {};
        for (const [name, meta] of Object.entries(manifest))
          art[name] = {
            meta,
            image: {
              name,
              complete: true,
              naturalWidth: dimensions[name].width,
              naturalHeight: dimensions[name].height,
            },
          };
        const renderer = Object.assign(Object.create(Renderer.prototype), {
          w,
          h,
          ctx,
          art,
          plane: {
            name: "plane",
            complete: true,
            naturalWidth: 1254,
            naturalHeight: 1254,
          },
          washer: { complete: false },
          reduced,
          cache: [{}, {}],
          label: () => {},
        });
        const fx = createEffects();
        if (finished) spawnEffects(fx, run, ["landing"], { reduced });
        let planeBounds;
        const sprite = renderer.sprite;
        renderer.sprite = function(image, frame, x, y, width, height, ...rest) {
          if (image === this.plane) {
            planeBounds = { left: x-width/2, right: x+width/2, top: y-height/2, bottom: y+height/2 };
          }
          return sprite.call(this, image, frame, x, y, width, height, ...rest);
        };
        renderer.draw(run, false, 1, fx);
        const people = draws.filter((a) => a[0] === art.people.image),
          table = draws.find((a) => a[0] === art.table.image),
          bowl = draws.find((a) => a[0] === art.bowl.image),
          props = draws.find((a) => a[0] === art.props.image && a[1] === dimensions.props.width*2/manifest.props.cols),
          plane = draws.find((a) => a[0] === renderer.plane);
        assert.equal(people.length, 4);
        for (const [i,a] of people.entries()) {
          assert.equal(a[2], finished ? dimensions.people.height/manifest.people.rows : 0);
          assert.ok(
            a[5] >= 0 && a[6] >= 0 && a[5] + a[7] <= w && a[6] + a[8] <= h,
          );
          const geometry = personGeometry.cells[i+(finished ? 4 : 0)];
          const head = a[6] + (geometry.bottom-geometry.height+1)/personGeometry.cellHeight*a[8];
          const foot = a[6] + geometry.bottom/personGeometry.cellHeight*a[8];
          const tabletop = table[6] + table[8]*.32;
          assert.ok(head < tabletop && foot >= tabletop, 'painted figure straddles table top');
        }
        for (const a of [table, bowl, props])
          assert.ok(
            a && a[5] >= 0 && a[6] >= 0 && a[5] + a[7] <= w && a[6] + a[8] <= h,
          );
        assert.ok(draws.indexOf(bowl) > draws.indexOf(people[3]));
        if (finished) {
          assert.ok(plane, "plane is drawn");
          assert.ok(planeBounds.left < bowl[5]+bowl[7] && planeBounds.right > bowl[5] &&
            planeBounds.top < bowl[6]+bowl[8] && planeBounds.bottom > bowl[6], 'plane overlaps bowl');
        }
      }
});
