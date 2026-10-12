"""Read-only validation and a concrete ordered diff against a scoped target."""
from copy import copy
from types import SimpleNamespace

from django.apps import apps
from rest_framework.exceptions import PermissionDenied

from apps.accounts import rbac
from apps.admin_api.serializers_makerspaces import MakerspaceSerializer
from apps.data_export.space_pack_configuration import SECTIONS, SETTINGS_FIELDS
from .role_authority import _superadmin, _validate_actions
from .space_pack_export import configuration_for, project_row, scoped_rows
from .space_pack_format import PackError, seal
from .space_pack_validation import (
    clean_row, identity_for, require_canonical_values, validate_configuration,
)


def settings_serializer(actor, makerspace, settings):
    serializer = MakerspaceSerializer(makerspace, data=settings, partial=True,
                                     context={"request": SimpleNamespace(user=actor)})
    serializer.is_valid(raise_exception=True)
    provided = {key: value for key, value in settings.items() if key in SETTINGS_FIELDS}
    validated = {key: serializer.validated_data[key] for key in provided}
    require_canonical_values(provided, validated)
    return serializer


def prepare(actor, makerspace, config):
    validate_configuration(config)
    if set(makerspace.enabled_modules or []) != set(config["modules"]) and not _superadmin(actor):
        raise PermissionDenied("Only a superadmin may change modules through a pack.")
    from apps.backup.module_gate import assert_uninstall_allowed
    assert_uninstall_allowed(makerspace, set(makerspace.enabled_modules or []), set(config["modules"]))
    current = configuration_for(actor, makerspace)
    candidate = copy(makerspace)
    candidate.enabled_modules = config["modules"]
    candidate.enabled_features = config["features"]
    checked = settings_serializer(actor, candidate, config["settings"])
    for key, value in checked.validated_data.items():
        setattr(candidate, key, value)
    steps, diff = [], []
    for name in ("modules", "features", "settings", "opening_hours"):
        if current[name] != config[name]:
            diff.append({"section": name, "key": name, "before": current[name], "after": config[name]})
    maps = {}
    for section, spec in SECTIONS.items():
        incoming = config[section]
        rows = incoming if spec.identity else ([] if incoming is None else [incoming])
        from .module_registry import module_available
        if spec.module and not module_available(spec.module):
            maps[section] = {}
            continue
        if rows and not rbac.can(actor, spec.action, makerspace.pk):
            raise PermissionDenied(f"Applying {section} requires {spec.action}.")
        lookup = {}
        existing = scoped_rows(actor, makerspace, spec).order_by("pk")
        if section == "active_waiver":
            existing = existing.filter(is_active=True)
        for row in existing:
            identity = identity_for(spec, {key: getattr(row, key) for key in spec.identity})
            if identity in lookup:
                raise PackError("ambiguous_pack_entry", f"{section} has duplicate local names.")
            lookup[identity] = row
        maps[section] = lookup
        for item in rows:
            values = clean_row(spec, item)
            identity = identity_for(spec, values)
            row = lookup.get(identity)
            if section == "active_waiver" and (row is None or project_row(row, spec.fields) != item):
                if scoped_rows(actor, makerspace, spec).filter(version=values["version"]).exists():
                    raise PackError("pack_waiver_version_exists", "Publish a new waiver version; existing liability text cannot be replaced.")
            if section == "item_templates" and row and row.is_archived:
                raise PackError("archived_pack_entry", "Rename the item template or unarchive its target first.")
            if section == "booking_rules" and row and not row.is_active:
                raise PackError("inactive_pack_entry", "Rename the booking rule or activate its target first.")
            if section == "notification_defaults":
                from apps.integrations.dispatch_channels import channel_module_blocks
                if values["enabled"] and channel_module_blocks(candidate, values["channel"]):
                    raise PackError("pack_module_disabled", "The notification channel module is not installed.")
            if section == "email_templates":
                from apps.admin_api.views_email_templates_common import STREAM_ACTIONS, STREAM_MODULES
                actions = STREAM_ACTIONS.get(values["stream"], ())
                if not any(rbac.can(actor, action, makerspace.pk) for action in actions):
                    raise PermissionDenied("The template requires its stream's management action.")
                module = STREAM_MODULES.get(values["stream"])
                if module and module not in config["modules"]:
                    raise PackError("pack_module_disabled", "The email stream module is not installed.")
            if section == "roles":
                if row and (row.is_default or row.is_protected):
                    raise PackError("protected_pack_role", "A pack cannot replace a built-in role.")
                _validate_actions(actor, makerspace, values["granted_actions"], row)
            if section == "item_templates" and values["category"] is not None:
                name = values["category"]
                category = maps["categories"].get((name,))
                if category is None:
                    matching = [entry for entry in config["categories"] if entry["slug"] == name]
                    if not matching:
                        raise PackError("missing_pack_reference", "An item category is missing.")
                    category = apps.get_model("inventory.Category")(makerspace=makerspace, **matching[0])
                values["category"] = category
            if section == "admission_policy":
                name = values["default_plan"]
                plan = maps["membership_plans"].get((name,)) if name else None
                matching = next((entry for entry in config["membership_plans"] if entry["name"] == name), None)
                if matching:
                    plan = apps.get_model("makerspaces.MembershipPlan")(
                        makerspace=makerspace, **clean_row(SECTIONS["membership_plans"], matching),
                    )
                if name and plan is None:
                    raise PackError("missing_pack_reference", "The admission default plan is missing.")
                values["default_plan"] = plan
                from .membership_admission_settings import validate_policy
                policy = apps.get_model(spec.model)(makerspace=candidate, **values)
                validate_policy(candidate, policy)
            before = project_row(row, spec.fields) if row else None
            if before != item:
                key = "/".join(map(str, identity)) or section
                diff.append({"section": section, "key": key, "before": before, "after": item})
                steps.append((section, row, values))
    # Admission settings maintain legacy aliases. Features remain independently
    # switchable, including configured vouch/form policies with their gates off.
    admission = config["admission_policy"]
    if admission is None and current["admission_policy"] is not None:
        aliases = ("membership_policy", "membership_dues_amount")
        if any(config["settings"][key] != current["settings"][key] for key in aliases):
            raise PackError("inconsistent_pack_policy", "Include the admission policy when changing its aliases.")
    return steps, {"base_checksum": seal(current)["checksum"], "changes": diff}
