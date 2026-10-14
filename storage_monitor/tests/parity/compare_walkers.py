"""Compare a historical Python walk with the current native adapter.

Results contain aggregate counts only. --show-paths opts into terminal-only
diagnostics; keep those diagnostics outside the public checkout.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT))

from tools.testkit import load_launcher


def snapshot(module, root):
    result = module.walk_tree(
        root, workers=module.SCAN_WORKER_COUNT,
        excluded_paths=module.EXCLUDED_BREAKDOWN_PATHS,
    )
    attributions, _, changes = module.resolve_hardlink_ownership(
        1, result.hardlink_candidates, module.build_walk_translation(), full_scan=True,
    )
    for parent, allocated in attributions:
        result.dir_local[parent] = result.dir_local.get(parent, 0) + allocated
    totals = module.rollup_subtree_totals(result.dir_local, str(root))
    shallow = {path: size for path, size in totals.items()
               if len(Path(path).relative_to(root).parts) <= 3}
    return {
        "directories": set(totals),
        "shallow_totals": shallow,
        "large_files": {item["path"] for item in result.large_files},
        "hardlink_owners": {values[3] for operation, values in changes if operation == "upsert"},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", required=True)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--show-paths", action="store_true")
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    # Reject outputs inside this worktree or the primary checkout.
    primary = Path(subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=REPOSITORY_ROOT, text=True,
    ).strip()).parent
    if any(output.is_relative_to(repository) for repository in (REPOSITORY_ROOT, primary)):
        parser.error("--output must resolve outside the repository")
    root = args.root.expanduser().resolve()
    source = subprocess.check_output(
        ["git", "show", f"{args.baseline_ref}:storage_monitor/storage_monitor"],
        cwd=REPOSITORY_ROOT,
    )
    # The historical launcher is code, never a copy of operational state.
    with tempfile.TemporaryDirectory(prefix="storage-monitor-parity-") as directory:
        baseline_path = Path(directory) / "baseline"
        baseline_path.write_bytes(source)
        baseline = load_launcher(baseline_path)
        current = load_launcher(REPOSITORY_ROOT / "storage_monitor/storage_monitor")
        left, right = snapshot(baseline, root), snapshot(current, root)
    report = {}
    for category in left:
        a, b = left[category], right[category]
        mismatches = set(a) ^ set(b)
        if category == "shallow_totals":
            mismatches.update(path for path in set(a) & set(b) if a[path] != b[path])
        report[category] = {"baseline": len(a), "native": len(b), "mismatches": len(mismatches)}
        if args.show_paths:
            for path in sorted(mismatches):
                detail = f" {a.get(path)} -> {b.get(path)}" if category == "shallow_totals" else ""
                print(f"{category}: {path!r}{detail}")
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.truncate(0)
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
