from __future__ import annotations
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re


def _headers(exc):
    response=getattr(exc,"response",None)
    raw=getattr(response,"headers",None) or {}
    try:return {str(k).casefold():str(v) for k,v in raw.items()}
    except Exception:return {}


def _positive(value):
    try:return max(0.0,float(value))
    except Exception:return None


def _retry_after(value,now=None):
    if not value:return None
    seconds=_positive(str(value).strip())
    if seconds is not None:return seconds
    try:
        target=parsedate_to_datetime(str(value).strip())
        if target.tzinfo is None:target=target.replace(tzinfo=timezone.utc)
        current=now or datetime.now(timezone.utc)
        return max(0.0,(target-current).total_seconds())
    except Exception:return None


def _ratelimit_reset(value):
    if not value:return None
    match=re.search(r"(?:^|;)\s*t\s*=\s*(\d+(?:\.\d+)?)",str(value),re.I)
    return _positive(match.group(1)) if match else None


def rate_limit_metadata(exc,now=None):
    headers=_headers(exc)
    retry_after=_retry_after(headers.get("retry-after"),now)
    reset=_ratelimit_reset(headers.get("ratelimit"))
    suggested=retry_after if retry_after is not None else reset
    source="retry-after" if retry_after is not None else "ratelimit_t" if reset is not None else None
    return {
        "retry_after_seconds":retry_after,
        "ratelimit_reset_seconds":reset,
        "rate_limit_wait_suggested_seconds":suggested,
        "rate_limit_wait_source":source,
        "ratelimit_header":headers.get("ratelimit"),
        "ratelimit_policy_header":headers.get("ratelimit-policy"),
        "inference_provider_header":headers.get("x-inference-provider"),
    }
