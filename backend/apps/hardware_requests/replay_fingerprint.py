"""Canonical identity is derived from serializer output, never unvalidated JSON."""

from datetime import datetime, timezone
import hashlib
import json
from uuid import UUID


def normalized(value):
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalized(item) for item in value]
    return value


def fingerprint(envelope):
    encoded = json.dumps(normalized(envelope), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
