"""Canonical representation and row-MAC calculation for audit events."""

import hashlib
import hmac
import json
from datetime import UTC, datetime
from decimal import Decimal


FORMAT_VERSION = 1
DOMAIN = "spaceworks.audit-log"
MIN_INTEGER = -(2**63)
MAX_INTEGER = 2**63 - 1


class AuditCanonicalizationError(ValueError):
    pass


def canonicalize_meta(value, *, path="meta"):
    """Return a JSON-safe value with deterministic containers and strict numbers."""
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        if not MIN_INTEGER <= value <= MAX_INTEGER:
            raise AuditCanonicalizationError(
                f"{path} integer is outside signed 64-bit range."
            )
        return value
    if isinstance(value, (float, Decimal)):
        raise AuditCanonicalizationError(
            f"{path} must not contain floats or Decimal values."
        )
    if isinstance(value, list):
        return [
            canonicalize_meta(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        # JSONB has no non-string keys and json.dumps coerces int keys to strings, so the
        # stored value already has stringified keys -- the MAC must cover THAT. Real
        # callers rely on this (request acceptance stores {item_pk: quantity}).
        coerced = {}
        for key, item in value.items():
            if isinstance(key, bool) or not isinstance(key, (str, int)):
                raise AuditCanonicalizationError(
                    f"{path} object keys must be strings or integers."
                )
            text_key = key if isinstance(key, str) else str(key)
            if text_key in coerced:
                # json.dumps would silently drop one of these; refuse instead of
                # MAC-ing a value that differs from what gets stored.
                raise AuditCanonicalizationError(
                    f"{path} object keys collide after coercion: {text_key!r}."
                )
            coerced[text_key] = item
        value = coerced
        return {
            key: canonicalize_meta(value[key], path=f"{path}.{key}")
            for key in sorted(value)
        }
    raise AuditCanonicalizationError(
        f"{path} contains unsupported value type {type(value).__name__}."
    )


def canonical_timestamp(value):
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise AuditCanonicalizationError("created_at must be a timezone-aware datetime.")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def canonical_payload_bytes(
    *,
    makerspace_id,
    event_uuid,
    actor_id,
    action,
    target_type,
    target_id,
    meta,
    created_at,
):
    payload = {
        "format_version": FORMAT_VERSION,
        "domain": DOMAIN,
        "makerspace_id": makerspace_id,
        "event_uuid": str(event_uuid),
        "actor_id": actor_id,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "meta": canonicalize_meta(meta),
        "created_at": canonical_timestamp(created_at),
    }
    normalized = canonicalize_meta(payload, path="payload")
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def calculate_row_mac(key, **payload):
    if not isinstance(key, bytes) or len(key) != 32:
        raise ValueError("Audit MAC key must contain exactly 32 bytes.")
    return hmac.new(key, canonical_payload_bytes(**payload), hashlib.sha256).digest()
