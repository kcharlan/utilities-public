'use strict';
// Data-only loading: neither require nor VM evaluation of historical JavaScript.
const path = require('node:path');
const os = require('node:os');
const SOURCE_ROOT = path.resolve(__dirname, '../..');
const REPO_ROOT = path.resolve(SOURCE_ROOT, '../..');
function dataOptions(env = process.env) {
  return {
    sourceRoot: SOURCE_ROOT, repoRoot: REPO_ROOT,
    dataHome: env.MARKET_ATLAS_DATA_HOME || path.join(os.homedir(), '.cache/market-atlas'),
    ...(env.MARKET_ATLAS_TEST_DATA_ROOT ? {dataRoot:env.MARKET_ATLAS_TEST_DATA_ROOT} : {}),
  };
}
function copyBundle(bundle) {
  return {...bundle, payload:structuredClone(bundle.payload), provenance:structuredClone(bundle.provenance),
    files:new Map([...bundle.files].map(([name,bytes]) => [name,Buffer.from(bytes)]))};
}
function createDatasetReader(options = dataOptions()) {
  const pinnedOptions = {...options, requireCurrentRecipe:true};
  let promise;
  async function verified() {
    if (!promise) promise = (async () => {
      try {
        const contract = await import('../../tools/data_contract.mjs');
        const bundle = pinnedOptions.dataRoot ? await contract.verifyBundle(pinnedOptions) : await contract.verifySelected(pinnedOptions);
        if (!bundle) throw new Error('missing');
        return bundle;
      } catch (error) {
        // Never include unknown paths, malformed payloads or data values in diagnostics.
        const kind = /stale/i.test(error.message) ? 'stale' : 'missing, corrupt or unsafe';
        throw new Error(`Verified test data is ${kind}; run npm run setup:data, then select a valid external generation with MARKET_ATLAS_TEST_DATA_ROOT or MARKET_ATLAS_DATA_HOME.`);
      }
    })();
    return promise;
  }
  return {
    async getDataset() {return copyBundle(await verified());},
    async getMarketRows() {return (await verified()).payload.rows.map(row => ({...row}));},
  };
}
// Lazy: an invented-only test can import this module without requiring history.
const reader = createDatasetReader();
module.exports = {...reader, createDatasetReader, dataOptions, SOURCE_ROOT, REPO_ROOT};
