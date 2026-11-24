// Reproduce the descriptive analysis without loading D3 or a browser.
const fs = require('node:fs');
const path = require('node:path');
const DAY = 86400000;
const VERIFICATION_DATE = 'November 24, 2026';
const median = values => {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted.length ? (sorted[Math.floor((sorted.length - 1) / 2)] + sorted[Math.floor(sorted.length / 2)]) / 2 : null;
};
function analyze(data, levels) {
  if (!data.length) throw new Error('Empty raw dataset');
  const {key} = require('./timeline-levels.cjs');
  const entries = levels && new Map(levels.entries.map(entry => [key(entry), entry]));
  const rows = data.filter(row => !entries || (entries.get(key(row))?.level <= 2 && !Object.hasOwn(entries.get(key(row)), 'of')))
    .map(row => ({...row, day: Date.parse(`${row.date}T00:00:00Z`) / DAY}));
  const major = rows.filter(row => ['flagship', 'mid'].includes(row.tier));
  const latest = data.reduce((a, b) => a.date > b.date ? a : b).date;
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
  return {total: rows.length, recorded:data.length, latest, checked:levels?.checked, cadence, sameDay, withinTwo, recent,
    years: counts(row => row.date.slice(0,4)), months: counts(row => row.date.slice(0,7)),
    weekdays: counts(row => new Date(row.day * DAY).getUTCDay()),
    moonshotLags: lags('Moonshot','Anthropic'), googleLags: lags('Google','OpenAI')};
}
function render(s) {
  const date = new Date(`${s.latest}T00:00:00Z`).toLocaleDateString('en-US', {timeZone:'UTC',month:'long',day:'numeric',year:'numeric'});
  const checked = s.checked ? new Date(`${s.checked}T00:00:00Z`).toLocaleDateString('en-US', {timeZone:'UTC',month:'long',day:'numeric',year:'numeric'}) : VERIFICATION_DATE;
  if (!s.total) return `<section class="findings">\n  <h2>What the data says: release-timing patterns</h2>\n  <p>Of ${s.recorded} recorded events through ${date}, zero Headline and Notable main entries are available for analysis. Verification checked ${checked}.</p>\n</section>`;
  const gap = value => value == null ? 'Insufficient data' : `${value} days`;
  const moonshot = s.moonshotLags.length ? `the lags are ${s.moonshotLags.join(', ')} days. Only ${s.moonshotLags.filter(lag => lag >= 42 && lag <= 56).length} of ${s.moonshotLags.length} falls in the 42–56 day window. The median is ${median(s.moonshotLags)} days.` : 'Insufficient data.';
  const google = s.googleLags.length ? `${median(s.googleLags)} days (mean ${(s.googleLags.reduce((a,b)=>a+b,0)/s.googleLags.length).toFixed(1)})` : 'Insufficient data';
  const cadenceLabs = ['Google','OpenAI','Alibaba (Qwen)','DeepSeek','Z.ai (Zhipu)','Anthropic','Moonshot','MiniMax','xAI','Mistral'];
  const topMonths = Object.entries(s.months).sort((a,b) => b[1]-a[1] || a[0].localeCompare(b[0])).slice(0,8);
  return `<section class="findings">
  <h2>What the data says: release-timing patterns</h2>
  <p>Descriptive analysis of <span data-notable-count>${s.total}</span> Headline and Notable main entries among ${s.recorded} recorded events through ${date}. Folded stages, snapshots and variants are excluded from analysis. “Major” means flagship + mid tiers. Grouped family releases count as one event.</p>
  <h3>1. Does Moonshot follow Anthropic by 6–8 weeks?</h3>
  <div class="verdict"><b>Moonshot's ${s.moonshotLags.length} major releases with a prior Anthropic major:</b> ${moonshot} These dates alone do not establish whether either lab responds to the other.</div>
  <h3>2. Google's timing relative to OpenAI</h3>
  <p>Across ${s.googleLags.length} Google major releases with a prior OpenAI major, the median lag is <b>${google}</b>.</p>
  <h3>3. Cross-lab release clusters</h3>
  <p>There are <b>${s.sameDay} same-day cross-lab release pairs</b> and ${s.withinTwo} pairs within 2 days (including same-day pairs). Multiple models on one date contribute multiple pairs, so these are event-pair counts, not distinct days.</p>
  <p>${s.recent.length ? `Recent releases include ${s.recent.map(row => `${row.model} (${new Date(`${row.date}T00:00:00Z`).toLocaleDateString('en-US', {timeZone:'UTC',month:'long',day:'numeric'})})`).join(', ')}.` : 'No Headline or Notable main entries fall in the recent window.'}</p>
  <h3>4. Release cadence</h3>
  <table><tr><th>Lab</th><th>Headline and Notable (median gap)</th><th>Major releases (median gap)</th></tr>
${cadenceLabs.map(lab=>`    <tr><td>${lab}</td><td>${gap(s.cadence[lab]?.all)}</td><td>${gap(s.cadence[lab]?.major)}</td></tr>`).join('\n')}
  </table>
  <p>Gaps include same-day events. Open-weight releases are a separate tier and are excluded from “major” even when they are a lab's flagship; compare these cadence figures with that classification in mind.</p>
  <h3>5. Weekday distribution</h3>
  <p>${['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'].map((name,i)=>`${name}: ${s.weekdays[i] || 0}`).join(' · ')}. These describe Headline and Notable main entries, not all industry launches.</p>
  <h3>6. Release volume</h3>
  <p>Releases per year: ${Object.entries(s.years).map(([year,count])=>`${count} (${year})`).join(' → ')}. The recorded observation period extends through ${date}.</p>
  <p>Largest monthly totals: ${topMonths.map(([month,count])=>`${month}: ${count}`).join(' · ')}.</p>
  <h3>7. Interpretation and limits</h3>
  <p>Release timing alone does not demonstrate competitive response or causation. These descriptive counts do not test statistical significance. Shared launch calendars, selection of notable releases, and multiple related models announced together can all produce apparent timing patterns.</p>
  <p class="caveat">Dates generally represent public announcements; explicitly noted hosted availability dates are used for some API models. Approximate dates are flagged in tooltips. A follower lag uses the most recent same-day or earlier major release; events with no prior leader release are excluded. Historical entries reflect earlier curation, while newer entries use current classification rules, so comparisons across periods are qualified. This is a curated timeline, not an exhaustive model registry. Access can be staged or restricted even after announcement. Verification checked ${checked}.</p>
</section>`;
}
const htmlPath = path.join(__dirname, '..', 'ai-model-timeline.html');
function readData(html) { const match = html.match(/(?:^|\n)const DATA = ([\s\S]*?);\n\nconst TIER_COLOR/); if (!match) throw new Error('DATA declaration missing'); return JSON.parse(match[1]); }
if (require.main === module) {
  const html = fs.readFileSync(htmlPath, 'utf8');
  const data = readData(html);
  const {readEmbeddedLevels, validateLevels} = require('./timeline-levels.cjs');
  const levels = readEmbeddedLevels(html), errors = validateLevels(data, levels);
  if (errors.length) throw new Error(errors.join('\n'));
  const stats = analyze(data, levels);
  if (process.argv.includes('--write')) fs.writeFileSync(htmlPath, html.replace(/<section class="findings">[\s\S]*?<\/section>/, () => render(stats)));
  console.log(JSON.stringify(stats, null, 2));
}
module.exports = {analyze, render, readData};
