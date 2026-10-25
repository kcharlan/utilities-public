const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const htmlPath = path.join(__dirname, '..', 'ai-model-timeline.html');
const html = fs.readFileSync(htmlPath, 'utf8');

function extractData() {
  const startMarker = 'const DATA = ';
  const endMarker = '\n\nconst TIER_COLOR';
  const start = html.indexOf(startMarker);
  const end = html.indexOf(endMarker, start);
  assert.notEqual(start, -1, 'DATA declaration is present');
  assert.notEqual(end, -1, 'DATA terminator is present');
  return JSON.parse(html.slice(start + startMarker.length, end).replace(/;\s*$/, ''));
}

function extractInlineScript() {
  const matches = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)];
  return matches.map(match => match[1]).find(source => source.includes('const DATA ='));
}

function extractCoreScript() {
  const match = html.match(/<script\s+id="timeline-core"\s*>([\s\S]*?)<\/script>/i);
  assert.ok(match, 'TimelineCore script is present');
  return match[1];
}

function loadCore() {
  const win = {};
  new Function('window', extractCoreScript())(win);
  return win.TimelineCore;
}

const data = extractData();

test('October 23 Kimi launch appears in the latest monthly report with weights still pending', () => {
  const kimi = data.filter(row => row.lab === 'Moonshot' && row.date === '2026-10-23');
  assert.deepEqual(kimi.map(row => row.model).sort(), ['Kimi K3.1 Pro', 'Kimi K3.1 Pro Highspeed']);
  for (const row of kimi) {
    assert.equal(row.tier, 'flagship');
    assert.match(row.note, /weights.*November 4, 2026/);
    assert.match(row.note, /kimi-k3\.1-pro/);
  }
  const core = loadCore();
  const bounds = {earliest:'2024-01-10', latest:data.reduce((max, row) => row.date > max ? row.date : max, '')};
  const range = core.resolveRange(core.presetSpec('month', bounds), bounds);
  assert.equal(range.end, '2026-10-23');
  const report = core.formatReportText(core.groupByMonth(kimi, 'desc', () => 0),
    {range, tiers:new Set(allTiers), allTiers, terms:['kimi k3.1']});
  assert.match(report, /Oct 23, 2026 · Moonshot · Kimi K3\.1 Pro · flagship/);
  assert.match(report, /Oct 23, 2026 · Moonshot · Kimi K3\.1 Pro Highspeed · flagship/);
});

test('Meta Wonder models remain in the current month and appear in the dated report', () => {
  const core = loadCore();
  const bounds = {earliest:'2024-01-10', latest:data.reduce((max, row) => row.date > max ? row.date : max, '')};
  assert.equal(bounds.latest, '2026-10-23');
  const meta = data.filter(row => row.lab === 'Meta' && row.date === '2026-10-12');
  assert.deepEqual(meta.map(row => row.model).sort(), ['Muse Wonder', 'Muse Wonder Full']);
  for (const row of meta) {
    assert.equal(row.source, 'https://research.meta.ai/blog/muse-wonder');
    assert.equal(row.tier, 'flagship');
  }
  const range = core.resolveRange(core.presetSpec('month', bounds), bounds);
  assert.equal(range.end, '2026-10-23');
  const report = core.formatReportText(core.groupByMonth(meta, 'desc', () => 0),
    {range, tiers:new Set(allTiers), allTiers, terms:['meta']});
  assert.match(report, /Oct 12, 2026 · Meta · Muse Wonder Full · flagship/);
  assert.match(report, /Oct 12, 2026 · Meta · Muse Wonder · flagship/);
});

test('October 13 Argon launch is distinct from its restricted preview and cyber variant', () => {
  const argon = data.filter(row => row.model.startsWith('Gemini 4 Argon'));
  assert.equal(argon.length, 3);
  const ga = argon.find(row => row.model === 'Gemini 4 Argon (general availability)');
  assert.equal(ga?.date, '2026-10-13');
  assert.equal(ga?.tier, 'flagship');
  assert.match(ga?.note || '', /Public launch.*gemini-4-argon/);
  assert.match(ga?.note || '', /Separate from the September 30/);
  const cyber = argon.find(row => row.model.includes('Cyber Permissive'));
  assert.equal(cyber?.date, '2026-10-13');
  assert.equal(cyber?.tier, 'specialty');
  assert.match(cyber?.note || '', /separate Fairwind allowlist/);
  assert.equal(argon.find(row => row.model === 'Gemini 4 Argon')?.date, '2026-09-30');
  const core = loadCore();
  const bounds = {earliest:'2024-01-10', latest:'2026-10-13'};
  const range = core.resolveRange(core.presetSpec('month', bounds), bounds);
  const report = core.formatReportText(core.groupByMonth([ga, cyber], 'desc', () => 0),
    {range, tiers:new Set(allTiers), allTiers, terms:['argon']});
  assert.match(report, /Oct 13, 2026 · Google · Gemini 4 Argon \(general availability\) · flagship/);
  assert.match(report, /Oct 13, 2026 · Google · Gemini 4 Argon Cyber Permissive \(allowlisted GA\) · specialty/);
});

const requiredReleases = [
  ['Beam (restricted preview)', 'Reflection AI', '2026-10-05', 'flagship'],
  ['EmbeddingGemma 2', 'Google', '2026-10-06', 'specialty'],
  ['Claude Haiku 5.5', 'Anthropic', '2026-10-07', 'small'],
  ['d1-3B / d1-omni-600M', 'Liquid AI', '2026-10-07', 'specialty'],
  ['pplx-embed-v2-late family', 'Perplexity', '2026-10-07', 'specialty'],
  ['Mistral Large 4 (public preview)', 'Mistral', '2026-10-06', 'flagship'],
  ['Gemini Nano Banana 2.1', 'Google', '2026-10-06', 'specialty'],
  ['pplx-decider-v1.1-27b', 'Perplexity', '2026-10-06', 'specialty'],
  ['Qwen-Image-2.1-Pro (API)', 'Alibaba (Qwen)', '2026-10-02', 'specialty'],
  ['Clef / Clef-flash', 'Cloudflare', '2026-10-01', 'specialty'],
  ['MAI-Voice-2.1 / MAI-Voice-2.1-Flash', 'Microsoft', '2026-10-01', 'specialty'],
  ['MAI-Transcribe-2-Streaming', 'Microsoft', '2026-10-01', 'specialty'],
  ['pplx-decider-v1-27b', 'Perplexity', '2026-10-01', 'specialty'],
  ['Strands Decider 2B', 'AWS Strands Labs', '2026-10-01', 'specialty'],
  ['FLUX 3 Image', 'Black Forest Labs', '2026-10-01', 'specialty'],
  ['Griffin-Lite (research preview)', 'Tavus', '2026-10-01', 'specialty'],
  ['Ling 3.1 Flash', 'Ant Group (inclusionAI)', '2026-09-30', 'mid'],
  ['pplx-embed-v2-context-9b-preview', 'Perplexity', '2026-09-30', 'specialty'],
  ['HY Image 3.5 Preview', 'Tencent', '2026-09-22', 'specialty'],
  ['Pareto 26.10 Preview', 'Unbiased', '2026-10-01', 'specialty'],
  ['Gemini 4 Argon', 'Google', '2026-09-30', 'flagship'],
  ['Cohere Embed 5 family', 'Cohere', '2026-09-30', 'specialty'],
  ['HeyGen Video 1', 'HeyGen', '2026-09-30', 'specialty'],
  ['Kling 4.0 (early access)', 'Kuaishou', '2026-09-30', 'specialty'],
  ['Praxis-1 (partner preview)', 'Runway', '2026-09-30', 'specialty'],
  ['GPT-6.1 Sol', 'OpenAI', '2026-09-29', 'mid'],
  ['Claude Sonnet 5.5', 'Anthropic', '2026-09-28', 'mid'],
  ['Eleven v4 / Eleven v4 Turbo', 'ElevenLabs', '2026-09-28', 'specialty'],
  ['Kling 4.0 Flash', 'Kuaishou', '2026-09-28', 'specialty'],
  ['Naive-N0.5-Flash', 'NaiveAI', '2026-09-27', 'open-weights'],
  ['MiMo-V2.6 MOPD family', 'Xiaomi', '2026-09-27', 'open-weights'],
  ['MiniMax-M3.1-Flash-Preview', 'MiniMax', '2026-09-27', 'mid'],
  ['LongCat-2.5-Preview', 'Meituan', '2026-09-25', 'flagship'],
  ['Perceptron Mk1.5', 'Perceptron', '2026-09-25', 'specialty'],
  ['Pixel Canary', 'Undisclosed (stealth)', '2026-09-25', 'specialty'],
  ['Decision Model Preview', 'Alibaba (Qwen)', '2026-09-24', 'specialty'],
  ['Space Bunny Alpha', 'Undisclosed (stealth)', '2026-09-23', 'specialty'],
  ['Aion 3.5 / Aion 3.5 Mini', 'AionLabs', '2026-09-23', 'specialty'],
  ['CLM-v0.1-8B', 'Contrastive-LM', '2026-09-23', 'specialty'],
  ['Qwen-Audio-3.1-Realtime-Plus', 'Alibaba (Qwen)', '2026-09-20', 'specialty'],
  ['HappyOyster 1.0 family', 'Alibaba (Qwen)', '2026-09-18', 'specialty'],
  ['Gemini 3.8 Live with Live Avatar', 'Google', '2026-09-24', 'specialty'],
  ['LFM2.5-VL-3B-DSpark', 'Liquid AI', '2026-09-24', 'specialty'],
  ['VeriLoop E2', 'Tsinghua SIGS Robot Lab', '2026-09-24', 'open-weights'],
  ['Gemini 3.8 Flash TTS family', 'Google', '2026-09-23', 'specialty'],
  ['Qwen3.8-Max-Prime', 'Alibaba (Qwen)', '2026-09-23', 'flagship'],
  ['Ember-1', 'Fireworks AI', '2026-09-23', 'specialty'],
  ['Claude Opus 5.5', 'Anthropic', '2026-09-22', 'flagship'],
  ['GPT-6 Sol', 'OpenAI', '2026-09-22', 'mid'],
  ['GPT-6 Luna', 'OpenAI', '2026-09-22', 'small'],
  ['Solar Mini 4', 'Upstage', '2026-09-22', 'small'],
  ['Grok 4.7', 'xAI', '2026-09-21', 'flagship'],
  ['Qwen3.8-Omni-Flash-Realtime', 'Alibaba (Qwen)', '2026-09-21', 'specialty'],
  ['MiMo-V2.6 family', 'Xiaomi', '2026-09-21', 'open-weights'],
  ['Step 5 Preview', 'StepFun', '2026-09-20', 'flagship'],
  ['Qwen-Image-2.1', 'Alibaba (Qwen)', '2026-09-20', 'open-weights'],
  ['Grok Voice Transcribe 2.0', 'xAI', '2026-09-18', 'specialty'],
  ['K2 Horizon family', 'MBZUAI (IFM)', '2026-09-03', 'open-weights'],
  ['MAI-Transcribe-2', 'Microsoft', '2026-09-03', 'specialty'],
  ['WeatherNext 3', 'Google', '2026-09-03', 'specialty'],
  ['Lyria 3.5', 'Google', '2026-09-04', 'specialty'],
  ['Ling-3.0-flash-Sante', 'Ant Group (inclusionAI)', '2026-09-04', 'specialty'],
  ['Ling-3.0-flash-VL', 'Ant Group (inclusionAI)', '2026-09-04', 'open-weights'],
  ['LLaDA2.2-mini', 'Ant Group (inclusionAI)', '2026-09-05', 'open-weights'],
  ['MiniCPM5-2B', 'OpenBMB', '2026-09-07', 'small'],
  ['Spark X2.5', 'iFLYTEK', '2026-09-07', 'flagship'],
  ['Nex-N2.5 family', 'Nex AGI', '2026-09-08', 'open-weights'],
  ['Mercury 2.5', 'Inception', '2026-09-08', 'mid'],
  ['GPT-Image-2.5 Flare / Sunburst', 'OpenAI', '2026-09-08', 'specialty'],
  ['Suno v6 family', 'Suno', '2026-09-09', 'specialty'],
  ['AuK / AuK-Flash', 'Tencent', '2026-09-09', 'specialty'],
  ['DeepSeek-V4.1-Flash', 'DeepSeek', '2026-09-10', 'open-weights'],
  ['SWE-2', 'Cognition', '2026-09-10', 'specialty'],
  ['YuE2-3B', 'M-A-P', '2026-09-10', 'specialty'],
  ['Kimi K2.8 Preview', 'Moonshot', '2026-09-11', 'mid'],
  ['Atria Dawn Preview', 'Shanghai AI Lab', '2026-09-11', 'open-weights'],
  ['Fugu Max / Fugu Ultra v2', 'Sakana AI', '2026-09-11', 'specialty'],
  ['Agnes-3.0-Flash Preview', 'Agnes AI', '2026-09-11', 'open-weights'],
  ['Gemini 3.8 Live family', 'Google', '2026-09-15', 'specialty'],
  ['Koa', 'Salesforce', '2026-09-15', 'specialty'],
  ['Jev', 'TypeSafe AI', '2026-09-15', 'specialty'],
  ['open-1b', 'Gensyn', '2026-09-15', 'open-weights'],
  ['XGEN-JING / JING-Flash-v1', 'XGEN Labs', '2026-09-16', 'specialty'],
  ['WeVisDoc-2B / 4B', 'Tencent', '2026-09-16', 'specialty'],
  ['Antigravity Agent 09-2026', 'Google', '2026-09-17', 'specialty'],
  ['Ternary Bonsai 2 27B', 'PrismML', '2026-09-17', 'open-weights'],
  ['Pareto 26.9', 'Unbiased', '2026-09-17', 'specialty'],
  ['Xing4.0-29B-A4B', 'China Telecom AI', '2026-09-17', 'open-weights'],
  ['SPARSEUP', 'Linkup Research', '2026-09-17', 'specialty'],
  ['Needle 3', 'Cactus Compute', '2026-09-17', 'small'],
  ['HuatuoGPT-3-9B', 'Freedom Intelligence', '2026-09-17', 'specialty'],
  ['Qwen3.8-LiveTranslate-Flash-Realtime', 'Alibaba (Qwen)', '2026-09-17', 'specialty'],
  ['Qwen3.8-Omni-Flash', 'Alibaba (Qwen)', '2026-09-18', 'specialty'],
  ['Laya', 'Convai Innovations', '2026-09-18', 'small'],
  ['Qwen3.8-Flash (API)', 'Alibaba (Qwen)', '2026-08-26'],
  ['Qwen-MT-Image 2.0', 'Alibaba (Qwen)', '2026-08-28'],
  ['GPT-6 Astra', 'OpenAI', '2026-09-03'],
  ['Qwen3.8-Max-0902', 'Alibaba (Qwen)', '2026-09-02'],
  ['Qwen3.8-Max', 'Alibaba (Qwen)', '2026-08-03'],
  ['Muse Spark 1.2', 'Meta', '2026-08-05'],
  ['Nemotron 3.5 Lightning', 'NVIDIA', '2026-08-11'],
  ['Grok 4.6', 'xAI', '2026-08-12'],
  ['Gemini 3.7 Flash', 'Google', '2026-08-13'],
  ['DeepSeek-V4-Pro (GA)', 'DeepSeek', '2026-08-13'],
  ['GLM-5.3', 'Z.ai (Zhipu)', '2026-08-14'],
  ['Qwen3.8-27B', 'Alibaba (Qwen)', '2026-08-14'],
  ['DeepSeek-V4-Flash-Vision-Exp', 'DeepSeek', '2026-08-21'],
  ['Gemini 3.5 Transcribe', 'Google', '2026-08-26'],
  ['GLM-5.3-Flash', 'Z.ai (Zhipu)', '2026-08-26'],
  ['Qwen3.8-Flash-Next', 'Alibaba (Qwen)', '2026-08-26'],
  ['Gemini Omni 1.1 Flash', 'Google', '2026-08-27'],
  ['Claude Fable 5.1 / Mythos 5.1', 'Anthropic', '2026-09-01'],
  ['Gemini 3.8 Flash', 'Google', '2026-09-02'],
  ['Gemini 3.8 Flash Cyber', 'Google', '2026-09-02'],
  ['Muse Spark 1.3', 'Meta', '2026-09-02'],
  ['Hy-MT2 family', 'Tencent', '2026-05-21'],
];

test('inline application JavaScript parses', () => {
  assert.doesNotThrow(() => new vm.Script(extractInlineScript()));
  assert.doesNotThrow(() => new vm.Script(extractCoreScript()));
});

test('contains every verified release from the October 8 sweep', () => {
  for (const [model, lab, date, tier] of requiredReleases) {
    const row = data.find(candidate => candidate.model === model && candidate.lab === lab && candidate.date === date);
    assert.ok(row, `missing ${model} (${lab}, ${date})`);
    if (tier) assert.equal(row.tier, tier, `${model} has the expected tier`);
  }
});

test('preserves the Qwen3.8-Max preview as a distinct historical event', () => {
  assert.ok(data.some(row => row.model === 'Qwen3.8-Max Preview' && row.date === '2026-07-19'));
  assert.ok(data.some(row => row.model === 'Qwen3.8-Max' && row.date === '2026-08-03'));
});

test('evidence-gates the September 17–18 Qwen additions', () => {
  const omni = data.find(row => row.model === 'Qwen3.8-Omni-Flash');
  assert.equal(omni.source, 'https://docs.qwencloud.com/changelog/models');
  assert.ok(data.some(row => row.model === 'Qwen3.8-LiveTranslate-Flash-Realtime' && row.date === '2026-09-17'));
  const world = data.find(row => row.model === 'HappyOyster 1.0 family' && row.date === '2026-09-18');
  assert.equal(world?.source, 'https://docs.qwencloud.com/changelog/models');
});

test('latest model records distinguish released models from restricted previews', () => {
  const sol = data.find(row => row.model === 'GPT-6.1 Sol');
  assert.equal(sol?.source, 'https://developers.openai.com/api/docs/changelog');
  assert.match(sol?.note || '', /gpt-6\.1-sol/);
  assert.match(data.find(row => row.model === 'Gemini 4 Argon')?.note || '', /Fairwind/);
  assert.match(data.find(row => row.model === 'Gemini 4 Argon')?.note || '', /not yet generally available/);
  assert.match(data.find(row => row.model === 'Praxis-1 (partner preview)')?.note || '', /weights.*not yet public/);
  assert.match(data.find(row => row.model === 'Mistral Large 4 (public preview)')?.note || '', /weights.*not yet public/);
  assert.match(data.find(row => row.model === 'Griffin-Lite (research preview)')?.note || '', /selected.*testers/);
  assert.match(data.find(row => row.model === 'Beam (restricted preview)')?.note || '', /select group.*not yet public/);
  assert.ok(!data.some(row => /GPT-6\.1 Astra|Grok 4\.8|^Beam$|GLM-5\.3 Fast/.test(row.model)));
});

test('tooltip placement uses measured bounds and clamps both viewport axes', () => {
  const script = extractInlineScript();
  assert.match(html, /#tooltip\{[^}]*max-width:min\(340px, calc\(100vw - 16px\)\)/);
  assert.match(script, /tooltip\.node\(\)\.getBoundingClientRect\(\)/);
  assert.match(script, /window\.innerWidth\s*-\s*tipRect\.width/);
  assert.match(script, /window\.innerHeight\s*-\s*tipRect\.height/);
  assert.doesNotMatch(script, /const tw\s*=\s*350/);
});

test('has valid, unique release records and secure source URLs', () => {
  const keys = new Set();
  for (const row of data) {
    assert.match(row.date, /^\d{4}-\d{2}-\d{2}$/);
    assert.ok(!Number.isNaN(Date.parse(`${row.date}T00:00:00Z`)), `${row.model} has a valid date`);
    assert.match(row.source, /^https:\/\//, `${row.model} uses an HTTPS source`);
    assert.ok(['flagship', 'mid', 'small', 'open-weights', 'specialty'].includes(row.tier));
    const key = `${row.model}\u0000${row.lab}\u0000${row.date}`;
    assert.ok(!keys.has(key), `duplicate release row: ${row.model} / ${row.lab} / ${row.date}`);
    keys.add(key);
  }
});

test('static header metadata and initial chart domain cover the dataset', () => {
  const latest = data.reduce((max, row) => row.date > max ? row.date : max, '');
  const labs = new Set(data.map(row => row.lab));
  assert.equal(latest, '2026-10-23');
  assert.match(html, new RegExp(`<span data-release-count>${data.length}<\\/span>`));
  assert.match(html, new RegExp(`<span data-lab-count>${labs.size}<\\/span>`));
  assert.match(html, /<span data-latest-date>October 23, 2026<\/span>/);
  assert.equal((html.match(/· checked October 25, 2026 ·/g) || []).length, 1);
  assert.equal((html.match(/Verification checked October 25, 2026/g) || []).length, 1);
  // Proportional range padding replaces the former fixed ±15-day x0 domain,
  // so assert the core-driven domain instead of its retired literal expression.
  const script = extractInlineScript();
  assert.match(script, /TimelineCore\.domainPaddingDays\(resolved\.start,\s*resolved\.end\)/);
  assert.match(script, /\.domain\(\[d3\.timeDay\.offset\(localDate\(resolved\.start\)/);
  assert.match(script, /d3\.timeDay\.offset\(localDate\(resolved\.end\)/);
});

const fixtureBounds = {earliest:'2024-01-10', latest:'2026-09-24'};
const allTiers = ['flagship', 'mid', 'small', 'open-weights', 'specialty'];

test('TimelineCore uses local dates for brush snaps and UTC calendar arithmetic', () => {
  const core = loadCore();
  assert.equal(core.toISODateLocal(new Date(2026, 8, 22)), '2026-09-22');
  for (const [month, day] of [[2, 8], [10, 1]]) {
    const iso = `2026-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    for (const hour of [0, 10]) assert.equal(core.snapToLocalDay(new Date(2026, month, day, hour, 30)), iso);
    for (const hour of [14, 23]) assert.equal(core.snapToLocalDay(new Date(2026, month, day, hour, 30)), core.addDays(iso, 1));
  }
  assert.equal(core.daysBetweenISO('2026-03-01', '2026-03-31'), 30);
  assert.equal(core.daysInclusive('2026-09-01', '2026-09-01'), 1);
  assert.equal(core.addDays('2024-02-28', 1), '2024-02-29');
  assert.equal(core.addDays('2025-12-31', 1), '2026-01-01');
  assert.equal(core.lastDayOfMonth(2024, 2), 29);
  assert.equal(core.monthKey('2026-09-22'), '2026-09');
  assert.equal(core.fmtShortDate('2026-09-22'), 'Sep 22, 2026');
  assert.equal(core.fmtLongDate('2026-09-22'), 'September 22, 2026');
  assert.equal(core.fmtMonthLabel('2026-09'), 'September 2026');
});

test('TimelineCore resolves presets, steps within bounds and rejects non-overlap', () => {
  const core = loadCore();
  const resolved = kind => core.resolveRange(core.presetSpec(kind, fixtureBounds), fixtureBounds);
  assert.deepEqual([resolved('month').start, resolved('month').end, resolved('month').label], ['2026-09-01', '2026-09-24', 'September 2026']);
  assert.deepEqual([resolved('quarter').start, resolved('quarter').end, resolved('quarter').label], ['2026-07-01', '2026-09-24', 'Q3 2026']);
  assert.deepEqual([resolved('year').start, resolved('year').end, resolved('year').label], ['2026-01-01', '2026-09-24', '2026 YTD']);
  const priorYear = core.resolveRange(core.stepSpec(core.presetSpec('year', fixtureBounds), -1, fixtureBounds), fixtureBounds);
  assert.deepEqual([priorYear.start, priorYear.end, priorYear.label], ['2025-01-01', '2025-12-31', '2025']);
  assert.deepEqual([resolved('last12').start, resolved('last12').end], ['2025-10-01', '2026-09-24']);
  const earliest = core.resolveRange({kind:'quarter', y:2024, q:1}, fixtureBounds);
  assert.equal(earliest.start, '2024-01-10');
  assert.equal(earliest.canPrev, false);
  const latestMonth = core.presetSpec('month', fixtureBounds);
  assert.equal(core.stepSpec(latestMonth, 1, fixtureBounds), null);
  assert.deepEqual(core.stepSpec(latestMonth, -1, fixtureBounds), {kind:'month', ym:'2026-08'});
  const october = {earliest:'2024-01-10', latest:'2026-10-03'};
  assert.deepEqual([core.resolveRange(core.presetSpec('quarter', october), october).start, core.resolveRange(core.presetSpec('quarter', october), october).end], ['2026-10-01', '2026-10-03']);
  assert.equal(core.periodOverlaps({kind:'quarter', y:2019, q:1}, fixtureBounds), false);
  assert.throws(() => core.resolveRange({kind:'quarter', y:2019, q:1}, fixtureBounds), /does not overlap/);
  assert.deepEqual(core.decodeState('#range=q:2019-1', fixtureBounds, allTiers).range, {kind:'all'});
});

test('TimelineCore validates, swaps and clamps custom ranges', () => {
  const core = loadCore();
  assert.deepEqual(core.normalizeCustom('2026-09-15', '2026-08-01', fixtureBounds), {kind:'custom', start:'2026-08-01', end:'2026-09-15'});
  assert.deepEqual(core.normalizeCustom('2023-01-01', '2030-01-01', fixtureBounds), {kind:'custom', start:'2024-01-10', end:'2026-09-24'});
  assert.deepEqual(core.normalizeCustom('', '2026-01-01', fixtureBounds), {error:'Enter both dates.'});
  assert.deepEqual(core.normalizeCustom('2026-02-30', '2026-03-01', fixtureBounds), {error:'Enter both dates.'});
  assert.deepEqual(core.normalizeCustom('2030-01-01', '2031-01-01', fixtureBounds), {error:'No releases are recorded in that period. Data covers 2024-01-10 – 2026-09-24.'});
});

test('TimelineCore all range follows the real data and uses proportional domain padding', () => {
  const core = loadCore();
  const bounds = {earliest:data.reduce((v,d)=>d.date<v?d.date:v,data[0].date), latest:data.reduce((v,d)=>d.date>v?d.date:v,data[0].date)};
  const all = core.resolveRange({kind:'all'}, bounds);
  assert.deepEqual([all.start, all.end], [bounds.earliest, bounds.latest]);
  assert.equal(core.domainPaddingDays('2026-09-22', '2026-09-22'), 1);
  assert.equal(core.domainPaddingDays(all.start, all.end), Math.max(1, Math.round((core.daysBetweenISO(all.start, all.end) + 1) * .02)));
  assert.ok(core.domainPaddingDays(all.start, all.end) >= 19);
});

test('TimelineCore groups releases with same-day tie order unchanged by date direction', () => {
  const core = loadCore();
  const rows = [
    {date:'2026-09-22',lab:'Zulu',tier:'mid',model:'Z'},
    {date:'2026-09-22',lab:'Alpha',tier:'small',model:'A'},
    {date:'2026-08-01',lab:'Alpha',tier:'flagship',model:'Old'},
  ];
  const rank = lab => ({Alpha:0,Zulu:1})[lab];
  assert.deepEqual(core.groupByMonth(rows, 'desc', rank).map(g => [g.key, g.rows.map(r=>r.model)]), [['2026-09',['A','Z']],['2026-08',['Old']]]);
  assert.deepEqual(core.groupByMonth(rows, 'asc', rank).map(g => [g.key, g.rows.map(r=>r.model)]), [['2026-08',['Old']],['2026-09',['A','Z']]]);
});

test('TimelineCore monthly counts cover every calendar month including empty months', () => {
  const core = loadCore();
  const bounds = {earliest:data.reduce((v,d)=>d.date<v?d.date:v,data[0].date), latest:data.reduce((v,d)=>d.date>v?d.date:v,data[0].date)};
  const months = core.monthlyTierCounts(data, bounds);
  assert.equal(months.reduce((n,m)=>n+m.total,0), data.length);
  assert.equal(months.length, 34);
  assert.equal(months[0].key, '2024-01');
  assert.equal(months.at(-1).key, '2026-10');
  assert.ok(months.every((month,i) => i===0 || month.start === core.addDays(months[i-1].end,1)));
  const sparse = core.monthlyTierCounts([{date:'2026-01-15',tier:'mid'}], {earliest:'2026-01-01',latest:'2026-03-31'});
  assert.deepEqual(sparse.map(m=>m.total), [1,0,0]);
});

test('TimelineCore formats a two-month report with three releases exactly', () => {
  const core = loadCore();
  const rows = [
    {date:'2026-09-22',lab:'Anthropic',model:'Claude Opus 5.5',tier:'flagship',source:'https://a.example'},
    {date:'2026-09-22',lab:'OpenAI',model:'GPT-6 Sol',tier:'mid',source:'https://b.example'},
    {date:'2026-08-01',lab:'OpenAI',model:'GPT-6 Astra',tier:'flagship',source:'https://c.example'},
  ];
  const groups = core.groupByMonth(rows, 'desc', lab => lab==='Anthropic'?0:1);
  const actual = core.formatReportText(groups, {range:{label:'Custom',start:'2026-08-01',end:'2026-09-22'}, tiers:new Set(allTiers), allTiers, terms:[]});
  assert.equal(actual, 'AI model releases · Custom · Aug 1 – Sep 22, 2026 · 3 releases · 2 labs\n\nSEPTEMBER 2026 (2)\nSep 22, 2026 · Anthropic · Claude Opus 5.5 · flagship · https://a.example\nSep 22, 2026 · OpenAI · GPT-6 Sol · mid · https://b.example\n\nAUGUST 2026 (1)\nAug 1, 2026 · OpenAI · GPT-6 Astra · flagship · https://c.example');
});

test('TimelineCore URL state round-trips each range and defaults invalid parts', () => {
  const core = loadCore();
  const ranges = [
    {kind:'all'}, {kind:'month',ym:'2026-09'}, {kind:'quarter',y:2026,q:3},
    {kind:'year',y:2026}, {kind:'last12',endYm:'2026-09'},
    {kind:'custom',start:'2026-08-01',end:'2026-09-15'},
  ];
  for (const range of ranges) {
    const state = {view:'report',range,sort:'asc',tiers:new Set(['flagship','mid']),terms:['moonshot','anthropic']};
    const hash = core.encodeState(state, fixtureBounds);
    assert.deepEqual(core.decodeState(hash, fixtureBounds, allTiers), state);
    if (range.kind === 'all') assert.match(hash, /^#view=report&sort=/);
    else assert.match(hash, /^#view=report&range=/);
  }
  assert.equal(core.encodeState({view:'timeline',range:{kind:'all'},sort:'desc',tiers:new Set(allTiers),terms:[]}, fixtureBounds), '');
  const noneSelected = {view:'timeline',range:{kind:'all'},sort:'desc',tiers:new Set(),terms:[]};
  assert.equal(core.encodeState(noneSelected, fixtureBounds), '#tiers=');
  assert.deepEqual(core.decodeState('#tiers=', fixtureBounds, allTiers), noneSelected);
  const invalid = core.decodeState('#range=q:2026-Q9&tiers=bogus&view=x', fixtureBounds, allTiers);
  assert.deepEqual(invalid, {view:'timeline',range:{kind:'all'},sort:'desc',tiers:new Set(allTiers),terms:[]});
  assert.deepEqual(core.decodeState('#tiers=mid,bogus', fixtureBounds, allTiers).tiers, new Set(allTiers));
});

const {analyze, render} = require('../scripts/timeline-analysis.cjs');

test('narrative statistics match the expanded dataset', () => {
  const stats = analyze(data);
  assert.equal(stats.total, 513);
  assert.equal(new Set(data.map(row => row.lab)).size, 93);
  assert.equal(stats.sameDay, 444);
  assert.equal(stats.withinTwo, 1851);
  assert.deepEqual(stats.years, {'2024': 88, '2025': 134, '2026': 291});
  assert.deepEqual(stats.weekdays, {'0':14, '1':85, '2':104, '3':103, '4':133, '5':62, '6':12});
  assert.equal(stats.cadence.OpenAI.major, 55);
  assert.equal(stats.cadence.Google.major, 52);
  assert.deepEqual(stats.moonshotLags, [14,90,50,31,38,64,4,16,10,25,25]);
  assert.ok(html.includes(render(stats)), 'published findings equal reproducible current analysis');
});

test('analysis handles same-day pairs, medians, and missing prior releases', () => {
  const rows = [
    {lab:'Moonshot', date:'2026-01-01', tier:'flagship'},
    {lab:'Anthropic', date:'2026-01-02', tier:'flagship'},
    {lab:'Moonshot', date:'2026-01-02', tier:'mid'},
    {lab:'Moonshot', date:'2026-01-04', tier:'flagship'},
    {lab:'Moonshot', date:'2026-01-04', tier:'specialty'},
  ];
  const stats = analyze(rows);
  assert.equal(stats.sameDay, 1, 'same-lab pairs excluded');
  assert.equal(stats.withinTwo, 4, 'two-day boundary included');
  assert.deepEqual(stats.moonshotLags, [0,2], 'no prior leader excluded, same-day leader included');
  assert.equal(stats.cadence.Moonshot.all, 1);
  assert.equal(stats.cadence.Moonshot.major, 1.5);
  assert.equal(stats.cadence.Anthropic.major, null);
});

test('recent-release summary follows the latest dated rows', () => {
  const summary = render(analyze(data));
  assert.match(summary, /Rerank 5 Pro \/ Fast \(October 21\)/);
  assert.match(summary, /Kimi K3\.1 Pro \(October 23\)/);
  assert.match(summary, /Kimi K3\.1 Pro Highspeed \(October 23\)/);
  assert.match(summary, /Nemotron 3\.5 Bolt E4B 4GB \(October 23\)/);
  assert.match(summary, /Canva Craft \(October 22\)/);
  assert.doesNotMatch(summary, /Voxtral Transcribe 3 family \(public preview\) \(October 20\)/);
  assert.doesNotMatch(summary, /Muse Wonder \(October 12\)/);
  assert.doesNotMatch(summary, /MISSINGNO\. \(October 10\)/);
  assert.doesNotMatch(summary, /The latest cluster spans Antigravity/);
});

test('new October data anchors calendar presets and preserves historical records', () => {
  const core = loadCore();
  const bounds = {earliest:'2024-01-10', latest:data.reduce((v,row) => row.date > v ? row.date : v, '')};
  for (const [kind, start, label] of [['month','2026-10-01','October 2026'], ['quarter','2026-10-01','Q4 2026'], ['last12','2025-11-01','Last 12 months']]) {
    const result = core.resolveRange(core.presetSpec(kind, bounds), bounds);
    assert.equal(result.start, start);
    assert.equal(result.end, bounds.latest);
    if (kind !== 'last12') assert.equal(result.label, label);
    assert.equal(result.canNext, false);
  }
  const originalRows = require('./fixtures/ai-model-timeline-2026-10-08.json');
  const {corrections} = require('../docs/ai_model_timeline_update_sources_2026_10_12.json');
  for (const original of originalRows) {
    const corrected = corrections.find(change => JSON.stringify(change.before) === JSON.stringify(original));
    assert.deepEqual(data.find(row => row.model === original.model && row.lab === original.lab && row.date === original.date), corrected?.after || original);
  }
});

test('October 8 evidence manifest exactly accounts for additions and preserved data', () => {
  const baseline = require('./fixtures/ai-model-timeline-2026-10-08.json');
  const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'docs', 'ai_model_timeline_update_sources_2026_10_08.json'), 'utf8'));
  const key = row => [row.model, row.lab, row.date].join('\u0000');
  const additions = new Set(manifest.additions.map(key));
  const original = baseline.filter(row => !additions.has(key(row)));
  assert.equal(manifest.preservedHistoricalRows, original.length);
  assert.equal(original.length, 404);
  assert.equal(manifest.additions.length, 19);
  assert.equal(baseline.length, original.length + manifest.additions.length);
  for (const row of [...original, ...manifest.additions]) {
    assert.deepEqual(baseline.find(candidate => key(candidate) === key(row)), row);
  }
});

test('October 12 evidence manifest exactly accounts for all additions and corrections', () => {
  const original = require('./fixtures/ai-model-timeline-2026-10-08.json');
  const manifest = require('../docs/ai_model_timeline_update_sources_2026_10_12.json');
  const key = row => [row.model, row.lab, row.date].join('\u0000');
  assert.equal(manifest.checked, '2026-10-12');
  assert.equal(manifest.preservedHistoricalRows, 423);
  assert.equal(original.length, 423);
  assert.equal(manifest.additions.length, 43);
  assert.equal(manifest.corrections.length, 1);
  for (const change of manifest.corrections) {
    assert.deepEqual(original.find(row => key(row) === key(change.before)), change.before);
  }
  const expected = original.map(row => manifest.corrections.find(change => key(change.before) === key(row))?.after || row).concat(manifest.additions);
  assert.equal(expected.length, 466);
  for (const row of expected) assert.deepEqual(data.find(candidate => key(candidate) === key(row)), row);
});

test('October 14 evidence manifest exactly accounts for new events and preserves the October 12 dataset', () => {
  const original = require('./fixtures/ai-model-timeline-2026-10-08.json');
  const previous = require('../docs/ai_model_timeline_update_sources_2026_10_12.json');
  const manifest = require('../docs/ai_model_timeline_update_sources_2026_10_14.json');
  const key = row => [row.model, row.lab, row.date].join('\u0000');
  const baseline = original.map(row => previous.corrections.find(change => key(change.before) === key(row))?.after || row).concat(previous.additions);
  assert.equal(manifest.checked, '2026-10-14');
  assert.equal(manifest.latestRelease, '2026-10-13');
  assert.equal(manifest.baselineManifest, 'ai_model_timeline_update_sources_2026_10_12.json');
  assert.equal(manifest.preservedHistoricalRows, baseline.length);
  assert.equal(manifest.additions.length, 6);
  assert.deepEqual(manifest.corrections, []);
  const expected = baseline.concat(manifest.additions);
  assert.equal(expected.length, 472, 'the October 14 snapshot remains fully accounted for');
  for (const row of expected) assert.deepEqual(data.find(candidate => key(candidate) === key(row)), row);
  assert.match(data.find(row => row.model === 'Natura-1 (research announcement)')?.note || '', /external user access were not established/);
  assert.match(data.find(row => row.model === 'GLM-Legal (beta announcement)')?.note || '', /access is by application/);
});

test('October 22 manifest accounts for its historical snapshot and preserves every prior row', () => {
  const original = require('./fixtures/ai-model-timeline-2026-10-08.json');
  const october12 = require('../docs/ai_model_timeline_update_sources_2026_10_12.json');
  const october14 = require('../docs/ai_model_timeline_update_sources_2026_10_14.json');
  const manifest = require('../docs/ai_model_timeline_update_sources_2026_10_22.json');
  const key = row => [row.model, row.lab, row.date].join('\u0000');
  const baseline = original.map(row => october12.corrections.find(change => key(change.before) === key(row))?.after || row)
    .concat(october12.additions, october14.additions);
  assert.equal(manifest.checked, '2026-10-22');
  assert.equal(manifest.latestRelease, '2026-10-21');
  assert.equal(manifest.baselineManifest, 'ai_model_timeline_update_sources_2026_10_14.json');
  assert.equal(manifest.preservedHistoricalRows, baseline.length);
  assert.equal(baseline.length, 472);
  assert.equal(manifest.additions.length, 32);
  assert.deepEqual(manifest.corrections, []);
  const expected = baseline.concat(manifest.additions);
  assert.equal(expected.length, 504);
  for (const row of expected) assert.deepEqual(data.find(candidate => key(candidate) === key(row)), row);
  assert.equal(expected.reduce((latest, row) => row.date > latest ? row.date : latest, ''), manifest.latestRelease);
  for (const row of manifest.additions) assert.ok(row.date <= manifest.checked, `${row.model} is not a future release`);
});

test('October 25 manifest accounts for every new row while preserving the October 22 snapshot', () => {
  const manifest = require('../docs/ai_model_timeline_update_sources_2026_10_25.json');
  const key = row => [row.model, row.lab, row.date].join('\u0000');
  const addedKeys = new Set(manifest.additions.map(key));
  const baseline = data.filter(row => !addedKeys.has(key(row)));
  assert.equal(manifest.checked, '2026-10-25');
  assert.equal(manifest.latestRelease, '2026-10-23');
  assert.equal(manifest.baselineManifest, 'ai_model_timeline_update_sources_2026_10_22.json');
  assert.equal(manifest.preservedHistoricalRows, 504);
  assert.equal(baseline.length, manifest.preservedHistoricalRows);
  assert.equal(manifest.additions.length, 9);
  assert.deepEqual(manifest.corrections, []);
  assert.equal(data.length, baseline.length + manifest.additions.length);
  for (const row of manifest.additions) {
    assert.deepEqual(data.find(candidate => key(candidate) === key(row)), row);
    assert.ok(row.date <= manifest.checked, `${row.model} is not a future release`);
  }
  assert.equal(data.reduce((latest, row) => row.date > latest ? row.date : latest, ''), manifest.latestRelease);
});

test('latest additions retain preview, weight-release, and announcement date distinctions', () => {
  const get = model => data.find(row => row.model === model);
  for (const [before, after] of [
    ['Beam (restricted preview)', 'Beam (open weights / public API beta)'],
    ['MiniMax-M3.1-Flash-Preview', 'MiniMax-M3.1-Flash (general availability)'],
    ['Pareto 26.10 Preview', 'Pareto 26.10 (stable)'],
    ['Step 5 Preview', 'Step 5 Preview (open weights)'],
  ]) {
    assert.ok(get(before) && get(after), `${before} and its later milestone both remain`);
    assert.ok(get(before).date < get(after).date);
  }
  assert.equal(get('Glimpse (research preview)')?.date, '2026-10-16');
  assert.equal(get('Strands Decider 26B-A4B (Gemma 4)')?.date, '2026-10-09');
  assert.equal(get('Nemotron 3.5 Embed 1B / 8B')?.date, '2026-10-20');
  assert.equal(get('Nemotron 3.5 Rerank 8B')?.date, '2026-10-20');
  assert.equal(get('Nemotron 3.5 Parse')?.date, '2026-10-17');
  assert.equal(get('DeepSeek-V4.1-Flash-1017')?.date, '2026-10-17');
  assert.match(get('Maxwell (controlled early access)')?.note || '', /Access is by request/);
  assert.match(get('Jev 1.14.0 (preview)')?.note || '', /effective switch date is not verified/);
  assert.equal(get('Nemotron 3.5 Bolt E4B 4GB')?.date, '2026-10-23');
  assert.equal(get('Nemotron 3.5 Bolt E4B 4GB')?.tier, 'open-weights');
  assert.equal(get('Hy-Nomas')?.date, '2026-10-23');
  assert.equal(get('Phonon 31m / 40m family (open weights)')?.date, '2026-10-20');
  assert.match(get('Phonon 31m / 40m family (open weights)')?.note || '', /40m variants use CC BY-NC/);
  assert.ok(!data.some(row => /GPT-6\.1 Terra|Gemini 4 Carbon|Fable 5\.2/.test(row.model)));
});

test('same-day labels stay beside their dots and clear the date axis', () => {
  const source = extractInlineScript();
  assert.equal((source.match(/\.attr\('y', labelY\)/g) || []).length, 2, 'initial render and relayout use the tested label position');
  const start = source.indexOf('const STACK_GAP =');
  const end = source.indexOf('\nfunction renderLanes()', start);
  const rows = data.filter(row => row.lab === 'OpenAI' && row.date === '2026-09-22').map(row => ({...row}));
  const context = {DATA:rows, visible:() => true, yLane:() => 47};
  vm.createContext(context);
  vm.runInContext(source.slice(start, end) + '\nupdateStackOffsets(); globalThis.positions = DATA.map(d => ({model:d.model, dot:yDot(d), y:labelY(d), dx:labelDx(d), anchor:labelAnchor(d)}));', context);
  assert.equal(context.positions.length, 2);
  for (const position of context.positions) {
    assert.ok(position.y - 10 >= 34, `${position.model} clears the date axis`);
    assert.equal(position.y, position.dot + 3, 'stacked label is vertically centered beside its dot');
    assert.ok(Math.abs(position.dx) >= 8, 'label clears the dot radius');
  }
  assert.equal(context.positions[0].anchor, 'end');
  assert.equal(context.positions[1].anchor, 'start');
  // Filtering one sibling out restores the usual single-release label above the dot.
  context.visible = row => row === rows[0];
  vm.runInContext('updateStackOffsets(); globalThis.single = {y:labelY(DATA[0]), dx:labelDx(DATA[0]), anchor:labelAnchor(DATA[0])};', context);
  assert.equal(context.single.y, 38);
  assert.equal(context.single.dx, 0);
  assert.equal(context.single.anchor, 'middle');
});

test('label placement retries colliding boxes and suppresses only labels with no room', () => {
  const {placeLabelBoxes} = loadCore();
  const box = (x,y,width=30,height=10) => ({x,y,width,height});
  const items = [
    {id:'first', candidates:[box(20,40)]},
    {id:'second', candidates:[box(35,40),box(55,40)]},
    {id:'crowded', candidates:[box(25,40),box(58,40)]},
    {id:'edge', candidates:[box(-5,60),box(0,60)]},
    {id:'dot', candidates:[box(90,40),box(90,60)]},
  ];
  const bounds = {left:0,right:150,top:34,bottom:100};
  const result = placeLabelBoxes(items,bounds,[box(95,42,8,8)]);
  assert.equal(result.get('first').x,20);
  assert.equal(result.get('second').x,55);
  assert.equal(result.get('crowded'),null);
  assert.equal(result.get('edge').x,0);
  assert.equal(result.get('dot').y,60);
  const visible = [...result.values()].filter(Boolean);
  for (let i=0;i<visible.length;i++) for (let j=i+1;j<visible.length;j++) {
    const a=visible[i],b=visible[j];
    assert.ok(a.x+a.width+2<=b.x || b.x+b.width+2<=a.x || a.y+a.height+2<=b.y || b.y+b.height+2<=a.y);
  }
  assert.deepEqual([...placeLabelBoxes(items,bounds,[box(95,42,8,8)])], [...result], 'placement is deterministic');
  assert.equal(placeLabelBoxes([{id:'second',candidates:[box(35,40)]}],bounds,[]).get('second').x,35,'a filtered-out label releases its space');
  assert.equal(placeLabelBoxes([{id:'axis',candidates:[box(20,30)]}],bounds,[]).get('axis'),null);
  assert.equal(placeLabelBoxes([{id:'wide',candidates:[box(0,60,151)]}],bounds,[]).get('wide'),null);
});

test('SVG placement integration coalesces redraws and restores labels when zoom creates room', () => {
  const core = loadCore();
  const rows = [100,130,160].map((px,i) => ({model:`Long label ${i}`,dt:px,lab:'Google',tier:'specialty',stackCount:1,stackOffset:0}));
  const makeNode = (d,attrs) => ({d,attrs:{...attrs},getAttribute(name){return this.attrs[name] ?? null;},setAttribute(name,value){this.attrs[name]=String(value);},
    getBBox(){return {width:80,height:10,y:Number(this.attrs.y)-8};}});
  const dotNodes=rows.map(d=>makeNode(d,{r:'4.5'}));
  const labelNodes=rows.map(d=>makeNode(d,{y:'38'}));
  const selection=nodes=>({each(fn){nodes.forEach(node=>fn.call(node,node.d));}});
  const frames=[];
  let scale=1;
  const context={TimelineCore:core,requestAnimationFrame:fn=>{frames.push(fn);return frames.length;},
    wrap:{node:()=>({hidden:false})},MARGIN:{left:34,right:20,top:34,bottom:10},W:250,curH:110,
    dots:selection(dotNodes),labels:selection(labelNodes),visible:()=>true,x:d=>100+(d-100)*scale,yDot:()=>47,
    labelAnchor:()=> 'middle',labelDx:()=>0,labelY:()=>38,
    d3:{select:node=>({attr(name,value){if(value==null) delete node.attrs[name];else node.setAttribute(name,value);return this;}})}};
  vm.createContext(context);
  const source=extractInlineScript();
  vm.runInContext(source.slice(source.indexOf('let labelPlacementFrame ='),source.indexOf('function redraw(){')),context);
  vm.runInContext('scheduleLabelPlacement(); scheduleLabelPlacement();',context);
  assert.equal(frames.length,1,'multiple zoom events share a single animation frame');
  frames.shift()();
  const initiallyVisible=labelNodes.filter(node=>node.attrs.display!=='none').length;
  assert.ok(initiallyVisible>0 && initiallyVisible<3,'dense cluster keeps the labels that fit');
  scale=4;
  context.W=470;
  labelNodes.forEach(node=>delete node.attrs.display); // redraw makes eligible labels available again.
  vm.runInContext('scheduleLabelPlacement();',context);
  frames.shift()();
  assert.equal(labelNodes.filter(node=>node.attrs.display!=='none').length,3,'zooming in restores suppressed labels');
  const boxes=labelNodes.map(node=>({x:Number(node.attrs.x),y:Number(node.attrs.y)-8,width:80,height:10}));
  for (const box of boxes) {
    assert.ok(box.x>=36 && box.x+box.width<=448 && box.y>=37 && box.y+box.height<=98);
    for (const d of rows) {
      const cx=context.x(d.dt);
      assert.ok(box.x+box.width+2<=cx-4.5 || box.x>=cx+4.5+2 || box.y+box.height+2<=42.5 || box.y>=51.5+2,'text clears every dot');
    }
  }
  assert.ok(extractInlineScript().includes('scheduleLabelPlacement();\n}'),'redraw invokes placement for zoom, filter and resize updates');
});
