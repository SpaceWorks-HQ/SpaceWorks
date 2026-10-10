"""Staff audit-list serializers: projected output and validated filters.

``AuditLogSerializer`` keeps every field the shipped list returned (``meta`` stays an
object for compatibility) but builds ``meta`` from the shared presentation projector, so
the raw stored metadata can no longer leave through this endpoint. The four added fields
are additive.
"""

from datetime import timedelta

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.audit.presentation import project

MAX_AUDIT_RANGE = timedelta(days=366)


class AuditTargetLinkSerializer(serializers.Serializer):
    label = serializers.CharField()
    path = serializers.CharField()


class AuditLogSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    actor = serializers.IntegerField(source="actor_id", allow_null=True, read_only=True)
    action = serializers.CharField(read_only=True)
    makerspace = serializers.IntegerField(
        source="makerspace_id", allow_null=True, read_only=True
    )
    target_type = serializers.CharField(read_only=True)
    target_id = serializers.CharField(read_only=True)
    meta = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(read_only=True)
    action_label = serializers.SerializerMethodField()
    actor_display = serializers.SerializerMethodField()
    meta_redacted = serializers.SerializerMethodField()
    target_link = serializers.SerializerMethodField()

    def _projection(self, row):
        cache = self.context.setdefault("_audit_projections", {})
        if row.pk not in cache:
            cache[row.pk] = project(row)
        return cache[row.pk]

    @extend_schema_field(serializers.DictField())
    def get_meta(self, row):
        return self._projection(row).meta

    def get_action_label(self, row) -> str:
        return self._projection(row).action_label

    def get_actor_display(self, row) -> str | None:
        actor = row.actor
        if actor is None:
            return None
        return actor.get_full_name() or actor.get_username()

    def get_meta_redacted(self, row) -> bool:
        return self._projection(row).meta_redacted

    @extend_schema_field(AuditTargetLinkSerializer(allow_null=True))
    def get_target_link(self, row):
        return self._projection(row).target_link


class AuditLogFilterSerializer(serializers.Serializer):
    """The audit-list filters. ``start`` is inclusive, ``end`` exclusive."""

    makerspace = serializers.IntegerField(required=False, min_value=1)
    action = serializers.CharField(required=False, max_length=128)
    target_type = serializers.CharField(required=False, max_length=200)
    target_id = serializers.CharField(required=False, max_length=100)
    actor = serializers.IntegerField(required=False, min_value=1)
    start = serializers.DateTimeField(required=False)
    end = serializers.DateTimeField(required=False)

    def validate(self, attrs):
        start, end = attrs.get("start"), attrs.get("end")
        if start is not None and end is not None:
            if end <= start:
                raise serializers.ValidationError({"end": "end must be after start."})
            if end - start > MAX_AUDIT_RANGE:
                raise serializers.ValidationError(
                    {"end": "The date range is limited to 366 days."}
                )
        return attrs


def apply_audit_filters(queryset, filters):
    """Apply already-validated filters; never pass a raw query string to the ORM."""
    lookups = {
        "makerspace": "makerspace_id",
        "action": "action",
        "target_type": "target_type",
        "target_id": "target_id",
        "actor": "actor_id",
        "start": "created_at__gte",
        "end": "created_at__lt",
    }
    applied = {
        lookups[name]: value
        for name, value in filters.items()
        if name in lookups and value not in (None, "")
    }
    return queryset.filter(**applied) if applied else queryset
