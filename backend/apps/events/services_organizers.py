from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import User
from apps.audit import services as audit
from apps.events.models import Event
from apps.events.organizer_authority import can_manage_event
from apps.events.organizer_models import EventOrganizer
from apps.makerspaces.guards import require_module_locked
from apps.organizations.models import Organization, OrganizationMembership


MAX_ORGANIZERS = 50


def _is_superadmin(actor):
    return bool(actor.is_superuser or actor.role == User.Role.SUPERADMIN)


@transaction.atomic
def replace_organizers(event, *, actor, organization_ids):
    requested = list(organization_ids)
    if len(requested) != len(set(requested)):
        raise ValidationError({"organization_ids": "Organization IDs must be unique."})
    if len(requested) > MAX_ORGANIZERS:
        raise ValidationError(
            {"organization_ids": f"At most {MAX_ORGANIZERS} organizers are allowed."}
        )

    locked_event = Event.objects.select_for_update().get(pk=event.pk)
    require_module_locked(locked_event.makerspace_id, "events")
    if not can_manage_event(actor, locked_event):
        raise PermissionDenied()

    existing = list(
        EventOrganizer.objects.select_for_update()
        .filter(event=locked_event)
        .order_by("pk")
    )
    existing_ids = {link.organization_id for link in existing}
    organizations = list(
        Organization.objects.select_for_update()
        .filter(pk__in=requested, is_active=True)
        .order_by("pk")
    )
    if {organization.pk for organization in organizations} != set(requested):
        raise ValidationError({"organization_ids": "An organization is unavailable."})

    newly_assigned = set(requested) - existing_ids
    if not _is_superadmin(actor) and newly_assigned:
        memberships = OrganizationMembership.objects.select_for_update().filter(
            organization_id__in=newly_assigned,
            user=actor,
            status=OrganizationMembership.Status.ACTIVE,
        )
        if set(memberships.values_list("organization_id", flat=True)) != newly_assigned:
            raise PermissionDenied(
                "You need an active membership in every assigned organization."
            )

    old_ids = sorted(link.organization_id for link in existing)
    if old_ids != sorted(requested):
        EventOrganizer.objects.filter(pk__in=[link.pk for link in existing]).delete()
        EventOrganizer.objects.bulk_create(
            [
                EventOrganizer(
                    event=locked_event,
                    organization=organization,
                    created_by=actor,
                )
                for organization in organizations
            ]
        )
        audit.record(
            actor,
            "event.organizers_updated",
            makerspace=locked_event.makerspace,
            target=locked_event,
            meta={"old_organization_ids": old_ids, "organization_ids": sorted(requested)},
        )

    return Event.objects.prefetch_related("organizers__organization").get(pk=locked_event.pk)
