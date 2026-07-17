# collector/collector.py
# Server is sole source of truth.
# - Totals live on the server and persist to state.json
# - Clients send idempotent "add" batches with a per-client sequence number
# - Server stores last_seq per client to dedupe retries
# - Extras: /counters /add /client_status /reset /flush /health
#
# Run under gunicorn in Docker (recommended), or directly for dev.

import os
import json
import tempfile
import threading
import signal
import atexit
from datetime import datetime, timezone
from typing import Dict, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Flask, request, jsonify, abort

import csv
from datetime import timedelta
from pathlib import Path


# -----------------------
# Configuration
# -----------------------
APP_ROOT     = os.path.abspath(os.getenv("APP_ROOT", os.getcwd()))
STATE_PATH   = os.path.abspath(os.getenv("STATE_PATH", os.path.join(APP_ROOT, "state.json")))
SNAP_DIR     = os.path.abspath(os.getenv("SNAP_DIR", os.path.join(APP_ROOT, "snapshots")))
LOG_PATH     = os.path.abspath(os.getenv("LOG_PATH", os.path.join(APP_ROOT, "collector.log")))
API_KEY_ENV  = os.getenv("API_KEY", "")
BUCKET_TIMEZONE_NAME = os.getenv("BUCKET_TIMEZONE", os.getenv("TZ", "America/New_York"))
def _get_env_int(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default

LOG_MAX_BYTES    = max(_get_env_int("LOG_MAX_BYTES", 10 * 1024 * 1024), 0)
LOG_BACKUP_COUNT = max(_get_env_int("LOG_BACKUP_COUNT", 5), 0)

# -----------------------
# Logging
# -----------------------
_log_lock = threading.RLock()
def _ensure_log_dir() -> None:
    log_dir = os.path.dirname(LOG_PATH)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

def _maybe_rotate_locked(incoming_len: int) -> None:
    if LOG_MAX_BYTES <= 0:
        return
    try:
        current_size = os.path.getsize(LOG_PATH)
    except FileNotFoundError:
        return
    except OSError:
        return
    if current_size + incoming_len <= LOG_MAX_BYTES:
        return

    try:
        if LOG_BACKUP_COUNT > 0:
            oldest = f"{LOG_PATH}.{LOG_BACKUP_COUNT}"
            if os.path.exists(oldest):
                os.remove(oldest)
            for idx in range(LOG_BACKUP_COUNT - 1, 0, -1):
                src = f"{LOG_PATH}.{idx}"
                if os.path.exists(src):
                    os.replace(src, f"{LOG_PATH}.{idx + 1}")
            os.replace(LOG_PATH, f"{LOG_PATH}.1")
        else:
            os.remove(LOG_PATH)
    except OSError:
        pass

def log(line: str) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    msg = f"{ts} {line}"
    with _log_lock:
        try:
            _ensure_log_dir()
            _maybe_rotate_locked(len(msg) + 1)
            with open(LOG_PATH, "a") as f:
                f.write(msg + "\n")
        except Exception:
            pass
    print(msg, flush=True)

# -----------------------
# Persistent state (SOT)
# STATE = {
#   "totals": {host:int, ...},
#   "daily_totals": {"YYYY-MM-DD": {host:int, ...}},
#   "clients": { client_id: {"last_seq": int} }
# }
# -----------------------
_state_lock = threading.RLock()
STATE: Dict[str, Any] = {
    "totals": {},
    "daily_totals": {},
    "clients": {}
}

def _empty_state() -> Dict[str, Any]:
    return {"totals": {}, "daily_totals": {}, "clients": {}}

def _bucket_timezone():
    try:
        return ZoneInfo(BUCKET_TIMEZONE_NAME)
    except ZoneInfoNotFoundError:
        log(f"[WARN] invalid BUCKET_TIMEZONE={BUCKET_TIMEZONE_NAME!r}; falling back to UTC")
        return timezone.utc

def _timestamp_ms_to_bucket_date(timestamp_ms: Any) -> str:
    try:
        ts = float(timestamp_ms)
        dt = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        dt = datetime.now(timezone.utc)
    return dt.astimezone(_bucket_timezone()).date().isoformat()

def _normalize_totals(raw: Any) -> Dict[str, int]:
    if not isinstance(raw, dict):
        return {}

    totals: Dict[str, int] = {}
    for key, value in raw.items():
        try:
            totals[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return totals

def _normalize_daily_totals(raw: Any) -> Dict[str, Dict[str, int]]:
    if not isinstance(raw, dict):
        return {}

    daily_totals: Dict[str, Dict[str, int]] = {}
    for day, totals in raw.items():
        if isinstance(day, str) and len(day) == 10:
            parsed = _normalize_totals(totals)
            if parsed:
                daily_totals[day] = parsed
    return daily_totals

def _copy_daily_totals() -> Dict[str, Dict[str, int]]:
    return {day: dict(totals) for day, totals in STATE.get("daily_totals", {}).items()}

def _atomic_write(path: str, data_dict: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_state_", dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data_dict, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass

def load_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_PATH):
        return _empty_state()
    try:
        with open(STATE_PATH, "r") as f:
            data = json.load(f) or {}
        data.setdefault("totals", {})
        data.setdefault("daily_totals", {})
        data.setdefault("clients", {})
        # normalize ints
        data["totals"] = _normalize_totals(data["totals"])
        data["daily_totals"] = _normalize_daily_totals(data["daily_totals"])
        if data["totals"] and not data["daily_totals"]:
            data["daily_totals"][_timestamp_ms_to_bucket_date(None)] = dict(data["totals"])
        for cid, meta in list(data["clients"].items()):
            if not isinstance(meta, dict):
                data["clients"][cid] = {"last_seq": 0}
            else:
                meta["last_seq"] = int(meta.get("last_seq", 0))
        return data
    except Exception as e:
        log(f"[WARN] failed to load {STATE_PATH}: {e}")
        return _empty_state()

def save_state() -> None:
    with _state_lock:
        _atomic_write(STATE_PATH, STATE)

def snapshot_totals() -> str:
    os.makedirs(SNAP_DIR, exist_ok=True)
    ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    snap = os.path.join(SNAP_DIR, f"snapshot_{ts}.json")
    with _state_lock:
        _atomic_write(
            snap,
            {
                "totals": dict(STATE["totals"]),
                "daily_totals": _copy_daily_totals(),
                "bucket_timezone": BUCKET_TIMEZONE_NAME,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    return snap

# -----------------------
# Flask app
# -----------------------
app = Flask(__name__)

def _auth_or_403(req):
    if not API_KEY_ENV:
        return
    if req.headers.get("X-API-KEY") != API_KEY_ENV:
        abort(403)

@app.before_request
def _preflight():
    cl = request.content_length
    if cl is not None and cl > 1024 * 1024:
        abort(413)

@app.get("/health")
def health():
    return jsonify({"ok": True}), 200

@app.get("/counters")
def get_counters():
    _auth_or_403(request)
    with _state_lock:
        return jsonify({"counters": dict(STATE["totals"])}), 200

@app.get("/client_status")
def client_status():
    _auth_or_403(request)
    cid = request.args.get("client_id", "")
    if not cid:
        return jsonify({"error": "missing client_id"}), 400
    with _state_lock:
        last_seq = int(STATE["clients"].get(cid, {}).get("last_seq", 0))
    return jsonify({"client_id": cid, "last_seq": last_seq}), 200

@app.post("/add")
def add():
    """
    Idempotent atomic add with per-client sequencing.

    Body:
      {
        "client_id": "uuid",
        "seq": <int>,            # client's next sequence (monotonic per client)
        "deltas": { "host": +n, ... },
        "ts": <ms since epoch>   # optional
      }

    Behavior:
      - If seq <= last_seq: treat as retry; ignore deltas, return 200.
      - If seq == last_seq + 1: apply deltas atomically to totals; set last_seq=seq; return 200.
      - If seq > last_seq + 1: out of order; return 409 with expected_next.
    """
    _auth_or_403(request)
    p = request.get_json(force=True, silent=True) or {}
    cid = p.get("client_id")
    seq = p.get("seq")
    deltas = p.get("deltas") or {}
    ts = p.get("ts")

    if not cid or not isinstance(deltas, dict):
        return jsonify({"error": "bad payload"}), 400
    try:
        seq = int(seq)
    except Exception:
        return jsonify({"error": "bad seq"}), 400

    with _state_lock:
        meta = STATE["clients"].setdefault(cid, {"last_seq": 0})
        last_seq = int(meta.get("last_seq", 0))

        if seq <= last_seq:
            log(f"[ADD] client={cid} seq={seq} <= last_seq={last_seq} (duplicate) — no-op")
            return jsonify({"ok": True, "applied": 0, "last_seq": last_seq}), 200

        if seq > last_seq + 1:
            log(f"[ADD] client={cid} seq={seq} > last_seq+1={last_seq+1} (out of order)")
            return jsonify({"error": "out_of_order", "expected_next": last_seq + 1}), 409

        # seq == last_seq + 1 → apply
        applied = 0
        bucket_day = _timestamp_ms_to_bucket_date(ts)
        day_totals = STATE.setdefault("daily_totals", {}).setdefault(bucket_day, {})
        for host, dv in deltas.items():
            try:
                d = int(dv)
            except Exception:
                continue
            if d > 0:
                h = str(host)
                STATE["totals"][h] = STATE["totals"].get(h, 0) + d
                day_totals[h] = day_totals.get(h, 0) + d
                applied += d

        meta["last_seq"] = seq
        save_state()

    try:
        ts_iso = datetime.fromtimestamp(float(ts) / 1000.0, tz=timezone.utc).isoformat()
    except Exception:
        ts_iso = "n/a"

    log(f"[ADD] client={cid} seq={seq} applied={applied} date={bucket_day} ts={ts_iso}")
    return jsonify({"ok": True, "applied": applied, "last_seq": seq}), 200

@app.post("/reset")
def reset():
    _auth_or_403(request)
    snap = snapshot_totals()
    with _state_lock:
        STATE["totals"].clear()
        STATE["daily_totals"].clear()
        STATE["clients"].clear()
        save_state()
    log(f"[RESET] snapshot={snap}")
    
    # Trigger rollup
    try:
        perform_rollup()
    except Exception as e:
        log(f"[RESET] rollup failed: {e}")

    return jsonify({"ok": True, "snapshot": snap}), 200


@app.post("/flush")
def flush():
    _auth_or_403(request)
    save_state()
    log("[FLUSH] state.json written")
    return jsonify({"ok": True}), 200

# -----------------------
# Startup / Shutdown
# -----------------------
def _graceful_flush(signame: str):
    try:
        save_state()
        log(f"[SHUTDOWN] {signame}: state flushed")
    except Exception as e:
        log(f"[SHUTDOWN] {signame}: flush failed: {e}")

def _install_signal_handlers():
    for sig in ("SIGTERM", "SIGINT"):
        if hasattr(signal, sig):
            signal.signal(getattr(signal, sig), lambda *_: _graceful_flush(sig))

def _atexit_flush():
    _graceful_flush("atexit")

def _init():
    os.makedirs(os.path.dirname(STATE_PATH) or ".", exist_ok=True)
    os.makedirs(SNAP_DIR, exist_ok=True)
    loaded = load_state()
    with _state_lock:
        STATE.clear()
        STATE.update(loaded)
    log("[INIT] collector started; state loaded; paths: "
        f"STATE_PATH={STATE_PATH} SNAP_DIR={SNAP_DIR} LOG_PATH={LOG_PATH}")


# -----------------------
# Rollup Logic
# -----------------------
CSV_FILENAME = "snapshots.csv"

def _load_existing_csv(csv_path: Path) -> tuple[dict[str, dict[str, int]], list[str]]:
    """Load existing CSV content, returning per-date totals and column order."""
    if not csv_path.exists():
        return {}, []

    data = {}
    with csv_path.open(newline="") as fp:
        reader = csv.DictReader(fp)
        if reader.fieldnames is None:
            return {}, []

        columns = [col for col in reader.fieldnames if col != "date"]
        for row in reader:
            date_key = row.get("date")
            if not date_key:
                continue
            totals = {}
            for col in columns:
                raw = (row.get(col) or "").strip()
                if raw:
                    try:
                        totals[col] = int(raw)
                    except ValueError:
                        # Log but continue or re-raise? keeping it simple like original
                        pass
            data[date_key] = totals

        return data, columns

def _timestamp_to_date_str(timestamp_ms: str, cutoff_hour: int) -> str:
    """Convert a millisecond epoch string to an ISO date (UTC)."""
    try:
        ts = int(timestamp_ms)
    except ValueError:
        raise ValueError(f"Invalid timestamp: {timestamp_ms!r}")

    dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
    if dt.hour < cutoff_hour:
        dt -= timedelta(days=1)
    return dt.date().isoformat()

def _rollup_single_snapshot(path: Path, cutoff_hour: int) -> dict[str, dict[str, int]]:
    """Return per-date totals found in a snapshot JSON file."""
    stem = path.stem
    if not stem.startswith("snapshot_"):
        raise ValueError(f"Unexpected snapshot filename: {path.name}")
    timestamp_ms = stem.split("_", 1)[1]

    with path.open() as fp:
        payload = json.load(fp)

    daily_totals = _normalize_daily_totals(payload.get("daily_totals"))
    if daily_totals:
        return daily_totals

    totals = payload.get("totals")
    if not isinstance(totals, dict):
        raise ValueError(f"Snapshot {path.name} missing 'totals' dict")

    day = _timestamp_to_date_str(timestamp_ms, cutoff_hour)
    return {day: _normalize_totals(totals)}

def _write_csv_file(csv_path: Path, data: dict[str, dict[str, int]], columns: list[str]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["date"] + columns

    with csv_path.open("w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for day in sorted(data.keys()):
            row = {"date": day}
            daily_totals = data.get(day, {})
            for col in columns:
                row[col] = daily_totals.get(col, 0)
            writer.writerow(row)

def perform_rollup(cutoff_hour: int = 8) -> int:
    """Scans SNAP_DIR for snapshots, rolls them up into snapshots.csv, and renames processed files."""
    base_dir = Path(SNAP_DIR)
    csv_path = base_dir / CSV_FILENAME
    
    # Glob for all snapshot_*.json files
    snapshots = sorted(base_dir.glob("snapshot_*.json"))
    
    if not snapshots:
        # If no snapshots, ensure CSV exists at least
        if not csv_path.exists():
            _write_csv_file(csv_path, {}, [])
        return 0

    aggregated, column_order = _load_existing_csv(csv_path)
    seen_columns = set(column_order)
    processed = []

    for snapshot in snapshots:
        try:
            snapshot_daily_totals = _rollup_single_snapshot(snapshot, cutoff_hour)
        except ValueError as exc:
            log(f"[ROLLUP] Skipping {snapshot.name}: {exc}")
            continue

        for day, totals in snapshot_daily_totals.items():
            day_totals = aggregated.setdefault(day, {})
            for key, value in totals.items():
                day_totals[key] = day_totals.get(key, 0) + value
                if key not in seen_columns:
                    seen_columns.add(key)
                    column_order.append(key)
        
        processed.append(snapshot)

    if processed:
        _write_csv_file(csv_path, aggregated, column_order)
        for snapshot in processed:
            bak_path = snapshot.with_name(snapshot.name + ".bak")
            snapshot.replace(bak_path)
        log(f"[ROLLUP] Rolled up {len(processed)} snapshot(s) into {csv_path.name}")
    
    return len(processed)

_init()

_install_signal_handlers()
atexit.register(_atexit_flush)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9000, threaded=True)
