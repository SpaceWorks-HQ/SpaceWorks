from rest_framework import serializers


class TimingPolicySerializer(serializers.Serializer):
    quiet_start = serializers.TimeField()
    quiet_end = serializers.TimeField()
    channels = serializers.ListField(child=serializers.ChoiceField(choices=(
        'email', 'telegram', 'slack', 'mattermost', 'discord', 'native_push', 'webhook',
    )), max_length=7)
    digest_at = serializers.TimeField()
    daily_digest_default = serializers.BooleanField(required=False)
    bounce_secret = serializers.CharField(write_only=True, required=False, allow_blank=True,
                                          min_length=32, max_length=200)
    bounce_configured = serializers.BooleanField(read_only=True)

    def validate(self, values):
        for key in ('quiet_start', 'quiet_end', 'digest_at'):
            clock = values.get(key)
            if clock and (clock.tzinfo or clock.second or clock.microsecond):
                raise serializers.ValidationError({key: 'Use local hours and minutes only.'})
        return values
