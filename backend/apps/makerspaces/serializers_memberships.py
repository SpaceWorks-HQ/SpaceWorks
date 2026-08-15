from rest_framework import serializers


class MembershipRequestCreateSerializer(serializers.Serializer):
    website = serializers.CharField(required=False, allow_blank=True, write_only=True)

    def validate_website(self, value):
        if value:
            raise serializers.ValidationError("Invalid request.")
        return value


class MembershipOutcomeSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=("joined", "requested"))
    membership_id = serializers.IntegerField(required=False)
    request_id = serializers.IntegerField(required=False)
    state = serializers.CharField()


class ClaimableInvitationSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    makerspace = serializers.DictField()
    inviter = serializers.CharField(allow_blank=True, allow_null=True)
    auto_activates = serializers.BooleanField()
    role = serializers.CharField(allow_blank=True, allow_null=True)


class InvitationListSerializer(serializers.Serializer):
    invitations = ClaimableInvitationSerializer(many=True)


class InvitationClaimOutcomeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    outcome = serializers.ChoiceField(choices=("active", "pending_approval"))


class ReferralCreateSerializer(serializers.Serializer):
    invite_email = serializers.EmailField(max_length=254)


class ReferralOutcomeSerializer(serializers.Serializer):
    state = serializers.CharField()


class MyMembershipRowSerializer(serializers.Serializer):
    makerspace = serializers.DictField()
    membership_status = serializers.CharField()
    role = serializers.CharField()
    actions = serializers.ListField(child=serializers.CharField())
    can_refer = serializers.BooleanField()
    can_verify = serializers.BooleanField()
    verified_at = serializers.DateTimeField(allow_null=True)
    referrals_enabled = serializers.BooleanField()
    waiver_accepted = serializers.BooleanField()
    waiver_acceptance_required = serializers.BooleanField()


class MyMembershipRequestSerializer(serializers.Serializer):
    makerspace = serializers.DictField()
    state = serializers.CharField()
    kind = serializers.CharField()


class MyMembershipsSerializer(serializers.Serializer):
    memberships = MyMembershipRowSerializer(many=True)
    requests = MyMembershipRequestSerializer(many=True)


class MemberWaiverResponseSerializer(serializers.Serializer):
    has_waiver = serializers.BooleanField()
    body = serializers.CharField(required=False)
    version = serializers.CharField(required=False)


class WaiverPublishSerializer(serializers.Serializer):
    body = serializers.CharField(required=False, allow_blank=True)
    version = serializers.CharField(required=False, allow_blank=True, max_length=64)
    clear = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        if not attrs.get("clear") and (not attrs.get("body") or not attrs.get("version")):
            raise serializers.ValidationError("Body and version are required unless clearing the waiver.")
        return attrs
