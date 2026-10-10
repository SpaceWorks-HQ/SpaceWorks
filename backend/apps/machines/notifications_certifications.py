"""Certification evidence edges and member expiry variants, without grant notes."""

from apps.integrations.destinations import NotificationScope
from apps.integrations.email_templates_registry_helpers import bag
from apps.integrations.notifications_research import bounded, notify_family, safe_adapter


@safe_adapter
def notify_certification(grant, event):
    certification = grant.certification_type
    return notify_family(
        certification.makerspace, "certifications", event,
        bag(id=grant.pk, name=bounded(certification.name),
            expires_at=bounded(grant.expires_at.isoformat() if grant.expires_at else "")),
        data={"certification_grant_id": grant.pk, "certification_type_id": certification.pk,
              "membership_id": grant.membership_id},
        scope=NotificationScope(machine_type=certification.machine_type_id),
        member_id=grant.membership.user_id,
    )
