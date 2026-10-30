"""Defensive redaction for Knowledge Engine diagnostics."""
from __future__ import annotations
import re
_PATTERNS=(re.compile(r"rag_sk_[A-Za-z0-9._-]+",re.I),re.compile(r"Bearer\s+[^\s,;]+",re.I),re.compile(r"Authorization\s*[:=]\s*[^\s,;]+",re.I))
def redact(value):
    if value is None:return None
    text=str(value)
    for p in _PATTERNS:text=p.sub("[REDACTED]",text)
    return text[:500]
