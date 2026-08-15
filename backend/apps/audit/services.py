from django.db import models

from apps.audit.models import AuditLog


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
        meta=clean_meta,
    )
