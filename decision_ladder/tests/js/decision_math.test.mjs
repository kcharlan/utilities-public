import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const source = readFileSync(new URL('../../decision_ladder', import.meta.url), 'utf8');
const code = source.split('// decision-math:begin')[1]?.split('// decision-math:end')[0] || '';
const module = {exports:{}};
new Function('module', 'ladderCore', code)(module, createRequire(import.meta.url)('../../../tools/frontend_vendor/ladder_core.js'));
const m = module.exports;
const row = (name, capability, price, latency, extra={}) => ({key:name, name, ranked:true, board:'api', capability, price, latency, ...extra});
const caps = {cost:5, latency:10};
test('pick moves preserve input and handle directions, boundaries and missing keys', () => {
  const picks=['a','b','c','d'];
  assert.deepEqual(m.movePick(picks,'d','a'),['d','a','b','c']);
  assert.deepEqual(m.movePick(picks,'a','c'),['b','c','a','d']);
  for (const [key,target] of [['x','a'],['a','x'],['a','a']]) assert.deepEqual(m.movePick(picks,key,target),picks);
  assert.deepEqual(m.shiftPick(picks,'b',-1),['b','a','c','d']);
  assert.deepEqual(m.shiftPick(picks,'b',1),['a','c','b','d']);
  for (const [key,delta] of [['a',-1],['d',1],['x',1]]) assert.deepEqual(m.shiftPick(picks,key,delta),picks);
  assert.deepEqual(picks,['a','b','c','d']);
});
test('not ranked rows sort by displayed listing then name and filter by name', () => {
  const rows=[row('Synthetic Z',1,1,1,{ranked:false,listing:'z-list'}),row('Synthetic B',1,1,1,{ranked:false,listing:'a-list'}),row('Synthetic A',1,1,1,{ranked:false,listing:'a-list'}),row('Synthetic ranked',1,1,1)];
  assert.deepEqual(m.notRankedRows(rows,'').map(r=>r.name),['Synthetic A','Synthetic B','Synthetic Z']);
  assert.deepEqual(m.notRankedRows(rows,'synthetic b').map(r=>r.name),['Synthetic B']);
  assert.deepEqual(m.notRankedRows([row('Synthetic Z',1,1,1,{ranked:false,listing:'z-list'}),row('Synthetic missing',1,1,1,{ranked:false,listing:null}),row('Synthetic A',1,1,1,{ranked:false,listing:'a-list'})],'').map(r=>r.name),['Synthetic A','Synthetic missing','Synthetic Z']);
});
test('tier numbers remain stable when searching ranked rows', () => {
  const rows=m.prepare([row('Synthetic top',9,1,1),row('Synthetic lower',7,1,1)],{board:'all',mode:'whole',axis:'price',caps});
  assert.equal(m.searchRows(m.tiers(rows),'lower')[0].tier,2);
  assert.deepEqual(m.defaultExpanded(m.tiers(rows),1),[1]);
  assert.deepEqual(m.tierGroups(m.tiers(rows)).map(g=>[g.tier,g.rows.length]),[[1,1],[2,1]]);
  assert.deepEqual(m.visibleTierRows(m.tierGroups(m.tiers(rows)),[1],false).map(r=>r.heading?'heading':r.name),['heading','Synthetic top','heading']);
  assert.deepEqual(m.chartMarks([{key:'a',name:'Synthetic A',cost:1},{key:'b',name:'Synthetic B',cost:1}],'A','b').map(r=>r.key),['a','b']);
});
test('chart marks describe axis provenance, match, highlight and size', () => {
  const rows=[{key:'a',name:'Synthetic A',cost:1,price_published:true,latency_assumed:true},
    {key:'b',name:'Synthetic B',cost:2,price_published:false,latency_assumed:false},
    {key:'zero',name:'Synthetic zero',cost:0}];
  const edge=[{key:'a',status:'frontier'},{key:'b',status:'dominated'}];
  const price=m.chartMarks(rows,'Synthetic A','b',edge,'price');
  assert.deepEqual(price.map(({key,frontier,published,dim,highlighted,size})=>({key,frontier,published,dim,highlighted,size})),[
    {key:'a',frontier:true,published:true,dim:false,highlighted:false,size:5},
    {key:'b',frontier:false,published:false,dim:true,highlighted:true,size:5.5}]);
  const latency=m.chartMarks(rows,'',null,edge,'latency');
  assert.deepEqual(latency.map(({published,dim,size})=>({published,dim,size})),[
    {published:false,dim:false,size:5},{published:true,dim:false,size:3.5}]);
});
test('frontier-only filtering excludes dominated and outside rows', () => {
  const rows=[{key:'a',inCaps:true,status:'frontier'},{key:'b',inCaps:true,status:'dominated'},
    {key:'c',inCaps:false,status:''}];
  assert.deepEqual(m.boardPartitions(rows,false),{inside:rows.slice(0,2),outside:rows.slice(2)});
  assert.deepEqual(m.boardPartitions(rows,true),{inside:rows.slice(0,1),outside:[]});
});
test('bestIn identifies ties and ignores missing values in either direction', () => {
  const rows=[{v:3},{v:1},{v:3},{v:null}];
  assert.deepEqual(m.bestIn(rows,'v','max'),[true,false,true,false]);
  assert.deepEqual(m.bestIn(rows,'v','min'),[false,true,false,false]);
  assert.deepEqual(m.bestIn([{v:1}],'v','min'),[false]);
  assert.deepEqual(m.bestIn([{v:null},{v:null}],'v','max'),[false,false]);
});
test('picker order ranks capability descending, then name, with unranked last', () => {
  const rows=[row('Synthetic Z',2,1,1),row('Synthetic A',2,1,1),row('Synthetic high',9,1,1,{ranked:false}),row('Synthetic low',1,1,1)];
  assert.deepEqual(m.pickerRows(rows).map(r=>r.name),['Synthetic A','Synthetic Z','Synthetic low','Synthetic high']);
});
test('rank presentation uses official exclusions and only compares eligible ranks', () => {
  const rows=[row('Synthetic excluded',4,1,1,{ranked:false,not_ranked_because:'Synthetic reason',capability_rank:1}),row('Synthetic price',4,6,1,{capability_rank:2}),row('Synthetic latency',4,1,11,{capability_rank:3}),row('Synthetic missing',4,null,null,{capability_rank:4}),row('Synthetic eligible',4,1,1,{capability_rank:5})];
  assert.deepEqual(rows.map(r=>m.rankText(r,'capability_rank',caps)),['Not ranked: Synthetic reason','Not ranked: price above the cap','Not ranked: latency above the cap','Not ranked: no price, no latency',5]);
  assert.deepEqual(m.rankBestIn(rows,'capability_rank',caps),[false,false,false,false,true]);
});
test('display formatters retain precision and translate feed tokens', () => {
  assert.equal(m.scoreText(4.123), '4.1'); assert.equal(m.scoreText(null), '');
  assert.equal(m.capText(0.0000646123456789, 'price'), '$0.0001');
  assert.equal(m.capText(1.2345, 'latency'), '1.23 s');
  assert.equal(m.secondsText(0.5), '0.5'); assert.equal(m.secondsText(1.2345), '1.23'); assert.equal(m.secondsText(0.00001234), '0.0000123');
  for (const [kind, token, expected] of [['price','tariff','published tariff'],['price','listed','listed price'],['price','estimate','estimate'],['price','estimated','estimate'],['price','mixed','part estimate'],['price','unpriced','no price'],['latency','api-end-to-end','measured end to end'],['latency','measured-loopback','loopback, adjusted'],['latency','demo-endpoint-x2','demo endpoint, adjusted'],['listing','synthetic-other','synthetic other'],['price','unknown-token','unknown token']]) assert.equal(m.label(kind,token),expected);
  assert.equal(m.label('price','toString'), 'toString');
  assert.equal(m.whenText('2026-01-02T03:04:55.123Z'), '2026-01-02 03:04 UTC');
  assert.equal(m.whenText('synthetic'), 'synthetic');
});
test('official cap boundaries and unavailable values', () => {
  for (const [price, latency, expected] of [[4,9,true],[5,10,true],[5.1,10,false],[5,10.1,false],[null,1,false],[1,null,false]]) {
    const r = row('Synthetic',1,price,latency,{within_caps:expected});
    assert.equal(m.withinCaps(r,caps),r.within_caps);
  }
  assert.deepEqual(m.capReasons(row('Synthetic',1,null,11),caps),['no price','latency above the cap']);
});
test('prepare, tiers, frontier, search and formats', () => {
  const rows = [row('Synthetic A',8.2,2,3),row('Synthetic B',8.4,1,4),row('Synthetic C',9,4,5),row('Synthetic D',null,1,1),row('Synthetic E',7,null,2)];
  const prepared = m.prepare(rows,{board:'all',mode:'whole',axis:'price',caps});
  assert.equal(prepared.length,4);
  assert.deepEqual(m.tiers(prepared).map(r=>[r.name,r.tier,r.tierSize]),[['Synthetic C',1,1],['Synthetic B',2,2],['Synthetic A',2,2],['Synthetic E',3,1]]);
  assert.deepEqual(m.boardFrontier(prepared).filter(r=>r.status==='frontier').map(r=>r.name),['Synthetic B','Synthetic C']);
  assert.deepEqual(m.searchRows(prepared,'synthetic b').map(r=>r.name),['Synthetic B']);
  assert.equal(m.priceText(0), '0.0000'); assert.equal(m.priceText(.02), '0.020'); assert.equal(m.priceText(1),'1.00'); assert.equal(m.priceText(null),'');
  assert.equal(m.latencyText(.5),'500 ms'); assert.equal(m.latencyText(1),'1.00 s');
  assert.ok(m.findings(prepared,caps,'whole').join(' ').includes('Synthetic C'));
  assert.equal(m.prepare(rows,{board:'open',mode:'decimal',axis:'latency',caps}).length,0);
});
test('decimal mode, latency axis, caps and tied sorting use real values', () => {
  const rows = [row('Synthetic Z',8.2,1,3), row('Synthetic A',8.2,1,2), row('Synthetic X',8.3,0,1), row('Synthetic unavailable',9,1,null), row('Synthetic unranked',10,1,1,{ranked:false})];
  const prepared = m.prepare(rows,{board:'api',mode:'decimal',axis:'latency',caps});
  assert.deepEqual(m.tiers(prepared).map(r=>r.name),['Synthetic unavailable','Synthetic X','Synthetic A','Synthetic Z']);
  assert.equal(prepared.find(r=>r.name==='Synthetic X').cost,1);
  assert.equal(prepared.find(r=>r.name==='Synthetic unavailable').inCaps,false);
  assert.deepEqual(m.capReasons(row('Synthetic',1,6,11),caps),['price above the cap','latency above the cap']);
  assert.deepEqual(m.capReasons(row('Synthetic',1,1,null),caps),['no latency']);
  assert.equal(m.boardFrontier(prepared).some(r=>r.name==='Synthetic unavailable'),false);
  assert.match(m.findings(prepared,caps,'decimal')[0],/3 ranked systems/);
  assert.deepEqual(m.searchRows(prepared,'MISSING'),[]);
});
test('findings preserve small positive steps and identify axis units', () => {
  const rows = [row('Synthetic A',1,1,1),row('Synthetic B',2,1.0001,1.0001)];
  for (const [axis, unit] of [['price','dollars per 1,000 decisions per point'],['latency','seconds per point']]) {
    const prepared=m.prepare(rows,{board:'all',mode:'whole',axis,caps});
    const text=m.findings(prepared,caps,'whole',axis).join(' ');
    assert.match(text,/0\.0001/);
    assert.ok(text.includes(unit));
  }
});
test('changes respect displayed score precision and method changes suppress rows', () => {
  const change={changed:[{name:'Synthetic A',capability:[8.1,8.2],price:[1,1],latency:[2,2],listing:['a','a'],capability_rank:[1,1],composite_rank:[2,2],composite:[3,4]}]};
  assert.equal(m.changesToShow(change,'whole').length,0);
  assert.equal(m.changesToShow(change,'decimal').length,1);
  assert.equal(m.changesToShow({changed:[{capability:[8.21,8.24]}]},'decimal').length,0);
  assert.equal(m.changesToShow({...change,method:[{label:'A'},{label:'B'}]},'decimal').length,0);
});
test('changes compare displayed price and latency in both scoring modes', () => {
  for (const mode of ['whole','decimal']) {
    for (const [field, hidden, visible] of [['price',[2.001,2.002],[2.001,2.02]],['latency',[3.001,3.002],[3.001,3.02]]]) {
      assert.equal(m.changesToShow({changed:[{[field]:hidden}]},mode).length,0);
      assert.equal(m.changesToShow({changed:[{[field]:visible}]},mode).length,1);
      assert.equal(m.changesToShow({changed:[{[field]:[null,hidden[0]]}]},mode).length,1);
      assert.equal(m.changesToShow({changed:[{[field]:[hidden[0],null]}]},mode).length,1);
    }
  }
});
test('change fields format each endpoint and omit differences hidden by formatting', () => {
  for (const mode of ['whole','decimal']) {
    for (const [field,value,expected] of [['capability',8.26,mode==='whole'?'8':'8.3'],['price',0.0651234567890123,'$0.065'],['latency',1.23456789012345,'1.23 s'],['listing','synthetic-listing','synthetic listing'],['capability_rank',4,'4'],['composite_rank',3,'3']]) {
      assert.equal(m.changeText(field,value,mode),expected);
      assert.equal(m.changeText(field,null,mode),'none');
      assert.equal(m.changeText(field,undefined,mode),'none');
    }
    assert.deepEqual(m.changeFields({capability:[8.1,9.2],price:[0.065,0.071],latency:[1,2],listing:['synthetic-old','synthetic-new'],capability_rank:[4,3],composite_rank:[null,2]},mode),[
      {label:'Capability',from:mode==='whole'?'8':'8.1',to:mode==='whole'?'9':'9.2'},
      {label:'Price',from:'$0.065',to:'$0.071'}, {label:'Latency',from:'1.00 s',to:'2.00 s'},
      {label:'Listing',from:'synthetic old',to:'synthetic new'}, {label:'Capability rank',from:'4',to:'3'},
      {label:'Composite rank',from:'none',to:'2'}]);
    assert.deepEqual(m.changeFields({price:[2.001,2.002],latency:[3.001,3.002]},mode),[]);
  }
});
