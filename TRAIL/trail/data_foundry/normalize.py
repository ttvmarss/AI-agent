"""NORMALIZATION: canonical Unicode, line endings, control characters."""
import re
import unicodedata

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BLANKS = re.compile(r"\n{4,}")


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    t = _CTRL.sub("", t)
    t = "\n".join(line.rstrip() for line in t.split("\n"))
    return _BLANKS.sub("\n\n\n", t).strip("\n") + "\n"
