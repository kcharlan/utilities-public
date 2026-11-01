"""Synthetic launchctl output for parser tests; nothing here reaches launchd.

Run as a script, this boots the launcher's real main() with every plist
directory confined to the temporary home and subprocess.run replaced.
"""
import os
import plistlib
import queue
import runpy
import subprocess
import sys
import threading
from pathlib import Path

LIST_OUTPUT = (
    "PID\tStatus\tLabel\n"
    "424242\t0\tcom.example.synthetic-running\n"
    "-\t78\tcom.example.synthetic-failed\n"
    "-\t-15\tcom.example.synthetic-signalled\n"
    "-\t-\tcom.example.synthetic-never-ran\n"
    "not-a-pid\tnot-a-status\tcom.example.synthetic-unparsable\n"
    "-\t0\tcom.example.synthetic-disabled\n"
    "-\t0\tcom.apple.example-synthetic\n"
    "line without tabs\n"
)

PRINT_DISABLED_OUTPUT = (
    "disabled services = {\n"
    '\t"com.example.synthetic-disabled" => disabled\n'
    '\t"com.example.synthetic-running" => enabled\n'
    '\t"com.example.synthetic-upper" => DISABLED\n'
    "}\n"
    "login item associations = {\n"
    "}\n"
)

PRINT_OUTPUT = (
    "gui/501/com.example.synthetic-running = {\n"
    "\tactive count = 1\n"
    "\tpath = /synthetic/LaunchAgents/com.example.synthetic-running.plist\n"
    "\tstate = running\n"
    "\tprogram = /usr/bin/true\n"
    "\truns = 3\n"
    "\tpid = 424242\n"
    "\tlast exit code = 78\n"
    "}\n"
)

BLAME_OUTPUT = "  speculative\n"


def fake_run(argv, **kwargs):
    """Answer launchctl queries, and refuse everything else."""
    if argv[:1] != ["launchctl"] or len(argv) < 2:
        raise RuntimeError(f"Unexpected subprocess in a synthetic test: {argv!r}")
    outputs = {
        "list": LIST_OUTPUT,
        "print-disabled": PRINT_DISABLED_OUTPUT,
        "print": PRINT_OUTPUT,
        "blame": BLAME_OUTPUT,
    }
    if argv[1] not in outputs:
        raise RuntimeError(f"Mutating launchctl call in a synthetic test: {argv!r}")
    return subprocess.CompletedProcess(argv, 0, stdout=outputs[argv[1]], stderr="")


def read_line_within(stream, timeout: float):
    """Read a line from a child's output, or return None if it stays silent."""
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: lines.put(stream.readline()), daemon=True).start()
    try:
        return lines.get(timeout=timeout)
    except queue.Empty:
        return None


def _boot_main(launcher: str, port: str) -> None:
    home = Path(os.environ["LAUNCHMASTER_HOME"])
    home.mkdir(parents=True, exist_ok=True)
    with (home / "com.example.synthetic-running.plist").open("wb") as plist:
        plistlib.dump(
            {
                "Label": "com.example.synthetic-running",
                "ProgramArguments": ["/usr/bin/true"],
                "KeepAlive": True,
            },
            plist,
        )
    subprocess.run = fake_run
    namespace = runpy.run_path(launcher, run_name="launchmaster_test_main")
    # Functions retain the runpy globals, which are distinct from its returned dict.
    globals_ = namespace["main"].__globals__
    globals_["PLIST_DIRS"] = {"user-agent": str(home)}
    sys.argv = ["launchmaster", "--no-browser", "--port", port]
    globals_["main"]()


if __name__ == "__main__":
    _boot_main(sys.argv[1], sys.argv[2])
