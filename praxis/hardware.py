"""Hardware awareness + a physical performance model for local LLMs.

The model is deliberately simple physics: decoding is memory-bandwidth bound, so
    tokens/s ~ bandwidth / bytes read per token
where the bytes per token are the *active* weights (a mixture-of-experts reads only its active experts) and the
weights are split between VRAM (fast) and system RAM (slower). It is an ESTIMATE used to rank candidates before
anything is downloaded; `praxis bench` replaces it with a measured number.
"""
import ctypes
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

GB = 2**30

# Memory bandwidth (GB/s) of common NVIDIA cards. Unknown cards fall back to a conservative default.
_GPU_BW = [
    (r"3050.*6\s*gb|3050 6", 168), (r"rtx 3050", 224), (r"rtx 3060 ti", 448), (r"rtx 3060", 360),
    (r"rtx 3070", 448), (r"rtx 3080", 760), (r"rtx 3090", 936), (r"rtx 4060 ti", 288), (r"rtx 4060", 272),
    (r"rtx 4070 ti", 504), (r"rtx 4070", 504), (r"rtx 4080", 717), (r"rtx 4090", 1008),
    (r"rtx 5060", 448), (r"rtx 5070", 672), (r"rtx 5080", 960), (r"rtx 5090", 1792),
]
_DEFAULT_GPU_BW = 250.0
_DEFAULT_RAM_BW = 50.0  # GB/s: conservative dual-channel DDR4/DDR5 desktop; override in config for a measured value
EFF_GPU, EFF_RAM = 0.60, 0.45  # achieved fraction of peak bandwidth (CPU path loses more to compute/threading)
MAX_TPS = 120.0  # launch/sampling overhead caps tiny-active-parameter models well below the bandwidth bound
OVERHEAD = 1.12  # KV cache + runtime on top of the weight file


@dataclass
class GPU:
    name: str
    vram_bytes: int
    bw_gbps: float = _DEFAULT_GPU_BW


@dataclass
class Profile:
    os: str
    cpu: str
    cores: int
    ram_bytes: int
    ram_bw_gbps: float = _DEFAULT_RAM_BW
    gpus: list = field(default_factory=list)

    @property
    def vram_total(self):
        return sum(g.vram_bytes for g in self.gpus)

    @property
    def gpu_bw(self):
        return max((g.bw_gbps for g in self.gpus), default=0.0)

    def describe(self):
        g = ", ".join(f"{x.name} {x.vram_bytes / GB:.0f} GiB ({x.bw_gbps:.0f} GB/s)" for x in self.gpus) or "no discrete GPU"
        return (f"{self.cpu} ({self.cores} threads), {self.ram_bytes / GB:.0f} GiB RAM (~{self.ram_bw_gbps:.0f} GB/s), {g}")


def gpu_bandwidth(name, vram_bytes):
    label = f"{name} {vram_bytes // GB}gb".lower()
    for pat, bw in _GPU_BW:
        if re.search(pat, label):
            # the 3050 pattern needs the VRAM size to tell the 6GB (96-bit) card from the 8GB (128-bit) one
            if "3050" in pat and "6" not in pat.split("|")[0] and vram_bytes <= 6.5 * GB:
                return 168
            return bw
    return _DEFAULT_GPU_BW


def parse_nvidia_smi(text):
    gpus = []
    for line in text.strip().splitlines():
        m = re.match(r"^(.*?),\s*(\d+)\s*$", line.strip())
        if m:
            vram = int(m.group(2)) * 2**20
            gpus.append(GPU(m.group(1).strip(), vram, gpu_bandwidth(m.group(1), vram)))
    return gpus


def parse_meminfo(text):
    m = re.search(r"MemTotal:\s+(\d+)\s*kB", text)
    return int(m.group(1)) * 1024 if m else 0


def _ram_bytes():
    if sys.platform.startswith("win"):
        class MEM(ctypes.Structure):
            _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                        ("avail", ctypes.c_ulonglong), ("pt", ctypes.c_ulonglong), ("pa", ctypes.c_ulonglong),
                        ("vt", ctypes.c_ulonglong), ("va", ctypes.c_ulonglong), ("ve", ctypes.c_ulonglong)]
        m = MEM(); m.l = ctypes.sizeof(MEM)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return int(m.total)
    try:
        if os.path.exists("/proc/meminfo"):
            with open("/proc/meminfo") as f:
                return parse_meminfo(f.read())
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return 0


def _cpu_name():
    try:
        if os.path.exists("/proc/cpuinfo"):
            with open("/proc/cpuinfo") as f:
                m = re.search(r"model name\s*:\s*(.+)", f.read())
                if m:
                    return m.group(1).strip()
    except OSError:
        pass
    if sys.platform.startswith("win"):
        try:  # the marketing name ("AMD Ryzen 7 7700 8-Core Processor"), not the family code platform.processor() gives
            out = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"],
                                 capture_output=True, text=True, timeout=15).stdout.strip()
            if out:
                return out.splitlines()[0].strip()
        except Exception:
            pass
    return platform.processor() or platform.machine() or "unknown CPU"


def detect_hardware():
    gpus = []
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=15).stdout
            gpus = parse_nvidia_smi(out)
        except Exception:
            pass
    return Profile(sys.platform, _cpu_name(), os.cpu_count() or 1, _ram_bytes(), _DEFAULT_RAM_BW, gpus)


def profile_from_config(cfg, detected=None):
    """[hardware] overrides; 0/empty means 'use what was detected'."""
    base = detected or detect_hardware()
    gpus = list(base.gpus)
    if cfg.get("vram_gb"):
        vram = int(cfg["vram_gb"] * GB)
        name = cfg.get("gpu_name") or (gpus[0].name if gpus else "GPU")
        gpus = [GPU(name, vram, cfg.get("gpu_bw_gbps") or gpu_bandwidth(name, vram))]
    return Profile(base.os, base.cpu, base.cores, int(cfg["ram_gb"] * GB) if cfg.get("ram_gb") else base.ram_bytes,
                   cfg.get("ram_bw_gbps") or base.ram_bw_gbps, gpus)


def usable_ram_bytes(p):
    """RAM a model may occupy: leave room for the OS and the user's other programs."""
    reserve = max(min(6 * GB, 0.35 * p.ram_bytes), 0.20 * p.ram_bytes)
    return max(0, int(p.ram_bytes - reserve))


def _vram_budget(p):
    return p.vram_total * 0.92  # the desktop compositor and CUDA context take a slice


def fits(size_bytes, p, vram_only=False):
    need = size_bytes * OVERHEAD
    if vram_only:
        return p.vram_total > 0 and need <= _vram_budget(p)
    return need <= _vram_budget(p) + usable_ram_bytes(p)


def estimate_tokens_per_s(size_bytes, total_b, active_b, p):
    """Bandwidth-bound decode speed. MoE reads size*active/total bytes per token; layers split VRAM/RAM."""
    per_token = size_bytes * (active_b / total_b)
    f_gpu = 0.0
    if p.vram_total > 0:
        f_gpu = max(0.0, min(1.0, (_vram_budget(p) - 0.5 * GB) / size_bytes))
    t = 0.0
    if f_gpu > 0:
        t += per_token * f_gpu / (p.gpu_bw * 1e9 * EFF_GPU)
    if f_gpu < 1:
        t += per_token * (1 - f_gpu) / (p.ram_bw_gbps * 1e9 * EFF_RAM)
    return min(1.0 / t, MAX_TPS) if t > 0 else 0.0
