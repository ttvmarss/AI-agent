"""Secret scanner. Free cloud tiers may log or train on prompts, so a prompt that contains a credential never goes to one."""
import re

PATTERNS = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("api key", re.compile(r"\bsk-[A-Za-z0-9_\-]{24,}\b")),
    ("google api key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b")),
    ("slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
    # (?<![A-Za-z0-9]) rather than \b so DB_PASSWORD / STRIPE_SECRET_KEY style names match (underscore is a word char)
    ("password assignment", re.compile(r"(?i)(?<![A-Za-z0-9])(?:pass(?:word|wd)?|secret|api[_-]?key|access[_-]?token|auth[_-]?token)"
                                       r"[A-Za-z_]*\s*[:=]\s*['\"]?[^\s'\"]{8,}")),
]


def find_secrets(text):
    return sorted({kind for kind, rx in PATTERNS if rx.search(text or "")})


def redact(text):
    for kind, rx in PATTERNS:
        text = rx.sub(f"[REDACTED {kind}]", text)
    return text
