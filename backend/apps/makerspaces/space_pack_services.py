"""Actor-scoped, transactional pack preview/apply and platform presets."""
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied

from apps.accounts import rbac
from apps.admin_api.permissions import active_user
from apps.audit import services as audit
from .guards import require_feature
from .models import SpacePackProfile
from .role_authority import _superadmin
from .servability import servable_queryset
from .space_pack_export import scoped_rows
from .space_pack_format import PackConflict, PackError, open_pack
from .space_pack_mutations import write_section
from .space_pack_prepare import prepare, settings_serializer
from .space_pack_validation import validate_configuration, validate_profile_references


def authorized_space(actor, pk, *, lock=False):
    if not active_user(actor):
        raise PermissionDenied()
    query = rbac.scope_by_action(actor, rbac.Action.MANAGE_MAKERSPACE,
                                servable_queryset(), field="pk")
    if lock:
        query = query.select_for_update()
    return get_object_or_404(query, pk=pk)


@transaction.atomic
def preview_pack(actor, makerspace, pack):
    makerspace = authorized_space(actor, makerspace.pk)
    require_feature(makerspace, "packs.import")
    _, preview = prepare(actor, makerspace, open_pack(pack))
    return {**preview, "applied": False}


@transaction.atomic
def apply_pack(actor, makerspace, pack, *, base_checksum=None, creating=False):
    # Match ordinary settings writers: root then recipient rows, before domain rows.
    authorized_space(actor, makerspace.pk)
    from apps.tenant_migration.gate_runtime import assert_write_allowed
    assert_write_allowed(makerspace.pk)
    from apps.backup.custody import with_makerspace_custody_lock
    with with_makerspace_custody_lock(makerspace.pk):
        return _apply_pack_locked(actor, makerspace, pack, base_checksum=base_checksum, creating=creating)


def _apply_pack_locked(actor, makerspace, pack, *, base_checksum, creating):
    makerspace = authorized_space(actor, makerspace.pk, lock=True)
    if creating:
        require_superadmin(actor)
    else:
        require_feature(makerspace, "packs.import")
        if not base_checksum:
            raise PackError("pack_preview_required", "Preview this pack before applying it.")
    config = open_pack(pack)
    steps, preview = prepare(actor, makerspace, config)
    if not creating and preview["base_checksum"] != base_checksum:
        raise PackConflict("stale_pack_preview", "Configuration changed. Preview the pack again.")
    # The capability service owns dependency validation and the backup custody guard.
    if set(makerspace.enabled_modules or []) != set(config["modules"]):
        from .module_install import ModuleInstallError, replace_modules
        try:
            replace_modules(makerspace, config["modules"], actor)
        except ModuleInstallError as exc:
            raise PackError("invalid_pack_modules", str(exc)) from exc
    settings = dict(config["settings"])
    # The admission writer owns these aliases once configured. Sending them to
    # the legacy editor would downgrade vouch/closed to its nearest legacy mode,
    # even on an otherwise idempotent import.
    if config["admission_policy"] is not None:
        settings.pop("membership_policy")
        settings.pop("membership_dues_amount")
    else:
        settings = {key: value for key, value in settings.items()
                    if getattr(makerspace, key) != value}
    serializer = settings_serializer(actor, makerspace, {
        **settings, "enabled_features": config["features"],
    })
    makerspace = serializer.save()
    audit.record(actor, "makerspace.updated", makerspace=makerspace, target=makerspace,
                 meta={"fields": sorted({key for change in preview["changes"]
                       if change["section"] == "settings" for key in change["after"]})})
    for key, value in config["opening_hours"].items():
        setattr(makerspace, key, value)
    makerspace.save(update_fields=["timezone", "opening_hours", "updated_at"])
    if any(change["section"] == "opening_hours" for change in preview["changes"]):
        audit.record(actor, "makerspace.updated", makerspace=makerspace, target=makerspace,
                     meta={"fields": ["timezone", "opening_hours"]})
    if any(change["section"] == "features" for change in preview["changes"]):
        audit.record(actor, "makerspace.features_changed", makerspace=makerspace, target=makerspace,
                     meta={"fields": ["enabled_features"]})
    from apps.data_export.space_pack_configuration import SECTIONS
    for section, row, values in steps:
        # Names in the pack are references to the TARGET, never source IDs. Newly
        # created categories/plans earlier in the same transaction now have real IDs.
        values = dict(values)
        for field, other_section, natural_field in (
            ("category", "categories", "slug"), ("default_plan", "membership_plans", "name"),
        ):
            if field in values and values[field] is not None:
                reference = values[field]
                values[field] = get_object_or_404(
                    scoped_rows(actor, makerspace, SECTIONS[other_section]),
                    **{natural_field: getattr(reference, natural_field)},
                )
        write_section(actor, makerspace, section, row, values)
    # Admission's ordinary settings editor opts feature gates in/out. A pack
    # also carries the operator's later kill-switch choices, so restore those
    # explicit choices after the domain writer has synchronized its aliases.
    makerspace.refresh_from_db()
    if set(makerspace.enabled_features) != set(config["features"]):
        settings_serializer(actor, makerspace, {"enabled_features": config["features"]}).save()
        audit.record(actor, "makerspace.features_changed", makerspace=makerspace,
                     target=makerspace, meta={"fields": ["enabled_features"]})
    audit.record(actor, "makerspace.space_pack_applied", makerspace=makerspace,
                 target=makerspace, meta={"checksum": pack["checksum"],
                     "sections": sorted({item["section"] for item in preview["changes"]})})
    return {**preview, "applied": True}


def require_superadmin(actor):
    if not active_user(actor) or not _superadmin(actor):
        raise PermissionDenied("Only a superadmin may manage platform install profiles.")


@transaction.atomic
def save_profile(actor, *, name, pack):
    require_superadmin(actor)
    config = validate_configuration(open_pack(pack))
    validate_profile_references(config)
    # Validate ordinary settings with their existing serializer, without a tenant
    # write. Full target-specific grant/reference checks happen at creation/import.
    from .models import Makerspace
    candidate = Makerspace(enabled_modules=pack["configuration"]["modules"],
                           enabled_features=pack["configuration"]["features"])
    settings_serializer(actor, candidate, pack["configuration"]["settings"])
    row = SpacePackProfile(name=name, pack=pack)
    row.full_clean()
    row.save()
    audit.record(actor, "platform.space_pack_profile_saved", target=row,
                 meta={"checksum": pack["checksum"]})
    return row


def apply_saved_profile(actor, makerspace, profile_id):
    require_superadmin(actor)
    profile = get_object_or_404(SpacePackProfile.objects.select_for_update(), pk=profile_id)
    return apply_pack(actor, makerspace, profile.pack, creating=True)
