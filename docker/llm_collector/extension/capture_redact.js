// Redaction for the full request capture. Kept independent of Chrome APIs so it
// can be tested. Values are replaced with REDACTED; names are kept so the
// capture still shows which parameters and headers were present.

(() => {
  const REDACTED = "REDACTED";
  const MAX_VALUE_CHARS = 16384;

  // Parameter, header and form-field names whose values are credentials or
  // session or account identifiers. `at` is Google's XSRF form token; `verify`
  // carries ChatGPT's WebSocket token; `oai-did` is its device id.
  const SENSITIVE_NAME = /sid|session|token|auth|cookie|secret|passw|api[-_]?key|^key$|signature|^sig$|xsrf|csrf|credential|client-data|visitor|account[-_]?id|^oai-did$|^verify$/i;
  function isSensitiveName(name) {
    return name.toLowerCase() === "at" || SENSITIVE_NAME.test(name);
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
    return text.length > MAX_VALUE_CHARS ? { value: text.slice(0, MAX_VALUE_CHARS), truncated: true } : { value: text };
  }

  // "Name: value" lines, as in Google WebChannel's $httpHeaders URL parameter,
  // which carries Authorization and API-key headers inside the URL.
  const HEADER_LINE = /^([\w-]+)([ \t]*:[ \t]*)(.*)$/gm;
  const HAS_HEADER_LINE = /^[\w-]+[ \t]*:/m;
  function redactHeaderBlock(text) {
    return text.replace(HEADER_LINE, (_, name, sep, value) =>
      name + sep + (isSensitiveName(name) ? REDACTED : scrubText(value)));
  }

  function decodeComponent(raw) {
    try { return decodeURIComponent(raw.replace(/\+/g, " ")); } catch { return null; }
  }

  // Path segments such as ChatGPT's /ws/user/user-<id>/.
  const PATH_IDS = /\b(user-)[A-Za-z0-9]{12,}/g;

  // Rebuilds the query by hand so non-sensitive values keep their original
  // encoding. The fragment is dropped; it never reaches the server.
  function redactUrl(urlString) {
    const u = new URL(urlString);
    const path = u.pathname.replace(PATH_IDS, `$1${REDACTED}`);
    const query = u.search.slice(1);
    if (!query) return `${u.origin}${path}`;
    const parts = query.split("&").map(part => {
      const eq = part.indexOf("=");
      const rawName = eq < 0 ? part : part.slice(0, eq);
      const name = decodeComponent(rawName) ?? rawName;
      if (isSensitiveName(name)) return `${rawName}=${REDACTED}`;
      const value = eq < 0 ? null : decodeComponent(part.slice(eq + 1));
      if (value && /[\r\n]/.test(value) && HAS_HEADER_LINE.test(value)) {
        return `${rawName}=${encodeURIComponent(redactHeaderBlock(value))}`;
      }
      return scrubText(part);
    });
    return `${u.origin}${path}?${parts.join("&")}`;
  }

  function redactHeaders(headers) {
    return (headers || []).map(({ name, value }) => ({
      name,
      value: isSensitiveName(name) ? REDACTED : scrubText(value ?? "")
    }));
  }

  function redactForm(form) {
    const out = {};
    let truncated = false;
    for (const [name, values] of Object.entries(form)) {
      out[name] = values.map(v => {
        if (isSensitiveName(name)) return REDACTED;
        const c = capped(scrubText(v));
        if (c.truncated) truncated = true;
        return c.value;
      });
    }
    return { formData: out, ...(truncated && { truncated }) };
  }

  const FORM_BODY = /^[\w.%*~-]+=[^&]*(&[\w.%*~-]+=[^&]*)*$/;
  function parseForm(text) {
    const form = {};
    for (const [k, v] of new URLSearchParams(text)) (form[k] ||= []).push(v);
    return form;
  }

  // Chrome supplies either parsed formData or raw byte chunks; file chunks only
  // carry a local path, which is never recorded.
  function redactBody(requestBody) {
    if (!requestBody) return null;
    if (requestBody.error) return { error: requestBody.error };
    if (requestBody.formData) return redactForm(requestBody.formData);

    const chunks = requestBody.raw || [];
    if (chunks.some(c => c.file)) {
      return { bytes: chunks.reduce((n, c) => n + (c.bytes ? c.bytes.byteLength : 0), 0), text: "<file>" };
    }
    const parts = chunks.filter(c => c.bytes);
    const total = parts.reduce((n, c) => n + c.bytes.byteLength, 0);
    const joined = new Uint8Array(total);
    let offset = 0;
    for (const c of parts) { joined.set(new Uint8Array(c.bytes), offset); offset += c.bytes.byteLength; }
    const text = new TextDecoder("utf-8").decode(joined);

    if (FORM_BODY.test(text)) return { bytes: total, ...redactForm(parseForm(text)) };
    const c = capped(scrubText(text));
    return { bytes: total, text: c.value, ...(c.truncated && { truncated: true }) };
  }

  globalThis.LLMCaptureRedact = Object.freeze({
    MAX_VALUE_CHARS, REDACTED, isSensitiveName, scrubText, redactUrl, redactHeaders, redactBody
  });
})();
