// Redaction for the full request capture. Kept independent of Chrome APIs so it
// can be tested. Values are replaced with REDACTED; names are kept so the
// capture still shows which parameters and headers were present.

(() => {
  const REDACTED = "REDACTED";
  const MAX_VALUE_CHARS = 16384;
  const OMITTED = "<omitted>";
  const MAX_DEPTH = 32;
  const MAX_VALUES = 10000;
  const MAX_DECODING = 2;
  const byteLength = value => new TextEncoder().encode(typeof value === 'string' ? value : JSON.stringify(value)).byteLength;
  const MAX_STRING_BYTES = 16 * 1024;
  const MAX_URL_HEADER_BYTES = 8 * 1024;
  const MAX_BODY_BYTES = 64 * 1024;
  const MAX_RECORD_BYTES = 128 * 1024;
  // Only this worker's fully inspected body objects can carry a safe prefix.
  // Session serialization cannot transfer this provenance to restored input.
  const sanitizedBodyPrefixes = new WeakMap();
  const state = () => ({ visited: 0, active: new Set() });
  function visit(s, depth) {
    if (depth > MAX_DEPTH || ++s.visited > MAX_VALUES) throw new Error("inspection limit");
  }

  // Parameter, header and form-field names whose values are credentials or
  // session or account identifiers. `at` is Google's XSRF form token; `verify`
  // carries ChatGPT's WebSocket token; `oai-did` is its device id.
  const SENSITIVE_NAME = /sid|session|token|auth|cookie|secret|passw|api[-_]?key|^key$|signature|^sig$|xsrf|csrf|credential|client-data|visitor|account[-_]?id|^oai-did$|^verify$/i;
  function isSensitiveName(name) {
    return String(name).toLowerCase() === "at" || SENSITIVE_NAME.test(String(name));
  }

  // Token formats that can appear inside any text, plus JSON members whose name
  // looks sensitive.
  const TEXT_PATTERNS = [
    [/("[^"]*(?:token|secret|passw|session|auth|cookie|api_?key)[^"]*"\s*:\s*")[^"]*(")/gi, `$1${REDACTED}$2`],
    // Also matches percent- and plus-encoded separators, as in URL parameters.
    [/\b(Bearer|SAPISIDHASH|SAPISID1PHASH|SAPISID3PHASH)(\s+|%20|\+)[\w.~+\/=-]+/g, `$1$2${REDACTED}`],
    [/\bya29\.[\w.-]+/g, REDACTED],
    [/\bAIza[\w-]{35}/g, REDACTED]
  ];
  function scrubText(text) {
    let out = String(text);
    for (const [pattern, replacement] of TEXT_PATTERNS) out = out.replace(pattern, replacement);
    return out;
  }

  function capped(text) {
    let value = text.slice(0, MAX_VALUE_CHARS);
    if (byteLength(value) > MAX_STRING_BYTES) {
      // Decode a bounded UTF-8 prefix without manufacturing half a surrogate.
      value = new TextDecoder().decode(new TextEncoder().encode(value).slice(0, MAX_STRING_BYTES), { stream: true });
    }
    return { value, ...(value !== text && { truncated: true }) };
  }
  function boundBodyStrings(body) {
    let truncated = false;
    function bound(value) {
      if (!value || typeof value !== 'object') return;
      for (const name of Object.keys(value)) {
        if (typeof value[name] === 'string') {
          const c = capped(value[name]);
          value[name] = c.value;
          if (c.truncated) truncated = true;
        } else bound(value[name]);
      }
    }
    bound(body);
    if (truncated) body.truncated = true;
    return body;
  }

  // "Name: value" lines, as in Google WebChannel's $httpHeaders URL parameter,
  // which carries Authorization and API-key headers inside the URL.
  const HAS_HEADER_LINE = /^[\w-]+[ \t]*:/m;
  function redactHeaderBlock(text, s, depth, layers) {
    return text.split(/(\r\n|\r|\n)/).map(line => {
      if (!line || /^(\r\n|\r|\n)$/.test(line)) return line;
      const match = line.match(/^([\w-]+)([ \t]*:[ \t]*)(.*)$/);
      if (!match) throw new Error("invalid header block");
      return match[1] + match[2] + headerValue(match[1], match[3], s, depth + 1, layers);
    }).join("");
  }

  function decodeComponent(raw) {
    try { return decodeURIComponent(raw.replace(/\+/g, " ")); } catch { return null; }
  }

  // Path segments such as ChatGPT's /ws/user/user-<id>/.
  const PATH_IDS = /\b(user-)[A-Za-z0-9]{12,}/g;
  function redactPath(pathname) {
    try {
      // Decode path escapes before matching identifiers, but retain unchanged spelling.
      const original = String(pathname);
      if (byteLength(original) > MAX_URL_HEADER_BYTES) return OMITTED;
      const decoded = decodeURIComponent(original);
      const safe = scrubText(decoded.replace(PATH_IDS, `$1${REDACTED}`));
      return safe === decoded ? original : safe;
    } catch { return OMITTED; }
  }

  function walk(value, s, depth, layers) {
    visit(s, depth);
    if (typeof value === "string") return inspectText(value, s, depth, layers);
    if (value === null || typeof value === "boolean" || typeof value === "number") return value;
    if (!value || typeof value !== "object" || s.active.has(value)) throw new Error("unsafe value");
    s.active.add(value);
    try {
      if (Array.isArray(value)) return value.map(v => walk(v, s, depth + 1, layers));
      const out = Object.create(null);
      for (const [name, v] of Object.entries(value)) {
        out[name] = isSensitiveName(name) ? REDACTED
          : name.toLowerCase() === '$httpheaders' && typeof v === 'string'
            ? redactHeaderBlock(v, s, depth + 1, layers)
            : walk(v, s, depth + 1, layers);
      }
      return out;
    } finally { s.active.delete(value); }
  }

  function inspectText(text, s, depth, layers) {
    if (depth > MAX_DEPTH) throw new Error("inspection limit");
    const trimmed = text.trim();
    if (/^[{[\"]/.test(trimmed)) {
      let parsed;
      try { parsed = JSON.parse(text); } catch { return OMITTED; }
      const safe = JSON.stringify(walk(parsed, s, depth + 1, layers));
      // Preserve whitespace and escaping when nothing needed changing.
      return safe === JSON.stringify(parsed) ? text : safe;
    }
    if (/^(?:https?|wss?):\/\//i.test(trimmed) || /^(?:\/|\.\.?\/|\?)/.test(trimmed)) {
      return urlValue(text, s, depth + 1, layers);
    }
    if (/%[0-9a-f]{2}/i.test(text)) {
      if (layers >= MAX_DECODING) return OMITTED;
      const decoded = decodeComponent(text);
      if (decoded === null) return OMITTED;
      const safe = inspectText(decoded, s, depth + 1, layers + 1);
      return safe === decoded ? text : safe === OMITTED ? OMITTED : encodeURIComponent(safe);
    }
    return scrubText(text);
  }

  function headerValue(name, value, s, depth, layers) {
    visit(s, depth);
    if (isSensitiveName(name)) return REDACTED;
    if (/^(location|content-location|referer)$/i.test(name)) return urlValue(value, s, depth + 1, layers);
    if (/^refresh$/i.test(name)) {
      const match = value.match(/^(\s*\d+(?:\.\d+)?\s*;\s*url\s*=\s*)(.*)$/i);
      if (!match) return /^\s*\d+(?:\.\d+)?\s*$/.test(value) ? value : OMITTED;
      const target = match[2].replace(/^(["'])(.*)\1$/, '$2');
      const safe = urlValue(target, s, depth + 1, layers);
      return safe === OMITTED ? OMITTED : match[1] + safe;
    }
    if (/^link$/i.test(name)) {
      // Consume every entry and parameter; a valid first target cannot hide an
      // unbracketed or otherwise malformed remainder. Quoted commas are data.
      const entry = /\s*<([^<>\s]*)>((?:\s*;\s*[!#$%&'*+.^_`|~\w-]+(?:\s*=\s*(?:"(?:[^"\\\r\n]|\\.)*"|[!#$%&'*+.^_`|~\w-]+))?)*)\s*(,|$)/y;
      const parts = [];
      while (entry.lastIndex < value.length) {
        const match = entry.exec(value);
        if (!match) return OMITTED;
        const url = urlValue(match[1], s, depth + 1, layers);
        if (url === OMITTED || (match[3] && entry.lastIndex === value.length)) return OMITTED;
        parts.push('<' + url + '>' + scrubText(match[2]));
        if (!match[3]) return parts.join(', ');
      }
      return OMITTED;
    }
    return inspectText(value, s, depth + 1, layers);
  }

  function decodedName(rawName) {
    let name = rawName;
    for (let layer = 0; layer < MAX_DECODING; layer++) {
      const decoded = decodeComponent(name);
      if (decoded === null) return null;
      name = decoded;
      if (!/%[0-9a-f]{2}/i.test(name)) return name;
    }
    return null;
  }

  // Rebuilds the query by hand so non-sensitive values keep their original
  // encoding. The fragment is dropped; it never reaches the server.
  function urlValue(urlString, s, depth, layers) {
    visit(s, depth);
    let u;
    const relative = !/^[a-z][a-z\d+.-]*:/i.test(urlString);
    try { u = new URL(urlString, "https://relative.invalid/"); } catch { return OMITTED; }
    if (!/^(https?|wss?):$/.test(u.protocol)) return OMITTED;
    const path = redactPath(relative && !urlString.startsWith('//') ? urlString.split(/[?#]/)[0] : u.pathname);
    if (path === OMITTED) return OMITTED;
    const prefix = relative ? (urlString.startsWith('//') ? '//' + u.host : '') : u.origin;
    const query = u.search.slice(1);
    if (!query) return `${prefix}${path}`;
    const parts = query.split("&").map(part => {
      visit(s, depth + 1);
      const eq = part.indexOf("=");
      const rawName = eq < 0 ? part : part.slice(0, eq);
      const name = decodedName(rawName);
      if (name === null) return `${OMITTED}=${OMITTED}`;
      if (isSensitiveName(name)) return `${rawName}=${REDACTED}`;
      const value = eq < 0 ? null : decodeComponent(part.slice(eq + 1));
      if (eq < 0) return rawName;
      if (value === null || layers >= MAX_DECODING) return `${rawName}=${encodeURIComponent(OMITTED)}`;
      const safe = name.toLowerCase() === '$httpheaders' || (/[\r\n]/.test(value) && HAS_HEADER_LINE.test(value))
        ? redactHeaderBlock(value, s, depth + 1, layers + 1)
        : inspectText(value, s, depth + 1, layers + 1);
      return safe === value ? part : `${rawName}=${encodeURIComponent(safe)}`;
    });
    return `${prefix}${path}?${parts.join("&")}`;
  }
  function redactUrl(urlString) {
    if (byteLength(String(urlString)) > MAX_URL_HEADER_BYTES) return OMITTED;
    try {
      const safe = urlValue(String(urlString), state(), 0, 0);
      return byteLength(safe) > MAX_URL_HEADER_BYTES ? OMITTED : safe;
    } catch { return OMITTED; }
  }

  function redactHeaders(headers) {
    const s = state();
    try {
      return (headers || []).map(({ name, value }) => ({
        name: byteLength(String(name)) > MAX_URL_HEADER_BYTES ? OMITTED : name,
        value: byteLength(String(value ?? '')) > MAX_URL_HEADER_BYTES ? OMITTED : boundedHeaderValue(name, String(value ?? ''), s)
      }));
    } catch { return [{ name: OMITTED, value: OMITTED }]; }
  }
  function boundedHeaderValue(name, value, s) {
    const safe = headerValue(name, value, s, 0, 0);
    return byteLength(safe) > MAX_URL_HEADER_BYTES ? OMITTED : safe;
  }
  function safeText(value) {
    try { return inspectText(String(value), state(), 0, 0); } catch { return OMITTED; }
  }

  function redactForm(form) {
    const out = Object.create(null);
    const s = state();
    let truncated = false;
    try {
      for (const [name, values] of Object.entries(form)) {
        out[name] = values.map(v => {
          visit(s, 0);
          if (isSensitiveName(name)) return REDACTED;
          const safe = name.toLowerCase() === '$httpheaders'
            ? redactHeaderBlock(String(v), s, 0, 0) : inspectText(String(v), s, 0, 0);
          const c = capped(safe);
          if (c.truncated) truncated = true;
          return c.value;
        });
        if (byteLength(out) > MAX_BODY_BYTES - 64) return { formData: Object.create(null), omitted: OMITTED, truncated: true };
      }
    } catch { return { formData: Object.create(null), omitted: OMITTED }; }
    const body = { formData: out, ...(truncated && { truncated }) };
    return byteLength(body) > MAX_BODY_BYTES ? { formData: Object.create(null), omitted: OMITTED, truncated: true } : body;
  }

  const FORM_BODY = /^[\w.%*~-]+=[^&]*(&[\w.%*~-]+=[^&]*)*$/;
  function parseForm(text) {
    const form = Object.create(null);
    for (const [k, v] of new URLSearchParams(text)) (form[k] ||= []).push(v);
    return form;
  }

  // Chrome supplies either parsed formData or raw byte chunks; file chunks only
  // carry a local path, which is never recorded.
  function redactBody(requestBody) {
    if (!requestBody) return null;
    if (requestBody.error) return boundBodyStrings({ error: safeText(requestBody.error) });
    if (requestBody.formData) return redactForm(requestBody.formData);

    const chunks = requestBody.raw || [];
    if (chunks.some(c => c.file)) {
      return { bytes: chunks.reduce((n, c) => n + (c.bytes ? c.bytes.byteLength : 0), 0), text: "<file>" };
    }
    const parts = chunks.filter(c => c.bytes);
    const total = parts.reduce((n, c) => n + c.bytes.byteLength, 0);
    if (total > 1024 * 1024) return { bytes: total, text: OMITTED, truncated: true };
    const joined = new Uint8Array(total);
    let offset = 0;
    for (const c of parts) { joined.set(new Uint8Array(c.bytes), offset); offset += c.bytes.byteLength; }
    const text = new TextDecoder("utf-8").decode(joined);

    if (FORM_BODY.test(text)) return { bytes: total, ...redactForm(parseForm(text)) };
    const c = capped(safeText(text));
    const body = { bytes: total, text: c.value, ...(c.truncated && { truncated: true }) };
    if (c.truncated) sanitizedBodyPrefixes.set(body, c.value);
    return body;
  }

  function sanitizeDiagnosticRecord(kind, record) {
    if (!['capture', 'debug'].includes(kind) || !record || typeof record !== 'object' || Array.isArray(record)) return null;
    try {
      // Walk first: malformed/cyclic or over-budget records never reach consumers.
      const out = walk(record, state(), 0, 0);
      const safePrefix = sanitizedBodyPrefixes.get(record.body);
      if (safePrefix !== undefined) out.body.text = safePrefix;
      if (record.body?.formData) out.body = { ...out.body, ...redactForm(record.body.formData) };
      if (out.body) boundBodyStrings(out.body);
      for (const key of ['url', 'initiator']) if (typeof record[key] === 'string') {
        const safe = redactUrl(record[key]);
        // Initiator origins historically have no trailing slash.
        out[key] = key === 'initiator' && safe === record[key] + '/' ? record[key] : safe;
      }
      if (typeof record.path === 'string') out.path = redactPath(record.path);
      for (const key of ['requestHeaders', 'responseHeaders']) {
        if (Object.hasOwn(record, key)) out[key] = redactHeaders(record[key]);
      }
      if (Array.isArray(record.redirects)) out.redirects = record.redirects.map(r => ({ ...walk(r, state(), 0, 0), url: redactUrl(r.url) }));
      return boundDiagnosticRecord(out);
    } catch { return null; }
  }

  // Mutate admitted records in place: re-inspection would lose the provenance
  // of already sanitized JSON prefixes. Late header/redirect growth uses this
  // same reducer and can never resurrect an evicted request.
  function boundDiagnosticRecord(rec) {
    if (rec.body && byteLength(rec.body) > MAX_BODY_BYTES) rec.body = { omitted: OMITTED, truncated: true };
    if (byteLength(rec) <= MAX_RECORD_BYTES) return rec;
    if (rec.body) rec.body = { omitted: OMITTED, truncated: true };
    rec.truncated = true;
    for (const field of ['redirects', 'requestHeaders', 'responseHeaders']) {
      while (rec[field]?.length && byteLength(rec) > MAX_RECORD_BYTES) rec[field].shift();
    }
    return byteLength(rec) > MAX_RECORD_BYTES ? null : rec;
  }

  globalThis.LLMCaptureRedact = Object.freeze({
    MAX_VALUE_CHARS, REDACTED, isSensitiveName, scrubText, redactUrl, redactHeaders, redactBody,
    redactPath, sanitizeDiagnosticRecord, boundDiagnosticRecord
  });
})();
