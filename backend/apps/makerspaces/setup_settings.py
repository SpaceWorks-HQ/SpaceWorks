"""Validated, audited settings paths shared by setup and the existing staff editors."""
from types import SimpleNamespace

from apps.admin_api.serializers_makerspaces import MakerspaceSerializer
from apps.admin_api.serializers_membership_plans import MembershipPlanSerializer
from apps.audit import services as audit
from apps.makerspaces.models import MembershipPlan
from apps.makerspaces.serializers_admission import AdmissionSettingsSerializer
from .membership_admission_settings import settings_for, update_settings
from .loan_policy_settings import update_loan_policy
from .profile_settings import write_profile
from .settings_validation import validate_settings as validate


def changed(serializer, instance):
    """Re-running confirmed setup leaves already matching settings and audits alone."""
    return any(getattr(instance, key, object()) != value for key, value in serializer.validated_data.items())


def save_space(actor, space, values):
    serializer = MakerspaceSerializer(space, data=values, partial=True,
                                     context={"request": SimpleNamespace(user=actor)})
    validate(serializer)
    if changed(serializer, space):
        before = list(space.enabled_features)
        space = serializer.save()
        audit.record(actor, "makerspace.updated", makerspace=space, target=space,
                     meta={"fields": sorted(serializer.validated_data)})
        if before != space.enabled_features:
            audit.record(actor, "makerspace.features_changed", makerspace=space, target=space,
                         meta={"before": before, "after": space.enabled_features})
    return space


def save_plan(actor, space, values):
    row = MembershipPlan.objects.filter(makerspace=space, name=values.get("name")).first()
    serializer = MembershipPlanSerializer(row, data=values)
    validate(serializer)
    if row is None or changed(serializer, row):
        creating = row is None
        row = serializer.save(makerspace=space)
        row.full_clean()
        fields = sorted(serializer.validated_data)
        # Literal actions and meta keep the audit discovery guard able to see both.
        if creating:
            audit.record(actor, "membership_plan.created", makerspace=space, target=row,
                         meta={"plan_id": row.pk, "fields": fields})
        else:
            audit.record(actor, "membership_plan.updated", makerspace=space, target=row,
                         meta={"plan_id": row.pk, "fields": fields})
    return row


def apply_settings(actor, space, settings):
    if "space" in settings:
        values = dict(settings["space"])
        if "timezone" in values:
            from apps.admin_api.serializers_makerspace_profile import MakerspaceProfileSerializer
            check = MakerspaceProfileSerializer(data={"timezone": values.pop("timezone")}, partial=True)
            validate(check)
            write_profile(actor, space, check.validated_data)
        if values:
            space = save_space(actor, space, values)
    if "loan_policy" in settings:
        from apps.admin_api.serializers_loan_policy import ReturnPolicySerializer
        from .models_loan_policy import MakerspaceLoanPolicy
        policy = MakerspaceLoanPolicy.for_makerspace(space)
        check = ReturnPolicySerializer(policy, data=settings["loan_policy"], partial=True)
        validate(check)
        if not policy.pk or changed(check, policy):
            update_loan_policy(actor, space, settings["loan_policy"])
    if "loan_charges" in settings:
        from rest_framework.exceptions import ValidationError
        from apps.admin_api.serializers_payments import MakerspacePaymentSettingsSerializer
        from apps.payments.models import MakerspacePaymentSettings
        values = settings["loan_charges"]
        if any(not key.startswith("loan_") for key in values):
            raise ValidationError({"loan_charges": "Use loan charge fields only."})
        row = MakerspacePaymentSettings.for_makerspace(space)
        check = MakerspacePaymentSettingsSerializer(row, data=values, partial=True)
        validate(check)
        if not row.pk or changed(check, row):
            row = check.save()
            audit.record(actor, "payments.settings_updated", makerspace=space, target=row,
                         meta={"fields": sorted(values)})
    plan = save_plan(actor, space, settings["plan"]) if "plan" in settings else None
    if "admission" in settings or plan:
        values = dict(settings.get("admission", {}))
        if plan:
            values["default_plan"] = plan.pk
        row = settings_for(space)
        check = AdmissionSettingsSerializer(row, data=values, partial=True, context={"makerspace": space})
        validate(check)
        if not row.configured or changed(check, row):
            update_settings(actor, space, check.validated_data)
            space.refresh_from_db()
    if "machine_policy" in settings:
        from django.db.models import Q
        from apps.machines.models import MachineType
        from apps.machines.policy_settings import update_policy
        for machine_type in MachineType.objects.filter(Q(makerspace=space) | Q(makerspace__isnull=True)):
            update_policy(actor, space, machine_type, settings["machine_policy"])
    if "notifications" in settings:
        from apps.integrations.timing_settings import update_policy
        update_policy(actor, space, settings["notifications"])
    if "currency" in settings:
        from apps.admin_api.serializers_makerspace_profile import MakerspaceProfileSerializer
        from apps.payments.models import MakerspacePaymentSettings
        check = MakerspaceProfileSerializer(data={"default_currency": settings["currency"]}, partial=True)
        validate(check)
        row = MakerspacePaymentSettings.objects.filter(makerspace=space).first() or MakerspacePaymentSettings(makerspace=space)
        currency = check.validated_data["default_currency"]
        if row.default_currency != currency or not row.pk:
            row.default_currency = currency
            row.save()
            audit.record(actor, "makerspace.updated", makerspace=space, target=space,
                         meta={"fields": ["default_currency"]})
    return space
