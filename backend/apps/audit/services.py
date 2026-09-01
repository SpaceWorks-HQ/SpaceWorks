import ipaddress
import logging
import re
import uuid
from datetime import UTC, datetime

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import models
from django.utils.crypto import salted_hmac

from apps.audit.canonical import calculate_row_mac, canonicalize_meta
from apps.audit.keys import (
    AuditMacKeyUnavailable,
    audit_mac_configured,
    get_audit_mac_key,
)
from apps.audit.models import AuditLog
from apps.encryption.blind_index import canonical_email

logger = logging.getLogger(__name__)


_FINGERPRINT_PREFIX = "hmac-sha256:"
_EMAIL_KEY = re.compile(r"(?:^|_)(?:email(?:_address)?|emails)$")
_IP_KEY = re.compile(r"(?:^|_)(?:ip|ip_address)$")


def _fingerprint(kind, value):
    digest = salted_hmac(
        "apps.audit.metadata.v1",
        f"{kind}:{value}",
        algorithm="sha256",
    ).hexdigest()
    return f"{_FINGERPRINT_PREFIX}{digest}"


def _sensitive_scalar(value, key):
    if not isinstance(value, str) or not value or value.startswith(_FINGERPRINT_PREFIX):
        return None

    candidate = value.strip()
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        pass
    else:
        return "ip", str(address)

    try:
        validate_email(candidate)
    except ValidationError:
        pass
    else:
        return "email", canonical_email(candidate)

    normalized_key = re.sub(r"[^a-z0-9]+", "_", str(key or "").lower()).strip("_")
    if _EMAIL_KEY.search(normalized_key):
        return "email", canonical_email(candidate)
    if _IP_KEY.search(normalized_key):
        return "ip", candidate.lower()
    return None


def _sanitize_meta(value, *, key=None):
    """Recursively replace email/IP values without changing metadata paths."""
    if isinstance(value, dict):
        return {
            item_key: _sanitize_meta(item, key=item_key)
            for item_key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_meta(item, key=key) for item in value]
    sensitive = _sensitive_scalar(value, key)
    return _fingerprint(*sensitive) if sensitive else value


def record(actor, action, *, makerspace=None, target=None, target_type="", meta=None):
    target_id = ""
    if isinstance(target, models.Model):
        target_type = target._meta.label_lower
        target_id = str(target.pk)

    clean_meta = dict(meta or {})
    claim = getattr(actor, "_claim_audit_context", None)
    if claim is not None:
        # These keys are reserved and overwrite caller input. Attribution must not be
        # optional at each mutation surface, or forgeable by a service's metadata.
        clean_meta.update(
            {
                "claim_session_id": claim.session_id,
                "claim_issued_by_id": claim.issued_by_id,
                "claim_redemption_ip": claim.redemption_ip,
            }
        )

    stored_meta = canonicalize_meta(_sanitize_meta(clean_meta))
    event_uuid = uuid.uuid4()
    created_at = datetime.now(UTC)
    actor_id = actor.pk if actor is not None else None
    makerspace_id = makerspace.pk if makerspace is not None else None
    action = str(action)
    target_type = str(target_type or "")
    target_id = str(target_id or "")
    # An audit row must never be lost to a key problem: record() is on every
    # state-changing path, so raising here would take out issue/return entirely. A NULL
    # row_mac is an already-modelled, honest "unattested" state (the CHECK constraint
    # only binds non-NULL values), and verify_audit_macs reports it.
    row_mac = None
    if audit_mac_configured():
        try:
            mac_key = get_audit_mac_key(makerspace_id)
        except AuditMacKeyUnavailable:
            logger.critical(
                "audit_mac_key_unavailable",
                extra={"makerspace_id": makerspace_id, "action": action},
            )
        else:
            row_mac = calculate_row_mac(
                mac_key,
                makerspace_id=makerspace_id,
                event_uuid=event_uuid,
                actor_id=actor_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                meta=stored_meta,
                created_at=created_at,
            )

    return AuditLog.objects.create(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        makerspace_id=makerspace_id,
        meta=stored_meta,
        event_uuid=event_uuid,
        row_mac=row_mac,
        created_at=created_at,
    )
