from rest_framework import serializers


class MemberCalendarFeedStateSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(read_only=True)
    token_hint = serializers.CharField(allow_null=True, read_only=True)
    created_at = serializers.DateTimeField(allow_null=True, read_only=True)
    rotated_at = serializers.DateTimeField(allow_null=True, read_only=True)


class MemberCalendarFeedIssueSerializer(serializers.Serializer):
    confirm_bearer_risk = serializers.BooleanField()

    def validate_confirm_bearer_risk(self, value):
        if value is not True:
            raise serializers.ValidationError("Confirm that anyone with the URL can read the feed.")
        return value


class MemberCalendarFeedIssuedSerializer(serializers.Serializer):
    feed_url = serializers.URLField(read_only=True)
    token_hint = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)

