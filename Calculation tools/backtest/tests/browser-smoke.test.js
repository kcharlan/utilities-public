'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');

const { chromium } = require('@playwright/test');
const { resolveTarget, requirePrerequisites, verifyTarget, assertAllowedRequests, assertCsvDownload } = require('./helpers/browser-target.cjs');
const { loadExpected } = require('./helpers/runner.cjs');
let TARGET, APP_URL;
const activeBrowsers = new Set();
let interrupted = false;
test.before(async () => {
  if (!process.env.MARKET_ATLAS_TEST_RUNTIME_ROOT || !process.env.MARKET_ATLAS_TEST_EXPECTED_ROOT) {
    throw new Error('Independent external browser expectations are required; run npm run test:browser.');
  }
  const { safeRoot, guardDirectory } = await import('../tools/data_contract.mjs');
  const { SOURCE_ROOT, REPO_ROOT } = require('./helpers/dataset.cjs');
  if (!process.env.MARKET_ATLAS_TEST_BROWSER_TEMP) throw new Error('External owned browser temporary directory required; run npm run test:browser.');
  await safeRoot(process.env.MARKET_ATLAS_TEST_BROWSER_TEMP, {sourceRoot:SOURCE_ROOT, repoRoot:REPO_ROOT});
  await guardDirectory(process.env.MARKET_ATLAS_TEST_BROWSER_TEMP);
  const expected = await loadExpected(process.env.MARKET_ATLAS_TEST_EXPECTED_ROOT);
  TARGET = resolveTarget(process.env.MARKET_ATLAS_TEST_RUNTIME_ROOT, process.env.MARKET_ATLAS_TEST_URL, {
    expected, purpose: process.env.MARKET_ATLAS_TEST_PURPOSE,
    documentRoutes: process.env.MARKET_ATLAS_TEST_DOCUMENT_ROUTES,
  });
  APP_URL = TARGET.url;
});
async function interruptBrowser(signal) {
  interrupted = true;
  process.exitCode = signal === 'SIGINT' ? 130 : 143;
  await Promise.allSettled([...activeBrowsers].map(browser => browser.context.close()));
}
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => { void interruptBrowser(signal); });

test('cold browser frontier timing for one and three configurations', { timeout: 40_000 }, async (t) => {
  const browser = await launchChrome();
  const cdp = new CdpClient(browser.target.webSocketDebuggerUrl);
  let primaryError;
  try {
    await monitorBrowser(cdp);
    await navigate(cdp, APP_URL);
    await poll(() => cdp.evaluate(`typeof BacktestApp !== 'undefined' && document.querySelector('#strategy-select').options.length > 0`), 'benchmark application');
    await cdp.evaluate(`(() => {
      const strategy = document.querySelector('#strategy-select');
      strategy.value = 'guytonKlinger'; strategy.dispatchEvent(new Event('change', {bubbles:true}));
      BacktestApp.setMode('sweep');
    })()`);
    await poll(() => cdp.evaluate(`/Sweep view recalculated/.test(document.querySelector('#app-status-message').textContent)`), 'benchmark Sweep', 25_000);
    const single = await cdp.evaluate(`(async () => {
      const start = performance.now();
      document.querySelector('#frontier-run').click();
      while (!document.querySelector('.frontier-chart') || BacktestApp.state.stageInFlight) await new Promise(resolve => setTimeout(resolve, 5));
      return { milliseconds: performance.now() - start, points: document.querySelectorAll('.frontier-point').length };
    })()`);
    assert.equal(single.points, 25);
    t.diagnostic('Cold single GK frontier: ' + single.milliseconds.toFixed(1) + ' ms');
    assert.ok(single.milliseconds <= 1000, 'single 25-value GK frontier should complete within one second');
    await navigate(cdp, APP_URL);
    await poll(() => cdp.evaluate(`typeof BacktestApp !== 'undefined' && document.querySelector('#strategy-select').options.length > 0`), 'fresh triple benchmark application');
    await cdp.evaluate(`(() => {
      const strategy = document.querySelector('#strategy-select');
      strategy.value = 'guytonKlinger'; strategy.dispatchEvent(new Event('change', {bubbles:true}));
      const options = BacktestApp.readOptions();
      BacktestApp.state.comparisons = ['fixedReal', 'barbell'].map((strategyId, index) => ({
        id:index+1,strategyId,params:Object.fromEntries(BacktestEngine.STRATEGIES[strategyId].paramSchema.map(field=>[field.key,field.default])),options
      }));
      BacktestApp.setMode('sweep');
    })()`);
    await poll(() => cdp.evaluate(`!BacktestApp.state.stageInFlight && document.querySelectorAll('.comparison-chip').length === 3`), 'three benchmark configurations', 25_000);
    const triple = await cdp.evaluate(`(async () => {
      const start = performance.now();
      document.querySelector('#frontier-run').click();
      while (!document.querySelector('.frontier-chart') || BacktestApp.state.stageInFlight) await new Promise(resolve => setTimeout(resolve, 5));
      return { milliseconds: performance.now() - start, points: document.querySelectorAll('.frontier-point').length };
    })()`);
    assert.equal(triple.points, 75);
    const legend = await cdp.evaluate(`(() => {
      const labels = [...document.querySelectorAll('.frontier-count-label')];
      return { text:labels.map(label=>label.textContent).join(' '), fits:labels.every(label=>{const box=label.getBBox();return box.x+box.width<=1000 && box.width<=155}), identities:[...document.querySelectorAll('.frontier-point')].filter((point,index)=>index%25===0).map(point=>point.getAttribute('aria-label')) };
    })()`);
    assert.ok(legend.fits, 'all three count identities fit inside their SVG margin');
    for (const identity of ['Live · Guyton-Klinger guardrails', 'Pinned 1 · Fixed real (4% rule)', 'Pinned 2 ·']) assert.ok(legend.text.includes(identity), 'complete configuration identity is readable');
    assert.ok(legend.identities[0].startsWith('Live ·') && legend.identities[1].startsWith('Pinned 1 ·') && legend.identities[2].startsWith('Pinned 2 ·'), 'every series identifies itself in point tooltips');
    t.diagnostic('Cold GK + fixed real + barbell frontier: ' + triple.milliseconds.toFixed(1) + ' ms');
  } catch (error) {
    primaryError = error;
    throw error;
  } finally {
    await closeBrowser(browser, cdp, primaryError);
  }
});

test('frontier endpoint failure counts stay clear of complete legends at narrow and desktop widths', { timeout: 30_000 }, async (t) => {
  const browser = await launchChrome();
  const cdp = new CdpClient(browser.target.webSocketDebuggerUrl);
  let primaryError;
  const labels = ['Live · Guyton-Klinger guardrails', 'Pinned 1 · Fixed real (4% rule)', 'Pinned 2 · Barbell'];
  try {
    await monitorBrowser(cdp);
    await navigate(cdp, APP_URL);
    await poll(() => cdp.evaluate(`typeof MarketAtlasCharts !== 'undefined'`), 'chart builders');
    for (const theme of ['light', 'dark']) {
      for (const width of [720, 1200]) {
        for (const failedCount of [27, 123]) {
          const layout = await cdp.evaluate(`(() => {
            document.documentElement.dataset.theme = ${JSON.stringify(theme)};
            let figure = document.querySelector('#frontier-layout-regression');
            if (!figure) {
              figure = document.createElement('figure');
              figure.id = 'frontier-layout-regression';
              figure.className = 'sweep-figure frontier-figure';
              document.body.append(figure);
            }
            const labels = ${JSON.stringify(labels)};
            figure.innerHTML = MarketAtlasCharts.frontierSvg({
              yUnit:'dollars', yMax:40000, windowCount:123, isPercent:true,
              series:labels.map((label,index)=>({label,color:'var(--series-'+(index+1)+')',
                points:Array.from({length:25},(_,pointIndex)=>({value:.02+pointIndex*.0025,
                  worstFloor:20000,medianFloor:30000,failedCount:pointIndex===24?${failedCount}:0}))}))
            });
            const svg = figure.querySelector('svg');
            svg.style.width = '${width}px';
            const scale = svg.getBoundingClientRect().width / svg.viewBox.baseVal.width;
            const swatches = [...svg.querySelectorAll('.frontier-count-swatch')];
            const legend = [...svg.querySelectorAll('.frontier-count-label')];
            return swatches.map((swatch,index)=>{
              const baseline = Number(swatch.getAttribute('y1'))+8;
              const endpoint = svg.querySelectorAll('.frontier-point')[index*25+24];
              const count = [...svg.querySelectorAll('text')].find(text=>
                Number(text.getAttribute('y'))===baseline && text.getAttribute('x')===endpoint.getAttribute('cx'));
              const row = legend.filter(text=>Number(text.getAttribute('y'))>=baseline &&
                (!swatches[index+1] || Number(text.getAttribute('y'))<Number(swatches[index+1].getAttribute('y1'))+8));
              return {
                count:count.textContent,
                gap:swatch.getBoundingClientRect().left-Number(swatch.getAttribute('stroke-width'))*scale/2-count.getBoundingClientRect().right,
                identity:row.map(text=>text.textContent).join(' '),
                fits:row.every(text=>{const box=text.getBBox();return box.x>=0 && box.x+box.width<=1000 && box.y+box.height<=svg.viewBox.baseVal.height}),
                separated:row.every(text=>{const box=text.getBBox();return !swatches[index+1] || box.y+box.height<Number(swatches[index+1].getAttribute('y1'))})
              };
            });
          })()`);
          for (const [index, row] of layout.entries()) {
            assert.equal(row.count, String(failedCount));
            assert.ok(row.gap >= 4, `${theme} ${width}px series ${index+1} count ${failedCount}: gap ${row.gap.toFixed(2)}px must be at least 4px`);
            assert.equal(row.identity, labels[index] + ' · failed', 'complete configuration identity remains visible');
            assert.ok(row.fits, 'legend fits inside the SVG');
            assert.ok(row.separated, 'wrapped legend stays clear of the next series row');
          }
        }
      }
    }
  } catch (error) {
    primaryError = error;
    throw error;
  } finally {
    await closeBrowser(browser, cdp, primaryError);
  }
});


async function monitorBrowser(cdp) {
  await cdp.open();
  cdp.errors = [];
  cdp.requests = [];
  cdp.downloads = new Set();
  cdp.on('Runtime.consoleAPICalled', event => {
    if (event.type === 'error') cdp.errors.push('console: ' + event.args.map(arg => arg.value || arg.description).join(' '));
  });
  cdp.on('Runtime.exceptionThrown', event => cdp.errors.push('exception: ' + (event.exceptionDetails.exception?.description || event.exceptionDetails.text)));
  cdp.on('Log.entryAdded', ({entry}) => { if (entry.level === 'error') cdp.errors.push('log: ' + entry.text); });
  cdp.on('Network.requestWillBeSent', ({request}) => cdp.requests.push(request.url));
  await Promise.all(['Page.enable', 'Runtime.enable', 'Log.enable', 'Network.enable'].map(method => cdp.send(method)));
}

async function navigate(cdp, url) {
  const result = await cdp.send('Page.navigate', {url});
  assert.equal(result.errorText, undefined, 'Navigation failed: ' + (result.errorText || ''));
  await poll(() => cdp.evaluate('document.readyState === "complete" && location.href === ' + JSON.stringify(url)), 'complete tested entry');
  assert.deepEqual(await cdp.evaluate('[...document.scripts].map(script => script.src).filter(Boolean)'), TARGET.scriptUrls, 'Exact ordered resolved script URLs');
  const noticeSelector = 'a[href="' + TARGET.expected.noticePath + '"]';
  assert.equal(await cdp.evaluate('document.querySelector(' + JSON.stringify(noticeSelector) + ')?.href'), TARGET.noticeUrl, 'Expected relative notice URL');
}

async function closeBrowser(browser, cdp, primaryError) {
  const failures = [];
  try { cdp.close(); } catch (error) { failures.push(error); }
  activeBrowsers.delete(browser);
  try { await browser.context.close(); } catch (error) { failures.push(error); }
  try { fs.rmSync(browser.userDataDir, {recursive: true, force: true}); } catch (error) { failures.push(error); }
  try { assert.deepEqual(cdp.errors || [], [], 'Browser errors: ' + (cdp.errors || []).join('\n')); } catch (error) { failures.push(error); }
  try { assertAllowedRequests(TARGET, cdp.requests || [], cdp.downloads || new Set()); } catch (error) { failures.push(error); }
  if (failures.length) throw new AggregateError(primaryError ? [primaryError, ...failures] : failures, 'Browser scenario/cleanup observations failed');
}

async function collectDownload(cdp, browser, key, selector) {
  await poll(() => cdp.evaluate(`!BacktestApp.state.stageInFlight && !!BacktestApp.state.exportModels.${key} && !document.querySelector(${JSON.stringify(selector)}).disabled`), 'committed ' + key + ' export', 25_000);
  const model = await cdp.evaluate('JSON.parse(JSON.stringify(BacktestApp.state.exportModels.' + key + '))');
  assert.ok(model && model.rows.length, 'Committed export model is available');
  assert.equal(path.basename(model.filename), model.filename, 'Export filename stays inside isolated download directory');
  const file = path.join(browser.downloadDir, model.filename);
  assert.equal(fs.existsSync(file), false, 'No stale download can satisfy this export');
  await cdp.evaluate('document.querySelector(' + JSON.stringify(selector) + ').click()');
  await poll(() => fs.existsSync(file) && !fs.existsSync(file + '.crdownload'), 'complete ' + key + ' CSV download');
  assertCsvDownload(file, model);
  await poll(() => browser.downloadEvents.some(event => event.filename === model.filename), 'observed actual blob download');
  const event = browser.downloadEvents.find(event => event.filename === model.filename);
  assert.ok(event.url.startsWith('blob:'), 'Actual CSV download uses a blob URL');
  cdp.downloads.add(event.url);
  assert.equal(await cdp.evaluate('document.querySelector("#app-status-message").textContent'), 'Exported ' + model.filename + '.', 'Export status identifies the actual file');
  return model;
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function poll(operation, description, timeout = 10_000) {
  const deadline = Date.now() + timeout;
  let lastError;
  while (Date.now() < deadline) {
    if (interrupted) throw new Error('Browser matrix interrupted');
    try {
      const value = await operation();
      if (value) return value;
    } catch (error) {
      lastError = error;
    }
    await delay(25);
  }
  throw new Error(`Timed out waiting for ${description}${lastError ? `: ${lastError.message}` : ''}`);
}

function getJson(port, pathname) {
  return new Promise((resolve, reject) => {
    const request = http.get({ hostname: '127.0.0.1', port, path: pathname }, (response) => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', (chunk) => { body += chunk; });
      response.on('end', () => {
        try { resolve(JSON.parse(body)); } catch (error) { reject(error); }
      });
    });
    request.on('error', reject);
    request.setTimeout(1_000, () => request.destroy(new Error('DevTools HTTP request timed out')));
  });
}

class CdpClient {
  constructor(webSocketUrl) {
    this.socket = new WebSocket(webSocketUrl);
    this.nextId = 1;
    this.pending = new Map();
    this.listeners = new Map();
  }

  async open(timeout = 5_000) {
    if (this.socket.readyState === WebSocket.OPEN) return;
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('CDP WebSocket open timed out')), timeout);
      this.socket.addEventListener('open', () => { clearTimeout(timer); resolve(); }, { once: true });
      this.socket.addEventListener('error', () => { clearTimeout(timer); reject(new Error('CDP WebSocket failed')); }, { once: true });
    });
    this.socket.addEventListener('message', (event) => this.receive(event.data));
    this.socket.addEventListener('close', () => {
      for (const { reject, timer } of this.pending.values()) {
        clearTimeout(timer);
        reject(new Error('CDP WebSocket closed'));
      }
      this.pending.clear();
    });
  }

  receive(data) {
    const message = JSON.parse(typeof data === 'string' ? data : Buffer.from(data).toString('utf8'));
    if (message.id) {
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      clearTimeout(pending.timer);
      if (message.error) pending.reject(new Error(`${message.error.message} (${message.error.code})`));
      else pending.resolve(message.result || {});
      return;
    }
    for (const listener of this.listeners.get(message.method) || []) listener(message.params || {});
  }

  on(method, listener) {
    const listeners = this.listeners.get(method) || [];
    listeners.push(listener);
    this.listeners.set(method, listeners);
  }

  send(method, params = {}, timeout = 10_000) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${method} timed out`));
      }, timeout);
      this.pending.set(id, { resolve, reject, timer });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression, timeout = 10_000) {
    const result = await this.send('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
      userGesture: true,
    }, timeout);
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
    }
    return result.result && result.result.value;
  }

  close() {
    if (this.socket.readyState < WebSocket.CLOSING) this.socket.close();
  }
}

async function launchChrome() {
  if (interrupted) throw new Error('Browser matrix interrupted');
  const executablePath = requirePrerequisites(chromium, TARGET);
  await verifyTarget(TARGET);
  const {guardPrivateDirectory} = require('./helpers/runner.cjs');
  await guardPrivateDirectory(process.env.MARKET_ATLAS_TEST_BROWSER_TEMP);
  const userDataDir = fs.mkdtempSync(path.join(process.env.MARKET_ATLAS_TEST_BROWSER_TEMP, 'market-atlas chrome '));
  fs.chmodSync(userDataDir, 0o700);
  let context;
  try {
    await guardPrivateDirectory(userDataDir);
    // Playwright supplies the managed browser's supported launch defaults and
    // reaps its processes. All application automation still uses the original
    // CDP client and assertions below.
    context = await chromium.launchPersistentContext(userDataDir, {
      executablePath,
      headless: true,
      args: ['--remote-debugging-port=0'],
    });
    const activePortPath = path.join(userDataDir, 'DevToolsActivePort');
    const activePort = await poll(() => {
      if (!fs.existsSync(activePortPath)) return null;
      const [port] = fs.readFileSync(activePortPath, 'utf8').trim().split(/\r?\n/);
      return Number(port) || null;
    }, 'Chromium DevTools port');
    const target = await poll(async () => {
      const targets = await getJson(activePort, '/json/list');
      return targets.find(item => item.type === 'page' && item.webSocketDebuggerUrl);
    }, 'Chromium page target');
    const downloadDir = path.join(userDataDir, 'downloads');
    fs.mkdirSync(downloadDir, {mode: 0o700});
    await guardPrivateDirectory(downloadDir);
    const browser = {context, userDataDir, downloadDir, target, downloadEvents: []};
    for (const page of context.pages()) page.on('download', download => browser.downloadEvents.push({url:download.url(), filename:download.suggestedFilename()}));
    activeBrowsers.add(browser);
    if (interrupted) { await context.close(); throw new Error('Browser launch interrupted'); }
    return browser;
  } catch (error) {
    const failures = [error];
    try { if (context) await context.close(); } catch (cleanupError) { failures.push(cleanupError); }
    try { fs.rmSync(userDataDir, {recursive: true, force: true}); } catch (cleanupError) { failures.push(cleanupError); }
    if (failures.length > 1) throw new AggregateError(failures, 'Browser launch and cleanup failed');
    throw error;
  }
}

test('static app browser smoke matrix', { timeout: 90_000 }, async (t) => {
  const browser = await launchChrome();
  const cdp = new CdpClient(browser.target.webSocketDebuggerUrl);
  let primaryError;

  try {
    await monitorBrowser(cdp);
    await cdp.send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: browser.downloadDir });
    await navigate(cdp, APP_URL);

    const waitFor = (expression, description, timeout = 15_000) => poll(
      () => cdp.evaluate(expression), description, timeout,
    );
    const snapshot = (expression) => cdp.evaluate(`JSON.parse(JSON.stringify(${expression}))`);
    const setValue = (selector, value, eventType = 'input') => cdp.evaluate(`(() => {
      const control = document.querySelector(${JSON.stringify(selector)});
      control.value = ${JSON.stringify(String(value))};
      control.dispatchEvent(new Event(${JSON.stringify(eventType)}, { bubbles: true }));
      return control.value;
    })()`);
    const click = (selector) => cdp.evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);

    await waitFor(
      `document.querySelector('#window-stats .stat-value')?.textContent.startsWith('Solvent through 1 of 30')`,
      'default partial 2025 window',
    );
    const boot = await snapshot(`({
      url: location.href,
      start: document.querySelector('#start-year').value,
      horizon: document.querySelector('#horizon').value,
      engine: typeof BacktestEngine?.simulate,
      rows: MARKET_DATA?.rows?.length,
      outcome: document.querySelector('#window-stats .stat-value').textContent,
      scripts: [...document.scripts].map((script) => script.src).filter(Boolean),
    })`);
    assert.equal(boot.url, APP_URL);
    assert.equal(boot.start, '2025');
    assert.equal(boot.horizon, '30');
    assert.equal(boot.engine, 'function');
    assert.ok(boot.rows > 100);
    assert.match(boot.outcome, /Solvent through 1 of 30/);
    assert.match(await cdp.evaluate(`document.querySelector('#need-status').textContent`), /Need \$36,000 real\/yr · 90%/);
    assert.deepEqual(await cdp.evaluate(`[...document.querySelectorAll('#window-stats .stat-group-cells')].map(group => group.children.length)`), [3, 4]);
    for (const [target, groupName, lifestyleLabels] of [
      ['window-stats', 'Portfolio', ['Spending floor', 'Spending range', 'Typical year', 'Below your need']],
      ['sweep-stats', 'Solvency', ['Worst floor', 'Typical floor', 'Deepest cut', 'Lifestyle-worst start']],
    ]) {
      const unavailable = await cdp.evaluate(`(() => {
        renderUnavailableStats('no contiguous rows', '${target}');
        const element = document.getElementById('${target}');
        return { name: element.querySelector('.stat-group-label').textContent,
          labels: [...element.querySelectorAll('.lifestyle-group .stat-label')].map(cell => cell.textContent),
          values: [...element.querySelectorAll('.stat-value')].map(cell => cell.textContent),
          detail: element.querySelector('.stat-detail').textContent };
      })()`);
      assert.equal(unavailable.name, groupName);
      assert.deepEqual(unavailable.labels, lifestyleLabels);
      assert.deepEqual(unavailable.values, Array(7).fill('—'));
      assert.equal(unavailable.detail, 'no contiguous rows');
    }
    await cdp.evaluate('BacktestApp.recalculate()');
    // Every script must be a local file — the app has no network dependency.
    // Names are pinned too, so a new module is a deliberate edit here rather
    // than a silent addition, and the load order stays visible.
    assert.deepEqual(boot.scripts.map((url) => new URL(url).protocol), Array(9).fill(TARGET.protocol));
    assert.deepEqual(
      boot.scripts.map((url) => url.split('/').pop()),
      ['market-data.js', 'format.js', 'stats.js', 'views.js', 'lifestyle.js', 'charts.js', 'csv.js', 'engine.js', 'app.js'],
    );
    assert.deepEqual(boot.scripts, TARGET.scriptUrls, 'Exact ordered resolved script URLs');
    assertAllowedRequests(TARGET, cdp.requests);

    const notice = await cdp.evaluate('document.querySelector(' + JSON.stringify('a[href="' + TARGET.expected.noticePath + '"]') + ').href');
    assert.equal(notice, TARGET.noticeUrl, 'Notice link resolves relative to the tested document');
    await click('[data-theme-choice="dark"]');
    await waitFor('document.documentElement.dataset.theme === "dark"', 'dark theme');
    await cdp.send('Page.reload');
    await waitFor('typeof BacktestApp !== "undefined" && document.querySelector("#strategy-select").options.length > 0 && document.documentElement.dataset.theme === "dark"', 'reload preserves appearance');
    assert.equal(await cdp.evaluate('document.querySelector("#start-year").value'), '2025', 'Reload starts with the synthetic example controls');
    await click('[data-theme-choice="light"]');
    await waitFor('document.documentElement.dataset.theme === "light"', 'light theme');
    await click('[data-theme-choice="system"]');
    assert.equal(await cdp.evaluate('document.documentElement.hasAttribute("data-theme")'), false);

    await cdp.evaluate(`(() => {
      const values = { stock: '50', bond: '50', bill: '0' };
      for (const [asset, value] of Object.entries(values)) {
        const input = document.querySelector('#allocation-' + asset);
        input.value = value;
        input.dispatchEvent(new Event('input', { bubbles: true }));
      }
    })()`);
    await setValue('#start-year', 1966, 'change');
    await waitFor(`document.querySelector('#window-stats .stat-value')?.textContent === 'Failed · 1990'`, '1966 failure');
    const failedLifestyle = await snapshot(`({ stats: document.querySelector('#window-stats').textContent, strip: !!document.querySelector('figure.spending-strip svg'), rows: [...document.querySelectorAll('.ledger-table tbody tr')].map(row => row.textContent), filename: BacktestApp.state.exportModels.window.filename })`);
    assert.match(failedLifestyle.stats, /Spending floor\$0/);
    assert.match(failedLifestyle.stats, /depleted 1990 · 5 unfunded yrs/);
    assert.equal(failedLifestyle.strip, true);
    assert.equal(failedLifestyle.rows.length, 30);
    assert.ok(failedLifestyle.rows.slice(-5).every(row => row.includes('unfunded · $0 real spending')));
    assert.equal(failedLifestyle.filename, 'market-atlas-window-1966-1995.csv');
    await setValue('#allocation-stock', 60);
    await setValue('#allocation-bond', 40);
    await setValue('#strategy-select', 'guytonKlinger', 'change');
    await waitFor(`document.querySelector('#window-stats').textContent.includes('reached 1978 (year 13) · held 14 yrs')`, 'guardrails lifestyle');
    assert.match(await cdp.evaluate(`document.querySelector('#window-stats').textContent`), /57% of year 1/);
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
    const rangeLayout = await cdp.evaluate(`(() => { const value = document.querySelector('.spending-range-stat .stat-value'); const range = document.createRange(); range.selectNodeContents(value); return { lines: range.getClientRects().length, width: value.clientWidth, textWidth: range.getBoundingClientRect().width, font: getComputedStyle(value).fontSize }; })()`);
    assert.equal(rangeLayout.lines, 1, 'compact GK spending range fits one desktop line');
    assert.ok(rangeLayout.textWidth <= rangeLayout.width, 'spending range remains within its cell');
    assert.equal(rangeLayout.font, '16px');
    await cdp.send('Emulation.clearDeviceMetricsOverride');
    const belowBefore = await cdp.evaluate(`document.querySelectorAll('#window-stats .stat-value')[6].textContent`);
    await setValue('#need-amount', 30000);
    await waitFor(`document.querySelector('#need-percent').value === '75'`, 'dollar anchor linked percentage');
    assert.notEqual(await cdp.evaluate(`document.querySelectorAll('#window-stats .stat-value')[6].textContent`), belowBefore);
    await setValue('#need-amount', -1);
    assert.equal(await cdp.evaluate(`document.querySelector('#need-amount').getAttribute('aria-invalid')`), 'true');
    assert.deepEqual(await snapshot(`BacktestApp.state.need`), {anchor:'dollars',amount:30000});
    await setValue('#need-amount', 30000);
    await setValue('#strategy-select', 'fixedReal', 'change');
    await setValue('[data-param-key="initialRate"]', 5);
    await waitFor(`document.querySelector('#need-percent').value === '60'`, 'dollars hold with new rate');
    await setValue('#need-percent', 90);
    await waitFor(`document.querySelector('#need-amount').value === '45000'`, 'percentage resolves new baseline');
    await setValue('[data-param-key="initialRate"]', 4);
    await waitFor(`document.querySelector('#need-amount').value === '36000'`, 'percentage follows rate');
    await setValue('#need-percent', 201);
    assert.equal(await cdp.evaluate(`document.querySelector('#need-percent').getAttribute('aria-invalid')`), 'true');
    assert.deepEqual(await snapshot(`BacktestApp.state.need`), { anchor: 'percent', ratio: .9 });
    await setValue('#need-percent', 90);
    await cdp.evaluate(`document.querySelector('#need-amount').focus()`);
    await setValue('[data-param-key="initialRate"]', 5);
    await waitFor(`document.querySelector('#need-status').textContent.includes('$45,000')`, 'focused linked field readout');
    assert.equal(await cdp.evaluate(`document.querySelector('#need-amount').value`), '36000', 'focused linked field is preserved');
    await cdp.evaluate(`document.querySelector('#need-amount').blur()`);
    await setValue('[data-param-key="initialRate"]', 0);
    await waitFor(`document.querySelector('#need-amount').value === ''`, 'zero baseline has no percentage-derived dollar need');
    assert.doesNotMatch(await cdp.evaluate(`document.querySelector('#need-status').textContent`), /NaN|Infinity/);
    assert.equal(await cdp.evaluate(`BacktestApp.state.exportModels.window.rows[0].withdrawal_real_pct_of_year1`), null);
    await setValue('[data-param-key="initialRate"]', 4);
    await waitFor(`document.querySelector('#need-amount').value === '36000'`, 'baseline restored');
    for (const width of [1280, 390]) {
      await cdp.send('Emulation.setDeviceMetricsOverride', { width, height: 900, deviceScaleFactor: 1, mobile: false });
      const columns = await cdp.evaluate(`[...document.querySelectorAll('#window-stats .stat-group-cells')].map(group => getComputedStyle(group).gridTemplateColumns.split(' ').length)`);
      assert.deepEqual(columns, width === 390 ? [2, 2] : [3, 4]);
      assert.equal(await cdp.evaluate(`document.documentElement.scrollWidth <= innerWidth`), true, 'page has no horizontal overflow');
    }
    await cdp.send('Emulation.clearDeviceMetricsOverride');
    await setValue('#allocation-stock', 50);
    await setValue('#allocation-bond', 50);
    await setValue('#start-year', 1975, 'change');
    await waitFor(`document.querySelector('#window-stats .stat-value')?.textContent === 'Survived'`, '1975 survival');
    const realView = await snapshot(`({
      terminal: document.querySelectorAll('#window-stats .stat-value')[1].textContent,
      end: document.querySelector('.balance-chart').dataset.endTotal,
      header: document.querySelector('.ledger-table thead').textContent,
    })`);
    await click('[data-display="nominal"]');
    await waitFor(`document.querySelector('.balance-chart').dataset.endTotal !== ${JSON.stringify(realView.end)}`, 'nominal chart render');
    const nominalView = await snapshot(`({
      terminal: document.querySelectorAll('#window-stats .stat-value')[1].textContent,
      end: document.querySelector('.balance-chart').dataset.endTotal,
      header: document.querySelector('.ledger-table thead').textContent,
    })`);
    assert.equal(nominalView.terminal, realView.terminal, 'terminal statistic remains real');
    assert.notEqual(nominalView.end, realView.end, 'chart endpoint changes display basis');
    assert.match(realView.header, /Total · real/);
    assert.match(nominalView.header, /Total · nominal/);

    await click('#sweep-tab');
    await waitFor(`document.querySelector('#sweep-stats .stat-value')?.textContent === '92.8%' && document.querySelector('.heatmap-table')`, 'modern sweep render', 25_000);
    const sweep = await snapshot(`({
      survived: document.querySelector('#sweep-stats .stat-detail').textContent,
      stats: document.querySelector('#sweep-stats').textContent,
      chartTitle: document.querySelector('.sweep-chart title').textContent,
      heatmapMetric: document.querySelector('#heatmap-metric').value,
      cellCount: document.querySelectorAll('[data-heatmap-cell]').length,
      safeFloorRow: [...document.querySelectorAll('.sweep-table tr')].find((row) => /Minimum sustainable rate/.test(row.textContent))?.textContent || '',
    })`);
    assert.match(sweep.survived, /64 of 69 complete windows/);
    assert.match(sweep.stats, /1966/);
    assert.match(sweep.chartTitle, /Sustainable withdrawal rate by start year/);
    assert.equal(sweep.heatmapMetric, 'success');
    assert.equal(sweep.cellCount, 98 * 12);
    assert.match(sweep.safeFloorRow, /3\.67%/);

    assert.match(sweep.stats, /Worst floor/);
    assert.match(sweep.stats, /5 failed · earliest 1964 start/);
    await setValue('#sweep-chart-metric', 'spending', 'change');
    await waitFor(`/Real spending range/.test(document.querySelector('.sweep-chart title')?.textContent || '')`, 'spending range sweep');
    assert.equal(await cdp.evaluate(`document.querySelector('.sweep-chart').closest('.sweep-chart-scroll').parentElement.className`), 'sweep-figure');
    const spendingYear = await cdp.evaluate(`(() => { const point = document.querySelector('.sweep-point rect') || document.querySelector('rect.sweep-point'); const year = point.closest('.sweep-point').dataset.startYear; point.dispatchEvent(new MouseEvent('click', { bubbles: true })); return year; })()`);
    await waitFor(`!document.querySelector('#window-mode').hidden && document.querySelector('#start-year').value === ${JSON.stringify(spendingYear)}`, 'spending range click-through');
    await click('#sweep-tab');
    await waitFor(`/Real spending range/.test(document.querySelector('.sweep-chart title')?.textContent || '')`, 'spending sweep restored');
    await setValue('#heatmap-metric', 'floor', 'change');
    await waitFor(`/floor \\$/i.test(document.querySelector('[data-heatmap-cell]')?.getAttribute('aria-label') || '') && [...document.querySelectorAll('.heatmap-table thead th')].some(th => th.textContent === 'Worst')`, 'floor heatmap');
    assert.equal(await cdp.evaluate(`document.querySelectorAll('[data-heatmap-cell]').length`), 98 * 12);
    await setValue('#sweep-chart-metric', 'auto', 'change');
    await setValue('#heatmap-metric', 'success', 'change');
    await waitFor(`/Sustainable withdrawal rate/.test(document.querySelector('.sweep-chart title')?.textContent || '') && /Survived|Failed/.test(document.querySelector('[data-heatmap-cell]')?.getAttribute('aria-label') || '')`, 'automatic chart and success heatmap restored');

    const focusBefore = await cdp.evaluate(`(() => {
      const cell = document.querySelector('[data-heatmap-cell][tabindex="0"]');
      cell.focus();
      cell.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
      return { before: cell.dataset.heatmapColumn, after: document.activeElement.dataset.heatmapColumn };
    })()`);
    assert.equal(Number(focusBefore.after), Number(focusBefore.before) + 1);

    await cdp.evaluate(`document.querySelector('[data-start-year="1966"][data-horizon="30"]').click()`);
    await waitFor(`!document.querySelector('#window-mode').hidden && document.querySelector('#start-year').value === '1966' && document.querySelector('#horizon').value === '30' && document.querySelector('#window-stats .stat-value')?.textContent === 'Failed · 1990'`, 'heatmap click-through');

    await Promise.all([
      setValue('#allocation-stock', 50),
      setValue('#allocation-bond', 30),
      setValue('#allocation-bill', 20),
    ]);
    await setValue('#strategy-select', 'barbell', 'change');
    await waitFor(`document.querySelector('#allocation-stock').disabled && /managed/i.test(document.querySelector('#allocation-status').textContent)`, 'managed barbell allocation');
    const managed = await snapshot(`([...document.querySelectorAll('[data-allocation]')].map((input) => ({ disabled: input.disabled, value: input.value })))`);
    assert.ok(managed.every((item) => item.disabled));
    await setValue('#strategy-select', 'fixedReal', 'change');
    await waitFor(`![...document.querySelectorAll('[data-allocation]')].some((input) => input.disabled) && document.querySelector('#allocation-stock').value === '50'`, 'manual allocation restoration');
    assert.deepEqual(await snapshot(`([...document.querySelectorAll('[data-allocation]')].map((input) => input.value))`), ['50', '30', '20']);

    assert.equal(await cdp.evaluate(`document.querySelector('#export-window-csv').disabled`), false);
    const windowDownload = await collectDownload(cdp, browser, 'window', '#export-window-csv');
    assert.equal(windowDownload.rows.length, 30);
    assert.ok(windowDownload.rows.every(row => row.need_real === 36000), 'Window CSV retains the accepted synthetic need');
    await waitFor(`/^Exported market-atlas-window-1966-\\d{4}\\.csv\.$/.test(document.querySelector('#app-status-message').textContent)`, 'window export status');

    await click('#sweep-tab');
    await waitFor(`document.querySelector('.heatmap-table') && document.querySelector('#sweep-progress').hidden`, 'restored fixed-real sweep', 25_000);
    const curveDownload = await collectDownload(cdp, browser, 'sweepCurve', '#export-sweep-curve-csv');
    assert.equal(curveDownload.rows.length, 98);
    assert.ok(curveDownload.rows.every(row => row.strategy_id === 'fixedReal' && row.need_real === 36000), 'Curve CSV identifies the accepted synthetic configuration');
    const heatmapDownload = await collectDownload(cdp, browser, 'sweepHeatmap', '#export-sweep-heatmap-csv');
    assert.equal(heatmapDownload.rows.length, 98 * 12);
    assert.ok(heatmapDownload.rows.every(row => row.metric === 'success'), 'Heatmap CSV matches the committed metric');
    await setValue('#strategy-select', 'guytonKlinger', 'change');
    await waitFor(`document.querySelector('.heatmap-table') && document.querySelector('#sweep-progress').hidden && document.querySelector('#comparison-tray').textContent.includes('Guyton')`, 'Guyton-Klinger committed sweep', 30_000);
    const committedGrid = await cdp.evaluate(`document.querySelector('.heatmap-table').outerHTML`);
    await setValue('#heatmap-metric', 'safe', 'change');
    await waitFor(`!document.querySelector('#sweep-progress').hidden && /heatmap/i.test(document.querySelector('#sweep-progress').textContent) && !document.querySelector('#cancel-heatmap').hidden`, 'adaptive heatmap progress', 30_000);
    await click('#cancel-heatmap');
    await waitFor(`/cancelled/.test(document.querySelector('#app-status-message').textContent) && document.querySelector('#sweep-progress').hidden`, 'adaptive heatmap cancellation');
    assert.equal(await cdp.evaluate(`document.querySelector('.heatmap-table').outerHTML`), committedGrid, 'cancel preserves committed heatmap');

    await setValue('#heatmap-metric', 'success', 'change');
    await waitFor(`/Sweep view recalculated/.test(document.querySelector('#app-status-message').textContent)`, 'success sweep committed after cancellation');
    await click('#frontier-run');
    await waitFor(`document.querySelector('.frontier-figure svg') && document.querySelector('#sweep-progress').hidden`, 'default frontier');
    assert.ok(await cdp.evaluate(`document.querySelectorAll('.frontier-point').length >= 25`));
    assert.equal(await cdp.evaluate(`BacktestApp.state.frontier.override`), null, 'untouched default step remains an implicit default');
    const committedFrontier = await cdp.evaluate(`document.querySelector('.frontier-figure svg').outerHTML`);
    await setValue('#frontier-from', 2);
    await setValue('#frontier-to', 6);
    await setValue('#frontier-step', .1);
    await click('#frontier-run');
    await waitFor(`!document.querySelector('#sweep-progress').hidden && /frontier values/.test(document.querySelector('#sweep-progress').textContent)`, 'frontier progress');
    await click('#cancel-heatmap');
    assert.equal(await cdp.evaluate(`document.querySelector('.frontier-figure svg').outerHTML`), committedFrontier, 'frontier cancellation preserves its committed SVG');
    assert.equal(await cdp.evaluate(`document.querySelector('#export-sweep-curve-csv').disabled || document.querySelector('#export-sweep-heatmap-csv').disabled`), false, 'frontier cancellation preserves both Sweep exports');
    assert.match(await cdp.evaluate(`document.querySelector('#app-status-message').textContent`), /Frontier calculation cancelled/);

    await setValue('#frontier-step', .25);
    await click('#frontier-run');
    assert.match(await cdp.evaluate(`document.querySelector('#app-status-message').textContent`), /increment/, 'explicit default step must obey the parameter increment');
    assert.equal(await cdp.evaluate(`document.querySelector('.frontier-chart').outerHTML`), committedFrontier);
    await cdp.evaluate(`(() => {
      const field = document.querySelector('#frontier-step');
      field.value = '.1'; field.dispatchEvent(new Event('input', {bubbles:true}));
      document.querySelector('#frontier-run').click();
      field.value = '.2'; field.dispatchEvent(new Event('input', {bubbles:true}));
      document.querySelector('#frontier-run').click();
    })()`);
    await waitFor(`!BacktestApp.state.stageInFlight && /Frontier calculated/.test(document.querySelector('#app-status-message').textContent)`, 'latest frontier request committed');
    assert.equal(await cdp.evaluate(`document.querySelectorAll('.frontier-point').length`), 21, 'superseded 41-value request cannot overwrite the 21-value frontier');
    await cdp.evaluate(`BacktestApp.cancelCurrentRender()`);
    assert.equal(await cdp.evaluate(`document.querySelector('#export-sweep-curve-csv').disabled || document.querySelector('#export-sweep-heatmap-csv').disabled`), false, 'cancel with no stage in flight cannot invalidate committed Sweep exports');

    const beforeAutoFrontier = await cdp.evaluate(`document.querySelector('.frontier-chart').outerHTML`);
    await setValue('#fee-rate', .1);
    await waitFor(`BacktestApp.state.stageInFlight === 'frontier' && !document.querySelector('#sweep-progress').hidden`, 'automatic frontier following changed Sweep', 25_000);
    await click('#cancel-heatmap');
    assert.equal(await cdp.evaluate(`document.querySelector('.frontier-chart')?.outerHTML || ''`), beforeAutoFrontier, 'cancelled automatic recompute preserves the frontier across the Sweep commit');
    assert.equal(await cdp.evaluate(`document.querySelector('#export-sweep-curve-csv').disabled || document.querySelector('#export-sweep-heatmap-csv').disabled`), false, 'cancelled automatic frontier keeps refreshed Sweep exports');

    assert.deepEqual(await cdp.evaluate(`['from','to','step'].map(key => document.querySelector('label[for="frontier-' + key + '"]').textContent)`), ['From (%)','To (%)','Step (%)']);
    await setValue('#frontier-param', 'preservationCutoffYears', 'change');
    assert.equal(await cdp.evaluate(`document.querySelector('label[for="frontier-from"]').textContent`), 'From', 'numeric years have no percentage unit');
    await setValue('#frontier-param', '__each__', 'change');
    for (const theme of ['dark', 'light']) {
      await click(`[data-theme-choice="${theme}"]`);
      await waitFor(`!BacktestApp.state.stageInFlight && /Frontier calculated/.test(document.querySelector('#app-status-message').textContent)`, 'themed frontier commit');
      const styled = await cdp.evaluate(`(() => {
        const input = getComputedStyle(document.querySelector('#frontier-from'));
        const reference = getComputedStyle(document.querySelector('#sweep-horizon'));
        return {background:input.backgroundColor,expectedBackground:reference.backgroundColor,color:input.color,expectedColor:reference.color,heading:!!document.querySelector('.frontier-figure .chart-heading h4'),button:document.querySelector('#frontier-run').classList.contains('small-button'),caption:document.querySelector('.frontier-body figcaption').classList.contains('chart-caveat')};
      })()`);
      assert.equal(styled.background, styled.expectedBackground, `${theme} frontier input uses the shared field surface`);
      assert.equal(styled.color, styled.expectedColor, `${theme} frontier input uses the shared ink`);
      assert.ok(styled.heading && styled.button && styled.caption, 'frontier uses the neighboring figure typography and controls');

      for (const width of [1280, 390, 320]) {
        await cdp.send('Emulation.setDeviceMetricsOverride', { width, height: 844, deviceScaleFactor: 1, mobile: true });
        const responsive = await snapshot(`({
          documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
          internalScroller: [...document.querySelectorAll('.heatmap-scroll, .sweep-chart-scroll, .ledger-table-wrap')]
            .some((element) => element.scrollWidth > element.clientWidth),
        })`);
        assert.equal(responsive.documentFits, true, `${width}px document must not overflow horizontally`);
        assert.equal(responsive.internalScroller, true, `${width}px wide results must scroll internally`);
      }
    }
    await cdp.send('Emulation.clearDeviceMetricsOverride');

    await setValue('#heatmap-metric', 'safe', 'change');
    await waitFor(`BacktestApp.state.stageInFlight === 'sweep' && !document.querySelector('#sweep-progress').hidden && /heatmap/.test(document.querySelector('#sweep-progress').textContent)`, 'Sweep owns shared progress with a visible frontier', 25_000);
    assert.equal(await cdp.evaluate(`document.querySelector('#frontier-run').disabled`), true, 'manual frontier computation waits until Sweep commits');
    await click('#frontier-run');
    assert.equal(await cdp.evaluate(`BacktestApp.state.stageInFlight`), 'sweep', 'Compute cannot replace the active Sweep owner');
    await click('#cancel-heatmap');
    assert.match(await cdp.evaluate(`document.querySelector('#app-status-message').textContent`), /Heatmap calculation cancelled/);
    assert.equal(await cdp.evaluate(`BacktestApp.state.stageInFlight`), null);
    assert.equal(await cdp.evaluate(`document.querySelector('#frontier-run').disabled`), false, 'cancel restores the committed frontier control');
    const beforeFreshSweep = await cdp.evaluate(`document.querySelector('.frontier-chart').outerHTML`);
    await setValue('#heatmap-metric', 'success', 'change');
    await setValue('#fee-rate', .2);
    await waitFor(`!BacktestApp.state.stageInFlight && /Frontier calculated/.test(document.querySelector('#app-status-message').textContent) && document.querySelector('#comparison-tray').textContent.includes('Fee: 0.2%')`, 'fresh successful Sweep automatically computes its visible frontier', 25_000);
    assert.notEqual(await cdp.evaluate(`document.querySelector('.frontier-chart').outerHTML`), beforeFreshSweep, 'automatic frontier uses the newly committed portfolio input');
    assert.equal(await cdp.evaluate(`document.querySelector('#export-sweep-curve-csv').disabled || document.querySelector('#export-sweep-heatmap-csv').disabled`), false);

    await setValue('#sweep-horizon', 31);
    await waitFor(`BacktestApp.state.stageInFlight === 'sweep' && !document.querySelector('#sweep-progress').hidden`, 'Sweep pending while frontier Hide remains available', 25_000);
    await click('#frontier-hide');
    assert.equal(await cdp.evaluate(`BacktestApp.state.stageInFlight`), 'sweep', 'Hide preserves the useful ongoing Sweep');
    await waitFor(`!BacktestApp.state.stageInFlight && /Sweep view recalculated/.test(document.querySelector('#app-status-message').textContent)`, 'Sweep commits after frontier hidden', 25_000);
    assert.deepEqual(await snapshot(`({visible:BacktestApp.state.frontier.visible,bodyHidden:document.querySelector('.frontier-body').hidden,hideHidden:document.querySelector('#frontier-hide').hidden,run:document.querySelector('#frontier-run').textContent})`), {visible:false,bodyHidden:true,hideHidden:true,run:'Compute frontier'}, 'Sweep cannot resurrect a frontier hidden after its snapshot');
    assert.equal(await cdp.evaluate(`document.querySelector('#export-sweep-curve-csv').disabled || document.querySelector('#export-sweep-heatmap-csv').disabled`), false, 'hidden frontier does not prevent refreshed exports');

    await setValue('#frontier-param', 'adjustment', 'change');
    assert.deepEqual(await cdp.evaluate(`['from','to','step'].map(key=>document.querySelector('#frontier-'+key).value)`), ['5','15','1'], 'displayed fallback fields match the model lattice');
    await setValue('#frontier-param', 'preservationCutoffYears', 'change');
    assert.deepEqual(await cdp.evaluate(`['from','to','step'].map(key=>document.querySelector('#frontier-'+key).value)`), ['0','30','1'], 'displayed cutoff fields use explicit integer metadata');
    await click('#frontier-run');
    await waitFor(`!BacktestApp.state.stageInFlight && /Frontier calculated/.test(document.querySelector('#app-status-message').textContent)`, 'GK-specific numeric frontier');
    assert.equal(await cdp.evaluate(`document.querySelectorAll('.frontier-point').length`), 31);
    assert.equal(await cdp.evaluate(`BacktestApp.state.frontier.override`), null, 'untouched integer metadata remains implicit');
    await setValue('#frontier-from', 1);
    await click('#frontier-run');
    await waitFor(`!BacktestApp.state.stageInFlight && document.querySelectorAll('.frontier-point').length === 30`, 'explicit cutoff override before strategy reset');
    await cdp.evaluate(`(() => {
      const configuration = {strategyId:'fixedReal',params:{initialRate:.04},options:BacktestApp.readOptions()};
      BacktestApp.applyConfigurationToControls(configuration);
      BacktestApp.recalculate();
    })()`);
    await waitFor(`!BacktestApp.state.stageInFlight`, 'configuration-applier strategy change committed', 25_000);
    assert.equal(await cdp.evaluate(`BacktestApp.state.frontier.paramKey`), null, 'applying another strategy resets the strategy-specific frontier key');
    assert.equal(await cdp.evaluate(`BacktestApp.state.frontier.override`), null);
    assert.match(await cdp.evaluate(`document.querySelector('#app-status-message').textContent`), /Frontier calculated/, 'the visible frontier recomputes using the applied strategy default');

  } catch (error) {
    primaryError = error;
    throw error;
  } finally {
    await closeBrowser(browser, cdp, primaryError);
  }
});
