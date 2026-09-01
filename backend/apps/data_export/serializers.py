from rest_framework import serializers

from apps.data_export.models import DataExportJob
from apps.data_export.types import Fidelity


class DataExportCreateSerializer(serializers.Serializer):
    fidelity = serializers.ChoiceField(
        # The label spells out the scope because the VALUE does not: "REDACTED" reads as
        # "PII removed", and this mode removes audit metadata and form answers, not member
        # contact details. The value is a stored API contract and is deliberately unchanged.
        choices=(
            (
                Fidelity.REDACTED.value,
                "Readable — audit metadata and form answers redacted; "
                "member contact details included",
            ),
        ),
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
