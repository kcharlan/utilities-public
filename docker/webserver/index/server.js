import Fastify from 'fastify';
import replyFrom from '@fastify/reply-from';
import fs from 'fs/promises';
import path from 'path';
import crypto from 'node:crypto';
import { load as loadHTML } from 'cheerio';

const WEBROOT = process.env.WEBROOT || '/mnt/webroot';
const CONFIG_ROOT = process.env.CONFIG_ROOT || '/mnt/config';
const CONFIG_FILE = process.env.CONFIG_FILE || path.join(CONFIG_ROOT, 'endpoints.json');
const HOST_GATEWAY = process.env.HOST_DOCKER_GATEWAY || 'host.docker.internal';
const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1']);
const CLIENT_HINT_TTL_MS = 1000 * 60 * 5;
const clientEndpointHints = new Map();
const RESERVED_PREFIXES = ['/files', '/configure', '/api/py', '/api/node'];
const DATE_FORMATTER = new Intl.DateTimeFormat('en-US', {
  year: 'numeric',
  month: 'short',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit'
});

class ConfigError extends Error {
  constructor(message, statusCode = 400) {
    super(message);
    this.name = 'ConfigError';
    this.statusCode = statusCode;
  }
}

class EndpointStore {
  constructor(filePath) {
    this.filePath = filePath;
    this.data = { endpoints: [], updatedAt: new Date().toISOString() };
  }

  async init() {
    await fs.mkdir(path.dirname(this.filePath), { recursive: true });
    try {
      const raw = await fs.readFile(this.filePath, 'utf8');
      const parsed = JSON.parse(raw);
      if (!parsed || !Array.isArray(parsed.endpoints)) {
        throw new Error('Invalid schema');
      }
      this.data = {
        endpoints: parsed.endpoints.map((endpoint) => this.#sanitizeStoredEndpoint(endpoint)),
        updatedAt: parsed.updatedAt || new Date().toISOString()
      };
      this.#sort();
    } catch (err) {
      if (err.code !== 'ENOENT') {
        console.warn('[configure] Failed to read config, recreating:', err.message);
      }
      await this.#persist();
    }
  }

  list() {
    return this.data.endpoints;
  }

  getById(id) {
    return this.data.endpoints.find((ep) => ep.id === id);
  }

  match(pathname) {
    const cleanPath = normalizeRequestPath(pathname);
    for (const endpoint of this.data.endpoints) {
      if (!endpoint.enabled) continue;
      if (pathMatches(cleanPath, endpoint.path)) {
        const remainder = cleanPath.length === endpoint.path.length
          ? ''
          : cleanPath.slice(endpoint.path.length);
        return { endpoint, remainder };
      }
    }
    return null;
  }

  async create(payload) {
    const normalized = this.#normalizePayload(payload);
    this.#ensurePathAvailable(normalized.path);
    const now = new Date().toISOString();
    const entry = {
      id: crypto.randomUUID(),
      name: normalized.name,
      path: normalized.path,
      target: normalized.target,
      stripPath: normalized.stripPath,
      enabled: normalized.enabled,
      notes: normalized.notes,
      createdAt: now,
      updatedAt: now
    };
    this.data.endpoints.push(entry);
    this.#sort();
    await this.#persist();
    return entry;
  }

  async update(id, payload) {
    const existing = this.getById(id);
    if (!existing) {
      throw new ConfigError('Endpoint not found.', 404);
    }
    const normalized = this.#normalizePayload(payload);
    this.#ensurePathAvailable(normalized.path, id);
    Object.assign(existing, normalized, { updatedAt: new Date().toISOString() });
    this.#sort();
    await this.#persist();
    return existing;
  }

  async delete(id) {
    const idx = this.data.endpoints.findIndex((ep) => ep.id === id);
    if (idx === -1) {
      throw new ConfigError('Endpoint not found.', 404);
    }
    this.data.endpoints.splice(idx, 1);
    await this.#persist();
  }

  #sanitizeStoredEndpoint(endpoint) {
    return {
      id: endpoint.id || crypto.randomUUID(),
      name: String(endpoint.name || 'Untitled').trim() || 'Untitled Endpoint',
      path: normalizePrefix(endpoint.path || '/placeholder'),
      target: normalizeTarget(endpoint.target || 'http://example.com'),
      stripPath: Boolean(endpoint.stripPath ?? true),
      enabled: endpoint.enabled !== false,
      notes: typeof endpoint.notes === 'string' ? endpoint.notes : '',
      createdAt: endpoint.createdAt || new Date().toISOString(),
      updatedAt: endpoint.updatedAt || new Date().toISOString()
    };
  }

  #normalizePayload(payload) {
    if (!payload || typeof payload !== 'object') {
      throw new ConfigError('Invalid payload.');
    }
    const name = String(payload.name ?? '').trim();
    if (!name) {
      throw new ConfigError('Name is required.');
    }
    const normalizedPath = normalizePrefix(payload.path ?? '');
    if (!normalizedPath || normalizedPath === '/') {
      throw new ConfigError('Path must start with "/" and cannot be root.');
    }
    if (RESERVED_PREFIXES.some((prefix) => normalizedPath === prefix || normalizedPath.startsWith(prefix + '/'))) {
      throw new ConfigError('Path conflicts with a reserved route.');
    }
    const target = normalizeTarget(payload.target ?? '');
    const stripPath = payload.stripPath !== false;
    const enabled = payload.enabled !== false;
    const notes = typeof payload.notes === 'string' ? payload.notes.trim() : '';
    return { name, path: normalizedPath, target, stripPath, enabled, notes };
  }

  #ensurePathAvailable(pathValue, ignoreId) {
    const clash = this.data.endpoints.find((ep) => ep.path === pathValue && ep.id !== ignoreId);
    if (clash) {
      throw new ConfigError('Another endpoint already uses that path.');
    }
  }

  #sort() {
    this.data.endpoints.sort((a, b) => {
      if (a.path.length === b.path.length) {
        return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
      }
      return b.path.length - a.path.length;
    });
  }

  async #persist() {
    this.data.updatedAt = new Date().toISOString();
    const tmpPath = `${this.filePath}.tmp`;
    await fs.writeFile(tmpPath, JSON.stringify(this.data, null, 2));
    await fs.rename(tmpPath, this.filePath);
  }
}

function normalizePrefix(input) {
  let value = String(input || '').trim();
  if (!value.startsWith('/')) {
    value = `/${value}`;
  }
  value = value.replace(/\/+/g, '/');
  if (value.length > 1 && value.endsWith('/')) {
    value = value.replace(/\/+$/, '');
  }
  return value;
}

function normalizeTarget(input) {
  const raw = String(input || '').trim();
  if (!raw) {
    throw new ConfigError('Target URL is required.');
  }
  let url;
  try {
    url = new URL(raw);
  } catch {
    throw new ConfigError('Target URL must be absolute (include http/https).');
  }
  if (!['http:', 'https:'].includes(url.protocol)) {
    throw new ConfigError('Only http:// or https:// targets are supported.');
  }
  url.hash = '';
  url.search = '';
  if (url.pathname.length > 1 && url.pathname.endsWith('/')) {
    url.pathname = url.pathname.replace(/\/+$/, '');
  }
  return url.toString();
}

function normalizeRequestPath(pathname) {
  if (!pathname) return '/';
  if (!pathname.startsWith('/')) {
    return `/${pathname}`;
  }
  return pathname;
}

function pathMatches(requestPath, prefix) {
  return requestPath === prefix || requestPath.startsWith(`${prefix}/`);
}

function buildUpstreamUrl(endpoint, remainder, rawUrl) {
  const original = new URL(rawUrl, 'http://localhost');
  const suffix = endpoint.stripPath ? (remainder || '/') : original.pathname;
  const targetUrl = new URL(endpoint.target);
  remapLoopbackHost(targetUrl);
  targetUrl.pathname = joinPaths(targetUrl.pathname, suffix);
  targetUrl.search = original.search;
  return targetUrl.toString();
}

function joinPaths(basePath, extraPath) {
  const base = basePath === '/' ? '' : basePath.replace(/\/+$/, '');
  const extra = !extraPath || extraPath === '/' ? '' : extraPath.replace(/^\/+/, '');
  if (!base && !extra) {
    return '/';
  }
  if (!base) {
    return `/${extra}`;
  }
  if (!extra) {
    return base;
  }
  return `${base}/${extra}`;
}

function remapLoopbackHost(url) {
  if (!HOST_GATEWAY) return;
  if (LOOPBACK_HOSTS.has(url.hostname)) {
    url.hostname = HOST_GATEWAY;
  }
}

async function ensureFileBrowserDir(reqPath) {
  const reqPathname = decodeURIComponent(reqPath || '');
  const fsPath = path.join(WEBROOT, reqPathname);
  let stat;
  try {
    stat = await fs.stat(fsPath);
  } catch {
    return WEBROOT;
  }
  return stat.isDirectory() ? fsPath : WEBROOT;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (ch) => {
    switch (ch) {
      case '&': return '&amp;';
      case '<': return '&lt;';
      case '>': return '&gt;';
      case '"': return '&quot;';
      case '\'': return '&#39;';
      default: return ch;
    }
  });
}

function formatBytes(bytes) {
  if (bytes == null) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB', 'PB'];
  let size = bytes;
  let unit = 'B';
  for (const next of units) {
    const value = size / 1024;
    if (value < 1) break;
    size = value;
    unit = next;
  }
  return `${size.toFixed(size >= 10 ? 0 : 1)} ${unit}`;
}

function formatDate(date) {
  if (!date) return '—';
  return DATE_FORMATTER.format(date);
}

function buildHref(parts, { trailingSlash = false } = {}) {
  const encoded = parts.map((part) => encodeURIComponent(part)).join('/');
  if (!encoded) {
    return trailingSlash ? '/files' : '/';
  }
  const base = `/${encoded}`;
  return trailingSlash ? `${base}/` : base;
}

function describeType(item) {
  if (item.type === 'dir') return 'Folder';
  if (!item.ext) return 'File';
  const label = item.ext.replace('.', '').toUpperCase();
  return label || 'File';
}

async function inferTitle(filePath, fileName) {
  try {
    const data = await fs.readFile(filePath, 'utf8');
    const $ = loadHTML(data);
    const t = $('title').first().text().trim();
    return t || fileName;
  } catch {
    return fileName;
  }
}

async function scanDir(dir) {
  const entries = await fs.readdir(dir, { withFileTypes: true });
  const visible = entries.filter((entry) => !entry.name.startsWith('.'));
  const items = await Promise.all(visible.map(async (entry) => {
    const full = path.join(dir, entry.name);
    const stat = await fs.stat(full);
    if (entry.isDirectory()) {
      return { type: 'dir', name: entry.name, mtime: stat.mtime };
    }
    const ext = path.extname(entry.name).toLowerCase();
    let title = entry.name;
    if (ext === '.html' || ext === '.htm') {
      title = await inferTitle(full, entry.name);
    }
    return { type: 'file', name: entry.name, title, ext, size: stat.size, mtime: stat.mtime };
  }));

  items.sort((a, b) => {
    if (a.type !== b.type) return a.type === 'dir' ? -1 : 1;
    const labelA = a.title || a.name;
    const labelB = b.title || b.name;
    return labelA.localeCompare(labelB, undefined, { sensitivity: 'base' });
  });
  return items;
}

function renderConfigureHtml(payload) {
  const initialState = JSON.stringify(payload).replace(/</g, '\\u003c');
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Configure · Local Web Server</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg: #eef2ff;
      --surface: rgba(255,255,255,0.93);
      --text: #0f172a;
      --text-strong: #0f172a;
      --muted: #64748b;
      --accent: #2563eb;
      --border: rgba(15,23,42,0.08);
      --row-border: rgba(15,23,42,0.08);
      --row-hover: rgba(37,99,235,0.08);
      --danger: #f43f5e;
      --success: #16a34a;
      --input-bg: rgba(255,255,255,0.92);
      --input-text: #0f172a;
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --bg: #0f172a;
        --surface: rgba(15,23,42,0.94);
        --text: #e2e8f0;
        --text-strong: #f8fafc;
        --muted: #94a3b8;
        --accent: #60a5fa;
        --border: rgba(148,163,184,0.22);
        --row-border: rgba(148,163,184,0.2);
        --row-hover: rgba(96,165,250,0.18);
        --danger: #fb7185;
        --input-bg: rgba(15,23,42,0.85);
        --input-text: #f8fafc;
      }
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Inter", "Segoe UI", system-ui, -apple-system, sans-serif;
      color: var(--text);
      background:
        radial-gradient(1200px 600px at -10% -10%, rgba(37,99,235,0.15), transparent 55%),
        radial-gradient(1200px 600px at 110% 110%, rgba(16,185,129,0.13), transparent 60%),
        var(--bg);
      min-height: 100vh;
    }
    .muted { color: var(--muted); }
    code { font-family: "JetBrains Mono", "Fira Code", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    .page {
      min-height: 100vh;
      display: flex;
      align-items: flex-start;
      justify-content: center;
      padding: 48px 16px 64px;
    }
    .card {
      width: 100%;
      max-width: 1040px;
      background: var(--surface);
      border-radius: 24px;
      padding: 40px;
      border: 1px solid var(--border);
      box-shadow: 0 24px 60px rgba(15, 23, 42, 0.16);
      backdrop-filter: blur(12px);
    }
    .card__header {
      display: flex;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 16px;
      margin-bottom: 28px;
    }
    .eyebrow {
      text-transform: uppercase;
      letter-spacing: 0.32em;
      font-size: 0.7rem;
      font-weight: 600;
      color: var(--muted);
    }
    h1 {
      margin: 8px 0 6px;
      font-size: clamp(1.8rem, 3vw, 2.4rem);
      color: var(--text-strong);
    }
    .subtitle {
      margin: 0;
      color: var(--muted);
      font-size: 0.95rem;
    }
    .ghost-link {
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 10px 18px;
      font-size: 0.9rem;
      font-weight: 600;
      text-decoration: none;
      color: var(--accent);
      background: rgba(37,99,235,0.08);
      transition: all 0.18s ease;
      align-self: flex-start;
    }
    .ghost-link:hover { border-color: rgba(37,99,235,0.4); background: rgba(37,99,235,0.12); }
    .section-title {
      margin: 0 0 10px;
      font-size: 1.1rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
    }
    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 12px;
    }
    thead th {
      text-align: left;
      font-size: 0.75rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
      padding: 14px 16px;
      border-bottom: 1px solid var(--row-border);
    }
    .table-wrap {
      border: 1px solid var(--border);
      border-radius: 20px;
      overflow: hidden;
      background: var(--table-bg);
      margin-top: 16px;
      color: var(--text);
    }
    tbody td {
      padding: 18px 16px;
      border-bottom: 1px solid var(--row-border);
      font-size: 0.95rem;
      vertical-align: top;
      color: inherit;
      background: transparent;
    }
    .table-wrap table,
    .table-wrap tbody td,
    .table-wrap tbody th,
    .table-wrap tbody strong,
    .table-wrap tbody code {
      color: var(--text);
    }
    .table-wrap code {
      background: rgba(15,23,42,0.05);
      border-radius: 6px;
      padding: 2px 6px;
      display: inline-flex;
      align-items: center;
    }
    tbody tr:hover { background: var(--row-hover); }
    .status-pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 4px 12px;
      font-size: 0.78rem;
      font-weight: 600;
      border-radius: 999px;
      background: rgba(22,163,74,0.12);
      color: var(--success);
    }
    .status-pill[aria-pressed="false"] {
      background: rgba(244,63,94,0.12);
      color: var(--danger);
    }
    .table-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    button, input, textarea {
      font: inherit;
    }
    .btn {
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 10px 14px;
      background: transparent;
      color: var(--text);
      font-weight: 600;
      cursor: pointer;
      transition: border-color 0.2s ease;
    }
    .btn:hover { border-color: var(--accent); }
    .btn--danger { border-color: rgba(244,63,94,0.4); color: var(--danger); }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px 20px;
      margin-top: 16px;
    }
    .field label {
      display: block;
      font-size: 0.8rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 8px;
    }
    .field input[type="text"], .field textarea, .field input[type="url"] {
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px 14px;
      background: var(--input-bg);
      color: var(--input-text);
    }
    .field input::placeholder,
    .field textarea::placeholder {
      color: var(--muted);
    }
    .field textarea { resize: vertical; min-height: 80px; }
    .inline-check {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-top: 16px;
      font-size: 0.9rem;
      color: var(--muted);
    }
    .form-actions {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 24px;
    }
    .btn--primary {
      background: var(--accent);
      border-color: var(--accent);
      color: white;
    }
    .badge-note {
      display: inline-flex;
      padding: 2px 10px;
      border-radius: 999px;
      background: rgba(148,163,184,0.2);
      font-size: 0.75rem;
    }
    .empty-state {
      padding: 36px;
      text-align: center;
      border: 1px dashed var(--border);
      border-radius: 18px;
      margin-top: 16px;
    }
    .toast {
      position: fixed;
      top: 24px;
      right: 24px;
      padding: 14px 18px;
      border-radius: 14px;
      background: rgba(15,23,42,0.92);
      color: #fff;
      box-shadow: 0 20px 40px rgba(15, 23, 42, 0.25);
      opacity: 0;
      transform: translateY(-10px);
      transition: opacity 0.2s ease, transform 0.2s ease;
      pointer-events: none;
    }
    .toast[aria-live="assertive"] { opacity: 1; transform: translateY(0); }
    @media (max-width: 720px) {
      .card { padding: 28px 20px; }
      table, thead, tbody, tr, td, th { display: block; }
      thead { display: none; }
      tbody tr { border: 1px solid var(--row-border); border-radius: 16px; margin-bottom: 12px; padding: 16px; }
      tbody td { border: none; padding: 8px 0; }
      tbody td::before {
        content: attr(data-label);
        display: block;
        font-size: 0.75rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
        margin-bottom: 4px;
      }
      .table-actions { justify-content: flex-start; }
    }
  </style>
</head>
<body>
  <div class="page">
    <main class="card" aria-label="Configuration">
      <header class="card__header">
        <div>
          <div class="eyebrow">Control Panel</div>
          <h1>Endpoint Manager</h1>
          <p class="subtitle">Create friendly paths on this server that proxy traffic to any container or host on your network.</p>
        </div>
        <a class="ghost-link" href="/files">Back to Files</a>
      </header>
      <section>
        <div class="section-title">Active Routes</div>
        <div id="endpoint-table"></div>
      </section>
      <section style="margin-top:32px;">
        <div class="section-title">Add / Edit Endpoint</div>
        <form id="endpoint-form">
          <div class="grid">
            <div class="field">
              <label for="name">Display Name</label>
              <input id="name" name="name" type="text" required placeholder="Example: Calculators" />
            </div>
            <div class="field">
              <label for="path">Public Path</label>
              <input id="path" name="path" type="text" required placeholder="/calculators" />
            </div>
            <div class="field" style="grid-column: 1 / -1;">
              <label for="target">Upstream Target (http/https)</label>
              <input id="target" name="target" type="url" required placeholder="http://calculator-service:8080" />
            </div>
            <div class="field" style="grid-column: 1 / -1;">
              <label for="notes">Notes (optional)</label>
              <textarea id="notes" name="notes" placeholder="Any extra context for future you."></textarea>
            </div>
          </div>
          <label class="inline-check">
            <input id="stripPath" name="stripPath" type="checkbox" checked /> Strip the public path before proxying
          </label>
          <label class="inline-check">
            <input id="enabled" name="enabled" type="checkbox" checked /> Enable immediately
          </label>
          <div class="form-actions">
            <button class="btn btn--primary" type="submit">Save Endpoint</button>
            <button class="btn" type="reset">Reset</button>
          </div>
        </form>
      </section>
    </main>
  </div>
  <div class="toast" role="status" id="toast"></div>
  <script>
    const INITIAL_STATE = ${initialState};
  </script>
  <script>
    const tableRoot = document.getElementById('endpoint-table');
    const form = document.getElementById('endpoint-form');
    const toast = document.getElementById('toast');
    const fields = {
      name: document.getElementById('name'),
      path: document.getElementById('path'),
      target: document.getElementById('target'),
      notes: document.getElementById('notes'),
      stripPath: document.getElementById('stripPath'),
      enabled: document.getElementById('enabled')
    };
    let editingId = null;
    let endpoints = INITIAL_STATE.endpoints || [];

    function showToast(message, kind = 'info') {
      toast.textContent = message;
      toast.setAttribute('aria-live', 'assertive');
      toast.style.background = kind === 'error' ? 'var(--danger)' : 'rgba(15,23,42,0.92)';
      clearTimeout(showToast._timeout);
      showToast._timeout = setTimeout(() => {
        toast.removeAttribute('aria-live');
      }, 3200);
    }

    async function refreshEndpoints() {
      const res = await fetch('/configure/api/endpoints');
      if (!res.ok) {
        throw new Error('Failed to load endpoints');
      }
      const data = await res.json();
      endpoints = data.endpoints;
      renderTable();
    }

    function renderTable() {
      if (!endpoints.length) {
        tableRoot.innerHTML = \`<div class="empty-state">
          <strong>No custom routes yet.</strong>
          <p class="muted">Use the form below to point <code>localhost:7711/your-path</code> to another container.</p>
        </div>\`;
        return;
      }
      const rows = endpoints.map((ep) => \`
        <tr data-id="\${ep.id}">
          <td data-label="Name"><strong>\${escape(ep.name)}</strong><br><code>\${escape(ep.path)}</code></td>
          <td data-label="Target"><code>\${escape(ep.target)}</code><br><span class="badge-note">\${ep.stripPath ? 'Strip path' : 'Preserve path'}</span></td>
          <td data-label="Status"><span class="status-pill" aria-pressed="\${ep.enabled}">\${ep.enabled ? 'Enabled' : 'Disabled'}</span></td>
          <td data-label="Notes">\${ep.notes ? escape(ep.notes) : '<span class="muted">—</span>'}</td>
          <td data-label="Actions">
            <div class="table-actions">
              <button class="btn" data-action="edit">Edit</button>
              <button class="btn" data-action="toggle">\${ep.enabled ? 'Disable' : 'Enable'}</button>
              <button class="btn btn--danger" data-action="delete">Delete</button>
            </div>
          </td>
        </tr>\`).join('');
      tableRoot.innerHTML = \`<div class="table-wrap"><table><thead><tr>
        <th>Name</th><th>Target</th><th>Status</th><th>Notes</th><th>Actions</th>
      </tr></thead><tbody>\${rows}</tbody></table></div>\`;
    }

    tableRoot.addEventListener('click', async (event) => {
      const actionBtn = event.target.closest('button[data-action]');
      if (!actionBtn) return;
      const row = actionBtn.closest('tr[data-id]');
      const id = row?.dataset.id;
      if (!id) return;
      const ep = endpoints.find((item) => item.id === id);
      if (!ep) return;
      const action = actionBtn.dataset.action;
      try {
        if (action === 'edit') {
          editingId = id;
          fields.name.value = ep.name;
          fields.path.value = ep.path;
          fields.target.value = ep.target;
          fields.notes.value = ep.notes || '';
          fields.stripPath.checked = !!ep.stripPath;
          fields.enabled.checked = !!ep.enabled;
          form.querySelector('button[type="submit"]').textContent = 'Save Changes';
          form.scrollIntoView({ behavior: 'smooth' });
        } else if (action === 'toggle') {
          await saveEndpoint({ ...ep, enabled: !ep.enabled });
          showToast(ep.enabled ? 'Endpoint disabled' : 'Endpoint enabled');
        } else if (action === 'delete') {
          if (!confirm('Delete this endpoint?')) return;
          await fetch(\`/configure/api/endpoints/\${id}\`, { method: 'DELETE' });
          await refreshEndpoints();
          showToast('Endpoint removed');
          if (editingId === id) {
            form.reset();
            editingId = null;
            form.querySelector('button[type="submit"]').textContent = 'Save Endpoint';
          }
        }
      } catch (err) {
        console.error(err);
        showToast(err.message || 'Something went wrong', 'error');
      }
    });

    async function saveEndpoint(payload) {
      const endpointId = editingId || payload.id;
      const method = endpointId ? 'PUT' : 'POST';
      const url = endpointId ? \`/configure/api/endpoints/\${endpointId}\` : '/configure/api/endpoints';
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.message || 'Request failed');
      }
      await refreshEndpoints();
    }

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const payload = {
        name: fields.name.value.trim(),
        path: fields.path.value.trim(),
        target: fields.target.value.trim(),
        notes: fields.notes.value.trim(),
        stripPath: fields.stripPath.checked,
        enabled: fields.enabled.checked
      };
      try {
        if (!payload.name || !payload.path || !payload.target) {
          throw new Error('Please fill in the required fields.');
        }
        await saveEndpoint(payload);
        showToast(editingId ? 'Changes saved' : 'Endpoint added');
        form.reset();
        fields.stripPath.checked = true;
        fields.enabled.checked = true;
        editingId = null;
        form.querySelector('button[type="submit"]').textContent = 'Save Endpoint';
      } catch (err) {
        console.error(err);
        showToast(err.message, 'error');
      }
    });

    form.addEventListener('reset', () => {
      editingId = null;
      form.querySelector('button[type="submit"]').textContent = 'Save Endpoint';
      fields.stripPath.checked = true;
      fields.enabled.checked = true;
    });

    function escape(text) {
      return text.replace(/[&<>"']/g, (ch) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', "'": '&#39;'
      })[ch]);
    }

    renderTable();
  </script>
</body>
</html>`;
}

async function serveConfigureUi(reply, store) {
  const html = renderConfigureHtml({
    endpoints: store.list(),
    reservedPrefixes: RESERVED_PREFIXES,
    updatedAt: store.data.updatedAt
  });
  reply.header('Cache-Control', 'no-store');
  reply.type('text/html; charset=utf-8').send(html);
}

async function serveFileBrowser(req, reply) {
  const reqPath = decodeURIComponent(req.params['*'] || '');
  const dir = await ensureFileBrowserDir(reqPath);
  const items = await scanDir(dir);
  const relative = path.relative(WEBROOT, dir);
  const segments = relative ? relative.split(path.sep).filter(Boolean) : [];
  const displayPath = segments.length ? `/${segments.join('/')}/` : '/';

  const breadcrumbParts = ['<a href="/files">All Files</a>'];
  segments.forEach((seg, idx) => {
    breadcrumbParts.push('<span class="crumb-sep">/</span>');
    const href = buildHref(segments.slice(0, idx + 1), { trailingSlash: true });
    breadcrumbParts.push(`<a href="${href}">${escapeHtml(seg)}</a>`);
  });

  const parentHref = segments.length === 0
    ? null
    : (segments.length === 1 ? '/files' : buildHref(segments.slice(0, -1), { trailingSlash: true }));

  const parentRow = parentHref ? `<tr class="row-parent">
      <td class="cell-name" data-label="Name">
        <a class="entry" href="${parentHref}" aria-label="Go up to the parent directory">
          <span class="icon icon-up" data-icon="↩" aria-hidden="true"></span>
          <span class="name-text">.. <span class="muted">(Parent)</span></span>
        </a>
      </td>
      <td class="cell-type" data-label="Type"><span class="badge badge-dir">Folder</span></td>
      <td class="cell-size" data-label="Size">—</td>
      <td class="cell-date" data-label="Modified">—</td>
    </tr>` : '';

  const entryRows = items.map((it) => {
    const href = buildHref([...segments, it.name], { trailingSlash: it.type === 'dir' });
    const iconClass = it.type === 'dir' ? 'icon-dir' : 'icon-file';
    const iconSymbol = it.type === 'dir' ? '📁' : '📄';
    const safeName = escapeHtml(it.name);
    const label = it.type === 'file' && it.title && it.title !== it.name
      ? `${escapeHtml(it.title)} <span class="muted">(${safeName})</span>`
      : `${safeName}${it.type === 'dir' ? '/' : ''}`;
    const typeLabel = escapeHtml(describeType(it));
    const sizeLabel = it.type === 'dir' ? '—' : formatBytes(it.size);
    const modifiedLabel = formatDate(it.mtime);
    const badgeClass = it.type === 'dir' ? 'badge-dir' : 'badge-file';
    return `<tr>
      <td class="cell-name" data-label="Name">
        <a class="entry" href="${href}">
          <span class="icon ${iconClass}" data-icon="${iconSymbol}" aria-hidden="true"></span>
          <span class="name-text">${label}</span>
        </a>
      </td>
      <td class="cell-type" data-label="Type"><span class="badge ${badgeClass}">${typeLabel}</span></td>
      <td class="cell-size" data-label="Size">${sizeLabel}</td>
      <td class="cell-date" data-label="Modified">${modifiedLabel}</td>
    </tr>`;
  }).join('');

  let bodyHtml = parentRow;
  if (entryRows) {
    bodyHtml += entryRows;
  } else {
    bodyHtml += `<tr class="empty">
      <td colspan="4">
        <div class="empty-state">
          <strong>This folder is empty.</strong>
          <p class="muted">Add files under <code>${escapeHtml(displayPath)}</code> to see them listed here.</p>
        </div>
      </td>
    </tr>`;
  }

  const html = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Files · ${escapeHtml(displayPath)}</title>
  <style>
${getFileBrowserStyles()}
  </style>
</head>
<body>
  <div class="page">
    <main class="card" aria-label="Directory listing">
      <header class="card__header">
        <div>
          <div class="eyebrow">Local Webroot</div>
          <h1>File Browser</h1>
          <p class="subtitle">Serving <code>${escapeHtml(displayPath)}</code></p>
        </div>
        <a class="ghost-link" href="/configure" title="Configure endpoints">Configure</a>
      </header>
      <nav class="breadcrumbs" aria-label="Breadcrumb">
        ${breadcrumbParts.join(' ')}
      </nav>
      <div class="table-wrap" role="region" aria-live="polite">
        <table role="grid">
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Type</th>
              <th scope="col">Size</th>
              <th scope="col">Modified</th>
            </tr>
          </thead>
          <tbody>
            ${bodyHtml}
          </tbody>
        </table>
      </div>
    </main>
  </div>
</body>
</html>`;

  reply.type('text/html; charset=utf-8').send(html);
}

function getFileBrowserStyles() {
  return `
    :root {
      color-scheme: light dark;
      --bg: #eef2ff;
      --surface: rgba(255,255,255,0.93);
      --text: #0f172a;
      --text-strong: #0f172a;
      --muted: #64748b;
      --accent: #2563eb;
      --border: rgba(15,23,42,0.08);
      --table-bg: rgba(255,255,255,0.75);
      --table-head: rgba(15,23,42,0.04);
      --row-border: rgba(15,23,42,0.06);
      --row-hover: rgba(37,99,235,0.08);
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --bg: #0f172a;
        --surface: rgba(15,23,42,0.92);
        --text: #e2e8f0;
        --text-strong: #f8fafc;
        --muted: #94a3b8;
        --accent: #60a5fa;
        --border: rgba(148,163,184,0.25);
        --table-bg: rgba(15,23,42,0.85);
        --table-head: rgba(148,163,184,0.12);
        --row-border: rgba(148,163,184,0.14);
        --row-hover: rgba(96,165,250,0.14);
      }
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Inter", "Segoe UI", system-ui, -apple-system, sans-serif;
      color: var(--text);
      background:
        radial-gradient(1200px 600px at -10% -10%, rgba(37,99,235,0.15), transparent 55%),
        radial-gradient(1200px 600px at 110% 110%, rgba(16,185,129,0.13), transparent 60%),
        var(--bg);
      min-height: 100vh;
    }
    code { font-family: "JetBrains Mono", "Fira Code", ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; }
    .page {
      min-height: 100vh;
      display: flex;
      align-items: flex-start;
      justify-content: center;
      padding: 56px 16px;
    }
    .card {
      width: 100%;
      max-width: 980px;
      background: var(--surface);
      border-radius: 22px;
      padding: 32px 36px;
      border: 1px solid var(--border);
      box-shadow: 0 24px 60px rgba(15, 23, 42, 0.16);
      backdrop-filter: blur(12px);
    }
    .card__header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
    }
    .eyebrow {
      text-transform: uppercase;
      letter-spacing: 0.32em;
      font-size: 0.7rem;
      font-weight: 600;
      color: var(--muted);
    }
    h1 {
      margin: 8px 0 4px;
      font-size: clamp(1.75rem, 3vw, 2.2rem);
      color: var(--text-strong);
    }
    .subtitle {
      margin: 0;
      color: var(--muted);
      font-size: 0.95rem;
    }
    .ghost-link {
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 10px 18px;
      font-size: 0.9rem;
      font-weight: 600;
      text-decoration: none;
      color: var(--accent);
      background: rgba(37,99,235,0.08);
      transition: all 0.18s ease;
    }
    .ghost-link:hover {
      border-color: rgba(37,99,235,0.4);
      background: rgba(37,99,235,0.12);
    }
    .breadcrumbs {
      margin-top: 20px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      font-size: 0.9rem;
      color: var(--muted);
    }
    .breadcrumbs a {
      color: inherit;
      text-decoration: none;
      padding-bottom: 2px;
      border-bottom: 1px solid transparent;
    }
    .breadcrumbs a:hover {
      color: var(--text-strong);
      border-color: currentColor;
    }
    .crumb-sep { opacity: 0.6; }
    .table-wrap {
      margin-top: 28px;
      border: 1px solid var(--border);
      border-radius: 16px;
      overflow: hidden;
      background: var(--table-bg);
    }
    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 540px;
    }
    thead th {
      text-align: left;
      padding: 16px 22px;
      font-size: 0.75rem;
      letter-spacing: 0.09em;
      text-transform: uppercase;
      color: var(--muted);
      background: var(--table-head);
    }
    tbody td {
      padding: 18px 22px;
      border-top: 1px solid var(--row-border);
      vertical-align: middle;
      font-size: 0.95rem;
    }
    tbody tr:hover { background: var(--row-hover); }
    .entry {
      display: flex;
      align-items: center;
      gap: 12px;
      color: var(--text-strong);
      font-weight: 600;
      text-decoration: none;
    }
    .entry:hover { color: var(--accent); }
    .name-text .muted { font-weight: 500; }
    .icon {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 34px;
      height: 34px;
      border-radius: 12px;
      font-size: 1rem;
      background: rgba(37,99,235,0.12);
      color: #1d4ed8;
    }
    .icon-file { background: rgba(16,185,129,0.12); color: #047857; }
    .icon-up { background: rgba(234,179,8,0.16); color: #b45309; }
    .icon::before { content: attr(data-icon); }
    .badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      padding: 4px 12px;
      font-size: 0.75rem;
      font-weight: 600;
      border-radius: 999px;
      background: rgba(37,99,235,0.10);
      color: #1d4ed8;
    }
    .badge-file { background: rgba(16,185,129,0.12); color: #047857; }
    .empty { text-align: center; }
    .empty-state { padding: 36px 18px; }
    .empty-state p { margin: 8px 0 0; font-size: 0.9rem; }
    @media (max-width: 720px) {
      .card { padding: 28px 20px; border-radius: 18px; }
      .table-wrap { border: none; background: transparent; }
      table, thead, tbody, tr, td, th { display: block; width: 100%; }
      thead { display: none; }
      tbody tr {
        border: 1px solid var(--border);
        border-radius: 14px;
        margin-bottom: 14px;
        padding: 14px;
        background: var(--table-bg);
      }
      tbody td { border: none; padding: 8px 0; }
      tbody td::before {
        content: attr(data-label);
        display: block;
        font-size: 0.7rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
        margin-bottom: 4px;
      }
      .icon { width: 32px; height: 32px; }
    }
  `;
}

function getRequestPath(req) {
  try {
    const url = new URL(req.raw.url, 'http://localhost');
    return url.pathname || '/';
  } catch {
    return '/';
  }
}

function buildForwardedFor(req) {
  const clientIp = req.ip || '';
  const existing = req.headers['x-forwarded-for'];
  if (!existing) return clientIp;
  if (!clientIp) return existing;
  return existing.includes(clientIp) ? existing : `${existing}, ${clientIp}`;
}

function resolveEndpointForRequest(pathname, req, store) {
  const direct = store.match(pathname);
  if (direct) {
    rememberEndpointHint(req, direct.endpoint);
    return direct;
  }
  const refererEndpoint = matchByReferer(req, store);
  if (refererEndpoint) {
    rememberEndpointHint(req, refererEndpoint);
    return { endpoint: refererEndpoint, remainder: pathname };
  }
  const stickyEndpoint = matchByClientHint(req, store);
  if (stickyEndpoint) {
    return { endpoint: stickyEndpoint, remainder: pathname };
  }
  return null;
}

function matchByReferer(req, store) {
  const referer = req.headers['referer'];
  if (!referer) return null;
  let refPathname;
  try {
    const refUrl = new URL(referer);
    refPathname = refUrl.pathname || '/';
  } catch {
    return null;
  }
  const refPath = normalizeRequestPath(refPathname);
  const match = store.match(refPath);
  if (!match) return null;
  const { endpoint } = match;
  if (!endpoint.stripPath) return null;
  if (!pathMatches(refPath, endpoint.path)) return null;
  return endpoint;
}

function rememberEndpointHint(req, endpoint) {
  if (!endpoint || !endpoint.stripPath) return;
  const key = getClientHintKey(req);
  if (!key) return;
  clientEndpointHints.set(key, {
    endpointId: endpoint.id,
    expiresAt: Date.now() + CLIENT_HINT_TTL_MS
  });
  if (clientEndpointHints.size > 1000) {
    pruneClientHints();
  }
}

function matchByClientHint(req, store) {
  const key = getClientHintKey(req);
  if (!key) return null;
  const hint = clientEndpointHints.get(key);
  if (!hint) return null;
  if (hint.expiresAt < Date.now()) {
    clientEndpointHints.delete(key);
    return null;
  }
  const endpoint = store.getById(hint.endpointId);
  if (!endpoint || !endpoint.stripPath) {
    clientEndpointHints.delete(key);
    return null;
  }
  return endpoint;
}

function getClientHintKey(req) {
  const base = req.headers['x-forwarded-for'] || req.ip;
  if (!base) return null;
  const ua = req.headers['user-agent'] || '';
  return `${base}|${ua}`;
}

function pruneClientHints() {
  const now = Date.now();
  for (const [key, hint] of clientEndpointHints) {
    if (hint.expiresAt < now) {
      clientEndpointHints.delete(key);
    }
  }
}

async function maybeProxyDynamicEndpoint(req, reply, store, pathname = getRequestPath(req)) {
  const normalizedPath = normalizeRequestPath(pathname);
  const match = resolveEndpointForRequest(normalizedPath, req, store);
  if (!match) {
    return false;
  }
  const targetUrl = buildUpstreamUrl(match.endpoint, match.remainder, req.raw.url);
  const forwardedFor = buildForwardedFor(req);
  const forwardedProto = req.headers['x-forwarded-proto'] || req.protocol;
  try {
    await reply.from(targetUrl, {
      rewriteRequestHeaders: (request, headers) => ({
        ...headers,
        'x-forwarded-host': request.headers.host || '',
        'x-forwarded-proto': forwardedProto,
        'x-forwarded-for': forwardedFor,
        'x-endpoint-id': match.endpoint.id
      })
    });
  } catch (err) {
    const detail = err?.cause?.message || err?.message || 'Unable to reach upstream service.';
    req.log.error({ err, endpointId: match.endpoint.id }, 'Proxy failed');
    reply.code(502).send({
      error: 'Upstream unavailable',
      message: detail,
      endpointId: match.endpoint.id
    });
  }
  return true;
}

const app = Fastify({ logger: false });
const RAW_PROXY_CONTENT_TYPES = [
  /^application\/x-www-form-urlencoded(?:;.*)?$/i
];
RAW_PROXY_CONTENT_TYPES.forEach((pattern) => {
  app.addContentTypeParser(pattern, { parseAs: 'buffer' }, (_req, payload, done) => {
    done(null, payload);
  });
});
await app.register(replyFrom);
const store = new EndpointStore(CONFIG_FILE);
await store.init();

app.get('/configure', async (req, reply) => {
  await serveConfigureUi(reply, store);
});

app.get('/configure/', async (req, reply) => {
  await serveConfigureUi(reply, store);
});

app.get('/configure/api/endpoints', async (req, reply) => {
  reply.header('Cache-Control', 'no-store');
  reply.send({
    endpoints: store.list(),
    reservedPrefixes: RESERVED_PREFIXES,
    updatedAt: store.data.updatedAt
  });
});

app.post('/configure/api/endpoints', async (req, reply) => {
  try {
    const endpoint = await store.create(req.body);
    reply.code(201).send({ endpoint });
  } catch (err) {
    handleConfigError(err, reply);
  }
});

app.put('/configure/api/endpoints/:id', async (req, reply) => {
  try {
    const endpoint = await store.update(req.params.id, req.body);
    reply.send({ endpoint });
  } catch (err) {
    handleConfigError(err, reply);
  }
});

app.delete('/configure/api/endpoints/:id', async (req, reply) => {
  try {
    await store.delete(req.params.id);
    reply.code(204).send();
  } catch (err) {
    handleConfigError(err, reply);
  }
});

app.all('/*', async (req, reply) => {
  const pathname = getRequestPath(req);

  if (pathname === '/configure' || pathname === '/configure/') {
    if (req.method === 'GET' || req.method === 'HEAD') {
      await serveConfigureUi(reply, store);
    } else {
      reply.code(405).send({ error: 'Method not allowed' });
    }
    return;
  }

  const proxied = await maybeProxyDynamicEndpoint(req, reply, store, pathname);
  if (proxied) {
    return;
  }

  if (req.method !== 'GET' && req.method !== 'HEAD') {
    reply.code(404).send({ error: 'Not found' });
    return;
  }

  await serveFileBrowser(req, reply);
});

function handleConfigError(err, reply) {
  if (err instanceof ConfigError) {
    reply.code(err.statusCode).send({ message: err.message });
  } else {
    console.error('[configure] unexpected error', err);
    reply.code(500).send({ message: 'Unexpected server error' });
  }
}

if (process.env.FASTIFY_DISABLE_LISTEN !== 'true') {
  app.listen({ port: 3000, host: '0.0.0.0' });
}

export { renderConfigureHtml };
