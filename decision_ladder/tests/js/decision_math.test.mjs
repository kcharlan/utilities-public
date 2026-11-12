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
