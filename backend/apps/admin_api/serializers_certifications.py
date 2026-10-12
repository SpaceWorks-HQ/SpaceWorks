"""Serializers for the staff certification-type and grant surfaces."""

from contextlib import contextmanager

from django.db import IntegrityError, transaction
from rest_framework import serializers

from apps.accounts import rbac
from apps.machines.models import CertificationGrant, CertificationType


class CertificationTypeSerializer(serializers.ModelSerializer):
    validity_days = serializers.IntegerField(
        min_value=1, max_value=2147483647, allow_null=True, required=False,
    )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        makerspace_id = self.instance.makerspace_id if self.instance else self.context["makerspace_id"]
        machine_type = attrs.get("machine_type", getattr(self.instance, "machine_type", None))
        name = attrs.get("name", getattr(self.instance, "name", ""))
        rows = rbac.scope_by_makerspace(
            self.context["request"].user, CertificationType.objects.all(),
        ).filter(makerspace_id=makerspace_id, machine_type=machine_type, name=name)
        if self.instance:
            rows = rows.exclude(pk=self.instance.pk)
        if rows.exists():
            raise serializers.ValidationError({"name": "A certification with this name already exists for this machine type."})
        return attrs

    class Meta:
        model = CertificationType
        fields = [
            "id",
            "machine_type",
            "name",
            "description",
            "validity_days",
            "is_required_for_service",
            "is_required_for_booking",
            "is_active",
            "created_at",
            "updated_at",
        ]
        # `makerspace` comes from the URL, never the body: accepting it would let a
        # staff member in one lab create a requirement in another. `is_active` is
        # cleared by DELETE (soft-delete) rather than edited straight to False, so the
        # deactivation is audited as such.
        read_only_fields = ["id", "is_active", "created_at", "updated_at"]


class CertificationTypeUpdateSerializer(CertificationTypeSerializer):
    class Meta(CertificationTypeSerializer.Meta):
        # The machine type is immutable: repointing it would silently move every issued
        # grant to hardware the trained members were never assessed on.
        read_only_fields = CertificationTypeSerializer.Meta.read_only_fields + [
            "machine_type"
        ]


class CertificationGrantSerializer(serializers.ModelSerializer):
    member_name = serializers.SerializerMethodField()
    is_live = serializers.SerializerMethodField()

    class Meta:
        model = CertificationGrant
        fields = [
            "id",
            "certification_type",
            "membership",
            "member_name",
            "granted_by",
            "granted_at",
            "expires_at",
            "revoked_at",
            "revoked_by",
            "notes",
            "is_live",
        ]
        read_only_fields = fields

    def get_member_name(self, obj):
        user = obj.membership.user
        return user.display_name or user.get_full_name() or user.username

    def get_is_live(self, obj):
        return obj.certification_type.is_active and obj.is_active()


class CertificationGrantCreateSerializer(serializers.Serializer):
    membership_id = serializers.IntegerField()
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class CertificationGrantRevokeSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class CertificationTypePageSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)
    results = CertificationTypeSerializer(many=True)


class CertificationGrantPageSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)
    results = CertificationGrantSerializer(many=True)


@contextmanager
def certification_type_write():
    """Turn a concurrent name collision into the same field error as validation.

    The savepoint keeps the outer audited transaction usable after a database
    constraint rejects the write. Other integrity failures still propagate.
    """
    try:
        with transaction.atomic():
            yield
    except IntegrityError as exc:
        constraint = getattr(getattr(exc.__cause__, "diag", None), "constraint_name", None)
        if constraint != "certificationtype_uniq_name":
            raise
        raise serializers.ValidationError({"name": "A certification with this name already exists for this machine type."}) from exc
