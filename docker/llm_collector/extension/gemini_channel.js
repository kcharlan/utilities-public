// Classifies Gemini WebChannel posts to geminiweb-pa.clients6.google.com/v1/processSession.
// Kept independent of Chrome APIs so it can be tested.
//
// Each post carries reqN___data__ form fields, each a base64 protobuf message.
// Only the first byte (the protobuf tag) of each message is base64-decoded; the
// rest, which holds the prompt text, is never decoded, logged or kept. A user
// prompt is field 2 (tag byte 0x12); session setup is field 1 and end of turn
// is field 4.

(() => {
  const PROMPT_TAG = 0x12;
  const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  function b64Index(c) {
    if (c === "+" || c === "-") return 62;
    if (c === "/" || c === "_") return 63;
    return B64.indexOf(c);
  }

  function firstByte(data) {
    if (typeof data !== "string" || data.length < 2) return null;
    const hi = b64Index(data[0]);
    const lo = b64Index(data[1]);
    if (hi < 0 || lo < 0) return null;
    return ((hi << 2) | (lo >> 4)) & 0xff;
  }

  // Chrome gives parsed formData for url-encoded posts, otherwise raw bytes.
  function formOf(requestBody) {
    if (!requestBody) return {};
    if (requestBody.formData) return requestBody.formData;
    const parts = (requestBody.raw || []).filter(c => c.bytes);
    if (!parts.length) return {};
    const form = {};
    for (const c of parts) {
      for (const [k, v] of new URLSearchParams(new TextDecoder().decode(c.bytes))) (form[k] ||= []).push(v);
    }
    return form;
  }

  function messageBytes(requestBody) {
    const form = formOf(requestBody);
    return Object.keys(form)
      .map(k => [k, k.match(/^req(\d+)___data__$/)])
      .filter(([, m]) => m)
      .sort(([, a], [, b]) => Number(a[1]) - Number(b[1]))
      .map(([k]) => firstByte(form[k][0]));
  }

  // Protobuf field number of each message, or null when it is not base64 protobuf.
  function messageFields(requestBody) {
    return messageBytes(requestBody).map(b => (b === null ? null : b >> 3));
  }

  function promptCount(requestBody) {
    return messageBytes(requestBody).filter(b => b === PROMPT_TAG).length;
  }

  globalThis.LLMGeminiChannel = Object.freeze({ messageFields, promptCount });
})();
