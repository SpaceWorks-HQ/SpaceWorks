"""Review failed attempts without rewriting their domain/evidence history."""

from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.accounts import rbac
from apps.audit import services as audit
from apps.hardware_requests.models_replay import ReplayCommand
from apps.hardware_requests.replay_records import audit_meta, lease_snapshot
from apps.hardware_requests.replay_recovery_policy import OPERATION_ACTIONS, subject_context, visible_replays
from apps.admin_api.permissions import require_action
from apps.tenant_migration.gate_runtime import assert_write_allowed, boundary_tenant_write


class ResolutionConflict(APIException):
    status_code = 409
    default_detail = "This resolution conflicts with the retained replay history."
    default_code = "replay_resolution_conflict"


def failed_replay(user, pk):
    return get_object_or_404(visible_replays(user).select_related(
        "station", "actor", "resolved_by", "predecessor",
    ), pk=pk, state=ReplayCommand.State.FAILED)


def validate_replacement(user, source, replacement):
    context = subject_context(source)
    if (replacement.pk == source.pk or replacement.state != "succeeded"
            or replacement.makerspace_id != source.makerspace_id
            or replacement.operation_kind != source.operation_kind
            or replacement.operation_version != source.operation_version
            or not any(context) or subject_context(replacement) != context
            or replacement.aggregate_id == source.aggregate_id
            or replacement.created_at < source.completed_at
            or replacement.completed_at < source.completed_at):
        raise ResolutionConflict("Use a fresh succeeded command for the same operation and handover subject.")
    if visible_replays(user).filter(replacement_command=replacement).exclude(pk=source.pk).exists():
        raise ResolutionConflict("That successful command already resolves another failure.")


def resolve_replay(user, pk, *, resolution_code, replacement_command_id=None):
    source = failed_replay(user, pk)
    with boundary_tenant_write(source.makerspace_id), transaction.atomic():
        assert_write_allowed(source.makerspace_id)
        ids = {pk}
        if replacement_command_id:
            ids.add(replacement_command_id)
        # Lock only commands, in deterministic order. Nullable domain FKs are not joined.
        commands = {row.pk: row for row in visible_replays(user).select_for_update().filter(
            pk__in=ids, makerspace_id=source.makerspace_id,
        ).order_by("pk")}
        source = commands.get(pk)
        if source is None or source.state != "failed":
            raise Http404
        require_action(user, OPERATION_ACTIONS[source.operation_kind], source.makerspace_id)
        if source.resolution_code:
            if (source.resolution_code == resolution_code
                    and source.replacement_command_id == replacement_command_id):
                return source
            raise ResolutionConflict("This failure has already been reviewed with a different resolution.")
        if resolution_code == ReplayCommand.Resolution.REPLACED_ONLINE:
            replacement = commands.get(replacement_command_id)
            if replacement is None:
                raise ResolutionConflict("The replacement is unavailable in your current action scope.")
            validate_replacement(user, source, replacement)
        source.resolution_code = resolution_code
        source.resolved_by = user
        source.resolved_at = timezone.now()
        source.replacement_command_id = replacement_command_id
        source.save(update_fields=("resolution_code", "resolved_by", "resolved_at", "replacement_command"))
        audit.record(user, "kiosk.replay_resolved", makerspace=source.makerspace, target=source.station,
                     meta={**audit_meta(source, lease_snapshot(source)), "resolution_code": resolution_code,
                           "replacement_replay_id": str(replacement_command_id) if replacement_command_id else None})
        return source
