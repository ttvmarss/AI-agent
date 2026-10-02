"""SAFETY / CORRUPTION FILTERING: documents that contain credentials are dropped whole; e-mail addresses are redacted. Counts go to the manifest."""
import re

SECRET = [("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
          ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
          ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
          ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
          ("api_key_assignment", re.compile(r"(?i)\b(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token)\b\s*[:=]\s*['\"][A-Za-z0-9_\-]{24,}['\"]")),
          ("openai_style_key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"))]
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def scan(text):
    """-> (reason or None, redacted_text, n_redactions)."""
    for name, rx in SECRET:
        if rx.search(text):
            return f"secret:{name}", text, 0
    out, n = EMAIL.subn("<EMAIL>", text)
    return None, out, n
