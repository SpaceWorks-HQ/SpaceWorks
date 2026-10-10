from rest_framework import serializers

from apps.accounts.models_staff_invitations import StaffInvitation


class StaffInvitationSerializer(serializers.ModelSerializer):
    email = serializers.CharField(read_only=True)
    role_name = serializers.CharField(source="role.name", read_only=True)

    class Meta:
        model = StaffInvitation
        fields = ["id", "email", "makerspace", "role", "role_name", "expires_at",
                  "accepted_at", "revoked_at", "created_at"]


class StaffInvitationCreateSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    role_id = serializers.IntegerField(min_value=1)
    expires_in_days = serializers.IntegerField(min_value=1, max_value=30, default=7)


class StaffInvitationDeliverySerializer(StaffInvitationSerializer):
    accept_url = serializers.CharField()
    delivery_status = serializers.CharField()


class StaffInvitationAcceptSerializer(serializers.Serializer):
    token = serializers.CharField(min_length=20, max_length=200, write_only=True)
    makerspace_slug = serializers.SlugField()
    password = serializers.CharField(max_length=1024, write_only=True, trim_whitespace=False)
    code = serializers.CharField(max_length=64, required=False, default="", write_only=True)


class StaffInvitationAcceptedSerializer(serializers.Serializer):
    detail = serializers.CharField()
