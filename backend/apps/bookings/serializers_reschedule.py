from rest_framework import serializers


class BookingRescheduleSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()

    def validate(self, values):
        if values['ends_at'] <= values['starts_at']:
            raise serializers.ValidationError({'ends_at': 'End must be after start.'})
        return values
