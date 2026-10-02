"""LANGUAGE / DOMAIN TAGGING. The declared directory wins; otherwise the file type decides. Natural-language script is detected from characters."""
from .ingest import CODE_EXT, DOC_EXT, STRUCT_EXT
import os

CATEGORIES = ("language", "code", "mathematics", "science", "technical", "structured_data", "reasoning", "educational")


def category_of(rel, declared):
    if declared:
        return declared
    ext = os.path.splitext(rel)[1].lower()
    if ext in CODE_EXT:
        return "code"
    if ext in STRUCT_EXT:
        return "structured_data"
    if ext in DOC_EXT:
        return "technical"
    return "language"


def script_of(text):
    """Dominant script of the letters: latin, cjk, cyrillic, greek, arabic, other."""
    counts = {}
    for c in text[:20000]:
        if not c.isalpha():
            continue
        o = ord(c)
        s = "latin" if o < 0x250 else "greek" if 0x370 <= o < 0x400 else "cyrillic" if 0x400 <= o < 0x530 else "arabic" if 0x600 <= o < 0x700 else \
            "cjk" if 0x3040 <= o < 0xA000 or 0xAC00 <= o < 0xD7B0 else "other"
        counts[s] = counts.get(s, 0) + 1
    return max(counts, key=counts.get) if counts else "none"


def programming_language(rel):
    return CODE_EXT.get(os.path.splitext(rel)[1].lower(), "")
