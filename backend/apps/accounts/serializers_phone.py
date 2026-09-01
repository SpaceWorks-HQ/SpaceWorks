from rest_framework import serializers


class PhoneStartSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=32)


class PhoneConfirmSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=32)
    # Not an IntegerField: a code is a fixed-length digit string, and "012345" must not
    # be coerced to 12345 and then fail to match its own digest.
    code = serializers.CharField(min_length=6, max_length=6)


class PhoneStartResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()


class PhoneStatusSerializer(serializers.Serializer):
    phone_e164 = serializers.CharField(allow_blank=True)
    verified = serializers.BooleanField()
