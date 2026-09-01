from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from apps.accounts.models_claim import MemberClaimCode


class MemberClaimCodeIssueRequestSerializer(serializers.Serializer):
    membership_id = serializers.IntegerField(min_value=1)


class MemberClaimCodeSerializer(serializers.ModelSerializer):
    membership_id = serializers.IntegerField(read_only=True)
    member_display_name = serializers.SerializerMethodField()
    issued_by_id = serializers.IntegerField(read_only=True, allow_null=True)
    status = serializers.SerializerMethodField()

    class Meta:
        model = MemberClaimCode
        fields = (
            "id",
            "membership_id",
            "member_display_name",
            "issued_by_id",
            "issued_at",
            "expires_at",
            "consumed_at",
            "revoked_at",
            "status",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.CharField())
    def get_member_display_name(self, claim):
        user = claim.membership.user
        return user.display_name or user.username

    @extend_schema_field(serializers.CharField())
    def get_status(self, claim):
        if claim.revoked_at is not None:
            return "revoked"
        if claim.consumed_at is not None:
            return "consumed"
        return "issued"


class MemberClaimCodeIssueResponseSerializer(MemberClaimCodeSerializer):
    code = serializers.CharField(read_only=True)
    qr_svg = serializers.CharField(read_only=True)

    class Meta(MemberClaimCodeSerializer.Meta):
        fields = MemberClaimCodeSerializer.Meta.fields + ("code", "qr_svg")
