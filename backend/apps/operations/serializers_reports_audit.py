"""Query filters for the ``audit-trail`` export (dates come from the shared parser)."""

from rest_framework import serializers


class AuditReportFilterSerializer(serializers.Serializer):
    action = serializers.CharField(required=False, max_length=100)
    target_type = serializers.CharField(required=False, max_length=200)
    target_id = serializers.CharField(required=False, max_length=100)
    actor = serializers.IntegerField(required=False, min_value=1)
