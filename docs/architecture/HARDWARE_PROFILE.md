# Hardware Profile (M0)

## Critical limitation

**The owner's Windows PC was NOT audited.** M0 ran in an ephemeral Linux cloud container. The blueprint's "Windows 11, Ryzen 7, 32 GB, RTX 3050 4 GB" remains *reported, unverified*. Every Windows/GPU line below is marked accordingly. To close this, run the read-only script on the PC and send back the output:

```
powershell -ExecutionPolicy Bypass -File scripts\audit_windows.ps1 > audit_windows.txt
```
(The script is not executed here; it only reads system information. Review it before running.)

## A. Verified: the M0 container (this is NOT the target machine)

| Item | Value (commands run 2026-10-08) |
|---|---|
| OS | Linux 6.18.44, x86_64 |
| CPU | Intel Xeon @ 2.10 GHz, 4 vCPU |
| RAM | 15 GiB total, no swap |
| Disk | 252 GB volume, ~31 GB available to this session |
| GPU | **None** (`nvidia-smi` missing) |
| Python | 3.13.16; pip 24.0 |
| PyTorch | **Not installed** (no CUDA check possible here) |
| pytest | Not installed |
| Node / npm | 22.22.0 / 10.9.4 |
| Git | 2.43.0 |
| .NET SDK | **Not installed** |
| PowerShell, Swift | Not installed |
| Browser | Playwright Chromium present under /opt/pw-browsers |

Consequences: the container is useful for the browser/backend/CI-style parts (Python, Node, Playwright). It **cannot** validate CUDA, the Windows Bridge, UI Automation, Hyper-V, or macOS anything.

## B. Reported, unverified: the owner's PC

| Item | Reported | Verification command (in script) | State |
|---|---|---|---|
| OS | Windows 11 | `Win32_OperatingSystem` | unverified |
| CPU | Ryzen 7 (model unknown) | `Win32_Processor` | unverified |
| RAM | 32 GB | `Win32_ComputerSystem` | unverified |
| GPU | RTX 3050 4 GB (laptop vs desktop unknown) | `nvidia-smi`, `Win32_VideoController` | unverified |
| Python / PyTorch CUDA / .NET / Node / Git | unknown | version commands | unverified |
| Free disk | unknown | `Get-PSDrive` | unverified |
| Hyper-V (needs Pro/Enterprise + virtualization enabled) | unknown | `Get-WindowsOptionalFeature` | unverified; decides whether TB-003 VM testing is possible |
| macOS hardware | Not reported at all | — | **no Mac is known to exist**; macOS qualification (XP-009, M12M) is blocked until one does |

## C. Back-of-envelope VRAM arithmetic (calculation, NOT measurement)

Assumptions: fp32 master weights, AdamW (2 states), fp32 gradients ⇒ ~16 bytes/parameter before activations.

| Params | Weights+grads+Adam | Notes |
|---|---|---|
| 5M | ~80 MB | trivial |
| 40M | ~640 MB | leaves ~3 GB nominal for activations/CUDA context on a 4 GB card |

Activations scale with batch × sequence × layers; the Windows desktop compositor also consumes VRAM. Sequence 256–512 with small micro-batches plus gradient accumulation and bf16/fp16 autocast looks *plausible* for ~15–40M, which is what the blueprint proposes, but **fit and throughput are unknown until M3 benchmarks run on the real GPU.** RTX 30-series (Ampere) supports bf16 in hardware per NVIDIA's published specs — this should be confirmed by `torch.cuda.is_bf16_supported()` on the machine, not assumed.

## D. Sustainable load policy (proposed, to be validated at M3/M4)

- Training and GPU-heavy tests are time-sliced on the 4 GB card (TB-022); no simultaneous GPU lanes unless measured headroom proves it.
- Training pauses on owner command, game/stream detection, thermal threshold, or low disk/RAM. Thresholds are set from measured idle/load temperatures, not guessed.
- If the GPU is a laptop part, sustained power/thermal limits may cut throughput; measure sustained tokens/sec over ≥30 minutes, not a burst.
