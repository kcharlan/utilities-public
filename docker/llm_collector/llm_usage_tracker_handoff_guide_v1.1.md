# LLM Usage Tracker — Handoff and Developer Guide (v2)

This document explains **how the system operates**, **how to extend it for new AI sites**, and **how it evolved technically**. It’s intended for engineers or LLMs inheriting the project for maintenance or enhancement.

---

## 1. System Overview

### Components

**1. Browser Extension (Client)**

- Captures outbound POSTs to target AI endpoints (ChatGPT, Gemini, Perplexity, etc.).
- Maintains:
  - `client_id`: UUID per browser profile.
  - `seq`: last confirmed sequence number.
  - `pending`: unsent increments.
- Uses `chrome.storage.local` for persistence across restarts.

**2. Collector (Server)**

- Flask app running in Docker.
- Persists counters to `state.json`.
- Archives snapshots on `/reset` to `snapshots/`.
- Tracks per-client `last_seq` for idempotence.

### Persistence Model

| Component | File                   | Purpose                |
| --------- | ---------------------- | ---------------------- |
| Collector | `state.json`           | Source of truth        |
| Collector | `snapshots/`           | Rotated archives       |
| Collector | `collector.log`        | Operational log        |
| Browser   | `chrome.storage.local` | Local cache & sequence |

---

## 2. Synchronization Model

The collector is authoritative.  
Clients only push **deltas** (count changes).

### Flow

1. Client sees a POST → increments `pending[host]`.
2. Sends `{client_id, seq+1, deltas}` to `/add`.
3. Collector checks sequence:
   - Accept if `seq == last_seq + 1`.
   - Reject (409) if out-of-order.
4. On 409, client fetches `/client_status` and realigns.
5. Server persists after every accepted update.

Both persist sequences, so either side can restart safely.

---

## 3. Reliability Scenarios

| Case              | Behavior                 | Recovery              |
| ----------------- | ------------------------ | --------------------- |
| Collector restart | Reloads `state.json`     | Clients auto-realign  |
| Browser restart   | Fetches `/client_status` | Auto-align            |
| Network loss      | Caches pending deltas    | Retries               |
| Client reinstall  | New `client_id`          | New stream            |
| `/reset`          | Archives + zeroes        | Continues at next seq |

---

## 4. Operations

### Build and Run

```bash
cd llm_collector/llm_collector_container
./up.sh
```

Collector runs at `http://127.0.0.1:9000`.

### Reset / Snapshot

Archive and clear counts:

```bash
source ~/.config/llm_collector/secret.env
curl -X POST "$COLLECTOR_URL/reset" -H "X-API-KEY: $API_KEY"
```

Response includes snapshot filename.

---

## 5. Browser Extension

### Capture Rules

- Match outbound POSTs via fetch/XHR hook.
- Apply host/path allowlists.
- Ignore background or telemetry requests.

### State Management

| Field       | Meaning                    |
| ----------- | -------------------------- |
| `client_id` | Unique per browser profile |
| `seq`       | Server-confirmed sequence  |
| `pending`   | Local unsent deltas        |

Startup routine aligns local `seq` to `/client_status`.

---

## 6. Adding a New AI Site

1. **Enable Debug Mode** — set `DEBUG = true` in `background.js`.
2. **Trigger activity** — interact with the site while watching console logs.
3. **Identify valid POSTs** — distinguish prompt submissions from telemetry.
4. **Add Rules** — edit `HOST_ALLOW` / `HOST_DENY` accordingly.
5. **Test** — verify counts match real user actions and sync correctly.

---

## 7. Development Reference

### Endpoints

| Method | Path             | Description            |
| ------ | ---------------- | ---------------------- |
| GET    | `/counters`      | Current totals         |
| POST   | `/add`           | Add deltas             |
| POST   | `/reset`         | Archive + reset        |
| GET    | `/client_status` | Returns per-client seq |
| POST   | `/flush`         | Force save state       |

### File Layout

| Path                     | Purpose             |
| ------------------------ | ------------------- |
| `collector/collector.py` | Flask server        |
| `collector.log`          | Activity log        |
| `state.json`             | Persistent counters |
| `snapshots/`             | Historical archives |

---

## 8. Historical Evolution

| Phase | Key Changes                                                 |
| ----- | ----------------------------------------------------------- |
| v1    | Prototype; counted requests only in browser.                |
| v2    | Added collector + state.json persistence.                   |
| v3    | Introduced sequence model + idempotent sync.                |
| v4    | Containerized architecture, daily snapshots, robust resync. |

---

## 9. Testing and Validation

1. Start collector container.
2. Open extension popup → confirm connectivity.
3. Generate some AI queries.
4. Check `/counters` and popup values match.
5. Restart browser → counters persist.
6. Restart container → counters reload.
7. Run `/reset` → snapshot saved + zeroed totals.

All verified ✅ in latest architecture.

---

## 10. Handoff Checklist

1. Provide:
   - `llm_collector` repo.
   - `llm_usage_installation_guide_v2.md`.
   - This document.
2. Validate `/health` endpoint.
3. Confirm snapshot rotation works.
4. Confirm new-site enablement via debug pipeline.

---

**End of Document**
