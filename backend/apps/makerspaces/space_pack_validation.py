"""Strict pack shape and field validation, shared by imports and saved profiles."""
import json
from django.apps import apps
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.serializers.json import DjangoJSONEncoder
from rest_framework import serializers

from apps.data_export.space_pack_configuration import HOURS_FIELDS, SECTIONS, SETTINGS_FIELDS
from .capabilities import validate_capabilities
from .module_registry import MODULE_KEYS, module_available
from .space_pack_format import MAX_ROWS, PackError, canonical

AUTHORED_TEXT_FIELDS = frozenset({"body", "description", "subject", "text_body", "html_body"})
EMAIL_TEXT_FIELDS = frozenset({"subject", "text_body", "html_body"})


def require_canonical_values(original, validated):
    # Preview must describe exactly what the ordinary editor would persist.
    # Refuse coercion (e.g. "false" -> False) instead of showing different values.
    normalized = json.loads(json.dumps(validated, cls=DjangoJSONEncoder))
    if canonical(original) != canonical(normalized):
        raise PackError("noncanonical_pack_configuration", "Use the canonical field values produced by export.")


class StrictFieldsMixin:
    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise serializers.ValidationError("Unknown configuration fields.")
        return super().to_internal_value(data)


def identity_for(spec, values):
    identity = tuple(values[key] for key in spec.identity)
    # The role editor and its database constraint use case-insensitive names.
    if spec.model == "makerspaces.MakerspaceRole":
        return tuple(value.strip().casefold() for value in identity)
    return identity


def row_serializer(spec, *, instance=None, data=None):
    model = apps.get_model(spec.model)
    extras = {name: {"required": True} for name in spec.fields}
    for name in AUTHORED_TEXT_FIELDS & extras.keys():
        extras[name]["trim_whitespace"] = False
    if spec.model == "integrations.EmailTemplate":
        for name in EMAIL_TEXT_FIELDS:
            extras[name].update({"trim_whitespace": False, "allow_blank": True})
    meta = type("Meta", (), {"model": model, "fields": spec.fields, "validators": [], "extra_kwargs": extras})
    attributes = {"Meta": meta, "__module__": __name__}
    for name in spec.fields:
        field = model._meta.get_field(name)
        if field.is_relation:
            attributes[name] = serializers.CharField(allow_null=True, allow_blank=False)
    cls = type("Pack" + model.__name__ + "Serializer",
               (StrictFieldsMixin, serializers.ModelSerializer), attributes)
    return cls(instance=instance, data=data)


def clean_row(spec, row):
    if not isinstance(row, dict) or set(row) != set(spec.fields):
        raise PackError("invalid_pack_fields", f"{spec.model} needs exactly its configuration fields.")
    serializer = row_serializer(spec, data=row)
    serializer.is_valid(raise_exception=True)
    values = serializer.validated_data
    # Model.clean() contains template-registry checks that serializers alone omit.
    model = apps.get_model(spec.model)
    concrete = {key: value for key, value in values.items() if not model._meta.get_field(key).is_relation}
    candidate = model(**concrete)
    excluded = [field.name for field in model._meta.fields if field.name not in concrete]
    if spec.model == "integrations.EmailTemplate":
        # The established editor permits an empty body/subject. Model.clean still
        # checks the registry and template syntax, even when blank field checks skip.
        excluded += [key for key in EMAIL_TEXT_FIELDS if not concrete[key]]
    try:
        candidate.full_clean(exclude=excluded, validate_unique=False)
    except DjangoValidationError as exc:
        raise PackError("invalid_pack_configuration", str(exc)) from exc
    if spec.model == "makerspaces.MakerspaceRole":
        from .role_authority import _clean_actions
        values["granted_actions"] = sorted(_clean_actions(values["granted_actions"]))
    if spec.model == "makerspaces.MakerspaceWaiver":
        if any(values[key] != values[key].strip() or not values[key].strip() for key in ("version", "body")):
            raise PackError("invalid_pack_configuration", "Waiver text and version must be nonblank and trimmed.")
    if spec.model == "makerspaces.MakerspaceLoanPolicy":
        from apps.admin_api.serializers_loan_policy import ReturnPolicySerializer
        check = ReturnPolicySerializer(data=row)
        check.is_valid(raise_exception=True)
        values.update(check.validated_data)
    if spec.model == "integrations.EmailNotificationMute":
        from apps.integrations import notification_rules
        if (notification_rules.TARGETS.get(values["target"]) != values["audience"]
                or values["target"] not in notification_rules.valid_targets_for_stream(values["stream"])
                or not notification_rules.is_event_mutable(values["stream"], values["audience"], values["event"])):
            raise PackError("invalid_pack_configuration", "Invalid notification mute.")
    if spec.model == "bookings.BookableSpace":
        from apps.bookings.services_rules import MAX_ADVANCE_DAYS, MAX_DURATION_MINUTES, MAX_LEAD_MINUTES
        if (not 1 <= values["min_booking_duration_minutes"] <= values["max_booking_duration_minutes"] <= MAX_DURATION_MINUTES
                or not 0 <= values["booking_lead_time_minutes"] <= MAX_LEAD_MINUTES
                or not 1 <= values["max_booking_advance_days"] <= MAX_ADVANCE_DAYS):
            raise PackError("invalid_pack_configuration", "Invalid booking time bounds.")
    if spec.model == "makerspaces.MembershipPlan":
        from apps.admin_api.serializers_membership_plans import MembershipPlanSerializer
        check = MembershipPlanSerializer(data=row)
        check.is_valid(raise_exception=True)
        values.update(check.validated_data)
    if spec.model == "makerspaces.MakerspaceMembershipSettings":
        from .serializers_admission import AdmissionSettingsSerializer
        # Natural plan names are resolved separately. All other fields retain
        # the normal editor's bounds, currency and form-schema validation.
        check = AdmissionSettingsSerializer(
            data={key: value for key, value in row.items() if key != "default_plan"}, partial=True,
        )
        check.is_valid(raise_exception=True)
        values.update(check.validated_data)
    require_canonical_values(row, values)
    return values


def validate_aliases(config):
    admission = config["admission_policy"]
    if admission:
        mode = admission["join_mode"] if admission["join_mode"] in ("open", "invite_only") else "request"
        if (config["settings"]["membership_policy"] != mode
                or str(config["settings"]["membership_dues_amount"]) != str(admission["joining_fee"])):
            raise PackError("inconsistent_pack_policy", "Admission and legacy membership settings must agree.")
    loan = config["loan_policy"]
    if loan and loan["default_loan_days"] != config["settings"]["default_loan_days"]:
        raise PackError("inconsistent_pack_policy", "Loan default and legacy loan setting must agree.")


def validate_profile_references(config):
    # A new space has no preexisting natural keys to bind to. Saved presets must
    # therefore carry their own catalogue/plan reference closure.
    categories = {entry["slug"] for entry in config["categories"]}
    if any(entry["category"] is not None and entry["category"] not in categories
           for entry in config["item_templates"]):
        raise PackError("missing_pack_reference", "A saved profile must include every referenced category.")
    admission = config["admission_policy"]
    if admission and admission["default_plan"]:
        plans = {entry["name"]: entry for entry in config["membership_plans"]}
        if admission["default_plan"] not in plans:
            raise PackError("missing_pack_reference", "A saved profile must include its admission default plan.")


def validate_configuration(config):
    expected = {"modules", "features", "settings", "opening_hours", *SECTIONS}
    if not isinstance(config, dict) or set(config) != expected:
        raise PackError("invalid_pack_fields", "Unknown or missing configuration sections.")
    canonical(config)
    modules, features = config["modules"], config["features"]
    for keys in (modules, features):
        if not isinstance(keys, list) or any(not isinstance(key, str) for key in keys) or len(set(keys)) != len(keys):
            raise PackError("invalid_pack_configuration", "Capabilities must be lists of unique strings.")
    if set(modules) - MODULE_KEYS or any(not module_available(key) for key in modules):
        raise PackError("unavailable_pack_module", "A module is unknown or unavailable on this deployment.")
    try:
        canonical_modules, _ = validate_capabilities(modules, features)
        if set(canonical_modules) != set(modules):
            raise PackError("invalid_pack_configuration", "A pack must include all core modules.")
    except DjangoValidationError as exc:
        raise PackError("invalid_pack_configuration", str(exc)) from exc
    for name, fields in (("settings", SETTINGS_FIELDS), ("opening_hours", HOURS_FIELDS)):
        if not isinstance(config[name], dict) or set(config[name]) != set(fields):
            raise PackError("invalid_pack_fields", f"Invalid {name} fields.")
    from apps.admin_api.serializers_makerspace_profile import MakerspaceProfileSerializer
    profile = MakerspaceProfileSerializer(data=config["opening_hours"], partial=True)
    profile.is_valid(raise_exception=True)
    require_canonical_values(config["opening_hours"], profile.validated_data)
    count = 0
    for name, spec in SECTIONS.items():
        rows = config[name]
        if not spec.identity:
            rows = [] if rows is None else [rows]
        if not isinstance(rows, list):
            raise PackError("invalid_pack_configuration", f"{name} must be a list.")
        count += len(rows)
        if count > MAX_ROWS:
            raise PackError("pack_too_large", "A pack may contain at most 2000 entries.")
        if rows and spec.module and spec.module not in modules:
            raise PackError("pack_module_disabled", f"{name} requires {spec.module}.")
        identities = set()
        for row in rows:
            values = clean_row(spec, row)
            identity = identity_for(spec, values)
            if identity in identities:
                raise PackError("ambiguous_pack_entry", f"Duplicate entry in {name}.")
            identities.add(identity)
    validate_aliases(config)
    return config
