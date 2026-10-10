from rest_framework import serializers
from .serializers_member_memberships import AdminMembershipSerializer, MembershipRequestSerializer


class MembershipListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = AdminMembershipSerializer(many=True)


class MembershipRequestListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = MembershipRequestSerializer(many=True)
