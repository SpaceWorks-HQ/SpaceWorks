from rest_framework import serializers

from apps.data_export.models import DataExportJob
from apps.data_export.types import Fidelity


class DataExportCreateSerializer(serializers.Serializer):
    fidelity = serializers.ChoiceField(
        choices=((Fidelity.REDACTED.value, "Redacted"),),
        default=Fidelity.REDACTED.value,
        required=False,
    )


class DataExportJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataExportJob
        fields = (
            "id", "fidelity", "status", "manifest", "failure_code",
            "failure_detail", "deadline_at", "snapshot_at", "started_at",
            "completed_at", "expires_at", "created_at",
        )
        read_only_fields = fields


class DataExportDownloadUrlSerializer(serializers.Serializer):
    url = serializers.URLField()
    expires_at = serializers.DateTimeField()
