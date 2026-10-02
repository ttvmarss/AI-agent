"""Human-readable reports shared by the CLI and the desktop app. Estimates are always labeled as estimates."""
from .catalog import CATALOG, recommend
from .hardware import GB, estimate_tokens_per_s, fits


def hardware_report(p):
    lines = [f"CPU      {p.cpu} ({p.cores} threads)",
             f"RAM      {p.ram_bytes / GB:.0f} GiB, ~{p.ram_bw_gbps:.0f} GB/s (dual-channel estimate; set [hardware] ram_bw_gbps to override)"]
    if p.gpus:
        for g in p.gpus:
            note = ""
            if "3050" in g.name:
                note = ("  <- 8 GB model: 128-bit, 224 GB/s" if g.vram_bytes > 6.5 * GB
                        else "  <- 6 GB model: 96-bit, 168 GB/s (a slower, different card than the 8 GB one)")
            lines.append(f"GPU      {g.name}, {g.vram_bytes / GB:.0f} GiB VRAM, {g.bw_gbps:.0f} GB/s{note}")
        lines.append("Reading  Models that do not fit in VRAM spill into system RAM; decode speed then follows RAM "
                     "bandwidth. Mixture-of-experts models read only their active experts per token, so a 30B-A3B "
                     "model runs far faster than a dense 27B on this class of machine.")
    else:
        lines.append("GPU      none detected (CPU-only inference; speed follows RAM bandwidth)")
    return "\n".join(lines)


def ollama_tips(p):
    if not p.gpus or p.vram_total > 12.5 * GB:
        return ""
    return ("Ollama tuning for a small-VRAM GPU (variables documented in Ollama's FAQ; set them for your user account, "
            "then restart Ollama):\n"
            "  OLLAMA_FLASH_ATTENTION=1        reduces memory use as context grows\n"
            "  OLLAMA_KV_CACHE_TYPE=q8_0       context cache at ~1/2 the memory of f16 (needs flash attention)\n"
            "  OLLAMA_MAX_LOADED_MODELS=1      do not keep several models resident in 6-8 GiB of VRAM")


def model_table(p):
    rows = [f"{'model':<34}{'size':>7}{'active':>8}{'fits':>6}{'in VRAM':>9}{'est tok/s':>11}"]
    for m in sorted(CATALOG, key=lambda m: -m.equiv):
        s = m.size_gb * GB
        ok = fits(s, p)
        tps = estimate_tokens_per_s(s, m.total_b, m.active_b, p) if ok else 0
        rows.append(f"{m.tag:<34}{m.size_gb:>6.1f}G{m.active_b:>6.0f}B{'yes' if ok else 'no':>6}"
                    f"{'yes' if ok and fits(s, p, True) else '-':>9}{(f'{tps:.1f}' if ok else '-'):>11}")
    return "\n".join(rows)


def recommendation_report(p):
    r = recommend(p)
    out = ["Recommended local models for this machine (speeds are physics ESTIMATES, quality ranks are an unmeasured "
           "prior; run `praxis bench --all-ollama` after pulling to MEASURE both, and measured scores win):", ""]
    labels = {"daily": "daily driver  (best quality that is still interactive)",
              "fast": "fast helper   (fits fully in VRAM)",
              "deep": "deep thinker  (best quality that merely runs; slow, for hard background work)"}
    for key in ("daily", "fast", "deep"):
        x = r[key]
        if x:
            out.append(f"  {labels[key]}\n    {x.model.tag}  {x.model.size_gb:g} GB, ~{x.tps:.0f} tok/s (estimate)"
                       f"{' [MoE ' + format(x.model.total_b, 'g') + 'B / ' + format(x.model.active_b, 'g') + 'B active]' if x.model.moe else ''}\n"
                       f"    {x.pull_cmd}")
        else:
            out.append(f"  {labels[key]}\n    (nothing in the catalog fits this machine)")
    out += ["", model_table(p), "", "Catalog provenance: each row was read from the model's Ollama library page on "
            f"{CATALOG[0].checked} (see praxis/catalog.py)."]
    return "\n".join(out)
