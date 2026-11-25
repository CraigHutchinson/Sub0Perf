"""Operating-system specifics: the pin CPU, and the machine-wide CPU time counters (which move to Sub0Platform's host module).

Process launching and pid checks are Sub0Platform's `proc`; this module keeps the policy around them."""

import ctypes
import os
import sys
from pathlib import Path

from . import platform_path

platform_path.ensure()  # puts Sub0Platform's python/ on sys.path (it is fetched at configure time, not installed)
from sub0platform import proc as sub0platform_proc  # noqa: E402

_pin_cpu = None  # run every measurement on this one logical CPU (None = unpinned)


def set_pin_cpu(cpu):
    global _pin_cpu
    _pin_cpu = cpu


def pin_cpu():
    return _pin_cpu


def resolve_pin_cpu(option):
    """From --cpu: -2 = do not pin, -1 = the last logical CPU, otherwise that CPU."""
    if option == -2:
        return None
    return (os.cpu_count() or 1) - 1 if option == -1 else option


def launch(cmd, timeout=None):
    """Starts a measurement process at raised priority, pinned to the pin CPU when set, and waits for it (Sub0Platform's proc.launch).

    Pinning stops the scheduler moving the benchmark between cores mid-run (cold caches, different clocks);
    raised priority keeps ordinary background work from preempting it. With `timeout` (seconds) a process still running
    after that long is killed and subprocess.TimeoutExpired is raised.
    """
    sub0platform_proc.launch(cmd, timeout=timeout, cpu=_pin_cpu)


def cpu_times():
    """Returns (busy, total) CPU time counters for the whole machine, or None if unavailable."""
    if sys.platform == "win32":
        class FileTime(ctypes.Structure):
            _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]
        idle, kernel, user = FileTime(), FileTime(), FileTime()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        value = lambda t: (t.high << 32) | t.low
        total = value(kernel) + value(user)  # kernel time includes idle time
        return total - value(idle), total
    try:
        fields = [int(x) for x in Path("/proc/stat").read_text().split("\n")[0].split()[1:]]
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
        total = sum(fields)
        return total - idle, total
    except OSError:
        return None


def pid_alive(pid):
    """Whether a process with this id exists (never signals it: os.kill would terminate it on Windows)."""
    return sub0platform_proc.alive(pid) if pid > 0 else False
