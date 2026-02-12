from __future__ import annotations

import re


_PATTERNS = [
    # Authorization headers and bearer tokens.
    (re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(bearer\s+)[^\s,;]+"), r"\1[REDACTED]"),
    # Common secret key/value pairs.
    (re.compile(r"(?i)\b(token|access_token|refresh_token|api_key|secret)\s*[:=]\s*[^\s,;]+"), r"\1=[REDACTED]"),
]


def redact_secrets(text: str | None) -> str | None:
    if text is None:
        return None
    out = text
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out

