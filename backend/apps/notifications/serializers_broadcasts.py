from rest_framework import serializers

from apps.notifications.models_broadcasts import MemberBroadcast


class BroadcastInputSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    body = serializers.CharField(max_length=12000)
    plan_id = serializers.IntegerField(min_value=1, required=False)
    status = serializers.ChoiceField(choices=('active', 'lapsed'), required=False)
    certification_id = serializers.IntegerField(min_value=1, required=False)


class BroadcastSerializer(serializers.ModelSerializer):
    class Meta:
        model = MemberBroadcast
        fields = ('id', 'title', 'body', 'created_at')
        read_only_fields = fields


class BroadcastResultSerializer(serializers.Serializer):
    broadcast = BroadcastSerializer()
    recipients = serializers.IntegerField()


class SegmentChoiceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class BroadcastOptionsSerializer(serializers.Serializer):
    plans = SegmentChoiceSerializer(many=True)
    certifications = SegmentChoiceSerializer(many=True)
