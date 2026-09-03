from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts import rbac
from apps.accounts.schemas_auth import UserPayloadSerializer
from apps.inventory import public_image_storage
from apps.organizations import governance
from apps.organizations.access import is_superadmin
from apps.organizations.models import (
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
)


def _actor_membership(obj):
    rows = getattr(obj, "actor_memberships", ())
    return rows[0] if rows else None


class OrganizationSummarySerializer(serializers.ModelSerializer):
    governance_actions = serializers.SerializerMethodField()
    granted_actions = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = ("id", "slug", "name", "governance_actions", "granted_actions")
        read_only_fields = fields

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_governance_actions(self, obj):
        actor = self.context["actor"]
        if is_superadmin(actor):
            return sorted(governance.GOVERNANCE_ACTIONS)
        return sorted(governance.actions_for_membership(_actor_membership(obj)))

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_granted_actions(self, obj):
        actor = self.context["actor"]
        if is_superadmin(actor):
            return sorted(rbac.ORGANIZATION_GRANTABLE_ACTIONS)
        return sorted(rbac.actions_for_organization_membership(_actor_membership(obj)))


class OrganizationDetailSerializer(OrganizationSummarySerializer):
    logo_url = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = OrganizationSummarySerializer.Meta.fields + (
            "description",
            "website",
            "logo_url",
            "public_profile_enabled",
            "is_active",
            "legal_name",
            "registration_number",
            "contact_email",
            "billing_email",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_logo_url(self, obj):
        return public_image_storage.public_url(obj.logo_key) or None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        actor_actions = set(data["governance_actions"])
        if governance.MANAGE_ORGANIZATION_PROFILE not in actor_actions:
            for field in ("legal_name", "registration_number", "contact_email", "billing_email"):
                data.pop(field, None)
        return data


class OrganizationProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ("name", "slug", "description", "website", "public_profile_enabled")
        extra_kwargs = {field: {"required": False} for field in fields}


class OrganizationMembershipSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    display_name = serializers.CharField(source="user.display_name", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = OrganizationMembership
        fields = (
            "id", "user_id", "username", "display_name", "email", "status",
            "governance_actions", "granted_actions", "created_at", "updated_at",
        )
        read_only_fields = fields


class OrganizationMembershipListSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)
    results = OrganizationMembershipSerializer(many=True)


class OrganizationInvitationSerializer(serializers.ModelSerializer):
    organization_id = serializers.IntegerField(read_only=True)
    created_by_id = serializers.IntegerField(allow_null=True, read_only=True)
    redeemed_by_id = serializers.IntegerField(allow_null=True, read_only=True)
    state = serializers.SerializerMethodField()

    class Meta:
        model = OrganizationInvitation
        fields = (
            "id", "organization_id", "governance_actions", "granted_actions",
            "expires_at", "redeemed_at", "revoked_at", "created_by_id",
            "redeemed_by_id", "created_at", "state",
        )
        read_only_fields = fields

    @extend_schema_field(
        serializers.ChoiceField(choices=("active", "expired", "revoked", "redeemed"))
    )
    def get_state(self, obj):
        from django.utils import timezone

        if obj.redeemed_at is not None:
            return "redeemed"
        if obj.revoked_at is not None:
            return "revoked"
        if obj.expires_at <= timezone.now():
            return "expired"
        return "active"


class OrganizationInvitationListSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)
    results = OrganizationInvitationSerializer(many=True)


class OrganizationInvitationCreateSerializer(serializers.Serializer):
    governance_actions = serializers.ListField(child=serializers.CharField(), default=list)
    granted_actions = serializers.ListField(child=serializers.CharField(), default=list)
    expires_in_days = serializers.IntegerField(min_value=1, max_value=30, default=7)


class OrganizationInvitationCreatedSerializer(OrganizationInvitationSerializer):
    token = serializers.CharField(read_only=True)
    redeem_path = serializers.CharField(read_only=True)

    class Meta(OrganizationInvitationSerializer.Meta):
        fields = OrganizationInvitationSerializer.Meta.fields + ("token", "redeem_path")


class OrganizationInvitationRedeemSerializer(serializers.Serializer):
    token = serializers.CharField(min_length=20, max_length=200, trim_whitespace=True)


class OrganizationInvitationRedeemedSerializer(serializers.Serializer):
    membership = OrganizationMembershipSerializer()
    user = UserPayloadSerializer


class OrganizationListSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)
    results = OrganizationSummarySerializer(many=True)
