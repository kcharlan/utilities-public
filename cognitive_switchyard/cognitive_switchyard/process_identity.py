"""Read a process start identity without retaining its command line."""

from __future__ import annotations

import ctypes
import sys
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
