'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function loadCoordinator() {
  // Was sliced out of index.html by comment markers and run in a VM sandbox;
  // now a plain module import.
  const { createRenderCoordinator, executeRendererRequest, createLatestWinsScheduler } = require('../views.js');
  return { createRenderCoordinator, executeRendererRequest, createLatestWinsScheduler };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

test('app shell has no remote assets and uses intentional local font stacks', () => {
  const html = fs.readFileSync(require.resolve('../index.html'), 'utf8');
  assert.doesNotMatch(html, /(?:src|href)=["']https?:\/\//i);
  assert.doesNotMatch(html, /Fraunces|Hanken Grotesk|JetBrains Mono/);
  assert.match(html, /'Iowan Old Style', 'Baskerville', 'Palatino Linotype', 'Book Antiqua', Georgia, serif/);
  assert.match(html, /'Avenir Next', 'Gill Sans', 'Trebuchet MS', sans-serif/);
  assert.match(html, /'SFMono-Regular', Menlo, Consolas, monospace/);
});

test('latest renderer commits while a slower prior renderer is discarded', async () => {
  const { createRenderCoordinator, executeRendererRequest } = loadCoordinator();
  const coordinator = createRenderCoordinator();
  const slow = deferred();
  const commits = [];

  const oldRequest = coordinator.begin();
  const oldRun = executeRendererRequest(
    coordinator,
    oldRequest,
    () => slow.promise,
    Object.freeze({ mode: 'window' }),
  );
  const newRequest = coordinator.begin();
  const newRun = executeRendererRequest(
    coordinator,
    newRequest,
    async () => () => commits.push('new'),
    Object.freeze({ mode: 'window' }),
  );

  assert.equal(oldRequest.signal.aborted, true);
  assert.equal((await newRun).committed, true);
  slow.resolve(() => commits.push('old'));
  assert.equal((await oldRun).stale, true);
  assert.deepEqual(commits, ['new']);
});

test('stale renderer rejection is suppressed while a current rejection propagates', async () => {
  const { createRenderCoordinator, executeRendererRequest } = loadCoordinator();
  const coordinator = createRenderCoordinator();
  const slow = deferred();
  const oldRequest = coordinator.begin();
  const oldRun = executeRendererRequest(
    coordinator,
    oldRequest,
    () => slow.promise,
    Object.freeze({ mode: 'sweep' }),
  );

  coordinator.begin();
  slow.reject(new Error('stale failure'));
  assert.equal((await oldRun).stale, true);

  const currentRequest = coordinator.begin();
  await assert.rejects(
    executeRendererRequest(
      coordinator,
      currentRequest,
      async () => { throw new Error('current failure'); },
      Object.freeze({ mode: 'sweep' }),
    ),
    /current failure/,
  );
});

test('rapid scheduling aborts each predecessor and coalesces to the latest frame request', async () => {
  const { createRenderCoordinator, createLatestWinsScheduler } = loadCoordinator();
  const coordinator = createRenderCoordinator();
  const frames = [];
  const runs = [];
  const schedule = createLatestWinsScheduler(
    coordinator,
    async (request) => { runs.push(request.requestId); },
    (callback) => frames.push(callback),
  );

  const first = schedule();
  const second = schedule();
  const third = schedule();
  assert.equal(first.signal.aborted, true);
  assert.equal(second.signal.aborted, true);
  assert.equal(third.signal.aborted, false);
  assert.equal(frames.length, 1);

  await frames[0]();
  assert.deepEqual(runs, [third.requestId]);
});

test('transient progress commits only for the current request and resets on every successor', async () => {
  const { createRenderCoordinator, executeRendererRequest } = loadCoordinator();
  const visibleProgress = [];
  const coordinator = createRenderCoordinator(() => visibleProgress.splice(0));
  const slow = deferred();
  let staleReport;

  const oldRequest = coordinator.begin();
  const oldRun = executeRendererRequest(
    coordinator,
    oldRequest,
    async (_snapshot, context) => {
      staleReport = context.reportProgress;
      context.reportProgress(() => visibleProgress.push('old:1'));
      await slow.promise;
      return () => visibleProgress.push('old:final');
    },
    Object.freeze({ mode: 'sweep' }),
  );
  await Promise.resolve();
  assert.deepEqual(visibleProgress, ['old:1']);

  const successor = coordinator.begin();
  assert.deepEqual(visibleProgress, [], 'a new request clears predecessor progress immediately');
  assert.equal(staleReport(() => visibleProgress.push('stale')), false);
  assert.deepEqual(visibleProgress, []);

  const successorRun = executeRendererRequest(
    coordinator,
    successor,
    async (_snapshot, context) => {
      assert.equal(context.reportProgress(() => visibleProgress.push('new:1')), true);
      return () => visibleProgress.push('new:final');
    },
    Object.freeze({ mode: 'sweep' }),
  );
  assert.equal((await successorRun).committed, true);
  slow.resolve();
  assert.equal((await oldRun).stale, true);
  assert.deepEqual(visibleProgress, ['new:1', 'new:final']);
});

test('a current renderer error clears transient progress before propagating', async () => {
  const { createRenderCoordinator, executeRendererRequest } = loadCoordinator();
  const visibleProgress = [];
  const coordinator = createRenderCoordinator(() => visibleProgress.splice(0));
  const request = coordinator.begin();

  await assert.rejects(
    executeRendererRequest(
      coordinator,
      request,
      async (_snapshot, context) => {
        context.reportProgress(() => visibleProgress.push('working'));
        throw new Error('render failed');
      },
      Object.freeze({ mode: 'sweep' }),
    ),
    /render failed/,
  );
  assert.deepEqual(visibleProgress, []);
});

test('explicit cancellation aborts the active render, clears progress, and rejects late commits', async () => {
  const { createRenderCoordinator, executeRendererRequest } = loadCoordinator();
  const visibleProgress = [];
  const coordinator = createRenderCoordinator(() => visibleProgress.splice(0));
  const slow = deferred();
  const request = coordinator.begin();
  const run = executeRendererRequest(
    coordinator,
    request,
    async (_snapshot, context) => {
      context.reportProgress(() => visibleProgress.push('heatmap 1/10'));
      await slow.promise;
      return () => visibleProgress.push('late grid');
    },
    Object.freeze({ mode: 'sweep' }),
  );
  await Promise.resolve();
  assert.deepEqual(visibleProgress, ['heatmap 1/10']);
  assert.equal(coordinator.cancelCurrent(), true);
  assert.equal(request.signal.aborted, true);
  assert.deepEqual(visibleProgress, []);
  slow.resolve();
  assert.equal((await run).stale, true);
  assert.deepEqual(visibleProgress, []);
  assert.equal(coordinator.cancelCurrent(), false);
});
