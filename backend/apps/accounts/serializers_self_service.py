from collections.abc import Mapping

from rest_framework import serializers

from apps.accounts.models import User


class AccountProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["display_name", "first_name", "last_name", "phone"]

    def to_internal_value(self, data):
        if not isinstance(data, Mapping):
            return super().to_internal_value(data)
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({key: "This field is not member-editable." for key in unknown})
        return super().to_internal_value(data)


class AccountSessionSerializer(serializers.Serializer):
    id = serializers.CharField()
    kind = serializers.ChoiceField(choices=["web", "device"])
    created_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField(allow_null=True)
    last_used_at = serializers.DateTimeField(allow_null=True)
    current = serializers.BooleanField()


class AccountSessionPageSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = AccountSessionSerializer(many=True)
