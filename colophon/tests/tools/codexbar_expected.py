"""Generate CodexBar reference expectations for Colophon's token-accounting cases (maintainer tool).

For each case directory (``<case>/codex-home`` plus ``case.json``) this runs a CodexBar CLI built
from the pinned upstream commit and writes ``<case>/expected.json`` with three staged views:

  rows            per input file, the usage rows CodexBar emitted (its ``usage_rows`` cache table)
  day_aggregates  per (day, model) totals CodexBar aggregated (its ``day_aggregates`` table)
  report          the CLI's own ``cost --format json`` daily/totals/coverage output

Colophon never runs this. Tests only read the committed ``expected.json`` files.

Isolation (all verified on 2026-10-03; see colophon-prebuilt PROVENANCE.md):
  * ``HOME`` alone does NOT move CodexBar's cache. ``CFFIXED_USER_HOME`` does, so both are set to
    a throwaway fake home.
  * The CLI runs under ``sandbox-exec`` with network denied, all writes under the real ``$HOME``
    denied, and reads of the real ``~/.codex`` and ``~/Library/Caches/CodexBar`` denied. The guard
    is self-tested before any run.
  * App preferences still come from the real ``com.steipete.codexbar`` domain (cfprefsd), so the
    report period is forced with ``--period all`` and the bucket time zone is read back from the
    scan metadata and recorded in ``expected.json``.
  * The real cache directory and preference domains are fingerprinted before and after; any change
    aborts with an error. The fingerprint detects, but cannot prevent, preference writes made through
    cfprefsd (mach services are outside the sandbox's file rules). The CodexBar app must not be running.
  * Each case's recorded ``mtimes_ms`` are applied to the working copy, because git does not keep mtimes.
  * A ``CODEX_HOME`` reached through a symlink (``/tmp`` -> ``/private/tmp``) never completes
    scanning in this CodexBar build, so case copies live under a symlink-free work directory.

Run (stdlib only):
    colophon/.venv/bin/python colophon/tests/tools/codexbar_expected.py \
        --cli ~/Downloads/colophon-prebuilt/codexbar-cli-3bbf6bc48/CodexBarCLI [--case NAME ...]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PINNED_COMMIT = "3bbf6bc48c20d8e507b30ed93dbdce19ed928bb6"
PINNED_CLI_SHA256 = "232d6708fbd8e403619b7451c4ec55db86911707b8422ad73cfbc2108e151353"
DEFAULT_CASES = Path(__file__).resolve().parents[1] / "fixtures" / "token_cases"
DEFAULT_WORK = Path.home() / ".cache" / "colophon-codexbar-expected"
HOME = Path.home()
REAL_CACHE = HOME / "Library" / "Caches" / "CodexBar"
PREF_DOMAINS = ("com.steipete.codexbar", "com.steipete.codexbar.debug", "CodexBarCLI")
MAX_RUNS = 10
# A case is accepted after this many consecutive identical results (compared via canonical()).
# CodexBar never marks history coverage established while a fork baseline is unresolved (those
# children stay "unmetered"), so historyCoverageIsEstablished is recorded, not required.
STABLE_RUNS = 3
# CodexBar's float cost sums vary by about one ulp between processes (hash-seeded dictionary
# iteration order). Stability is judged, and expected.json is written, with floats rounded to this
# many significant digits; consumers compare costs with a relative tolerance far above that rounding.
COST_SIG_DIGITS = 12
REPORT_DROP = ("updatedAt",)


class GuardError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def profile_text(*, allow_real_codex_read: bool = False) -> str:
    """Sandbox profile. ``allow_real_codex_read`` is for real-data parity only (Task 24): CodexBar may then
    read the real ~/.codex; every write under the real home stays denied."""
    home = str(HOME)
    rules = [
        "(version 1)",
        "(allow default)",
        "(deny network*)",
        f'(deny file-write* (subpath "{home}"))',
        f'(deny file-read* (subpath "{REAL_CACHE}"))',
    ]
    if not allow_real_codex_read:
        rules.append(f'(deny file-read* (subpath "{home}/.codex"))')
    return "\n".join(rules + [""])


def real_state_fingerprint() -> str:
    """Names, sizes, mtimes of every file under the real CodexBar cache, plus the pref domains."""
    lines = []
    if REAL_CACHE.exists():
        for p in sorted(REAL_CACHE.rglob("*")):
            if p.is_file():
                st = p.stat()
                lines.append(f"{p.relative_to(REAL_CACHE)}\t{st.st_size}\t{st.st_mtime_ns}")
    for domain in PREF_DOMAINS:
        out = subprocess.run(["/usr/bin/defaults", "export", domain, "-"], capture_output=True)
        lines.append(f"pref\t{domain}\t{hashlib.sha256(out.stdout).hexdigest()}")
    return "\n".join(lines)


def app_running() -> bool:
    out = subprocess.run(["/usr/bin/pgrep", "-x", "CodexBar"], capture_output=True)
    return out.returncode == 0


def self_test_guard(profile: Path, *, expect_real_codex_read_denied: bool = True) -> None:
    probe = REAL_CACHE / ".colophon-guard-probe"
    if probe.exists():
        raise GuardError(f"stale probe file exists: {probe}; inspect and remove it by hand")
    w = subprocess.run(["/usr/bin/sandbox-exec", "-f", str(profile), "/usr/bin/touch", str(probe)],
                       capture_output=True)
    if w.returncode == 0 or probe.exists():
        raise GuardError("sandbox guard FAILED to block a write into the real CodexBar cache")
    if expect_real_codex_read_denied:
        r = subprocess.run(["/usr/bin/sandbox-exec", "-f", str(profile), "/bin/ls", str(HOME / ".codex")],
                           capture_output=True)
        if r.returncode == 0:
            raise GuardError("sandbox guard FAILED to block reading the real ~/.codex")
    c = subprocess.run(["/usr/bin/sandbox-exec", "-f", str(profile), "/bin/ls", str(REAL_CACHE)],
                       capture_output=True)
    if REAL_CACHE.exists() and c.returncode == 0:
        raise GuardError("sandbox guard FAILED to block reading the real CodexBar cache")
    n = subprocess.run(["/usr/bin/sandbox-exec", "-f", str(profile), "/usr/bin/curl", "-sS", "-m", "5",
                        "-o", "/dev/null", "https://models.dev/api.json"], capture_output=True)
    if n.returncode == 0:
        raise GuardError("sandbox guard FAILED to block network access")


def require_symlink_free(path: Path) -> None:
    if path.resolve() != path.absolute():
        raise GuardError(f"work directory must not traverse symlinks: {path} -> {path.resolve()}")


def seed_fake_home(fake: Path, catalog: dict) -> None:
    pricing = fake / "Library" / "Caches" / "CodexBar" / "model-pricing"
    pricing.mkdir(parents=True)
    (fake / ".codex").mkdir()  # trace DB location for this CodexBar build: <home>/.codex/logs_2.sqlite
    fetched = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # fresh: no refresh attempt
    artifact = {"version": 1, "fetchedAt": fetched, "catalog": {"providers": catalog}}
    (pricing / "models-dev-v1.json").write_text(json.dumps(artifact), encoding="utf-8")


def normalize_report(raw: str) -> dict:
    payload = json.loads(raw)
    if not isinstance(payload, list) or len(payload) != 1:
        raise RuntimeError(f"unexpected CLI payload shape: {raw[:200]}")
    rep = payload[0]
    for key in REPORT_DROP:
        rep.pop(key, None)

    def sort_breakdowns(entry: dict) -> dict:
        if "modelBreakdowns" in entry:
            entry["modelBreakdowns"] = sorted(entry["modelBreakdowns"], key=lambda b: b["modelName"])
        return entry

    return {
        "historyCoverageIsEstablished": rep.get("historyCoverageIsEstablished"),
        "provenance": rep.get("provenance"),
        "coverage": rep.get("coverage"),
        "totals": rep.get("totals"),
        "daily": [sort_breakdowns(d) for d in sorted(rep.get("daily", []), key=lambda d: d["date"])],
        "error": rep.get("error"),
    }


def read_cache(fake: Path, codex_home: Path) -> dict:
    db = fake / "Library" / "Caches" / "CodexBar" / "cost-usage" / "cost-usage.sqlite"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        roots = (str(codex_home), str(codex_home.resolve()))

        def rel(path: str) -> str:
            for root in roots:
                if path.startswith(root + "/"):
                    return path[len(root) + 1:]
            raise RuntimeError(f"cache path outside the case home: {path}")

        files = {}
        for fid, path, scan_complete, session_id in con.execute(
                "select id, path, scan_complete, session_id from files order by path"):
            files[fid] = {"file": rel(path), "scan_complete": bool(scan_complete), "session_id": session_id,
                          "rows": []}
        for fid, idx, payload in con.execute(
                "select file_id, row_index, payload from usage_rows order by file_id, row_index"):
            row = json.loads(payload)
            row["row_index"] = idx
            files[fid]["rows"].append(row)
        cols = [c[1] for c in con.execute("pragma table_info(day_aggregates)")]
        aggs = [dict(zip(cols, r)) for r in con.execute("select * from day_aggregates order by day, model")]
        meta = {}
        for (payload,) in con.execute("select payload from scan_metadata"):
            meta = json.loads(payload)
        return {"files": sorted(files.values(), key=lambda f: f["file"]), "day_aggregates": aggs,
                "bucket_tz": meta.get("timeZoneIdentifier")}
    finally:
        con.close()


def canonical(value):
    if isinstance(value, float):
        return float(f"{value:.{COST_SIG_DIGITS}g}")
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in value.items()}
    if isinstance(value, list):
        return [canonical(v) for v in value]
    return value


def guarded_env(fake: Path, codex_home: Path) -> dict:
    """The only environment CodexBar may run with: the fake home in both HOME and CFFIXED_USER_HOME
    (HOME alone does not move CodexBar's cache), and CODEX_HOME at a symlink-free path."""
    return {"PATH": "/usr/bin:/bin", "HOME": str(fake), "CFFIXED_USER_HOME": str(fake),
            "CODEX_HOME": str(codex_home), "TZ": "UTC", "LANG": "en_US.UTF-8"}


def run_until_stable(cli: Path, profile: Path, fake: Path, codex_home: Path, commands: list[list[str]],
                     snapshot, *, max_runs: int = MAX_RUNS, stable_runs: int = STABLE_RUNS) -> tuple[object, int]:
    """Run every CodexBar command in ``commands`` (argument lists after the binary) once per attempt,
    keeping the fake home between attempts, until ``snapshot(stdouts)`` is identical (after
    canonical()) for ``stable_runs`` consecutive attempts. Returns (snapshot, attempts).

    The caller seeds ``fake`` (seed_fake_home), builds ``profile`` (profile_text + self_test_guard),
    and checks real_state_fingerprint() before and after."""
    env = guarded_env(fake, codex_home)
    previous, streak = None, 0
    for attempt in range(1, max_runs + 1):
        stdouts = []
        for command in commands:
            proc = subprocess.run(["/usr/bin/sandbox-exec", "-f", str(profile), str(cli), *command],
                                  capture_output=True, text=True, env=env, cwd=fake.parent, timeout=3600)
            if proc.returncode != 0:
                raise RuntimeError(f"CLI exit {proc.returncode} for {command}: {proc.stderr[:500]}")
            stdouts.append(proc.stdout)
        current = snapshot(stdouts)
        streak = streak + 1 if previous is not None and canonical(current) == canonical(previous) else 1
        if streak >= stable_runs:
            return current, attempt
        previous = current
    raise RuntimeError(f"no stable result after {max_runs} runs")


COST_COMMAND = ["cost", "--provider", "codex", "--period", "all", "--format", "json"]


def run_case(cli: Path, profile: Path, case_dir: Path, work: Path, catalog: dict) -> tuple[dict, int]:
    meta = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    dest = work / case_dir.name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(case_dir / "codex-home", dest / "codex-home", copy_function=shutil.copy2)
    codex_home = dest / "codex-home"
    # Git does not keep mtimes, and CodexBar's file order depends on them: apply the recorded ones.
    for rel_path, mtime_ms in meta["mtimes_ms"].items():
        ns = mtime_ms * 1_000_000
        os.utime(codex_home / rel_path, ns=(ns, ns))
    with tempfile.TemporaryDirectory(prefix="colophon-cb-fake-") as tmp:
        fake = Path(tmp) / "home"
        seed_fake_home(fake, catalog)
        try:
            return run_until_stable(
                cli, profile, fake, codex_home, [COST_COMMAND],
                lambda outs: {"report": normalize_report(outs[0]), **read_cache(fake, codex_home)})
        except RuntimeError as exc:
            raise RuntimeError(f"{case_dir.name}: {exc}") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CASES / "catalog.json",
                        help="pinned models.dev-shaped catalog (one shared file for every case set)")
    args = parser.parse_args()

    cli = args.cli.expanduser().resolve()
    if sha256_file(cli) != PINNED_CLI_SHA256:
        raise GuardError(f"{cli} is not the pinned build (sha256 mismatch)")
    if app_running():
        raise GuardError("quit the CodexBar app first (the before/after cache check needs it idle)")
    work = args.work_dir.expanduser().absolute()
    work.mkdir(parents=True, exist_ok=True)
    require_symlink_free(work)
    cases_root = args.cases.resolve()
    catalog_path = args.catalog.resolve()
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    names = args.case or json.loads((cases_root / "index.json").read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory(prefix="colophon-cb-guard-") as gdir:
        profile = Path(gdir) / "guard.sb"
        profile.write_text(profile_text(), encoding="utf-8")
        self_test_guard(profile)
        before = real_state_fingerprint()
        failures = []
        written = 0
        try:
            for name in names:
                case_dir = cases_root / name
                try:
                    result, runs = run_case(cli, profile, case_dir, work, catalog)
                except Exception as exc:  # report every failing case, then fail the run
                    failures.append(f"{name}: {exc}")
                    print(f"FAIL {name}: {exc}", file=sys.stderr)
                    continue
                result["generator"] = {
                    "tool": "colophon/tests/tools/codexbar_expected.py",
                    "upstream_commit": PINNED_COMMIT,
                    "cli_sha256": PINNED_CLI_SHA256,
                    "catalog_sha256": sha256_file(catalog_path),
                    "command": "cost --provider codex --period all --format json",
                }
                (case_dir / "expected.json").write_text(json.dumps(canonical(result), indent=2, sort_keys=True) + "\n",
                                                        encoding="utf-8")
                written += 1
                print(f"ok   {name}: runs={runs}"
                      f" established={result['report']['historyCoverageIsEstablished']}"
                      f" days={[d['date'] for d in result['report']['daily']]} tz={result['bucket_tz']}")
        finally:
            after = real_state_fingerprint()
        if after != before:
            print("ERROR: the real CodexBar cache or preferences changed during the run:", file=sys.stderr)
            b, a = set(before.splitlines()), set(after.splitlines())
            for line in sorted(b - a):
                print(f"  before: {line}", file=sys.stderr)
            for line in sorted(a - b):
                print(f"  after:  {line}", file=sys.stderr)
            return 2
    print(f"real CodexBar cache and preferences unchanged; {written}/{len(names)} cases written")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GuardError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(3)
