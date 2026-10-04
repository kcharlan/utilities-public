"""Turn private Codex rollout logs into scrubbed, synthetic-looking fixtures (maintainer tool).

Input is a private spec JSON (never committed) listing cases and their source rollout files:

    {"cases": [{"name": "s01_fork_depth1", "description": "...", "files": ["/abs/rollout-....jsonl", ...]}]}

Each case becomes ``<out>/<name>/codex-home`` plus ``case.json`` (the token_cases layout), so
``codexbar_expected.py --cases <out>`` produces its expected.json the same way.

Scrubbing is allowlist-based. Every record keeps its line position, top-level ``type``, ``ordinal``
and (shifted) ``timestamp``; payloads keep only the fields CodexBar's Codex parser reads
(CostUsageScanner.swift ``codexSessionMetadata``, the fast-line field list near line 3415, and
``CodexSubagentRolloutShape``) plus ``token_usage_record`` usage. Everything else is reduced to its
``type``. Fields upstream reads that the scrub keeps include ``turn_context`` ``payload.info.model``
and ``model_name``, the turn id keys ``codexTurnID`` reads (``turn_id``, ``turnId``, ``id`` on
``token_count`` payloads and their ``info``, and on ``task_started``), and the root ``model``.
``--validate`` is the proof that nothing accounting-relevant was dropped for a given input. Then:

  * session, thread, turn and response ids are replaced by generated ids (no mapping is written);
  * every timestamp, epoch field and file mtime moves by one whole-day offset that keeps the
    America/New_York UTC offset (no DST crossing), so local day buckets move as a block;
  * every token count is multiplied by TOKEN_SCALE (CodexBar's accounting is linear in them);
  * free text (cwd, agent paths, nicknames, titles, messages, instructions) never survives;
  * a final audit rejects any output string that is not a generated id, a synthetic constant,
    a model name, a record/payload type, or a timestamp.

``--validate --cli PATH`` additionally runs the pinned CodexBar CLI (via codexbar_expected) over a
private copy of the originals and over the scrubbed output, and requires the scrubbed rows to equal
the original rows after applying the same id map, time shift and token scale. Private copies live in
the codexbar_expected work directory, never in the repository.

Run (stdlib only):
    colophon/.venv/bin/python colophon/tests/tools/scrub_codex_logs.py --spec PRIVATE.json \
        [--out colophon/tests/fixtures/scrubbed] [--validate --cli PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codexbar_expected as ce  # noqa: E402  (single implementation of the guarded CLI run)

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "fixtures" / "scrubbed"
TOKEN_SCALE = 2
TARGET_FIRST_DAY = date(2025, 6, 2)  # daylight-saving time, like the real Jul-Oct 2026 sources
BUCKET_TZ = ZoneInfo("America/New_York")
TOKEN_FIELDS = ("input_tokens", "cached_input_tokens", "cache_read_input_tokens", "cache_write_input_tokens",
                "output_tokens", "reasoning_output_tokens", "total_tokens")
EPOCH_FIELDS = ("started_at", "completed_at")
TURN_ID_KEYS = ("turn_id", "turnId", "id")  # upstream codexTurnID: payload, then payload.info
SYNTHETIC_CONSTANTS = {"Codex Desktop", "0.0.0-synthetic", "openai", "vscode", "cli", "exec", "subagent",
                       "Agent", "synthetic", ""}
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-8[0-9a-f]{3}-[0-9a-f]{12}$")
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
MODEL_RE = re.compile(r"^(gpt|o\d|codex)[a-z0-9.\-]*$")
TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
GEN_RE = re.compile(r"^(turn|resp|call)-\d+$|^/synthetic/projects/[a-z]+$|^/root/agent_\d+(/agent_\d+)*$|^Agent-\d+$")


class Scrubber:
    def __init__(self, offset: timedelta):
        self.offset = offset
        self.ids: dict[str, str] = {}
        self.turns: dict[str, str] = {}
        self.responses: dict[str, str] = {}
        self.cwds: dict[str, str] = {}
        self.paths: dict[str, str] = {}

    # ---- value maps -------------------------------------------------------------------------
    def sid(self, value):
        if not isinstance(value, str) or not value.strip():
            return value
        key = value.strip()
        if key not in self.ids:
            n = len(self.ids) + 1
            ms = int((datetime.combine(TARGET_FIRST_DAY, datetime.min.time(), timezone.utc).timestamp()) * 1000) + n
            h = f"{ms:012x}"
            self.ids[key] = f"{h[:8]}-{h[8:12]}-7000-8000-{n:012x}"
        return self.ids[key]

    def turn(self, value):
        if not isinstance(value, str):
            return value
        return self.turns.setdefault(value, f"turn-{len(self.turns) + 1}")

    def response(self, value):
        if not isinstance(value, str):
            return value
        return self.responses.setdefault(value, f"resp-{len(self.responses) + 1}")

    def cwd(self, value):
        if not isinstance(value, str):
            return value
        letters = "abcdefghijklmnopqrstuvwxyz"
        return self.cwds.setdefault(value, f"/synthetic/projects/{letters[len(self.cwds) % 26]}")

    def agent_path(self, value):
        if not isinstance(value, str):
            return value
        depth = max(1, value.count("/") - 1)
        return self.paths.setdefault(value, "/root/" + "/".join(f"agent_{len(self.paths) + 1}" for _ in range(depth)))

    def ts(self, value):
        if not isinstance(value, str):
            return value
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        frac = value.split(".")[1].rstrip("Z") if "." in value else None
        out = (dt + self.offset).astimezone(timezone.utc)
        text = out.strftime("%Y-%m-%dT%H:%M:%S")
        return f"{text}.{frac}Z" if frac is not None else f"{text}Z"

    def epoch(self, value):
        return value + int(self.offset.total_seconds()) if isinstance(value, int) else value

    @staticmethod
    def usage(obj):
        if not isinstance(obj, dict):
            return None
        return {k: v * TOKEN_SCALE if isinstance(v, int) else v for k, v in obj.items() if k in TOKEN_FIELDS}

    # ---- records ------------------------------------------------------------------------------
    def session_meta(self, p: dict) -> dict:
        out: dict = {}
        for key in ("id", "session_id", "sessionId"):
            if key in p:
                out[key] = self.sid(p[key])
        if "timestamp" in p:
            out["timestamp"] = self.ts(p["timestamp"])
        if "cwd" in p:
            out["cwd"] = self.cwd(p["cwd"])
        out["originator"] = "Codex Desktop"
        out["cli_version"] = "0.0.0-synthetic"
        if "model_provider" in p:
            out["model_provider"] = "openai" if p["model_provider"] == "openai" else "openai"
        src = p.get("source")
        if isinstance(src, dict):
            spawn = ((src.get("subagent") or {}).get("thread_spawn") or {}) if isinstance(src.get("subagent"), dict) else {}
            if spawn:
                out["source"] = {"subagent": {"thread_spawn": {
                    "parent_thread_id": self.sid(spawn.get("parent_thread_id")),
                    "depth": spawn.get("depth"),
                    "agent_path": self.agent_path(spawn.get("agent_path")),
                    "agent_nickname": f"Agent-{spawn.get('depth') or 1}",
                    "agent_role": None}}}
            else:
                out["source"] = {"subagent": "subagent"} if "subagent" in src else {}
        elif isinstance(src, str):
            out["source"] = src if src in SYNTHETIC_CONSTANTS else "vscode"
        for key in ("forked_from_id", "forkedFromId", "parent_session_id", "parentSessionId", "parent_thread_id"):
            if key in p:
                out[key] = self.sid(p[key])
        if "agent_path" in p:
            out["agent_path"] = self.agent_path(p["agent_path"])
        if "agent_nickname" in p:
            out["agent_nickname"] = "Agent-1"
        if "subagent_history_start_ordinal" in p:
            out["subagent_history_start_ordinal"] = p["subagent_history_start_ordinal"]
        hb = p.get("history_base") or p.get("historyBase")
        if isinstance(hb, dict):
            out["history_base"] = {"thread_id": self.sid(hb.get("thread_id") or hb.get("threadId"))}
        return out

    def turn_context(self, p: dict) -> dict:
        out: dict = {}
        if "turn_id" in p:
            out["turn_id"] = self.turn(p["turn_id"])
        if "cwd" in p:
            out["cwd"] = self.cwd(p["cwd"])
        for key in ("model", "model_name"):
            if key in p:
                out[key] = p[key]
        info = p.get("info")
        if isinstance(info, dict):  # codexTurnContextModel also reads info.model / info.model_name
            kept = {k: info[k] for k in ("model", "model_name") if k in info}
            if kept:
                out["info"] = kept
        return out

    def token_count(self, p: dict) -> dict:
        out: dict = {"type": "token_count"}
        info = p.get("info")
        if isinstance(info, dict):
            oi: dict = {}
            for key in ("total_token_usage", "last_token_usage"):
                if key in info:
                    oi[key] = self.usage(info[key])
            for key in ("model_context_window",):
                if key in info:
                    oi[key] = info[key]
            for key in ("model", "model_name"):
                if key in info:
                    oi[key] = info[key]
            for key in TURN_ID_KEYS:
                if key in info:
                    oi[key] = self.turn(info[key])
            out["info"] = oi
        elif "info" in p:
            out["info"] = None
        for key in ("model", "model_name"):
            if key in p:
                out[key] = p[key]
        for key in TURN_ID_KEYS:
            if key in p:
                out[key] = self.turn(p[key])
        return out

    def event_msg(self, p: dict) -> dict:
        t = p.get("type")
        if t == "token_count":
            return self.token_count(p)
        out: dict = {"type": t}
        keys = TURN_ID_KEYS if t == "task_started" else ("turn_id",)
        for key in keys:
            if key in p:
                out[key] = self.turn(p[key])
        for key in EPOCH_FIELDS:
            if key in p:
                out[key] = self.epoch(p[key])
        return out

    def token_usage_record(self, p: dict) -> dict:
        out: dict = {}
        for key in ("thread_id", "root_thread_id"):
            if key in p:
                out[key] = self.sid(p[key])
        for key in ("turn_id", "root_turn_id"):
            if key in p:
                out[key] = self.turn(p[key])
        if "response_id" in p:
            out["response_id"] = self.response(p["response_id"])
        if "model" in p:
            out["model"] = p["model"]
        if "usage" in p:
            out["usage"] = self.usage(p["usage"])
        return out

    def record(self, obj: dict) -> dict:
        typ = obj.get("type")
        out: dict = {}
        for key in obj:  # preserve key order of the allowed top-level fields
            if key == "timestamp":
                out["timestamp"] = self.ts(obj["timestamp"])
            elif key == "ordinal":
                out["ordinal"] = obj["ordinal"]
            elif key == "type":
                out["type"] = typ
            elif key in ("id", "session_id", "sessionId") and typ == "session_meta":
                out[key] = self.sid(obj[key])
            elif key == "payload":
                p = obj["payload"]
                if not isinstance(p, dict):
                    out["payload"] = {}
                elif typ == "session_meta":
                    out["payload"] = self.session_meta(p)
                elif typ == "turn_context":
                    out["payload"] = self.turn_context(p)
                elif typ == "event_msg":
                    out["payload"] = self.event_msg(p)
                elif typ == "token_usage_record":
                    out["payload"] = self.token_usage_record(p)
                elif typ == "inter_agent_communication_metadata":
                    out["payload"] = {k: p[k] for k in ("trigger_turn",) if k in p}
                else:
                    out["payload"] = {k: p[k] for k in ("type", "role") if isinstance(p.get(k), str)}
            elif typ is None and key in ("usage",):
                out["usage"] = self.usage(obj["usage"])
            elif typ is None and key in ("data", "response", "result") and isinstance(obj[key], dict):
                out[key] = {"usage": self.usage(obj[key].get("usage"))} if "usage" in obj[key] else {}
            elif key in ("model", "model_name"):  # bare usage lines, and the root model upstream reads
                out[key] = obj[key]
        return out

    def line(self, raw: bytes) -> bytes:
        stripped = raw.rstrip(b"\n")
        if not stripped.strip():
            return raw  # keep empty lines: line indexes and boundary adjacency matter
        try:
            obj = json.loads(stripped)
        except ValueError:
            return b"not-json-placeholder" + (b"\n" if raw.endswith(b"\n") else b"")
        if not isinstance(obj, dict):
            return b"[]" + (b"\n" if raw.endswith(b"\n") else b"")
        text = json.dumps(self.record(obj), separators=(",", ":"), ensure_ascii=True).encode()
        return text + (b"\n" if raw.endswith(b"\n") else b"")


def file_offset(paths: list[Path]) -> timedelta:
    first = None
    for path in paths:
        with path.open("rb") as fh:
            for raw in fh:
                try:
                    ts = json.loads(raw).get("timestamp")
                except (ValueError, AttributeError):
                    continue
                if ts:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    first = dt if first is None else min(first, dt)
    if first is None:
        raise ValueError("no timestamps in the source files")
    local_first = first.astimezone(BUCKET_TZ).date()
    offset = timedelta(days=(TARGET_FIRST_DAY - local_first).days)
    return offset


def check_offset_keeps_tz(paths: list[Path], offset: timedelta) -> None:
    for path in paths:
        with path.open("rb") as fh:
            for raw in fh:
                try:
                    ts = json.loads(raw).get("timestamp")
                except (ValueError, AttributeError):
                    continue
                if not ts:
                    continue
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.astimezone(BUCKET_TZ).utcoffset() != (dt + offset).astimezone(BUCKET_TZ).utcoffset():
                    raise ValueError(f"time shift crosses a DST change for {path.name}; pick another target day")


def audit(home: Path, scrubber: Scrubber) -> None:
    generated = set(scrubber.ids.values()) | set(scrubber.turns.values()) | set(scrubber.responses.values()) \
        | set(scrubber.cwds.values()) | set(scrubber.paths.values())

    def string_ok(key: str, value: str) -> bool:
        if key in ("type", "role"):
            return bool(TYPE_RE.match(value))
        if key in ("model", "model_name"):
            return bool(MODEL_RE.match(value))
        if key == "timestamp":
            return bool(TS_RE.match(value))
        return value in generated or value in SYNTHETIC_CONSTANTS or bool(GEN_RE.match(value))

    def walk(value, where, key=""):
        if isinstance(value, dict):
            for k, v in value.items():
                if not TYPE_RE.match(k) and k not in ("sessionId", "forkedFromId", "parentSessionId", "historyBase", "turnId"):
                    raise ValueError(f"audit: unexpected key {k!r} in {where}")
                walk(v, where, k)
        elif isinstance(value, list):
            for v in value:
                walk(v, where, key)
        elif isinstance(value, str) and not string_ok(key, value):
            raise ValueError(f"audit: string not allowlisted for key {key!r} in {where}: {value[:60]!r}")
    for path in sorted(home.rglob("*.jsonl")):
        for raw in path.read_bytes().splitlines():
            if not raw.strip() or raw == b"not-json-placeholder" or raw == b"[]":
                continue
            try:
                walk(json.loads(raw), path.name)
            except ValueError as exc:
                if str(exc).startswith("audit:"):
                    raise
                # a scrubbed partial tail is allowed only as an exact synthetic fragment
                if raw != b'{"timestamp":"':
                    raise ValueError(f"audit: unparseable line in {path.name}")
        if not UUID_RE.match(path.stem[-36:]) or path.stem[-36:] not in generated:
            raise ValueError(f"audit: file name not generated: {path.name}")


def scrub_case(case: dict, out_root: Path) -> tuple[Path, Scrubber]:
    sources = [Path(p) for p in case["files"]]
    offset = file_offset(sources)
    check_offset_keeps_tz(sources, offset)
    scrubber = Scrubber(offset)
    case_dir = out_root / case["name"]
    if case_dir.exists():
        shutil.rmtree(case_dir)
    home = case_dir / "codex-home"
    mapping: dict[str, str] = {}
    for src in sources:
        raw = src.read_bytes()
        lines = raw.splitlines(keepends=True)
        body = []
        for i, line in enumerate(lines):
            is_tail = i == len(lines) - 1 and not line.endswith(b"\n")
            if is_tail:
                try:
                    json.loads(line)
                except ValueError:
                    body.append(b'{"timestamp":"')  # incomplete trailing segment, contents dropped
                    continue
            body.append(scrubber.line(line))
        first = json.loads(lines[0])
        new_sid = scrubber.sid((first.get("payload") or {}).get("id"))
        archived = "archived_sessions" in src.parts
        stamp = re.match(r"rollout-(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})-", src.name).group(1)
        new_stamp = (datetime.strptime(stamp, "%Y-%m-%dT%H-%M-%S") + offset).strftime("%Y-%m-%dT%H-%M-%S")
        sub = Path("archived_sessions") if archived else Path("sessions") / new_stamp[:4] / new_stamp[5:7] / new_stamp[8:10]
        dest = home / sub / f"rollout-{new_stamp}-{new_sid}.jsonl"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"".join(body))
        mtime = src.stat().st_mtime + offset.total_seconds()
        os.utime(dest, (mtime, mtime))
        mapping[str(src)] = dest.relative_to(home).as_posix()
    audit(home, scrubber)
    files = sorted(p.relative_to(home).as_posix() for p in home.rglob("*.jsonl"))
    mtimes = {p.relative_to(home).as_posix(): int(p.stat().st_mtime_ns // 1_000_000) for p in home.rglob("*.jsonl")}
    meta = {"name": case["name"], "description": case["description"], "files": files, "mtimes_ms": mtimes,
            "scrub": {"token_scale": TOKEN_SCALE, "tool": "colophon/tests/tools/scrub_codex_logs.py"}}
    (case_dir / "case.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    scrubber.file_map = mapping  # in memory only, for validation
    return case_dir, scrubber


def private_original_case(case: dict, work: Path) -> Path:
    """Copy originals (same relative layout) into the private work dir for the validation run."""
    d = work / "private-originals" / case["name"]
    if d.exists():
        shutil.rmtree(d)
    home = d / "codex-home"
    mt = {}
    for src in map(Path, case["files"]):
        rel = Path("archived_sessions") / src.name if "archived_sessions" in src.parts else \
            Path("sessions") / src.parent.relative_to(src.parents[3]) / src.name
        dest = home / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        mt[rel.as_posix()] = int(dest.stat().st_mtime_ns // 1_000_000)
    (d / "case.json").write_text(json.dumps({"name": case["name"], "mtimes_ms": mt}), encoding="utf-8")
    return d


def compare(case: dict, scrubber: Scrubber, original: dict, scrubbed: dict) -> list[str]:
    problems = []
    off_ms = int(scrubber.offset.total_seconds() * 1000)
    by_name = {Path(k).name: v for k, v in scrubber.file_map.items()}
    scr_files = {f["file"]: f for f in scrubbed["files"]}
    for f in original["files"]:
        target = by_name.get(Path(f["file"]).name)
        sf = scr_files.get(target)
        if sf is None:
            problems.append(f"no scrubbed file for {Path(f['file']).name[:24]}...")
            continue
        if len(f["rows"]) != len(sf["rows"]):
            problems.append(f"{target}: row count {len(f['rows'])} vs {len(sf['rows'])}")
            continue
        for a, b in zip(f["rows"], sf["rows"]):
            exp = dict(a)
            for k in ("input", "cached", "output", "reasoning"):
                exp[k] = a[k] * TOKEN_SCALE
            if a.get("timestampUnixMs") is not None:
                exp["timestampUnixMs"] = a["timestampUnixMs"] + off_ms
            exp["day"] = (date.fromisoformat(a["day"]) + timedelta(days=scrubber.offset.days)).isoformat()
            if a.get("turnID") is not None:
                exp["turnID"] = scrubber.turns.get(a["turnID"], f"<unmapped {a['turnID'][:8]}>")
            if exp != b:
                diffs = sorted(k for k in set(exp) | set(b) if exp.get(k) != b.get(k))
                problems.append(f"{target} row {a.get('row_index')}: fields differ {diffs}")
                break
    for key in ("historyCoverageIsEstablished", "coverage"):
        if original["report"][key] != scrubbed["report"][key]:
            problems.append(f"report {key}: {original['report'][key]} vs {scrubbed['report'][key]}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--cli", type=Path)
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for case in spec["cases"]:
        case_dir, scrubber = scrub_case(case, out)
        results.append((case, case_dir, scrubber))
        print(f"scrubbed {case['name']}: {len(scrubber.ids)} ids, offset {scrubber.offset.days} days")
    (out / "index.json").write_text(json.dumps([c["name"] for c in spec["cases"]], indent=2) + "\n", encoding="utf-8")
    if not args.validate:
        return 0
    if args.cli is None:
        parser.error("--validate needs --cli")
    cli = args.cli.expanduser().resolve()
    if ce.sha256_file(cli) != ce.PINNED_CLI_SHA256:
        raise ce.GuardError("CLI is not the pinned build")
    if ce.app_running():
        raise ce.GuardError("quit the CodexBar app first")
    work = ce.DEFAULT_WORK
    work.mkdir(parents=True, exist_ok=True)
    ce.require_symlink_free(work)
    catalog = json.loads((ce.DEFAULT_CASES / "catalog.json").read_text(encoding="utf-8"))
    failed = 0
    with tempfile.TemporaryDirectory(prefix="colophon-cb-guard-") as gdir:
        profile = Path(gdir) / "guard.sb"
        profile.write_text(ce.profile_text(), encoding="utf-8")
        ce.self_test_guard(profile)
        before = ce.real_state_fingerprint()
        try:
            for case, case_dir, scrubber in results:
                orig_dir = work / "private-originals" / case["name"]
                try:
                    orig_dir = private_original_case(case, work)
                    original, _ = ce.run_case(cli, profile, orig_dir, work / "validate-original", catalog)
                    scrubbed, _ = ce.run_case(cli, profile, case_dir, work / "validate-scrubbed", catalog)
                finally:  # private copies never outlive the run, even when it fails
                    shutil.rmtree(orig_dir, ignore_errors=True)
                    shutil.rmtree(work / "validate-original" / case["name"], ignore_errors=True)
                problems = compare(case, scrubber, original, scrubbed)
                rows = sum(len(f["rows"]) for f in original["files"])
                if problems:
                    failed += 1
                    print(f"VALIDATION FAILED {case['name']}:", *problems[:10], sep="\n  ")
                else:
                    print(f"validated {case['name']}: {rows} rows match after id map, x{TOKEN_SCALE}, "
                          f"{scrubber.offset.days}-day shift; established={original['report']['historyCoverageIsEstablished']}")
        finally:
            after = ce.real_state_fingerprint()
        if after != before:
            print("ERROR: the real CodexBar cache or preferences changed", file=sys.stderr)
            return 2
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ce.GuardError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(3)
