"""RAW MATERIAL -> FORMAT DETECTION. Reads local files only; nothing is fetched here. The first directory under a source root is the declared category."""
import json
import os
from dataclasses import dataclass, field

from ..utilities.files import sha256_text

TEXT_EXT = {".txt", ".md", ".rst", ".py", ".js", ".ts", ".c", ".h", ".cpp", ".java", ".go", ".rs", ".sh", ".json", ".yaml", ".yml", ".toml", ".xml", ".csv", ".ini",
            ".cfg", ".html", ".css", ".tex", ".sql", ".jsonl", ""}
CODE_EXT = {".py": "python", ".js": "javascript", ".ts": "typescript", ".c": "c", ".h": "c", ".cpp": "cpp", ".java": "java", ".go": "go", ".rs": "rust", ".sh": "shell", ".sql": "sql"}
STRUCT_EXT = {".json", ".yaml", ".yml", ".toml", ".xml", ".csv", ".ini", ".cfg", ".jsonl"}
DOC_EXT = {".md", ".rst", ".tex", ".html"}


@dataclass
class RawDoc:
    path: str
    rel: str
    fmt: str                     # text | binary | unreadable
    text: str = ""
    declared_category: str = ""
    bad_decode: int = 0          # bytes that were not valid UTF-8 (replaced)
    provenance: dict = field(default_factory=dict)


def detect_format(raw: bytes):
    if b"\x00" in raw[:4096]:
        return "binary"
    return "text"


def load_provenance(root):
    p = os.path.join(root, "PROVENANCE.jsonl")
    out = {}
    if os.path.isfile(p):
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    out[r["file"].replace("\\", "/")] = {k: v for k, v in r.items() if k != "file"}
    return out


def iter_raw(sources, base="."):
    for src in sources:
        root = src if os.path.isabs(src) else os.path.join(base, src)
        if not os.path.isdir(root):
            raise FileNotFoundError(f"data source directory not found: {root} (run scripts/fetch_corpus.py or point data.sources at your own text)")
        prov = load_provenance(root)
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for fn in sorted(files):
                if fn == "PROVENANCE.jsonl" or fn.startswith("."):
                    continue
                path = os.path.join(dirpath, fn)
                rel = os.path.relpath(path, root).replace("\\", "/")
                ext = os.path.splitext(fn)[1].lower()
                with open(path, "rb") as f:
                    raw = f.read()
                if ext not in TEXT_EXT or detect_format(raw) == "binary":
                    yield RawDoc(path, rel, "binary", provenance=prov.get(rel, {}))
                    continue
                text = raw.decode("utf-8", errors="replace")
                bad = text.count("�")
                parts = rel.split("/")
                yield RawDoc(path, rel, "text", text, parts[0] if len(parts) > 1 else "", bad, prov.get(rel, {}))
