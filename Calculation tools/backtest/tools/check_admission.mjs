/** Code-only Git admission defense in depth. Contextual staged review is mandatory. */
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const PROJECT = 'Calculation tools/backtest/';
const MAX_BLOB_BYTES = 32 * 1024 * 1024;
const OLE = Buffer.from('d0cf11e0a1b11ae1', 'hex');

function binaryContainer(bytes) {
  return bytes.subarray(0, 8).equals(OLE) || bytes.subarray(0, 2).equals(Buffer.from([0x1f, 0x8b]))
    || bytes.subarray(0, 2).equals(Buffer.from('PK'))
    || (bytes[0] === 0x78 && [0x01, 0x9c, 0xda].includes(bytes[1]));
}

const FIELDS = ['year', 'stock_tr', 'bond10_tr', 'tbill_tr', 'cpi_change', 'quality'];

function observation(row) {
  return row && typeof row === 'object' && Number.isInteger(row.year) && row.year >= 1800 && row.year < 2100
    && ['stock_tr', 'bond10_tr', 'cpi_change'].every(key => typeof row[key] === 'number' && Number.isFinite(row[key]))
    && (row.tbill_tr === null || (typeof row.tbill_tr === 'number' && Number.isFinite(row.tbill_tr)))
    && ['ok', 'reconstructed'].includes(row.quality);
}

function csvDataset(text) {
  // Parse RFC-style quoted fields, including doubled quotes and CRLF. Stop
  // after recognizing sixteen observations; unrelated source text is not CSV.
  text = text.replace(/^\uFEFF/, '');
  let fields = [], field = '', quoted = false, closed = false, atStart = true;
  let header = null, rows = 0;
  const complete = () => {
    fields.push(field); field = ''; closed = false; atStart = true;
    if (!header) {
      header = fields.map(value => value.trim().replace(/^\uFEFF/, ''));
      if (!FIELDS.every(key => header.includes(key))) return false;
    } else {
      if (fields.length !== header.length) return false;
      const row = Object.fromEntries(header.map((key, index) => [key, key === 'quality' ? fields[index]
        : key === 'tbill_tr' && fields[index] === '' ? null : fields[index].trim() === '' ? NaN : Number(fields[index])]));
      if (!observation(row)) return false;
      rows++;
    }
    fields = [];
    return true;
  };
  for (let i = 0; i <= text.length; i++) {
    if (!header && i > 4096) return false;
    const char = text[i];
    if (quoted) {
      if (char === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (char === '"') { quoted = false; closed = true; }
      else if (char === undefined) return false;
      else field += char;
      continue;
    }
    if (char === '"' && atStart) { quoted = true; atStart = false; }
    else if (char === ',') { fields.push(field); field = ''; closed = false; atStart = true; }
    else if (char === '\n' || char === '\r' || char === undefined) {
      if (char === '\r' && text[i + 1] === '\n') i++;
      if (char === undefined && !field && !fields.length) break;
      if (!complete()) return false;
      if (rows >= 16) return true;
    } else {
      if (closed || char === '"') return false;
      field += char; atStart = false;
    }
  }
  return false;
}

function embeddedDataset(text) {
  // Conservative fallback for copied JS object literals that are not JSON.
  // Never execute staged JS. Algorithmic generators have no materialized rows.
  const years = text.match(/"year"\s*:\s*(?:18|19|20)\d{2}\b/g) || [];
  return years.length >= 16 && FIELDS.every(key => text.includes(`"${key}"`));
}

export function inspectBlob(filename, bytes) {
  const normalized = filename.replaceAll('\\', '/');
  if (/(?:^|\/)(?:market-data\.(?:js|csv)|[^/]+\.xlsx?)$/i.test(normalized)
    || /(?:^|\/)(?:\.venv|cache|archives|exports|dist|site|builds|datasets|inputs)(?:\/|$)/i.test(normalized))
    return 'prohibited local data/runtime path';
  if (bytes.length > MAX_BLOB_BYTES) return 'oversized unreviewed blob';
  if (binaryContainer(bytes) || bytes.includes(0)) return 'binary workbook/archive or unreviewed binary';
  let text;
  try { text = new TextDecoder('utf-8', { fatal: true }).decode(bytes); }
  catch { return 'unreviewed non-UTF-8 binary'; }
  let parsed;try {parsed=JSON.parse(text);}catch { /* Source text need not be JSON. */ }
  const rows=Array.isArray(parsed)?parsed:parsed?.rows;
  if(Array.isArray(rows)&&rows.filter(observation).length>=16 || csvDataset(text) || embeddedDataset(text))return 'dataset-shaped data copy';
  return null;
}

export function checkIndex({ repoRoot, projectPrefix = PROJECT } = {}) {
  if (!repoRoot) throw new Error('An explicit repository root is required');
  const git = (...args) => execFileSync('git', args, {
    cwd: repoRoot, encoding: 'utf8', maxBuffer: MAX_BLOB_BYTES, stdio: ['ignore', 'pipe', 'pipe'],
  });
  const staged = new Set(git('diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z').split('\0').filter(Boolean));
  const records = git('ls-files', '--stage', '-z').split('\0').filter(record => {
    const filename = record.slice(record.indexOf('\t') + 1);
    return record && (filename.startsWith(projectPrefix) || staged.has(filename));
  });
  const findings = [];
  for (const record of records) {
    const matched = record.match(/^(\d+) ([a-f0-9]+) (\d)\t([\s\S]+)$/);
    if (!matched) throw new Error('Unrecognized Git index inventory');
    const [, mode, object, stage, filename] = matched;
    if (stage !== '0' || !['100644', '100755'].includes(mode)) {
      findings.push({ indexEntry: records.indexOf(record), reason: 'non-stage-zero or nonregular source object' });
      continue;
    }
    const size = Number(git('cat-file', '-s', object).trim());
    if (!Number.isSafeInteger(size) || size > MAX_BLOB_BYTES) {
      findings.push({ indexEntry: records.indexOf(record), reason: 'oversized unreviewed blob' });
      continue;
    }
    const bytes = execFileSync('git', ['cat-file', 'blob', object], {
      cwd: repoRoot, maxBuffer: MAX_BLOB_BYTES, stdio: ['ignore', 'pipe', 'pipe'],
    });
    const reason = inspectBlob(filename, bytes);
    if (reason) findings.push({ indexEntry: records.indexOf(record), reason });
  }
  return { ok: findings.length === 0, checkedFiles: records.length, findings,
    contextualReviewRequired: true };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const repoRoot = execFileSync('git', ['rev-parse', '--show-toplevel'], { encoding: 'utf8' }).trim();
    const result = checkIndex({ repoRoot });
    console.log(JSON.stringify(result));
    if (!result.ok) process.exitCode = 1;
  } catch {
    console.error('Admission inventory failed; review the Git index before proceeding.');
    process.exitCode = 1;
  }
}
