'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const E = require('../engine.js'), Csv = require('../csv.js');
const year = (stock=0,bill=0,cpi=0) => ({year:4200,stock_tr:stock,bond10_tr:0,tbill_tr:bill,tbill_dtb3_tr:0.1,cpi_change:cpi,quality:'invented'});
const options = (extra={}) => ({startingBalance:1000,allocation:{stock:0.8,bond:0,bill:0.2},...extra});
const close = (actual, expected) => assert.ok(Math.abs(actual-expected)<1e-8, `${actual} != ${expected}`);
function strategy(overrides={}) {return {settlement:'yearEnd',init(){return {};},step(){return {withdrawal:100,noteWithdrawalSources:true,notes:'decision'};},settle(){return {withdrawals:{stock:20,bond:0,bill:80},transfers:[{from:'stock',to:'bill',amount:30}],notes:'settled'};},...overrides};}
test('year-end settlement applies returns, fees, withdrawals and ordered transfers, then afterYear',()=>{
  let observed;
  const s=strategy({settle(state,ctx){assert.ok(Object.isFrozen(ctx)&&Object.isFrozen(ctx.balances)&&Object.isFrozen(ctx.startBalances));assert.deepEqual(ctx.startBalances,{stock:800,bond:0,bill:200});close(ctx.balances.stock,864);close(ctx.balances.bill,198);assert.equal(ctx.requestedGross,125);return {withdrawals:{stock:25,bond:0,bill:100},transfers:[{from:'stock',to:'bill',amount:30},{from:'bill',to:'stock',amount:10}],notes:'settled'};},afterYear(state,row,ctx){observed=row;assert.ok(Object.isFrozen(row));assert.equal(ctx.total,1000);}});
  const r=E.simulate([year(0.2,0.1,0.05)],s,{},options({feeRate:0.1,taxRate:0.2}));const row=r.rows[0];
  close(row.endBalances.stock,819);close(row.endBalances.bill,118);close(row.balancesAfterReturns.stock,960);close(row.withdrawalNominal,100);close(row.taxPaid,25);close(row.withdrawalReal,100);close(row.endTotalReal,937/1.05);assert.equal(row.settlement,'yearEnd');assert.equal(row.notes,'decision; withdrawal funded by stock and bills; settled');assert.deepEqual(observed,row);assert.equal(r.metrics.yearsCompleted,1);
});
test('year-end failure records real returns and fees, pays everything, and stops without afterYear',()=>{
  const s=strategy({step(){return {withdrawal:900};},settle(){assert.fail('failed year must not settle');},afterYear(){assert.fail('failed year must not complete');}});
  const r=E.simulate([year(-0.5),{...year(),year:4201}],s,{},options({feeRate:0.1,taxRate:0.2}));const row=r.rows[0];assert.equal(r.rows.length,1);assert.equal(row.failed,true);close(row.grossWithdrawal,540);close(row.withdrawalNominal,432);assert.deepEqual(row.returnAmounts,{stock:-400,bond:0,bill:0});assert.deepEqual(row.fees,{stock:40,bond:0,bill:20});assert.equal(row.portfolioReturn,-0.4);assert.equal(row.endCpiIndex,null);assert.deepEqual(row.endBalances,{stock:0,bond:0,bill:0});assert.equal(r.metrics.yearsCompleted,0);
});
test('year-end exact-total withdrawal succeeds and tiny negative arithmetic is clamped',()=>{
  const r=E.simulate([year()],strategy({step(){return {withdrawal:1000};},settle(){return {withdrawals:{stock:800+Number.EPSILON*1000,bond:0,bill:200},transfers:[]};}}),{},options());assert.equal(r.metrics.success,true);assert.equal(r.rows[0].endTotal,0);
});
test('year-end tiny negative transfer residual is clamped and null rebalances are accepted',()=>{
  const s=strategy({step(){return {withdrawal:100,rebalanceTo:null,rebalanceToDollars:null};},settle(){return {withdrawals:{stock:0,bond:0,bill:100},transfers:[{from:'bill',to:'stock',amount:100+Number.EPSILON*1000}]};}});
  const row=E.simulate([year()],s,{},options()).rows[0];assert.equal(row.endBalances.bill,0);close(row.endBalances.stock,900);
});
test('year-end validates forbidden decisions before settling',()=>{
  for (const decision of [{withdrawFrom:'proportional'},{withdrawFrom:null},{rebalanceTo:{stock:1,bond:0,bill:0}},{rebalanceToDollars:{dollarTargets:{bill:1},remainderAsset:'stock'}}]) {
    assert.throws(()=>E.simulate([year()],strategy({step(){return {withdrawal:1,...decision};}}),{},options()),/yearEnd/);
  }
  assert.throws(()=>E.simulate([year()],strategy({settle:undefined}),{},options()),/settle/);
});
test('year-end settlement rejects invalid shape, amounts, sums and sequential overdrafts',()=>{
  const valid={withdrawals:{stock:20,bond:0,bill:80},transfers:[]};
  for(const settlement of [null,[],{}, {...valid,notes:3}, {...valid,withdrawals:[]}, {...valid,withdrawals:{stock:20,bond:0}}, {...valid,withdrawals:{stock:NaN,bond:0,bill:80}}, {...valid,withdrawals:{stock:-1,bond:0,bill:101}}, {...valid,withdrawals:{stock:0,bond:0,bill:201}}, {...valid,withdrawals:{stock:20,bond:0,bill:79}}, {...valid,transfers:{}}, {...valid,transfers:[null]}, {...valid,transfers:[{from:'stock',to:'stock',amount:1}]}, {...valid,transfers:[{from:'unknown',to:'bill',amount:1}]}, {...valid,transfers:[{from:'stock',to:'bill',amount:-1}]}, {...valid,transfers:[{from:'stock',to:'bill',amount:Infinity}]}, {...valid,transfers:[{from:'bill',to:'stock',amount:100},{from:'bill',to:'stock',amount:21}]}]) {
    assert.throws(()=>E.simulate([year()],strategy({settle(){return settlement;}}),{},options()),/settlement|withdrawals|transfers/);
  }
});
test('year-end completed rows enforce CPI and finite arithmetic',()=>{
  for(const cpi of [null,NaN,-1,-2])assert.throws(()=>E.simulate([year(0,0,cpi)],strategy(),{},options()),/CPI|cpi/);
});
test('T-bill series shares validation, mapping, returns and available range',()=>{
  assert.equal(E.normalizeBillSeries(), 'damodaran');assert.deepEqual(E.returnColumns('dtb3'),{stock:'stock_tr',bond:'bond10_tr',bill:'tbill_dtb3_tr'});
  for(const invalid of [null,'',0,'other']){assert.throws(()=>E.normalizeBillSeries(invalid),RangeError);assert.throws(()=>E.simulate([year()],E.STRATEGIES.fixedPercent,{},options({billSeries:invalid})),RangeError);assert.throws(()=>E.availableYearRange(E.STRATEGIES.barbell,{},[year()],{billSeries:invalid}),RangeError);}
  const r=E.simulate([year()],E.STRATEGIES.fixedPercent,{rate:0},options({billSeries:'dtb3'}));assert.equal(r.rows[0].returnRates.bill,0.1);close(r.rows[0].endTotal,1020);
  const rows=[{...year(),tbill_dtb3_tr:null},{...year(),year:4201}];assert.equal(E.availableYearRange(E.STRATEGIES.barbell,{},rows).first,4200);assert.equal(E.availableYearRange(E.STRATEGIES.barbell,{},rows,{billSeries:'dtb3'}).first,4201);
  const failed=E.simulate([year()],{init(){return {};},step(){return {withdrawal:2000};}}, {},options({billSeries:'dtb3'}));assert.equal(failed.rows[0].returnRates.bill,0.1);
});
test('failure-note helper preserves legacy wording and labels year-end failures',()=>{
  assert.equal(Csv.failureNote({}), 'Portfolio depleted before returns were applied');assert.equal(Csv.failureNote({settlement:'yearEnd'}),'Portfolio depleted after returns were applied');
  const row=E.simulate([year(-0.9)],strategy({step(){return {withdrawal:900};}}),{},options()).rows[0];assert.match(Csv.windowExportRows([row])[0].notes,/depleted after/);
});
const josh = () => E.STRATEGIES.joshTbillFullRefill;
function runJosh(rows,params={},extra={}){return E.simulate(rows,josh(),params,options(extra));}
test('Josh starts with a fixed buffer and harvests a sufficient stock gain',()=>{
  const row=runJosh([year(0.2,0.05) ]).rows[0];assert.deepEqual(row.startBalances,{stock:760,bond:0,bill:240});close(row.withdrawalsByAsset.stock,80);close(row.withdrawalsByAsset.bill,0);close(row.endBalances.stock,832);close(row.endBalances.bill,252);assert.deepEqual(row.transfers,[]);
});
test('Josh harvests a small gain and funds the rest from bills; zero and down returns use bills',()=>{
  for(const [rate,stock,bill]of [[0.05,38,42],[0,0,80],[-0.1,0,80]]){const row=runJosh([year(rate)]).rows[0];close(row.withdrawalsByAsset.stock,stock);close(row.withdrawalsByAsset.bill,bill);}
});
test('Josh up-year bills-short withdrawal covers the shortfall from stocks and refills',()=>{
  // Initial stocks 920 gain 18.4; bills fall to 20. Gross spending 80
  // uses all 20 bills and 60 stocks before transferring the fixed 80 buffer.
  const row=runJosh([year(0.02,-0.75)],{bufferYears:1}).rows[0];
  close(row.withdrawalsByAsset.bill,20);close(row.withdrawalsByAsset.stock,60);
  assert.deepEqual(row.transfers,[{from:'stock',to:'bill',amount:80}]);close(row.endBalances.stock,798.4);close(row.endBalances.bill,80);
});
test('Josh bills-short withdrawal uses stocks then fully refills',()=>{
  const row=runJosh([year(-0.1)],{bufferYears:1}).rows[0]; // bills 80 exhausted; fixed refill 80
  assert.deepEqual(row.transfers,[{from:'stock',to:'bill',amount:80}]);close(row.endBalances.stock,748);close(row.endBalances.bill,80);
  const short=runJosh([year(-0.1,-0.5)],{bufferYears:1}).rows[0];close(short.withdrawalsByAsset.bill,40);close(short.withdrawalsByAsset.stock,40);close(short.endBalances.stock,708);
});
test('Josh partially refills when stocks are exhausted and reports it',()=>{
  const row=runJosh([year(-0.85,-0.9)]).rows[0];close(row.withdrawalsByAsset.bill,24);close(row.withdrawalsByAsset.stock,56);close(row.transfers[0].amount,58);close(row.endBalances.stock,0);assert.match(row.notes,/partial: stocks exhausted/);
});
test('Josh applies spending floors and ceiling with strict emergency trigger',()=>{
  const s=josh(),state=s.init({},options());const ctx=(total)=>({total,options:{taxRate:0}});
  assert.deepEqual(s.step(state,ctx(499.99)),{withdrawal:50,noteWithdrawalSources:true,notes:'emergency spending floor'});
  assert.equal(s.step(state,ctx(500)).withdrawal,60);assert.equal(s.step(state,ctx(500)).notes,'spending floor');assert.equal(s.step(state,ctx(2000)).withdrawal,140);assert.equal(s.step(state,ctx(2000)).notes,'spending ceiling');assert.equal(s.step(state,ctx(1000)).notes,'');
});
test('Josh failure pays partial spending after returns and a small positive bill residual does not refill',()=>{
  const failed=runJosh([year(-0.99,-0.99)]).rows[0];assert.equal(failed.failed,true);close(failed.grossWithdrawal,10);
  const row=runJosh([year(0,(80+0.137)/240-1)]).rows[0];close(row.endBalances.bill,0.137);assert.deepEqual(row.transfers,[]);
});
test('Josh computes robust bill-short split for floating point and absolute micro-dollar trigger',()=>{
  const s=josh(),state=s.init({},options());
  for(const B of [0.1,79.99999999999999,80+5e-7,80+2e-6]){
    const W=80,ctx={startBalances:{stock:760,bond:0,bill:240},balances:{stock:700,bond:0,bill:B},requestedGross:W};
    const plan=s.settle(state,ctx);assert.ok(B-plan.withdrawals.bill>=0);assert.equal(plan.transfers.length,B-W<=1e-6?1:0);
  }
});
test('Josh never overdraws T-bills where the stock-first split would exceed the balance by one ulp',()=>{
  // Invented inputs chosen so that W - (W - B) > B in IEEE arithmetic (by about 4.77e-12):
  // computing fromStock = W - B first would overdraw T-bills; fromBill = min(B, W - harvest) must not.
  const W=77391.3095811265,B=1185.7483638879737;assert.ok(W-(W-B)>B,'fixture must discriminate the stock-first order');
  const s=josh(),state=s.init({},options({startingBalance:1_000_000}));
  const plan=s.settle(state,{startBalances:{stock:900_000,bond:0,bill:240_000},balances:{stock:800_000,bond:0,bill:B},requestedGross:W});
  assert.equal(plan.withdrawals.bill,B);close(plan.withdrawals.stock+plan.withdrawals.bill,W);
  assert.deepEqual(plan.transfers,[{from:'stock',to:'bill',amount:240_000}]);
});
test('Josh fees precede harvest and gross spending is independent of tax',()=>{
  const row=runJosh([year(0.1,0.02)],{}, {feeRate:0.05,taxRate:0.25}).rows[0];close(row.requestedGrossWithdrawal,80);close(row.withdrawalNominal,60);close(row.withdrawalsByAsset.stock,34.2);close(row.withdrawalsByAsset.bill,45.8);
});
test('Josh validates all parameters and permits every frontier value and rate boundary',()=>{
  const s=josh();for(const field of s.paramSchema){for(const value of [NaN,-Infinity,field.min-1,field.max+1])assert.throws(()=>s.init({[field.key]:value},options()));assert.ok(Object.isFrozen(field.frontierRange));}
  assert.throws(()=>s.init({bufferYears:1.5},options()),RangeError);assert.throws(()=>s.init({rate:0.21,bufferYears:5},options()),RangeError);
  // The public ranges already imply floors <= ceiling and bufferYears*rate <= 1.
  // Invalid cross-constraint inputs still fail through the public init contract.
  assert.throws(()=>s.init({floorMultiple:1.01,ceilingMultiple:1},options()),RangeError);
  assert.throws(()=>s.init({emergencyMultiple:1.01,ceilingMultiple:1},options()),RangeError);
  for(const rate of [0,0.2])for(const bufferYears of [1,2,3,4,5])assert.doesNotThrow(()=>s.init({rate,bufferYears},options()));
  assert.doesNotThrow(()=>s.init({emergencyMultiple:1},options()));
  const L=require('../lifestyle.js');for(const field of s.paramSchema){const plan=L.frontierPlan(s,{},field.key);assert.ok(plan.values.length<=41);for(const value of plan.values)assert.doesNotThrow(()=>s.init({[field.key]:value},options()));}
});
test('Josh integrates selected series, sweep, grid, range and adaptive solvency search',()=>{
  const rows=Array.from({length:4},(_,i)=>({...year(),year:4200+i}));
  assert.deepEqual(E.resolveInitialAllocation(josh(),{},options()),{stock:0.76,bond:0,bill:0.24});assert.equal(E.availableYearRange(josh(),{},rows).first,4200);
  assert.notEqual(runJosh(rows).metrics.terminalWealthNominal,runJosh(rows,{}, {billSeries:'dtb3'}).metrics.terminalWealthNominal);
  assert.equal(E.maxSafeRate(rows,josh(),{},options({horizon:4}),{adaptiveStep:0.01}),0.2);
  assert.ok(E.sweepStartYears(rows,2,josh(),{},options({horizon:2})).length);assert.ok(E.sweepGrid(rows,[2],josh(),{},options()).length);
});
test('year-end adaptive safe-rate search agrees with complete simulations at its survival boundary',()=>{
  const rows=Array.from({length:4},(_,i)=>({...year(-0.5),year:4200+i}));
  const opt=options({horizon:4}),params={bufferYears:1},rate=E.maxSafeRate(rows,josh(),params,opt,{adaptiveStep:0.01});
  assert.ok(rate>0&&rate<0.2);assert.equal(runJosh(rows,{...params,rate},opt).metrics.success,true);assert.equal(runJosh(rows,{...params,rate:rate+1e-7},opt).metrics.success,false);
});
test('selected T-bill series affects every existing strategy that holds bills',()=>{
  for(const id of ['fixedReal','fixedPercent','guytonKlinger','barbell']){
    const s=E.STRATEGIES[id],opt=options({allocation:{stock:0.5,bond:0.2,bill:0.3}});
    const legacy=E.simulate([year()],s,{},opt),explicit=E.simulate([year()],s,{}, {...opt,billSeries:'damodaran'}),daily=E.simulate([year()],s,{}, {...opt,billSeries:'dtb3'});
    assert.equal(JSON.stringify(legacy),JSON.stringify(explicit));assert.equal(daily.rows[0].returnRates.bill,0.1);assert.notEqual(daily.metrics.terminalWealthNominal,legacy.metrics.terminalWealthNominal);
  }
});
