"""Atomically establish command ownership and its immutable evidence identity."""

from django.db import IntegrityError, transaction

from apps.audit import services as audit
from apps.evidence.models import EvidenceObjectRetentionState, EvidenceUploadFinalization
from apps.evidence.services_upload import issue_upload
from apps.evidence.storage import presigned_upload
from apps.hardware_requests.models_replay import ReplayCommand
from apps.hardware_requests.kiosk_online_commands import channel_meta
from apps.hardware_requests.replay_failures import ReplayFailure
from apps.hardware_requests.replay_fingerprint import fingerprint
from apps.hardware_requests.replay_records import age, audit_meta, ownership, result, scoped_targets
from apps.tenant_migration.gate_runtime import assert_write_allowed


def _upload_again(command, envelope):
    if command.evidence_id is None or command.state != ReplayCommand.State.PREPARED:
        return None
    if EvidenceObjectRetentionState.objects.filter(evidence_id=command.evidence_id).exists():
        raise ReplayFailure("evidence_invalid")
    if EvidenceUploadFinalization.objects.filter(
        evidence_id=command.evidence_id, status=EvidenceUploadFinalization.Status.FINALIZED,
    ).exists():
        return None
    photo = command.evidence
    upload = presigned_upload(photo.object_key, envelope["evidence"]["content_type"])
    return {"evidence_id": photo.pk, "object_key": photo.object_key,
            "upload_url": upload["url"], "fields": upload.get("fields", {}),
            **({"method": upload["method"], "headers": upload.get("headers", {})} if "method" in upload else {})}


def prepare(identity, envelope):
    with transaction.atomic():
        station, lease, user = identity.live(envelope["kind"])
        assert_write_allowed(station.makerspace_id)
        expires = age(envelope, lease)
        owner = dict(station=station, station_session_id=identity.session_id,
                     client_command_id=envelope["client_command_id"])
        existing = ReplayCommand.objects.select_for_update().filter(**owner).first()
        if existing is not None:
            ownership(existing, identity, envelope)
            station, lease, user = identity.live(envelope["kind"])
            age(envelope, lease)
            data = result(existing)
            data["upload"] = _upload_again(existing, envelope)
            return data
        predecessor = None
        if envelope["sequence"] > 1:
            predecessor = ReplayCommand.objects.filter(
                station=station, station_session_id=identity.session_id,
                aggregate_id=envelope["aggregate_id"], sequence=envelope["sequence"] - 1,
                client_command_id=envelope["predecessor_client_id"], actor=user,
                operator_lease_id=lease.pk,
            ).first()
            if predecessor is None:
                raise ReplayFailure("predecessor_missing")
        try:
            with transaction.atomic():
                command = ReplayCommand.objects.create(
                    **owner, makerspace=station.makerspace, actor=user, operator_lease_id=lease.pk,
                    station_version=identity.version, payload_fingerprint=fingerprint(envelope),
                    operation_kind=envelope["kind"], operation_version=envelope["version"],
                    aggregate_id=envelope["aggregate_id"], sequence=envelope["sequence"],
                    predecessor=predecessor, client_created_at=envelope["client_created_at"], expires_at=expires,
                    **scoped_targets(station, user, envelope),
                )
        except IntegrityError:
            # Concurrent INSERT of the same owner waits for the first transaction,
            # then reuses its committed command/evidence. A stream-position collision
            # under a different owner ID remains a conflict.
            command = ReplayCommand.objects.select_for_update().filter(**owner).first()
            if command is None:
                raise ReplayFailure("idempotency_conflict") from None
            ownership(command, identity, envelope)
            station, lease, user = identity.live(envelope["kind"])
            age(envelope, lease)
            return {**result(command), "upload": _upload_again(command, envelope)}
        upload = None
        if envelope["evidence"] is not None:
            station, lease, user = identity.live(envelope["kind"])
            age(envelope, lease)
            # The owner row exists before presigning; any failure rolls back both rows.
            photo, upload = issue_upload(
                station.makerspace, actor=user, **envelope["evidence"],
                audit_action="kiosk.evidence_upload_issued", audit_meta=channel_meta(lease, "evidence_prepare"),
            )
            command.evidence = photo
            command.save(update_fields=["evidence", "updated_at"])
        audit.record(user, "kiosk.replay_prepared", makerspace=station.makerspace,
                     target=station, meta=audit_meta(command, lease))
        return {**result(command), "upload": upload}
