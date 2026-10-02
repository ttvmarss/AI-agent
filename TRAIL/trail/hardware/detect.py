"""Hardware inspection and a recommendation (never a silent substitution): the machine decides the *scale*, not the *brain*."""
import os
import platform
import shutil
import subprocess


def _ram_bytes():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    try:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("l", ctypes.c_ulong), ("m", ctypes.c_ulong), ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong), ("tpf", ctypes.c_ulonglong),
                        ("apf", ctypes.c_ulonglong), ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ae", ctypes.c_ulonglong)]
        ms = MS(); ms.l = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
        return int(ms.tp)
    except Exception:
        return 0


def _cpu_name():
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def detect(path="."):
    import torch
    info = {"cpu": _cpu_name(), "cpu_threads": os.cpu_count() or 1, "ram_gb": round(_ram_bytes() / 2**30, 1),
            "os": platform.platform(), "python": platform.python_version(), "torch": torch.__version__,
            "cuda_available": bool(torch.cuda.is_available()), "gpus": [], "disk_free_gb": round(shutil.disk_usage(path).free / 2**30, 1)}
    if info["cuda_available"]:
        for i in range(torch.cuda.device_count()):
            p = torch.cuda.get_device_properties(i)
            info["gpus"].append({"name": p.name, "vram_gb": round(p.total_memory / 2**30, 1), "capability": f"{p.major}.{p.minor}"})
        info["bf16"] = bool(torch.cuda.is_bf16_supported())
    else:
        info["bf16"] = False
    info["precision"] = recommended_precision(info)
    info["recommendation"] = recommend(info)
    return info


def recommended_precision(info):
    if info["cuda_available"]:
        return "bf16" if info.get("bf16") else "fp16"
    return "fp32"                   # CPU: float32 is the reliable choice for training


def recommend(info):
    """-> {config, max_params_m, batch_hint}. Rule of thumb for AdamW mixed precision: ~16 bytes/param (weights, grads, two moments) plus activations."""
    if info["gpus"]:
        vram = max(g["vram_gb"] for g in info["gpus"])
        budget = vram * 0.6 * 2**30 / 16
    else:
        budget = info["ram_gb"] * 0.4 * 2**30 / 16
    m = budget / 1e6
    cfg = "trail_micro" if m < 150 else "trail_small" if m < 700 else "trail_base" if m < 5000 else "trail_large"
    if not info["gpus"]:
        cfg = "trail_micro"          # CPU training is only practical at micro scale
    return {"config": f"configs/{cfg}.yaml", "max_trainable_params_millions": round(m), "note":
            "a GPU is needed for anything above micro" if not info["gpus"] else "estimate; activations and sequence length reduce it"}


def report(info):
    g = "; ".join(f"{x['name']} {x['vram_gb']} GB (sm {x['capability']})" for x in info["gpus"]) or "none"
    r = info["recommendation"]
    return "\n".join([
        f"CPU        {info['cpu']} ({info['cpu_threads']} threads)", f"RAM        {info['ram_gb']} GB", f"GPU        {g}",
        f"CUDA       {info['cuda_available']}", f"precision  {info['precision']} (bf16 supported: {info['bf16']})",
        f"disk free  {info['disk_free_gb']} GB", f"torch      {info['torch']}   python {info['python']}", f"OS         {info['os']}", "",
        f"recommended config: {r['config']}  (about {r['max_trainable_params_millions']}M trainable parameters fit; {r['note']})"])
