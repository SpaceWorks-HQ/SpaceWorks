"""Bounded operational recovery DTOs; no payload, QR or channel credentials."""

from datetime import timedelta

from django.conf import settings
from rest_framework import serializers

from apps.accounts import rbac
from apps.hardware_requests.models_replay import ReplayCommand
from apps.hardware_requests.replay_recovery_policy import subject_context


class ReplayRecoverySerializer(serializers.ModelSerializer):
    makerspace_id = serializers.IntegerField(read_only=True)
    station_id = serializers.IntegerField(read_only=True)
    station_name = serializers.CharField(source="station.name")
    station_kind = serializers.CharField(source="station.kind")
    operator_display = serializers.SerializerMethodField()
    predecessor_id = serializers.UUIDField(allow_null=True)
    predecessor_state = serializers.CharField(source="predecessor.state", default=None, allow_null=True)
    evidence_id = serializers.IntegerField(allow_null=True)
    can_view_evidence = serializers.SerializerMethodField()
    subject_request_id = serializers.IntegerField(allow_null=True)
    subject_loan_id = serializers.IntegerField(allow_null=True)
    recovery_request_id = serializers.SerializerMethodField()
    recovery_loan_id = serializers.SerializerMethodField()
    result_request_id = serializers.IntegerField(allow_null=True)
    result_loan_id = serializers.IntegerField(allow_null=True)
    result_return_event_id = serializers.IntegerField(allow_null=True)
    replacement_command_id = serializers.UUIDField(allow_null=True)
    resolved_by_display = serializers.SerializerMethodField()
    retained_until = serializers.SerializerMethodField()

    class Meta:
        model = ReplayCommand
        fields = ("id", "makerspace_id", "station_id", "station_name", "station_kind", "operator_display",
                  "operation_kind", "operation_version", "aggregate_id", "sequence", "state",
                  "created_at", "client_created_at", "completed_at", "expires_at", "retained_until",
                  "failure_code", "failure_detail", "subject_request_id", "subject_loan_id",
                  "recovery_request_id", "recovery_loan_id", "result_request_id", "result_loan_id",
                  "result_return_event_id", "predecessor_id", "predecessor_state", "evidence_id",
                  "can_view_evidence", "resolution_code", "resolved_at", "resolved_by_display",
                  "replacement_command_id")

    def get_operator_display(self, obj) -> str:
        return (obj.actor.display_name or obj.actor.username)[:150]

    def get_resolved_by_display(self, obj) -> str | None:
        return ((obj.resolved_by.display_name or obj.resolved_by.username)[:150]
                if obj.resolved_by_id else None)

    def get_can_view_evidence(self, obj) -> bool:
        return rbac.can(self.context["request"].user, rbac.Action.UPLOAD_EVIDENCE, obj.makerspace_id)

    def get_recovery_request_id(self, obj) -> int | None:
        return subject_context(obj)[0]

    def get_recovery_loan_id(self, obj) -> int | None:
        return subject_context(obj)[1]

    def get_retained_until(self, obj) -> str:
        return (obj.completed_at + timedelta(seconds=settings.KIOSK_REPLAY_RETENTION_SECONDS)).isoformat()


class ReplayResolutionSerializer(serializers.Serializer):
    resolution_code = serializers.ChoiceField(choices=ReplayCommand.Resolution.choices)
    replacement_command_id = serializers.UUIDField(required=False, allow_null=True, default=None)

    def validate(self, attrs):
        requires_replacement = attrs["resolution_code"] == ReplayCommand.Resolution.REPLACED_ONLINE
        if requires_replacement != (attrs["replacement_command_id"] is not None):
            raise serializers.ValidationError("Only replaced_online requires a replacement command UUID.")
        return attrs


class ReplayRecoveryFilterSerializer(serializers.Serializer):
    state = serializers.ChoiceField(choices=["failed"], default="failed")
    resolution = serializers.ChoiceField(choices=["unresolved", "resolved", "all"], default="unresolved")
