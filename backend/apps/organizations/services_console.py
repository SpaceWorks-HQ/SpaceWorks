"""Superadmin organization setup, with tenant roots locked before changing reach."""
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import APIException, PermissionDenied

from apps.accounts import rbac
from apps.admin_api.permissions import active_user
from apps.audit import services as audit
from apps.makerspaces.servability import servable_queryset
from apps.organizations.access import is_superadmin
from apps.organizations.models import Organization, OrganizationMakerspace
from apps.tenant_migration.gate_runtime import assert_write_allowed


class OrganizationConflict(APIException):
    status_code = 409
    default_code = "organization_conflict"
    default_detail = "The organization or owner relationship changed. Refresh and try again."

    def __init__(self, detail=None):
        super().__init__({"detail": detail or self.default_detail, "code": self.default_code})


def require_superadmin(actor):
    if not active_user(actor) or not is_superadmin(actor):
        raise PermissionDenied()


def visible_spaces(actor):
    # Even a local membership must not let a platform actor grant authority by
    # proxy into a space that explicitly opted out of platform access.
    return rbac.scope_by_action(actor, rbac.Action.MANAGE_MAKERSPACE,
                                servable_queryset(), field="pk").filter(superadmin_access_enabled=True)


@transaction.atomic
def create_organization(actor, **values):
    require_superadmin(actor)
    try:
        with transaction.atomic():
            row = Organization.objects.create(created_by=actor, **values)
    except IntegrityError as exc:
        raise OrganizationConflict("An organization with this slug already exists.") from exc
    audit.record(actor, "organization.created", target=row, meta={"fields": sorted(values)})
    return row


@transaction.atomic
def change_link(actor, organization_id, makerspace_id, *, relationship=None):
    require_superadmin(actor)
    # Resolve visibility before returning a gate error for a hidden tenant. Take
    # the shared freeze lock before the makerspace root lock, as other services do.
    get_object_or_404(visible_spaces(actor), pk=makerspace_id)
    assert_write_allowed(makerspace_id)
    space = get_object_or_404(visible_spaces(actor).select_for_update(), pk=makerspace_id)
    organization = get_object_or_404(Organization.objects.select_for_update(), pk=organization_id)
    links = OrganizationMakerspace.objects.filter(organization=organization, makerspace=space)
    if relationship is None:
        row = get_object_or_404(links)
        audit.record(actor, "organization.link_deleted", makerspace=space, target=row,
                     meta={"organization_id": organization.pk, "relationship": row.relationship})
        row.delete()
        return None
    if not organization.is_active:
        raise OrganizationConflict("Reactivate the organization before linking a makerspace.")
    if relationship not in OrganizationMakerspace.Relationship.values:
        from rest_framework.exceptions import ValidationError
        raise ValidationError({"relationship": "Unknown relationship."})
    try:
        with transaction.atomic():
            row, created = links.get_or_create(defaults={"relationship": relationship, "created_by": actor})
            changed = not created and row.relationship != relationship
            if changed:
                row.relationship = relationship
                row.save(update_fields=["relationship", "updated_at"])
    except IntegrityError as exc:
        raise OrganizationConflict("This makerspace already has an owner organization.") from exc
    if created or changed:
        audit.record(actor, "organization.link_created" if created else "organization.link_updated",
                     makerspace=space, target=row,
                     meta={"organization_id": organization.pk, "relationship": relationship})
    return row
