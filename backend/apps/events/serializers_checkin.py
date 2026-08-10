from rest_framework import serializers


class EventCheckInResolveRequestSerializer(serializers.Serializer):
    checkin_token = serializers.CharField()


class EventCheckInResolveResponseSerializer(serializers.Serializer):
    registration_id = serializers.IntegerField()
    name = serializers.CharField()
    status = serializers.CharField()
    payment_status = serializers.CharField(allow_null=True)
