"""Live machine telemetry for the desktop app: CPU %, RAM, GPU utilisation and VRAM. Stdlib only, cross-platform."""
import ctypes
import os
import re
import shutil
import subprocess
import sys

from ..hardware import _ram_bytes


def parse_cpu_stat(text):
    """/proc/stat first line -> (busy_ticks, total_ticks)."""
    for line in text.splitlines():
        if line.startswith("cpu "):
            f = [int(x) for x in line.split()[1:9]]
            idle = f[3] + f[4]  # idle + iowait
            total = sum(f)
            return total - idle, total
    return 0, 0


def cpu_percent(a, b):
    dt = b[1] - a[1]
    return max(0.0, min(100.0, 100.0 * (b[0] - a[0]) / dt)) if dt > 0 else 0.0


def parse_nvidia_usage(text):
    out = []
    for line in text.strip().splitlines():
        m = re.match(r"^(.*?),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\s*$", line.strip())
        if m:
            out.append({"name": m.group(1).strip(), "util": int(m.group(2)),
                        "vram_used_gb": round(int(m.group(3)) / 1024, 2),
                        "vram_total_gb": round(int(m.group(4)) / 1024, 2), "temp": int(m.group(5))})
    return out


def _win_cpu_times():
    class FT(ctypes.Structure):
        _fields_ = [("lo", ctypes.c_ulong), ("hi", ctypes.c_ulong)]
    idle, kern, user = FT(), FT(), FT()
    ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
    v = lambda t: (t.hi << 32) | t.lo
    total = v(kern) + v(user)  # kernel time includes idle
    return total - v(idle), total


def _ram_available():
    if sys.platform.startswith("win"):
        class MEM(ctypes.Structure):
            _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                        ("avail", ctypes.c_ulonglong), ("pt", ctypes.c_ulonglong), ("pa", ctypes.c_ulonglong),
                        ("vt", ctypes.c_ulonglong), ("va", ctypes.c_ulonglong), ("ve", ctypes.c_ulonglong)]
        m = MEM(); m.l = ctypes.sizeof(MEM)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return int(m.avail)
    try:
        with open("/proc/meminfo") as f:
            m = re.search(r"MemAvailable:\s+(\d+)\s*kB", f.read())
            return int(m.group(1)) * 1024 if m else 0
    except OSError:
        return 0


class Telemetry:
    def __init__(self):
        self._prev = None
        self._ram_total = _ram_bytes()

    def _cpu_times(self):
        if sys.platform.startswith("win"):
            return _win_cpu_times()
        try:
            with open("/proc/stat") as f:
                return parse_cpu_stat(f.read())
        except OSError:
            return (0, 0)

    def sample(self):
        now = self._cpu_times()
        cpu = cpu_percent(self._prev, now) if self._prev else 0.0
        self._prev = now
        gpus = []
        if shutil.which("nvidia-smi"):
            try:
                out = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                                      "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=4).stdout
                gpus = parse_nvidia_usage(out)
            except Exception:
                pass
        total = self._ram_total or 1
        used = max(0, total - _ram_available())
        return {"cpu": cpu, "ram_used_gb": used / 2**30, "ram_total_gb": total / 2**30,
                "ram_pct": 100.0 * used / total, "gpus": gpus}
