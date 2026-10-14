"""Measure real-disk scans, keeping runtime state and results outside the repo.

Run with the project's virtual-environment Python. Phase timings are inclusive
and overlap: persist_full_walk includes upsert_node_rows, and parallel calls
can overlap one another. Their sum is not the total elapsed time.
"""

import argparse
import functools
import json
import os
from pathlib import Path
import sys
import threading
import time


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.testkit import load_launcher
from destination_guard import reject_repository_destinations


PHASE_NAMES = (
    "walk_tree",
    "resolve_hardlink_ownership",
    "rollup_subtree_totals",
    "persist_full_walk",
    "upsert_node_rows",
    "run_parallel_call_map",
    "probe_providers",
    "discover_cache_candidates",
    "collect_installed_bundle_ids",
    "collect_orphan_candidates",
    "scan_watchlist",
    "build_breakdowns_from_db",
    "fetch_large_files_from_db",
    "persist_report",
    "finalize_scan_run",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-home", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--runs", required=True, type=int)
    parser.add_argument(
        "--launcher", type=Path,
        default=REPOSITORY_ROOT / "storage_monitor" / "storage_monitor",
    )
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    runtime_home = args.runtime_home.expanduser().resolve()
    output = args.output.expanduser().resolve()
    reject_repository_destinations(parser, REPOSITORY_ROOT, runtime_home, output)

    os.environ["STORAGE_MONITOR_HOME"] = str(runtime_home)
    launcher = load_launcher(args.launcher)
    launcher.ensure_runtime_dirs()
    phases = {}
    lock = threading.Lock()

    def timed(name, function):
        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            started = time.perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - started
                with lock:
                    phases[name]["seconds"] += elapsed
                    phases[name]["calls"] += 1
        return wrapped

    for name in PHASE_NAMES:
        setattr(launcher, name, timed(name, getattr(launcher, name)))

    records = []
    for run in range(1, args.runs + 1):
        phases = {name: {"seconds": 0.0, "calls": 0} for name in PHASE_NAMES}
        started = time.perf_counter()
        scan_id = launcher.create_scan_run(launcher.iso_now())
        collect_started = time.perf_counter()
        report = launcher.collect_scan_report(scan_id)
        collect_s = time.perf_counter() - collect_started
        launcher.persist_report(report)
        launcher.finalize_scan_run(scan_id, report)
        total_s = time.perf_counter() - started
        summary = next(
            check["summary"] for check in report["checks"]
            if check["label"] == "Visible Data volume usage"
        )
        records.append({
            "run": run, "total_s": total_s, "collect_s": collect_s,
            "summary": summary, "phases": phases,
        })

    # Set permissions before truncating even when replacing an existing file.
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.truncate(0)
        json.dump(records, stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
