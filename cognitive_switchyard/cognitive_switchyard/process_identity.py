"""Read a process start identity without retaining its command line."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


class _ProcBsdInfo(ctypes.Structure):
    # struct proc_bsdinfo in macOS sys/proc_info.h (MAXCOMLEN is 16).
    _fields_ = [
        ("prefix", ctypes.c_uint32 * 12),
        ("comm", ctypes.c_char * 16),
        ("name", ctypes.c_char * 32),
        ("tail", ctypes.c_uint32 * 6),
        ("start_sec", ctypes.c_uint64),
        ("start_usec", ctypes.c_uint64),
    ]


def process_identity(pid: int) -> str | None:
    if pid <= 0:
        return None
    if sys.platform == "darwin":
        try:
            libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
            proc_pidinfo = libproc.proc_pidinfo
            proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
            proc_pidinfo.restype = ctypes.c_int
            info = _ProcBsdInfo()
            size = ctypes.sizeof(info)
            if proc_pidinfo(pid, 3, 0, ctypes.byref(info), size) != size:
                return None
            if info.start_sec == 0 and info.start_usec == 0:
                return None
            return f"darwin:{pid}:{info.start_sec}:{info.start_usec}"
        except (OSError, AttributeError):
            return None
    if sys.platform.startswith("linux"):
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
            # The parenthesized command can contain spaces and parentheses.
            fields = stat[stat.rindex(")") + 2:].split()
            return f"linux:{pid}:{int(fields[19])}"
        except (OSError, ValueError, IndexError):
            return None
    return None


class ProcessGroupInspectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class OwnedProcessGroup:
    process: subprocess.Popen
    leader_identity: str | None

    @classmethod
    def capture(cls, process: subprocess.Popen) -> "OwnedProcessGroup":
        group = cls(process, process_identity(process.pid))
        group.check_unreaped()
        return group

    def check_unreaped(self) -> None:
        if self.process.returncode is not None:
            raise ProcessGroupInspectionError("Owned group leader has already been reaped")
        try:
            os.waitid(os.P_PID, self.process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        except (AttributeError, ChildProcessError, OSError) as exc:
            raise ProcessGroupInspectionError("Cannot verify the owned group leader is unreaped") from exc


def owned_group_members(group: OwnedProcessGroup) -> tuple[tuple[int, str | None, int], ...]:
    """Inspect only a captured group while its leader remains unreaped."""
    group.check_unreaped()
    pgid, leader_identity = group.process.pid, group.leader_identity
    if pgid <= 0 or not (sys.platform == "darwin" or sys.platform.startswith("linux")):
        raise ProcessGroupInspectionError("Cannot inspect the owned process group on this platform")
    try:
        def snapshot():
            pids = None
            if sys.platform == "darwin":
                selector = ["-g", str(pgid)]
            else:
                matches = subprocess.run(["/usr/bin/pgrep", "-g", str(pgid)],
                                         capture_output=True, text=True, check=False, timeout=2)
                if matches.returncode != 0:
                    raise ProcessGroupInspectionError("Unable to enumerate the owned process group")
                pids = [int(item) for item in matches.stdout.split()]
                if not pids or any(pid <= 0 for pid in pids) or len(set(pids)) != len(pids):
                    raise ProcessGroupInspectionError("Invalid process group membership")
                selector = ["-p", ",".join(str(pid) for pid in pids)]
            result = subprocess.run(["/bin/ps", *selector, "-o", "pid=,pgid=,stat="],
                                    capture_output=True, text=True, check=False, timeout=2)
            if result.returncode != 0:
                raise ProcessGroupInspectionError("Unable to enumerate the owned process group")
            rows = [line.split() for line in result.stdout.splitlines()]
            if any(len(row) != 3 or int(row[1]) != pgid or (pids is not None and int(row[0]) not in pids)
                   for row in rows):
                raise ProcessGroupInspectionError("Unexpected process group member")
            return rows

        members = []
        for pid_text, group_text, state in snapshot():
            pid = int(pid_text)
            if int(group_text) != pgid:
                raise ProcessGroupInspectionError("Unexpected process group member")
            if state.startswith("Z"):
                members.append((pid, leader_identity if pid == pgid else "", 5))
                continue
            identity = process_identity(pid)
            if identity is None:
                current = {int(item[0]): item[2] for item in snapshot() if int(item[1]) == pgid}
                if pid not in current or current[pid].startswith("Z"):
                    if pid == pgid and pid in current:
                        members.append((pid, leader_identity, 5))
                    continue
                raise ProcessGroupInspectionError("Unable to identify a live process group member")
            if pid == pgid and leader_identity is None:
                raise ProcessGroupInspectionError("Leader identity was unavailable at launch")
            members.append((pid, identity, 0))
        if not any(pid == pgid and identity == leader_identity for pid, identity, _ in members):
            raise ProcessGroupInspectionError("Process group leader identity changed or is unavailable")
        return tuple(members)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise ProcessGroupInspectionError("Unable to inspect the owned process group") from exc


def signal_owned_group(group: OwnedProcessGroup, sig: int) -> None:
    """Signal only verified, live members of a captured process group."""
    members = owned_group_members(group)
    pgid = group.process.pid
    for pid, identity, status in members:
        if status == 5:  # SZOMB: already exited and awaiting collection.
            continue
        group.check_unreaped()
        if process_identity(pid) != identity or os.getpgid(pid) != pgid:
            raise ProcessGroupInspectionError("Process identity changed before signaling")
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            continue
