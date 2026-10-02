"""QUALITY FILTERING. Returns None to keep a document, or the name of the rule that rejected it (counted in the manifest)."""


def check(text: str, category: str, min_chars: int, max_chars: int, bad_decode: int = 0):
    n = len(text)
    if n < min_chars:
        return "too_short"
    if n > max_chars:
        return "too_long"
    if bad_decode / max(n, 1) > 0.01:
        return "corrupt_encoding"
    lines = text.split("\n")
    nonempty = [ln for ln in lines if ln.strip()]
    if not nonempty:
        return "empty"
    if max(len(ln) for ln in nonempty) > 20_000 and category != "structured_data":
        return "minified_or_binary_like"
    if len(nonempty) >= 20 and len(set(nonempty)) / len(nonempty) < 0.2 and category != "structured_data":
        return "repetitive_lines"
    if category in ("language", "science", "mathematics"):
        alpha = sum(c.isalpha() for c in text) / n
        if alpha < 0.5:
            return "low_alpha_ratio"
    if sum(not c.isprintable() and c not in "\n\t" for c in text) / n > 0.02:
        return "non_printable"
    return None
