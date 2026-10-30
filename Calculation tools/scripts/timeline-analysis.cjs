// Reproduce the descriptive analysis without loading D3 or a browser.
const fs = require('node:fs');
const path = require('node:path');
const DAY = 86400000;
const VERIFICATION_DATE = 'October 30, 2026';
const median = values => {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted.length ? (sorted[Math.floor((sorted.length - 1) / 2)] + sorted[Math.floor(sorted.length / 2)]) / 2 : null;
};
function analyze(data) {
  const rows = data.map(row => ({...row, day: Date.parse(`${row.date}T00:00:00Z`) / DAY}));
  const major = rows.filter(row => ['flagship', 'mid'].includes(row.tier));
  const latest = rows.reduce((a, b) => a.date > b.date ? a : b).date;
  const counts = key => rows.reduce((out, row) => { const k = key(row); out[k] = (out[k] || 0) + 1; return out; }, {});
  const cadence = Object.fromEntries([...new Set(rows.map(row => row.lab))].map(lab => {
    const gap = list => { const dates = list.filter(row => row.lab === lab).map(row => row.day).sort((a,b) => a-b); return median(dates.slice(1).map((day,i) => day-dates[i])); };
    return [lab, {all: gap(rows), major: gap(major)}];
  }));
  let sameDay = 0, withinTwo = 0;
  rows.forEach((a, i) => rows.slice(i + 1).forEach(b => {
    if (a.lab === b.lab) return;
    const lag = Math.abs(a.day - b.day);
    if (lag === 0) sameDay++;
    if (lag <= 2) withinTwo++;
  }));
  const lags = (follower, leader) => major.filter(row => row.lab === follower).sort((a,b) => a.day-b.day).flatMap(row => {
    const prior = major.filter(other => other.lab === leader && other.day <= row.day);
    return prior.length ? [row.day - Math.max(...prior.map(other => other.day))] : [];
  });
  const latestDay = Date.parse(`${latest}T00:00:00Z`) / DAY;
  const recent = rows.filter(row => latestDay - row.day <= 2)
    .sort((a,b) => b.day-a.day || (a.model || '').localeCompare(b.model || ''))
    .map(row => ({model:row.model, date:row.date}));
  return {total: rows.length, latest, cadence, sameDay, withinTwo, recent,
    years: counts(row => row.date.slice(0,4)), months: counts(row => row.date.slice(0,7)),
    weekdays: counts(row => new Date(row.day * DAY).getUTCDay()),
    moonshotLags: lags('Moonshot','Anthropic'), googleLags: lags('Google','OpenAI')};
}
function render(s) {
  const date = new Date(`${s.latest}T00:00:00Z`).toLocaleDateString('en-US', {timeZone:'UTC',month:'long',day:'numeric',year:'numeric'});
  const cadenceLabs = ['Google','OpenAI','Alibaba (Qwen)','DeepSeek','Z.ai (Zhipu)','Anthropic','Moonshot','MiniMax','xAI','Mistral'];
  const topMonths = Object.entries(s.months).sort((a,b) => b[1]-a[1] || a[0].localeCompare(b[0])).slice(0,8);
  const windowHits = s.moonshotLags.filter(lag => lag >= 42 && lag <= 56).length;
  return `<section class="findings">
  <h2>What the data says: release-timing patterns</h2>
  <p>Descriptive analysis of all <span data-release-count>${s.total}</span> dated release events through ${date}. “Major” means flagship + mid tiers. Grouped family releases count as one event; previews, hosted snapshots, and general releases can be separate events.</p>
  <h3>1. Does Moonshot follow Anthropic by 6–8 weeks?</h3>
  <div class="verdict"><b>No consistent 6–8 week pattern.</b> For Moonshot's ${s.moonshotLags.length} major releases with a prior Anthropic major, the lags are ${s.moonshotLags.join(', ')} days. Only ${windowHits} of ${s.moonshotLags.length} falls in the 42–56 day window. The median is ${median(s.moonshotLags)} days. These dates alone do not establish whether either lab responds to the other.</div>
  <h3>2. Google's timing relative to OpenAI</h3>
  <p>Across ${s.googleLags.length} Google major releases with a prior OpenAI major, the median lag is <b>${median(s.googleLags)} days</b> (mean ${(s.googleLags.reduce((a,b)=>a+b,0)/s.googleLags.length).toFixed(1)}). Gemini 1.5 Pro and Sora were announced on the same day, February 15, 2024; Gemini 2.5 Pro and GPT-4o image generation were also same-day events, March 25, 2025. Astra arrived after Gemini 3.8 Flash, so it does not change that earlier release's follower lag.</p>
  <h3>3. Cross-lab release clusters</h3>
  <p>There are <b>${s.sameDay} same-day cross-lab release pairs</b> and ${s.withinTwo} pairs within 2 days (including same-day pairs). Multiple models on one date contribute multiple pairs, so these are event-pair counts, not distinct days.</p>
  <p>Recent releases include ${s.recent.map(row => `${row.model} (${new Date(`${row.date}T00:00:00Z`).toLocaleDateString('en-US', {timeZone:'UTC',month:'long',day:'numeric'})})`).join(', ')}.</p>
  <h3>4. Release cadence</h3>
  <table><tr><th>Lab</th><th>All releases (median gap)</th><th>Major releases (median gap)</th></tr>
${cadenceLabs.map(lab=>`    <tr><td>${lab}</td><td>${s.cadence[lab].all} days</td><td>${s.cadence[lab].major} days</td></tr>`).join('\n')}
  </table>
  <p>Gaps include same-day events. Open-weight releases are a separate tier and are excluded from “major” even when they are a lab's flagship; compare these cadence figures with that classification in mind.</p>
  <h3>5. Weekday distribution</h3>
  <p>${['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'].map((name,i)=>`${name}: ${s.weekdays[i] || 0}`).join(' · ')}. These describe the selected release events, not all industry launches.</p>
  <h3>6. Release volume</h3>
  <p>Releases per year: ${Object.entries(s.years).map(([year,count])=>`${count} (${year})`).join(' → ')}. The final year is partial, through ${date}.</p>
  <p>Largest monthly totals: ${topMonths.map(([month,count])=>`${month}: ${count}`).join(' · ')}.</p>
  <h3>7. Interpretation and limits</h3>
  <p>Release timing alone does not demonstrate competitive response or causation. These descriptive counts do not test statistical significance. Shared launch calendars, selection of notable releases, and multiple related models announced together can all produce apparent timing patterns.</p>
  <p class="caveat">Dates generally represent public announcements; explicitly noted hosted availability dates are used for some API models. Approximate dates are flagged in tooltips. A follower lag uses the most recent same-day or earlier major release; events with no prior leader release are excluded. This is a curated timeline, not an exhaustive model registry. Access can be staged or restricted even after announcement. Verification checked ${VERIFICATION_DATE}.</p>
</section>`;
}
const htmlPath = path.join(__dirname, '..', 'ai-model-timeline.html');
function readData(html) { return JSON.parse(html.split('const DATA = ')[1].split(';\n\nconst TIER_COLOR')[0]); }
if (require.main === module) {
  const html = fs.readFileSync(htmlPath, 'utf8');
  const stats = analyze(readData(html));
  if (process.argv.includes('--write')) fs.writeFileSync(htmlPath, html.replace(/<section class="findings">[\s\S]*?<\/section>/, render(stats)));
  console.log(JSON.stringify(stats, null, 2));
}
module.exports = {analyze, render, readData};
