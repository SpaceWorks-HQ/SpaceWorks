"""Validated delivery predicates and live, tenant-local staff recipient selectors."""

from decimal import Decimal, InvalidOperation
import operator

from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from apps.accounts import rbac
from apps.admin_api.permissions import active_user
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from apps.operations.report_condition_metrics import condition_metrics

COMPARISONS = {"gt": operator.gt, "gte": operator.ge, "lt": operator.lt, "lte": operator.le, "eq": operator.eq}


class ReportConditionSerializer(serializers.Serializer):
    non_empty = serializers.BooleanField(required=False)
    metric = serializers.CharField(required=False, max_length=80, help_text="Sum this numeric column across the matching report rows.")
    operator = serializers.ChoiceField(choices=list(COMPARISONS), required=False)
    value = serializers.DecimalField(max_digits=20, decimal_places=6, required=False)
    currency = serializers.RegexField(r"^[a-z]{3}$", required=False)

    def to_internal_value(self, data):
        # Nested serializers receive raw data here, before DRF drops unknown keys.
        if isinstance(data, dict) and set(data) - set(self.fields):
            raise serializers.ValidationError("Unknown condition key.")
        return super().to_internal_value(data)

    def validate(self, attrs):
        metric_keys = {"metric", "operator", "value"}
        present = metric_keys & attrs.keys()
        if present and present != metric_keys:
            raise serializers.ValidationError("A threshold needs metric, operator and value.")
        if attrs.get("currency") and not present:
            raise serializers.ValidationError("Currency requires a metric threshold.")
        return attrs


@extend_schema_field(ReportConditionSerializer)
class ReportConditionField(serializers.DictField):
    """Keep JSON values intact until report-specific validation, with a typed schema."""


def validate_condition(value, definition):
    if not isinstance(value, dict):
        raise serializers.ValidationError("Condition must be an object.")
    payload = ReportConditionSerializer(data=value)
    payload.is_valid(raise_exception=True)
    result = payload.validated_data
    if result.get("metric") and result["metric"] not in condition_metrics(definition):
        raise serializers.ValidationError("Metric must be a registered numeric report column.")
    if result.get("currency") and "currency" not in definition.fields:
        raise serializers.ValidationError("This report has no currency dimension.")
    if "value" in result:
        result["value"] = str(result["value"])
    return result


def condition_matches(condition, rows):
    """Rows include a header. Thresholds sum numeric values, never mix currencies."""
    header, *records = rows
    if condition.get("non_empty") and not records:
        return False
    if not condition.get("metric"):
        return True
    metric = header.index(condition["metric"])
    if "currency" in header:
        currency_index = header.index("currency")
        if condition.get("currency"):
            records = [row for row in records if row[currency_index] == condition["currency"]]
        elif len({row[currency_index] for row in records}) > 1:
            raise ValueError("A multi-currency threshold requires a currency.")
    total = Decimal(0)
    for row in records:
        value = row[metric]
        if value is None:
            continue
        if isinstance(value, bool):
            raise ValueError("Threshold metric must be numeric.")
        try:
            number = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError("Threshold metric must be numeric.") from exc
        if not number.is_finite():
            raise ValueError("Threshold metric must be finite.")
        total += number
    return COMPARISONS[condition["operator"]](total, Decimal(condition["value"]))


def validate_roles(actor, space, slugs, action):
    roles = rbac.scope_by_action(actor, action, MakerspaceRole.objects.all()).filter(makerspace=space)
    if set(slugs) - set(roles.values_list("slug", flat=True)):
        raise serializers.ValidationError("Unknown recipient role in this makerspace.")
    return list(dict.fromkeys(slugs))


def recipient_emails(schedule, definition):
    """Selectors are role slugs / action enums, resolved with current RBAC each send.

    Explicit addresses remain for external recipients of existing schedules. If one
    names a local account, it is also subject to current report authority and opt-out.
    """
    candidates = rbac.scope_for_scheduled_work(
        MakerspaceMembership.objects.filter(makerspace=schedule.makerspace),
        makerspace_id=schedule.makerspace_id,
    ).select_related("user", "assigned_role")
    explicit = {email.strip().lower(): email.strip() for email in schedule.recipient_emails or []}
    emails = {}
    for member in candidates:
        user = member.user
        email = (user.email or "").strip()
        normalized = email.lower()
        is_explicit = normalized in explicit
        if is_explicit:
            explicit.pop(normalized)
        if not (member.status == "active" and member.receives_notifications and active_user(user)
                and rbac.can(user, definition.required_action, schedule.makerspace_id)):
            continue
        role = member.assigned_role
        role_selected = bool(role and role.makerspace_id == schedule.makerspace_id and role.slug in schedule.recipient_roles)
        if role is None and schedule.recipient_roles:
            role_selected = bool(rbac.scope_for_scheduled_work(MakerspaceRole.objects.all(),
                makerspace_id=schedule.makerspace_id).filter(
                makerspace_id=schedule.makerspace_id, legacy_role=member.role,
                slug__in=schedule.recipient_roles,
            ).exists())
        action_selected = any(rbac.can(user, action, schedule.makerspace_id) for action in schedule.recipient_actions)
        if email and (is_explicit or role_selected or action_selected):
            emails[normalized] = email
    emails.update(explicit)
    return list(emails.values())
