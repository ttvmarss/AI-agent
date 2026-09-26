"""evaluation.py — the stage AFTER research: consumes a ContextArtifact and
measures each candidate against this machine and this project.

Every check is computed from real data: facts the inspection gathered,
this PC's actual RAM/GPU (psutil / nvidia-smi), and the host project's
actual languages (file extensions on disk). A check with no data reports
`unknown` — it never guesses.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Dict, Iterator, List, Optional, Tuple

from .models import ContextArtifact, ResearchSource, new_id, now
from .providers.base import license_class

VERDICT_POINTS = {"pass": 1.0, "caution": 0.5, "fail": 0.0, "unknown": 0.35}
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def host_profile(project_root: Optional[str] = None) -> Dict:
    prof: Dict = {"ram_gb": None, "gpu": None, "vram_gb": None, "languages": [], "os": sys.platform}
    try:
        import psutil  # in JARVIS's requirements

        prof["ram_gb"] = round(psutil.virtual_memory().total / 2**30, 1)
    except Exception:  # noqa: BLE001
        try:
            with open("/proc/meminfo", encoding="utf-8") as f:
                kb = int(f.readline().split()[1])
            prof["ram_gb"] = round(kb / 2**20, 1)
        except Exception:  # noqa: BLE001
            pass
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5, creationflags=CREATE_NO_WINDOW,
            ).stdout.strip().splitlines()
            if out:
                name, mem = [x.strip() for x in out[0].split(",")[:2]]
                prof["gpu"], prof["vram_gb"] = name, round(float(mem) / 1024, 1)
        except Exception:  # noqa: BLE001
            pass
    root = project_root or os.environ.get("RESEARCH_LOCAL_ROOT") or os.getcwd()
    counts = {"Python": 0, "JavaScript/TypeScript": 0}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {".git", "node_modules", "vendor", "__pycache__", ".venv", "venv"}]
        for fn in filenames:
            if fn.endswith(".py"):
                counts["Python"] += 1
            elif fn.endswith((".js", ".ts", ".tsx", ".jsx", ".mjs")):
                counts["JavaScript/TypeScript"] += 1
    prof["languages"] = [k for k, v in sorted(counts.items(), key=lambda kv: -kv[1]) if v]
    return prof


def _lang_family(lang: Optional[str]) -> Optional[str]:
    if not lang:
        return None
    l = lang.lower()
    if l in ("python", "jupyter notebook"):
        return "Python"
    if l in ("javascript", "typescript", "javascript/typescript", "vue", "svelte"):
        return "JavaScript/TypeScript"
    return lang


def check(criterion: str, src: ResearchSource, host: Dict) -> Tuple[str, str]:
    m = src.meta
    if criterion == "license":
        lic = m.get("license")
        cls = license_class(lic)
        return {
            "permissive": ("pass", f"{lic} — permissive"),
            "copyleft": ("caution", f"{lic} — copyleft obligations"),
            "other": ("caution", f"{lic} — review terms"),
            "unknown": ("unknown", "No license detected"),
        }[cls]
    if criterion == "maintenance":
        age = m.get("days_since_update")
        if age is None:
            return "unknown", "No update date found"
        if age <= 180:
            return "pass", f"Updated {age} days ago"
        if age <= 365:
            return "caution", f"Updated {age} days ago"
        return "fail", f"No update for {age} days"
    if criterion == "adoption":
        if isinstance(m.get("stars"), int):
            s = m["stars"]
            return ("pass" if s >= 1000 else "caution" if s >= 100 else "fail"), f"{s:,} GitHub stars"
        if isinstance(m.get("weekly_downloads"), int):
            d = m["weekly_downloads"]
            return ("pass" if d >= 5000 else "caution" if d >= 200 else "fail"), f"{d:,} downloads / week"
        return "unknown", "No adoption data"
    if criterion == "stack":
        fam = _lang_family(m.get("language"))
        langs = host.get("languages") or []
        if not fam:
            return "unknown", "Implementation language unknown"
        if fam in langs:
            return "pass", f"{fam} — matches host stack ({', '.join(langs)})"
        return "caution", f"{fam} — would run as a separate service"
    if criterion == "hardware":
        need_v, need_r = m.get("min_vram_gb"), m.get("min_ram_gb")
        if need_v is None and need_r is None:
            return "unknown", "No hardware requirement stated in docs"
        notes, verdict = [], "pass"
        if need_v is not None:
            have = host.get("vram_gb")
            if have is None:
                verdict = "unknown"
                notes.append(f"needs {need_v:g} GB VRAM; GPU not detected")
            elif have >= need_v:
                notes.append(f"needs {need_v:g} GB VRAM, have {have:g} GB")
            else:
                verdict = "fail"
                notes.append(f"needs {need_v:g} GB VRAM, have {have:g} GB")
        if need_r is not None:
            have = host.get("ram_gb")
            if have is None:
                verdict = "unknown" if verdict == "pass" else verdict
                notes.append(f"needs {need_r:g} GB RAM; RAM unknown")
            elif have >= need_r:
                notes.append(f"needs {need_r:g} GB RAM, have {have:g} GB")
            else:
                verdict = "fail"
                notes.append(f"needs {need_r:g} GB RAM, have {have:g} GB")
        return verdict, "; ".join(notes)
    if criterion == "footprint":
        kb, deps = m.get("unpacked_kb"), m.get("dependency_count")
        if kb is None and deps is None and m.get("size_kb") is None:
            return "unknown", "Size unknown"
        if kb is not None:
            return ("pass" if (deps or 0) <= 25 else "caution"), f"{kb:,} KB unpacked, {deps} deps"
        return "pass", f"repo {m['size_kb']:,} KB"
    return "unknown", "Unsupported check"


class Evaluator:
    def __init__(self, criteria: List[str], host: Dict) -> None:
        self.criteria = [c for c in criteria] + (["footprint"] if "footprint" not in criteria else [])
        self.host = host

    def run(self, candidates: List[ResearchSource]) -> Iterator[Tuple[ResearchSource, str, str, str]]:
        for src in candidates:
            for c in self.criteria:
                verdict, detail = check(c, src, self.host)
                yield src, c, verdict, detail

    @staticmethod
    def comparison_artifact(parent: ContextArtifact, candidates: List[ResearchSource],
                            results: Dict[str, Dict[str, Tuple[str, str]]], host: Dict) -> ContextArtifact:
        rows = []
        for src in candidates:
            r = results.get(src.source_id, {})
            pts = [VERDICT_POINTS[v] for v, _ in r.values()] or [0]
            score = round(sum(pts) / len(pts), 3)
            rows.append((score, src, r))
        rows.sort(key=lambda x: -x[0])
        findings = []
        for rank, (score, src, r) in enumerate(rows, 1):
            findings.append({
                "title": src.title,
                "rank": rank,
                "fit_score": score,
                "url": src.url,
                "detail": "; ".join(f"{c}: {d}" for c, (v, d) in r.items()),
                "verdicts": {c: v for c, (v, d) in r.items()},
                "source_ids": [src.source_id],
            })
        top = findings[0]["title"] if findings else None
        unknowns = sum(1 for f in findings for v in f["verdicts"].values() if v == "unknown")
        summary = (f"{top} ranks first on measured fit ({findings[0]['fit_score']:.2f}). "
                   f"{unknowns} checks had no data and were left unknown." if top else "No candidates to compare.")
        return ContextArtifact(
            id=new_id("art"),
            type="CANDIDATE_COMPARISON",
            title="CANDIDATE COMPARISON",
            research_session_id=parent.research_session_id,
            summary=summary,
            findings=findings,
            evidence_ids=list(parent.evidence_ids),
            source_ids=[s.source_id for _, s, _ in rows],
            created_at=now(),
            confidence_metadata={"method": "measured checks", "host": host, "unknown_checks": unknowns},
            derived_from=[parent.id],
        )
