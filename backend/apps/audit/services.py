import ipaddress
import re

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import models
from django.utils.crypto import salted_hmac

from apps.audit.models import AuditLog
from apps.encryption.blind_index import canonical_email


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

    return AuditLog.objects.create(
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        makerspace=makerspace,
        meta=_sanitize_meta(clean_meta),
    )
