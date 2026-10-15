# Lessons learned

## 2026-10-15: Commit transport history with prompt accounting

In `docker/llm_collector/extension`, counting each Gemini WebChannel POST counts
transport retries repeatedly. Google's WireV8 encoder identifies messages as
`ofs + reqN`, where `N` is a relative message ID, not an array position; retry
reordering can lower the offset and leave sparse indexes. Join raw byte chunks
before decoding forms so keys, base64 prefixes and UTF-8 sequences remain whole.

Persist salted endpoint/SID hashes and interval history in the delivery owner's
same transaction as queued counts. Include non-prompt IDs, retain the salt and
history across extension and browser lifecycle boundaries, and fail closed at
bounds without eviction. Browser tab IDs and session-storage nonces cannot
establish durable transport identity. Known replays should need no write.
Exercise rejected persistence, mixed retries, lost acknowledgements, and explicit
queued-count clearing with an observation-identity conservation oracle.

## 2026-10-15: Persist immutable delivery identity before sending

In `docker/llm_collector`, serializing pending-count writes did not serialize
submissions. Two overlapping sends reused one sequence with different snapshots;
both replies subtracted counts although the collector accepted only the first.
Persist one immutable batch and keep newer observations in a separate queue.
Publish cloned state only after storage succeeds, and preserve an uncertain
batch across retries, clear actions and worker restarts. Persist a migration
baseline marker so an offline restart cannot submit before reconciliation.

Resetting a reporting period must retain deduplication receipts. Snapshot,
clearing and save need one lock boundary; otherwise a concurrent add can fall
between the snapshot and clear and disappear. Test conservation with observation
identities: accepted and uncertain in-flight sets may overlap after a lost reply,
so adding their counts is an invalid oracle.

Fetch resolving means headers arrived, not that body consumption succeeded.
Classify aborts and stream transport failures during JSON reading as retryable,
while treating malformed JSON as a protocol error. Publish a counted diagnostic
only after the observation commits. Keep rejected-recording diagnostics in the
session buffer and distinguish their errors from transient delivery errors;
an empty or unrelated successful drain cannot restore a rejected observation.

## 2026-10-15: Sanitize every diagnostic representation

In `docker/llm_collector/extension`, a credential-name regex applied to raw JSON
missed names supported by the form/query policy and values that were not strings.
Decoded URL containers, URL-valued headers, debug paths, and restored session
records provided additional ways around otherwise working capture redaction.

Use one sensitive-name classifier after parsing each recognized representation.
Bound structural inspection and decoding, omit uninspectable content, and use
own-property maps for untrusted member names. Treat session restoration as an
admission boundary: sanitize before publishing records and rewrite the safe
representation. Test the complete popup export and console boundary, including
when capture is off, because testing one capture field cannot establish that the
same credential is absent from neighboring diagnostic fields.

Review caught two boundary errors: recognizing one valid Link target does not
validate the remaining header, and reparsing a safe JSON prefix after truncation
loses long prompts. Consume an entire recognized container before publishing
any of it. Preserve live sanitation provenance outside serialized records, so
admission can distinguish a fully inspected prefix from untrusted restored text.
