from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.organizations import governance
from apps.organizations.access import lock_governance_membership
from apps.organizations.models import Organization


PUBLIC_PROFILE_FIELDS = frozenset(
    {"name", "slug", "description", "website", "public_profile_enabled"}
)


@transaction.atomic
def update_profile(organization, *, actor, **changes):
    unknown = set(changes) - PUBLIC_PROFILE_FIELDS
    if unknown:
        raise ValidationError({field: "This field cannot be edited here." for field in unknown})

    locked = Organization.objects.select_for_update().get(pk=organization.pk)
    lock_governance_membership(
        actor,
        locked,
        governance.MANAGE_ORGANIZATION_PROFILE,
    )
    changed_fields = []
    for field, value in changes.items():
        if getattr(locked, field) != value:
            setattr(locked, field, value)
            changed_fields.append(field)
    if changed_fields:
        locked.save(update_fields=[*changed_fields, "updated_at"])
        audit.record(
            actor,
            "organization.profile_updated",
            target=locked,
            meta={"fields": sorted(changed_fields), "slug": locked.slug},
        )
    return locked
