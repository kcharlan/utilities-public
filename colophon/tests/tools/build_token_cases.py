"""Build the synthetic token-accounting cases for Colophon's staged CodexBar port (Task 14).

Each case is a tiny, conspicuously synthetic Codex home under
``colophon/tests/fixtures/token_cases/<case>/codex-home``. Every case is self-contained and is
written on its own calendar day (CodexBar buckets one a12 row on the previous day).
Expected outputs are produced separately by ``codexbar_expected.py`` with a CodexBar CLI
built from the pinned upstream commit; this script only writes inputs plus ``case.json``.

Run (stdlib only, no shebang by design):
    colophon/.venv/bin/python colophon/tests/tools/build_token_cases.py [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "fixtures" / "token_cases"
BASE_DAY = datetime(2025, 3, 1, 9, 0, 0, tzinfo=timezone.utc)
MODEL = "gpt-5.6-sol"

# Pinned models.dev-shaped catalog (openai subset). codexbar_expected.py seeds it as CodexBar's
# models.dev cache so the costs in expected.json are reproducible; Colophon's Task 14 tests compare
# tokens only and do not read it. Rates are synthetic (deliberately not real prices). gpt-5.6-terra
# is absent here, but CodexBar still prices it from its built-in historical rates; the unpriced
# row in a10 is the one with no model evidence ("unknown").
CATALOG = {
    "openai": {
        "id": "openai",
        "name": "OpenAI",
        "models": {
            "gpt-5.4": {"id": "gpt-5.4", "name": "GPT-5.4", "limit": {"context": 1050000},
                        "cost": {"input": 1.5, "cache_read": 0.15, "output": 9,
                                 "context_over_200k": {"input": 3, "cache_read": 0.3, "output": 13.5}}},
            "gpt-5.5": {"id": "gpt-5.5", "name": "GPT-5.5", "limit": {"context": 1050000},
                        "cost": {"input": 3, "cache_read": 0.3, "output": 18,
                                 "context_over_200k": {"input": 6, "cache_read": 0.6, "output": 27}}},
            "gpt-5.6-sol": {"id": "gpt-5.6-sol", "name": "GPT-5.6 Sol", "limit": {"context": 1050000},
                            "cost": {"input": 2, "cache_read": 0.2, "cache_write": 2.5, "output": 12,
                                     "context_over_200k": {"input": 4, "cache_read": 0.4, "cache_write": 5,
                                                           "output": 18}}},
        },
    }
}


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def uuid7(at: datetime, seq: int) -> str:
    ms = int(at.timestamp() * 1000)
    h = f"{ms:012x}"
    tail = f"{seq:015x}"[-15:]
    return f"{h[:8]}-{h[8:12]}-7{tail[:3]}-8{tail[3:6]}-{tail[6:15]}000"[:36]


def usage(i: int, c: int, o: int, r: int = 0, cw: int = 0) -> dict:
    return {"input_tokens": i, "cached_input_tokens": c, "cache_write_input_tokens": cw,
            "output_tokens": o, "reasoning_output_tokens": r, "total_tokens": i + o}


class Log:
    """Appends compact Codex-shaped records with a monotonic synthetic clock."""

    def __init__(self, day_index: int, start_offset_min: int = 0):
        self.clock = BASE_DAY + timedelta(days=day_index, minutes=start_offset_min)
        self.lines: list[str] = []
        self.ordinal = 0

    def tick(self, seconds: float = 5.0) -> datetime:
        self.clock += timedelta(seconds=seconds)
        return self.clock

    def rec(self, typ: str | None, payload: dict | None, *, at: datetime | None = None,
            with_ts: bool = True, extra: dict | None = None) -> "Log":
        at = at or self.tick()
        obj: dict = {}
        if with_ts:
            obj["timestamp"] = iso(at)
        obj["ordinal"] = self.ordinal
        if typ is not None:
            obj["type"] = typ
        if payload is not None:
            obj["payload"] = payload
        if extra:
            obj.update(extra)
        self.ordinal += 1
        self.lines.append(json.dumps(obj, separators=(",", ":")))
        return self

    def meta(self, sid: str, *, at: datetime | None = None, forked_from: str | None = None,
             subagent_parent: str | None = None, depth: int = 1, agent_path: str = "/root/synthetic_task",
             history_start_ordinal: int | None = None, history_base: str | None = None,
             payload_ts: bool | str = True, wrapper_ts: bool = True, payload_at: datetime | None = None) -> "Log":
        """``at`` is the record (wrapper) time; ``payload_at`` overrides the payload's own timestamp.

        Real logs never step back in time after a session_meta: Codex rewrites copied-prefix record
        timestamps to the fork time or later, so an ``at`` ahead of the clock advances the clock.
        Embedded ancestor metas keep the ancestor's original creation time only in the payload.
        """
        at = at or self.tick(1)
        if at > self.clock:
            self.clock = at
        p: dict = {"session_id": sid, "id": sid}
        if isinstance(payload_ts, str):
            p["timestamp"] = payload_ts  # deliberately unparseable text
        elif payload_ts:
            p["timestamp"] = iso(payload_at or at)
        p.update({"cwd": "/synthetic/projects/alpha", "originator": "Codex Desktop",
                  "cli_version": "0.0.0-synthetic", "model_provider": "openai"})
        if subagent_parent is not None:
            p["source"] = {"subagent": {"thread_spawn": {"parent_thread_id": subagent_parent, "depth": depth,
                                                         "agent_path": agent_path,
                                                         "agent_nickname": "Agent-Alpha", "agent_role": None}}}
            p["parent_thread_id"] = subagent_parent
            p["agent_path"] = agent_path
            p["agent_nickname"] = "Agent-Alpha"
        else:
            p["source"] = "vscode"
        if forked_from is not None:
            p["forked_from_id"] = forked_from
        if history_start_ordinal is not None:
            p["subagent_history_start_ordinal"] = history_start_ordinal
        if history_base is not None:
            p["history_base"] = {"thread_id": history_base}
        return self.rec("session_meta", p, at=at, with_ts=wrapper_ts)

    def turn_context(self, model: str | None = MODEL, *, extra_payload: dict | None = None) -> "Log":
        p: dict = {"turn_id": "turn-ctx", "cwd": "/synthetic/projects/alpha"}
        if model is not None:
            p["model"] = model
        if extra_payload:
            p.update(extra_payload)
        return self.rec("turn_context", p)

    def task_started(self, turn_id: str) -> "Log":
        at = self.tick()
        return self.rec("event_msg", {"type": "task_started", "turn_id": turn_id,
                                      "started_at": int(at.timestamp())}, at=at)

    def task_complete(self, turn_id: str) -> "Log":
        at = self.tick()
        return self.rec("event_msg", {"type": "task_complete", "turn_id": turn_id,
                                      "completed_at": int(at.timestamp())}, at=at)

    def token_count(self, total: tuple | None, last: tuple | None, *, info_extra: dict | None = None,
                    payload_extra: dict | None = None, root_extra: dict | None = None) -> "Log":
        info: dict = {}
        if total is not None:
            info["total_token_usage"] = usage(*total)
        if last is not None:
            info["last_token_usage"] = usage(*last)
        info["model_context_window"] = 272000
        if info_extra:
            info.update(info_extra)
        p = {"type": "token_count", "info": info}
        if payload_extra:
            p.update(payload_extra)
        return self.rec("event_msg", p, extra=root_extra)

    def thread_settings(self) -> "Log":
        """Real subagent logs open their owned history with this record at subagent_history_start_ordinal."""
        return self.rec("event_msg", {"type": "thread_settings_applied"})

    def inter_agent(self, trigger: bool = True) -> "Log":
        return self.rec("inter_agent_communication_metadata", {"trigger_turn": trigger})

    def bare(self, usage_obj: dict, *, model: str | None = None, container: str | None = None,
             with_ts: bool = True) -> "Log":
        at = self.tick()
        obj: dict = {}
        if with_ts:
            obj["timestamp"] = iso(at)
        if model is not None:
            obj["model"] = model
        if container:
            obj[container] = {"usage": usage_obj}
        else:
            obj["usage"] = usage_obj
        self.lines.append(json.dumps(obj, separators=(",", ":")))
        return self

    def raw(self, text: str) -> "Log":
        self.lines.append(text)
        return self

    def write(self, home: Path, sid: str, *, archived: bool = False, tail: str | None = None,
              mtime_offset_s: int = 0) -> Path:
        day = self.clock.strftime("%Y/%m/%d")
        stamp = self.clock.strftime("%Y-%m-%dT%H-%M-%S")
        root = home / ("archived_sessions" if archived else f"sessions/{day}")
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"rollout-{stamp}-{sid}.jsonl"
        body = "\n".join(self.lines) + "\n"
        if tail is not None:
            body += tail
        path.write_text(body, encoding="utf-8")
        mtime = (self.clock + timedelta(seconds=mtime_offset_s)).timestamp()
        os.utime(path, (mtime, mtime))
        return path


CASES: list[tuple[str, str, object]] = []


def case(name: str, description: str):
    def wrap(fn):
        CASES.append((name, description, fn))
        return fn
    return wrap


def sid_for(day: int, n: int) -> str:
    return uuid7(BASE_DAY + timedelta(days=day), n)


# ---------- single-file state-machine cases (stage A) ----------

@case("a01_basic", "Plain cumulative totals with matching last deltas.")
def _a01(home: Path, day: int):
    sid = sid_for(day, 1)
    log = Log(day).meta(sid).turn_context().task_started("t1")
    log.token_count((1000, 0, 100), (1000, 0, 100))
    log.token_count((2500, 800, 250), (1500, 800, 150))
    log.token_count((4000, 2000, 400), (1500, 1200, 150))
    log.task_complete("t1").write(home, sid)


@case("a02_first_event_divergent", "First event total exceeds last (resumed counter): divergence latches.")
def _a02(home: Path, day: int):
    sid = sid_for(day, 1)
    log = Log(day).meta(sid).turn_context().task_started("t1")
    log.token_count((50000, 40000, 2000), (1000, 0, 100))
    log.token_count((52000, 41000, 2200), (2000, 1000, 200))
    log.token_count((53500, 42000, 2300), (1500, 1000, 100))
    log.task_complete("t1").write(home, sid)


@case("a03_gap_vs_last", "Total delta smaller than last, then a gap larger than last.")
def _a03(home: Path, day: int):
    sid = sid_for(day, 1)
    log = Log(day).meta(sid).turn_context().task_started("t1")
    log.token_count((1000, 0, 100), (1000, 0, 100))
    log.token_count((1800, 300, 180), (1000, 300, 100))
    log.token_count((5000, 1000, 500), (1000, 300, 100))
    log.task_complete("t1").write(home, sid)


@case("a04_repeated_total", "An identical cumulative total repeated is counted once.")
def _a04(home: Path, day: int):
    sid = sid_for(day, 1)
    log = Log(day).meta(sid).turn_context().task_started("t1")
    log.token_count((1000, 0, 100), (1000, 0, 100))
    log.token_count((2000, 500, 200), (1000, 500, 100))
    log.token_count((2000, 500, 200), (1000, 500, 100))
    log.token_count((3000, 1200, 300), (1000, 700, 100))
    log.task_complete("t1").write(home, sid)


@case("a05_stale_regression", "A total that falls back by about one recent increment is stale.")
def _a05(home: Path, day: int):
    sid = sid_for(day, 1)
    log = Log(day).meta(sid).turn_context().task_started("t1")
    log.token_count((1000, 0, 100), (1000, 0, 100))
    log.token_count((2000, 500, 200), (1000, 500, 100))
    log.token_count((1000, 0, 100), (1000, 500, 100))
    log.token_count((3000, 1200, 300), (1000, 700, 100))
    log.task_complete("t1").write(home, sid)


@case("a06_counter_restart", "A counter drop below the watermark latches interleaved mode.")
def _a06(home: Path, day: int):
    sid = sid_for(day, 1)
    log = Log(day).meta(sid).turn_context().task_started("t1")
    log.token_count((10000, 5000, 1000), (10000, 5000, 1000))
    log.token_count((12000, 6000, 1200), (2000, 1000, 200))
    log.token_count((1500, 500, 150), (1500, 500, 150))
    log.token_count((3500, 1500, 350), (2000, 1000, 200))
    log.token_count((14000, 7000, 1400), (2000, 1000, 200))
    log.task_complete("t1").write(home, sid)


@case("a07_total_only", "Events with a total and no last count the total delta.")
def _a07(home: Path, day: int):
    sid = sid_for(day, 1)
    log = Log(day).meta(sid).turn_context().task_started("t1")
    log.token_count((1000, 0, 100), (1000, 0, 100))
    log.token_count((2500, 900, 260), None)
    log.token_count((4000, 1800, 400), None)
    log.task_complete("t1").write(home, sid)


@case("a08_bare_usage", "Typeless bare usage lines: line model, data container, model in force, unknown, outside a turn.")
def _a08(home: Path, day: int):
    sid = sid_for(day, 1)
    log = Log(day).meta(sid)
    log.bare({"input_tokens": 700, "cached_input_tokens": 200, "output_tokens": 70}, model=None)
    log.turn_context("gpt-5.4").task_started("t1")
    log.bare({"input_tokens": 1000, "cached_input_tokens": 400, "output_tokens": 100}, model="gpt-5.5")
    log.bare({"input_tokens": 1200, "cached_input_tokens": 0, "output_tokens": 120}, container="data")
    log.bare({"input_tokens": 900, "cached_input_tokens": 300, "output_tokens": 90})
    log.task_complete("t1").write(home, sid)


@case("a09_model_in_force", "turn_context model tri-state: set, blank-then-set, all blank clears, omitted keeps.")
def _a09(home: Path, day: int):
    sid = sid_for(day, 1)
    log = Log(day).meta(sid)
    log.turn_context(None, extra_payload={"model": "  ", "model_name": "gpt-5.4"}).task_started("t1")
    log.token_count((1000, 0, 100), (1000, 0, 100))
    log.turn_context(None, extra_payload={"cwd": "/synthetic/projects/alpha"})
    log.token_count((2000, 0, 200), (1000, 0, 100))
    log.turn_context(None, extra_payload={"model": "", "model_name": " "})
    log.token_count((3000, 0, 300), (1000, 0, 100), info_extra={"model": "gpt-5.5"})
    log.task_complete("t1").write(home, sid)


@case("a10_token_count_model_fallback", "No turn_context: token_count model evidence order and unknown.")
def _a10(home: Path, day: int):
    sid = sid_for(day, 1)
    log = Log(day).meta(sid).task_started("t1")
    log.token_count((1000, 0, 100), (1000, 0, 100), info_extra={"model_name": "gpt-5.4"})
    log.token_count((2000, 0, 200), (1000, 0, 100), payload_extra={"model": "gpt-5.5"})
    log.token_count((3000, 0, 300), (1000, 0, 100), root_extra={"model": "gpt-5.6-terra"})
    log.token_count((4000, 0, 400), (1000, 0, 100))
    log.task_complete("t1").write(home, sid)


@case("a11_model_normalization",
      "Row models through normalizeCodexModel: openai/ prefix, gpt-5.6 and gpt-reserve aliases, "
      "a dated suffix on a bundled base, and a compact date that is not folded.")
def _a11(home: Path, day: int):
    sid = sid_for(day, 1)
    log = Log(day).meta(sid).task_started("t1")
    total = [0, 0, 0]
    for model in ("openai/gpt-5.5", "gpt-5.6", "gpt-reserve", "gpt-5.4-2026-03-05", "gpt-5.4-20260305"):
        log.turn_context(model)
        total = [total[0] + 1000, total[1] + 400, total[2] + 100]
        log.token_count(tuple(total), (1000, 400, 100))
    log.task_complete("t1").write(home, sid)


@case("a12_lenient_timestamp",
      "A space-separated timestamp: the lenient day-key parser accepts it (time zeroed, so the row lands "
      "on the previous New York day) but ISO parsing rejects it (no timestampUnixMs); a date-only "
      "timestamp is rejected by both and its token_count is dropped.")
def _a12(home: Path, day: int):
    sid = sid_for(day, 1)
    log = Log(day).meta(sid).turn_context().task_started("t1")
    date = log.clock.strftime("%Y-%m-%d")
    log.token_count((1000, 0, 100), (1000, 0, 100))
    log.token_count((2000, 0, 200), (1000, 0, 100), root_extra={"timestamp": f"{date} 09:30:00Z"})
    log.token_count((3000, 0, 300), (1000, 0, 100), root_extra={"timestamp": date})
    log.token_count((4000, 0, 400), (1000, 0, 100))
    log.task_complete("t1").write(home, sid)


# ---------- forks (stage B) ----------

def _parent(home: Path, day: int, n: int, totals: list[tuple], *, offset_min: int = 0) -> tuple[str, Log]:
    sid = sid_for(day, n)
    log = Log(day, offset_min).meta(sid).turn_context().task_started(f"p{n}")
    prev = (0, 0, 0)
    for t in totals:
        last = (t[0] - prev[0], t[1] - prev[1], t[2] - prev[2])
        log.token_count(t, last)
        prev = t
    log.task_complete(f"p{n}")
    return sid, log


def _fork_child(day: int, n: int, parent: str, fork_at: datetime, copied: list[tuple], own: list[tuple],
                ancestors: list[tuple[str, datetime]] | None = None, **meta_kwargs) -> tuple[str, Log]:
    """``ancestors`` are (session id, original creation time), outermost first; default is the parent."""
    sid = sid_for(day, n)
    log = Log(day, 30)
    log.meta(sid, at=fork_at, forked_from=parent, **meta_kwargs)
    for ancestor, created in ancestors or [(parent, fork_at - timedelta(minutes=30))]:
        log.meta(ancestor, payload_at=created)  # embedded ancestor metadata (copied prefix)
    prev = (0, 0, 0)
    for t in copied:
        last = (t[0] - prev[0], t[1] - prev[1], t[2] - prev[2])
        log.token_count(t, last)
        prev = t
    log.turn_context().task_started(f"c{n}")
    for t in own:
        last = (t[0] - prev[0], t[1] - prev[1], t[2] - prev[2])
        log.token_count(t, last)
        prev = t
    log.task_complete(f"c{n}")
    return sid, log


PARENT_TOTALS = [(10000, 4000, 1000), (20000, 12000, 2000)]
CHILD_OWN = [(26000, 16000, 2600), (31000, 20000, 3100)]


@case("b01_fork_parent_present", "Forked session with its parent log present: inherited totals subtracted.")
def _b01(home: Path, day: int):
    psid, plog = _parent(home, day, 1, PARENT_TOTALS)
    path = plog.write(home, psid)
    csid, clog = _fork_child(day, 2, psid, plog.clock + timedelta(minutes=1), PARENT_TOTALS, CHILD_OWN)
    clog.write(home, csid)


@case("b02_fork_parent_missing", "Forked session whose parent log is missing: fork baseline unresolved.")
def _b02(home: Path, day: int):
    psid = sid_for(day, 1)
    csid, clog = _fork_child(day, 2, psid, BASE_DAY + timedelta(days=day, minutes=10), PARENT_TOTALS, CHILD_OWN)
    clog.write(home, csid)


@case("b03_fork_timestamp_missing", "Forked session whose session_meta has no timestamp: unresolved.")
def _b03(home: Path, day: int):
    psid, plog = _parent(home, day, 1, PARENT_TOTALS)
    plog.write(home, psid)
    csid, clog = _fork_child(day, 2, psid, plog.clock + timedelta(minutes=1), PARENT_TOTALS, CHILD_OWN,
                             payload_ts=False, wrapper_ts=False)
    clog.write(home, csid)


def _fork_of_fork(home: Path, day: int, *, parents_written_last: bool) -> None:
    gsid, glog = _parent(home, day, 1, PARENT_TOTALS)
    psid, plog = _fork_child(day, 2, gsid, glog.clock + timedelta(minutes=1), PARENT_TOTALS, CHILD_OWN)
    copied = PARENT_TOTALS + CHILD_OWN
    own = [(36000, 24000, 3600), (40000, 27000, 4000)]
    created = BASE_DAY + timedelta(days=day)
    csid, clog = _fork_child(day, 3, psid, plog.clock + timedelta(minutes=1), copied, own,
                             ancestors=[(gsid, created), (psid, created + timedelta(minutes=30))])
    clog.write(home, csid)
    # Parents that keep writing after the fork end up newer than the grandchild.
    later = 3 * 3600 if parents_written_last else 0
    glog.write(home, gsid, mtime_offset_s=later)
    plog.write(home, psid, mtime_offset_s=later + 600 if later else 0)


@case("b04_fork_of_fork", "Grandparent, forked parent, forked child; both parents modified after the child.")
def _b04(home: Path, day: int):
    _fork_of_fork(home, day, parents_written_last=True)


@case("b05_fork_of_fork_missing_grandparent", "Fork of a fork whose grandparent log is missing.")
def _b05(home: Path, day: int):
    gsid = sid_for(day, 1)
    psid, plog = _fork_child(day, 2, gsid, BASE_DAY + timedelta(days=day, minutes=5), PARENT_TOTALS, CHILD_OWN)
    plog.write(home, psid)
    copied = PARENT_TOTALS + CHILD_OWN
    own = [(36000, 24000, 3600)]
    csid, clog = _fork_child(day, 3, psid, plog.clock + timedelta(minutes=1), copied, own)
    clog.write(home, csid)


@case("b06_history_base_continued_counter", "Fork whose history_base differs from forked_from: raised baseline.")
def _b06(home: Path, day: int):
    psid, plog = _parent(home, day, 1, [(5000, 2000, 500)])
    plog.write(home, psid)
    other = sid_for(day, 9)
    csid = sid_for(day, 2)
    log = Log(day, 30).meta(csid, at=plog.clock + timedelta(minutes=1), forked_from=psid, history_base=other)
    log.turn_context().task_started("c2")
    log.token_count((60000, 30000, 6000), (2000, 1000, 200))
    log.token_count((63000, 31500, 6300), (3000, 1500, 300))
    log.task_complete("c2").write(home, csid)


@case("b07_fork_parent_header_only", "Fork whose parent log is header-only (session_meta only).")
def _b07(home: Path, day: int):
    psid = sid_for(day, 1)
    Log(day).meta(psid).write(home, psid)
    csid = sid_for(day, 2)
    log = Log(day, 30).meta(csid, at=BASE_DAY + timedelta(days=day, minutes=20), forked_from=psid)
    log.turn_context().task_started("c2")
    log.token_count((3000, 1000, 300), (3000, 1000, 300))
    log.token_count((5000, 2000, 500), (2000, 1000, 200))
    log.task_complete("c2").write(home, csid)


@case("b08_fork_parent_unconsumed_tail",
      "Fork parent ends in an incomplete JSON segment and its last event precedes the fork: unresolved.")
def _b08(home: Path, day: int):
    psid, plog = _parent(home, day, 1, PARENT_TOTALS)
    plog.write(home, psid, tail='{"timestamp":"2025-')
    csid, clog = _fork_child(day, 2, psid, plog.clock + timedelta(minutes=30), PARENT_TOTALS, CHILD_OWN)
    clog.write(home, csid)


@case("b09_fork_parent_tail_covers_cutoff",
      "Fork parent ends in an incomplete JSON segment but its events reach past the fork time: resolved.")
def _b09(home: Path, day: int):
    psid, plog = _parent(home, day, 1, PARENT_TOTALS)
    plog.write(home, psid, tail='{"timestamp":"2025-')
    first_tc = next(json.loads(line)["timestamp"] for line in plog.lines
                    if '"type":"token_count"' in line)
    fork_at = datetime.strptime(first_tc, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc) + timedelta(seconds=1)
    csid, clog = _fork_child(day, 2, psid, fork_at, PARENT_TOTALS[:1],
                             [(15000, 6000, 1500), (18000, 8000, 1800)])
    clog.write(home, csid)


@case("b10_fork_of_fork_scan_order",
      "As b04, but the grandchild is the newest file: CodexBar's newest-first incremental scan leaves it "
      "unresolved (an upstream scan-order artifact; see the plan's decision on this case).")
def _b10(home: Path, day: int):
    _fork_of_fork(home, day, parents_written_last=False)


@case("b11_fork_timestamp_unparseable",
      "Forked session whose fork timestamp is unparseable text: lexical cutoff comparison.")
def _b11(home: Path, day: int):
    psid, plog = _parent(home, day, 1, PARENT_TOTALS)
    plog.write(home, psid)
    csid, clog = _fork_child(day, 2, psid, plog.clock + timedelta(minutes=1), PARENT_TOTALS, CHILD_OWN,
                             payload_ts="sometime after the parent", wrapper_ts=False)
    clog.write(home, csid)


# ---------- subagents (stage C) ----------

def _subagent_prefix(log: Log, parent: str, parent_totals: list[tuple]) -> tuple:
    log.meta(parent, payload_at=log.clock - timedelta(minutes=20))
    prev = (0, 0, 0)
    for t in parent_totals:
        log.token_count(t, (t[0] - prev[0], t[1] - prev[1], t[2] - prev[2]))
        prev = t
    return prev


@case("c01_subagent_explicit_ordinal", "Subagent with subagent_history_start_ordinal: explicit owned suffix.")
def _c01(home: Path, day: int):
    psid, plog = _parent(home, day, 1, PARENT_TOTALS)
    plog.write(home, psid)
    csid = sid_for(day, 2)
    log = Log(day, 30)
    log.meta(csid, at=plog.clock + timedelta(minutes=1), forked_from=psid, subagent_parent=psid,
             history_start_ordinal=4)
    prev = _subagent_prefix(log, psid, PARENT_TOTALS)
    assert log.ordinal == 4, "start ordinal must name the first owned record"
    log.thread_settings().turn_context().inter_agent(True).task_started("c2")
    log.token_count((24000, 14000, 2400), (24000 - prev[0], 14000 - prev[1], 2400 - prev[2]))
    log.token_count((27000, 16000, 2700), (3000, 2000, 300))
    log.task_complete("c2").write(home, csid)


@case("c02_subagent_independent", "Subagent with no embedded ancestor and no fork id: independent counter.")
def _c02(home: Path, day: int):
    psid, plog = _parent(home, day, 1, PARENT_TOTALS)
    plog.write(home, psid)
    csid = sid_for(day, 2)
    log = Log(day, 30).meta(csid, at=plog.clock + timedelta(minutes=1), subagent_parent=psid)
    log.turn_context().task_started("c2")
    log.token_count((2000, 500, 200), (2000, 500, 200))
    log.token_count((4500, 1500, 450), (2500, 1000, 250))
    log.task_complete("c2").write(home, csid)


@case("c03_subagent_copied_prefix_boundary", "Subagent with embedded ancestor meta and a turn_context + trigger boundary.")
def _c03(home: Path, day: int):
    psid, plog = _parent(home, day, 1, PARENT_TOTALS)
    plog.write(home, psid)
    csid = sid_for(day, 2)
    log = Log(day, 30).meta(csid, at=plog.clock + timedelta(minutes=1), forked_from=psid, subagent_parent=psid)
    prev = _subagent_prefix(log, psid, PARENT_TOTALS)
    log.turn_context().inter_agent(True).task_started("c2")
    log.token_count((23000, 13500, 2300), (3000, 1500, 300))
    log.token_count((26000, 15000, 2600), (3000, 1500, 300))
    log.task_complete("c2").write(home, csid)


@case("c04_subagent_boundary_empty_line", "As c03, with an empty line between turn_context and the trigger record.")
def _c04(home: Path, day: int):
    psid, plog = _parent(home, day, 1, PARENT_TOTALS)
    plog.write(home, psid)
    csid = sid_for(day, 2)
    log = Log(day, 30).meta(csid, at=plog.clock + timedelta(minutes=1), forked_from=psid, subagent_parent=psid)
    _subagent_prefix(log, psid, PARENT_TOTALS)
    log.turn_context().raw("").inter_agent(True).task_started("c2")
    log.token_count((23000, 13500, 2300), (3000, 1500, 300))
    log.token_count((26000, 15000, 2600), (3000, 1500, 300))
    log.task_complete("c2").write(home, csid)


@case("c05_subagent_parent_confirmed_candidate", "Explicit parent, no ancestor meta, zero-usage opening snapshot.")
def _c05(home: Path, day: int):
    psid, plog = _parent(home, day, 1, PARENT_TOTALS)
    plog.write(home, psid)
    csid = sid_for(day, 2)
    log = Log(day, 30).meta(csid, at=plog.clock + timedelta(minutes=1), forked_from=psid, subagent_parent=psid)
    log.token_count(PARENT_TOTALS[-1], (0, 0, 0))
    log.turn_context().task_started("c2")
    log.token_count((23000, 13500, 2300), (3000, 1500, 300))
    log.token_count((26000, 15000, 2600), (3000, 1500, 300))
    log.task_complete("c2").write(home, csid)


@case("c06_subagent_copied_prefix_no_suffix", "Embedded ancestor meta, no fork id, no boundary: unowned prefix suppressed.")
def _c06(home: Path, day: int):
    psid, plog = _parent(home, day, 1, PARENT_TOTALS)
    plog.write(home, psid)
    csid = sid_for(day, 2)
    log = Log(day, 30).meta(csid, at=plog.clock + timedelta(minutes=1), subagent_parent=psid)
    _subagent_prefix(log, psid, PARENT_TOTALS)
    log.token_count((23000, 13500, 2300), (3000, 1500, 300))
    log.write(home, csid)


@case("c07_subagent_unterminated_tail", "Subagent (copied prefix + boundary) ending in incomplete JSON: no rows yet.")
def _c07(home: Path, day: int):
    psid, plog = _parent(home, day, 1, PARENT_TOTALS)
    plog.write(home, psid)
    csid = sid_for(day, 2)
    log = Log(day, 30).meta(csid, at=plog.clock + timedelta(minutes=1), forked_from=psid, subagent_parent=psid)
    _subagent_prefix(log, psid, PARENT_TOTALS)
    log.turn_context().inter_agent(True).task_started("c2")
    log.token_count((23000, 13500, 2300), (3000, 1500, 300))
    log.write(home, csid, tail='{"timestamp":"2025-03')


@case("c08_subagent_complete_tail_no_newline", "As c07, but the final line is complete JSON without a newline.")
def _c08(home: Path, day: int):
    psid, plog = _parent(home, day, 1, PARENT_TOTALS)
    plog.write(home, psid)
    csid = sid_for(day, 2)
    log = Log(day, 30).meta(csid, at=plog.clock + timedelta(minutes=1), forked_from=psid, subagent_parent=psid)
    _subagent_prefix(log, psid, PARENT_TOTALS)
    log.turn_context().inter_agent(True).task_started("c2")
    last_line = Log(day, 50)
    last_line.ordinal = log.ordinal
    last_line.clock = log.clock
    last_line.token_count((23000, 13500, 2300), (3000, 1500, 300))
    log.write(home, csid, tail=last_line.lines[0])


def _dependent_middle(home: Path, day: int) -> tuple[str, Log]:
    """Depth-1 subagent fork of a missing root with a copied prefix and no local boundary:
    it depends on the root's totals, so it stays unresolved."""
    rsid = sid_for(day, 1)  # root log intentionally missing
    msid = sid_for(day, 2)
    mlog = Log(day, 10).meta(msid, at=BASE_DAY + timedelta(days=day, minutes=10), forked_from=rsid,
                             subagent_parent=rsid)
    _subagent_prefix(mlog, rsid, PARENT_TOTALS)
    mlog.token_count((23000, 13500, 2300), (3000, 1500, 300))
    mlog.write(home, msid)
    return msid, mlog


@case("c09_depth2_dependent_parent_unresolved",
      "Depth-2 subagent with no boundary under a depth-1 parent that depends on a missing root.")
def _c09(home: Path, day: int):
    msid, mlog = _dependent_middle(home, day)
    csid = sid_for(day, 3)
    clog = Log(day, 30).meta(csid, at=mlog.clock + timedelta(minutes=1), forked_from=msid, subagent_parent=msid,
                             depth=2, agent_path="/root/synthetic_task/inner_task")
    _subagent_prefix(clog, msid, PARENT_TOTALS + [(23000, 13500, 2300)])
    clog.token_count((25000, 14500, 2500), (2000, 1000, 200))
    clog.write(home, csid)


@case("c10_depth2_lineage_only_parent_missing", "Depth-2 subagent whose independent depth-1 parent has a missing parent.")
def _c10(home: Path, day: int):
    rsid = sid_for(day, 1)  # root log intentionally missing
    msid = sid_for(day, 2)
    mlog = Log(day, 10).meta(msid, at=BASE_DAY + timedelta(days=day, minutes=10), subagent_parent=rsid)
    mlog.turn_context().task_started("m2")
    mlog.token_count((2000, 500, 200), (2000, 500, 200))
    mlog.token_count((4000, 1500, 400), (2000, 1000, 200))
    mlog.task_complete("m2").write(home, msid)
    csid = sid_for(day, 3)
    clog = Log(day, 30).meta(csid, at=mlog.clock + timedelta(minutes=1), forked_from=msid, subagent_parent=msid,
                             depth=2, agent_path="/root/synthetic_task/inner_task")
    _subagent_prefix(clog, msid, [(2000, 500, 200), (4000, 1500, 400)])
    clog.turn_context().inter_agent(True).task_started("c3")
    clog.token_count((6000, 2500, 600), (2000, 1000, 200))
    clog.task_complete("c3").write(home, csid)


@case("c11_depth2_boundary_under_dependent_parent",
      "Depth-2 subagent with its own turn_context + trigger boundary under an unresolved dependent parent.")
def _c11(home: Path, day: int):
    msid, mlog = _dependent_middle(home, day)
    csid = sid_for(day, 3)
    clog = Log(day, 30).meta(csid, at=mlog.clock + timedelta(minutes=1), forked_from=msid, subagent_parent=msid,
                             depth=2, agent_path="/root/synthetic_task/inner_task")
    _subagent_prefix(clog, msid, PARENT_TOTALS + [(23000, 13500, 2300)])
    clog.turn_context().inter_agent(True).task_started("c3")
    clog.token_count((25000, 14500, 2500), (2000, 1000, 200))
    clog.task_complete("c3").write(home, csid)


@case("c12_subagent_candidate_not_confirmed",
      "As c05, but the zero-usage opening snapshot does not equal the parent's totals; the opening "
      "snapshot still counts nothing (for these totals the rows equal c05's).")
def _c12(home: Path, day: int):
    psid, plog = _parent(home, day, 1, PARENT_TOTALS)
    plog.write(home, psid)
    csid = sid_for(day, 2)
    log = Log(day, 30).meta(csid, at=plog.clock + timedelta(minutes=1), forked_from=psid, subagent_parent=psid)
    log.token_count((15000, 9000, 1500), (0, 0, 0))
    log.turn_context().task_started("c2")
    log.token_count((18000, 10500, 1800), (3000, 1500, 300))
    log.token_count((21000, 12000, 2100), (3000, 1500, 300))
    log.task_complete("c2").write(home, csid)


def build(out: Path) -> list[dict]:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    index = []
    for day, (name, description, fn) in enumerate(CASES):
        case_dir = out / name
        home = case_dir / "codex-home"
        home.mkdir(parents=True)
        fn(home, day)
        files = sorted(p.relative_to(home).as_posix() for p in home.rglob("*.jsonl"))
        mtimes = {p.relative_to(home).as_posix(): int(p.stat().st_mtime_ns // 1_000_000)
                  for p in home.rglob("*.jsonl")}
        meta = {"name": name, "description": description,
                "day_utc": (BASE_DAY + timedelta(days=day)).strftime("%Y-%m-%d"),
                "files": files, "mtimes_ms": mtimes}
        (case_dir / "case.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        index.append(meta)
    (out / "index.json").write_text(json.dumps([c["name"] for c in index], indent=2) + "\n", encoding="utf-8")
    (out / "catalog.json").write_text(json.dumps(CATALOG, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return index


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    cases = build(args.out)
    print(f"wrote {len(cases)} cases to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
