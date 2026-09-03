"""Serializers for the staff certification-type and grant surfaces."""

from rest_framework import serializers

from apps.machines.models import CertificationGrant, CertificationType


class CertificationTypeSerializer(serializers.ModelSerializer):
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
        return obj.is_active()


class CertificationGrantCreateSerializer(serializers.Serializer):
    membership_id = serializers.IntegerField()
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class CertificationGrantRevokeSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True, default="")
