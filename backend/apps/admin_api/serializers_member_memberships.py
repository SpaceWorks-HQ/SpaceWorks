from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field, inline_serializer

from apps.admin_api.serializers_payment_summary import PaymentSummaryMixin
from apps.makerspaces.models import MakerspaceMembership, MembershipRequest
from apps.makerspaces.waiver_state import active_waiver_for, current_acceptance


class RoleIdSerializer(serializers.Serializer):
    role_id = serializers.IntegerField()


class InvitationSerializer(RoleIdSerializer):
    invite_email = serializers.EmailField(max_length=254)


class RevokeSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)


class WitnessWaiverRequestSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or data:
            raise serializers.ValidationError(
                {"detail": "This endpoint does not accept request fields."}
            )
        return {}


class WitnessWaiverResponseSerializer(serializers.Serializer):
    membership_id = serializers.IntegerField()
    waiver_id = serializers.IntegerField()
    waiver_version = serializers.CharField()
    witnessed_at = serializers.DateTimeField()


class AdminMembershipSerializer(PaymentSummaryMixin, serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    payment = serializers.SerializerMethodField()
    assigned_role = serializers.SerializerMethodField()
    waiver_current = serializers.SerializerMethodField()
    waiver_required = serializers.SerializerMethodField()

    class Meta:
        model = MakerspaceMembership
        fields = ("id", "status", "user", "assigned_role", "can_refer", "can_verify", "verified_at", "activated_at", "revoked_at", "revocation_reason", "waiver_accepted_at", "waiver_version_accepted", "waiver_current", "waiver_required", "payment")

    @extend_schema_field(inline_serializer("AdminMembershipUser", {
        "id": serializers.IntegerField(),
        "username": serializers.CharField(),
        "email": serializers.EmailField(),
        "display_name": serializers.CharField(),
    }))
    def get_user(self, obj):
        return {"id": obj.user_id, "username": obj.user.username, "email": obj.user.email, "display_name": obj.user.display_name}

    @extend_schema_field(inline_serializer("AdminMembershipRole", {
        "id": serializers.IntegerField(),
        "name": serializers.CharField(),
        "slug": serializers.CharField(),
    }, allow_null=True))
    def get_assigned_role(self, obj):
        if not obj.assigned_role_id:
            return None
        return {"id": obj.assigned_role_id, "name": obj.assigned_role.name, "slug": obj.assigned_role.slug}

    def _active_waiver(self, obj):
        # Resolved once per serializer instance, per makerspace: a roster is one
        # response, and caching on the membership rows instead would let a superseded
        # waiver keep reading as current.
        if "active_waiver" in self.context:
            return self.context["active_waiver"]
        cache = getattr(self, "_active_waiver_cache", None)
        if cache is None:
            cache = self._active_waiver_cache = {}
        if obj.makerspace_id not in cache:
            cache[obj.makerspace_id] = active_waiver_for(obj.makerspace_id)
        return cache[obj.makerspace_id]

    @extend_schema_field(serializers.BooleanField())
    def get_waiver_current(self, obj):
        return current_acceptance(obj, active_waiver=self._active_waiver(obj))

    @extend_schema_field(serializers.BooleanField())
    def get_waiver_required(self, obj):
        return self._active_waiver(obj) is not None


class MembershipCapabilitiesSerializer(serializers.Serializer):
    can_refer = serializers.BooleanField(required=False)
    can_verify = serializers.BooleanField(required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Provide at least one capability.")
        return attrs


class MembershipRequestSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    assigned_role = serializers.SerializerMethodField()

    class Meta:
        model = MembershipRequest
        fields = ("id", "kind", "state", "invite_email", "user", "assigned_role", "decision_note", "created_at", "decided_at")

    @extend_schema_field(inline_serializer("MembershipRequestUser", {
        "id": serializers.IntegerField(),
        "username": serializers.CharField(),
        "email": serializers.EmailField(),
    }, allow_null=True))
    def get_user(self, obj):
        if not obj.user_id:
            return None
        return {"id": obj.user_id, "username": obj.user.username, "email": obj.user.email}

    @extend_schema_field(inline_serializer("MembershipRequestRole", {
        "id": serializers.IntegerField(),
        "name": serializers.CharField(),
    }, allow_null=True))
    def get_assigned_role(self, obj):
        return {"id": obj.assigned_role_id, "name": obj.assigned_role.name} if obj.assigned_role_id else None
