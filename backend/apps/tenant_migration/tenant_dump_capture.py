"""Request and materialize one immutable Lane D source capture."""

import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.backup import storage
from apps.backup.custody import with_makerspace_custody_lock
from apps.backup.digests import sha256_file
from apps.backup.recipient_selection import effective_tenant_recipients
from apps.backup.recipients import canonical_recipient, fingerprint_for
from apps.backup.services import superadmin_access_decision
from apps.backup.tenant_exit_custody import sync_tenant_exit_custody_locked

from .deployment_keys import public_deployment_identity
from .models import TenantDumpCapture
from .models_source_gate import SourceMigrationGate
from .object_export import capture_tenant_objects
from .source_gate import quiesced_snapshot
from .source_gate_release import release_after_copy_capture
from .tenant_dump_capture_database import capture_database_image
from .tenant_dump_catalog import CATALOG_SCHEMA_SHA256, validate_catalog
from .tenant_dump_errors import TenantDumpBuildError, TenantDumpCustodyError
from .tenant_dump_lineage import canonical_digest, object_ledger
from .tenant_dump_staging import create_capture_root, delete_owned_root


logger = logging.getLogger(__name__)


def request_tenant_dump_capture(actor, makerspace):
    """Freeze request-time custody under Part A's serialization boundary."""
    validate_catalog()
    rejected = None
    capture = None
    with with_makerspace_custody_lock(makerspace.pk) as custody:
        access_decision = superadmin_access_decision(custody.makerspace)
        recipients = canonical_tenant_recipient_snapshot(custody.makerspace.pk)
        state = sync_tenant_exit_custody_locked(custody)
        if not recipients:
            rejected = "A Lane D capture requires at least one verified tenant recipient."
            audit.record(
                actor,
                "tenant_migration.tenant_dump_request_refused",
                makerspace=custody.makerspace,
                target=custody.makerspace,
                meta={
                    "reason_code": "floor_breached_zero",
                    "superadmin_access_at_decision": access_decision,
                    "custody_alarm_revision": state.alarm_revision,
                },
            )
        else:
            capture = TenantDumpCapture.objects.create(
                makerspace=custody.makerspace,
                requested_by=actor,
                source_deployment_identity=public_deployment_identity(),
                source_makerspace_id=custody.makerspace.pk,
                source_makerspace_slug=custody.makerspace.slug,
                superadmin_access_at_decision=access_decision,
                frozen_tenant_recipients=list(recipients),
                source_encryption_mode=bool(settings.PII_ENCRYPTION_ENABLED),
                catalog_digest=CATALOG_SCHEMA_SHA256,
            )
            audit.record(
                actor,
                "tenant_migration.tenant_dump_requested",
                makerspace=custody.makerspace,
                target=capture,
                meta={
                    "superadmin_access_at_decision": (
                        capture.superadmin_access_at_decision
                    ),
                    "recipient_fingerprints": [
                        item["fingerprint"] for item in recipients
                    ],
                    "custody_state": state.state,
                    "custody_alarm_revision": state.alarm_revision,
                },
            )
    if rejected:
        raise TenantDumpCustodyError(rejected)
    return capture


def canonical_tenant_recipient_snapshot(makerspace_id):
    """Canonical cryptographic tuple set; caller holds the Part A recipient locks."""
    result = []
    seen = set()
    for row in effective_tenant_recipients(makerspace_id):
        try:
            canonical = canonical_recipient(row["public_recipient"])
        except ValidationError as exc:
            raise TenantDumpCustodyError(
                "An archive recipient is not a valid canonical native age key."
            ) from exc
        fingerprint = fingerprint_for(canonical)
        if fingerprint != row["fingerprint"]:
            raise TenantDumpCustodyError(
                "An archive recipient fingerprint does not match its canonical key."
            )
        identity = (canonical, fingerprint)
        if identity in seen:
            raise TenantDumpCustodyError(
                "The canonical tenant-recipient set contains a duplicate key."
            )
        seen.add(identity)
        result.append(
            {
                "public_recipient": canonical,
                "fingerprint": fingerprint,
            }
        )
    return tuple(sorted(result, key=lambda item: item["fingerprint"]))


def capture_tenant_dump_source(capture_id, *, sleep=None, storage_modes=None):
    """Freeze database plus exact object bytes, persist lineage, then reopen source."""
    capture = _claim_capture(capture_id)
    root = None
    lease = None
    lineage_persisted = False
    try:
        root = create_capture_root(capture.pk)
        gate_kwargs = {"purpose": SourceMigrationGate.Purpose.COPY_CAPTURE}
        if sleep is not None:
            gate_kwargs["sleep"] = sleep
        with quiesced_snapshot(
            capture.makerspace,
            capture.requested_by,
            **gate_kwargs,
        ) as lease:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT transaction_timestamp(), current_setting('server_version_num')"
                )
                snapshot_at, server_version_num = cursor.fetchone()
                cursor.execute("SELECT pg_export_snapshot()")
                snapshot_id = cursor.fetchone()[0]
            database_image = capture_database_image(
                snapshot_id, root / "database.source.dump"
            )
            modes = storage_modes or _storage_modes()
            objects = capture_tenant_objects(root, capture.makerspace, modes)

        ledger = object_ledger(objects)
        database_sha256 = sha256_file(database_image)
        ledger_sha256 = canonical_digest(ledger)
        _complete_capture(
            capture.pk,
            lease=lease,
            snapshot_at=snapshot_at,
            source_postgres_major=int(server_version_num) // 10000,
            database_sha256=database_sha256,
            objects=ledger,
            object_ledger_sha256=ledger_sha256,
        )
        lineage_persisted = True
        release_after_copy_capture(lease, actor=capture.requested_by)
        return TenantDumpCapture.objects.get(pk=capture.pk)
    except Exception as exc:
        if root is not None and not lineage_persisted:
            try:
                delete_owned_root(capture.pk)
            except Exception:
                logger.exception(
                    "tenant_dump_capture_cleanup_failed",
                    extra={"capture_id": str(capture.pk)},
                )
        _fail_capture(capture.pk, exc)
        raise


@transaction.atomic
def _claim_capture(capture_id):
    capture = TenantDumpCapture.objects.select_for_update().get(pk=capture_id)
    if capture.status != TenantDumpCapture.Status.REQUESTED:
        raise TenantDumpBuildError("The Lane D capture is not awaiting capture.")
    capture.status = TenantDumpCapture.Status.CAPTURING
    capture.refusal_code = ""
    capture.refusal_detail = ""
    capture.save(
        update_fields=("status", "refusal_code", "refusal_detail", "updated_at")
    )
    return capture


@transaction.atomic
def _complete_capture(
    capture_id,
    *,
    lease,
    snapshot_at,
    source_postgres_major,
    database_sha256,
    objects,
    object_ledger_sha256,
):
    capture = TenantDumpCapture.objects.select_for_update().get(pk=capture_id)
    if capture.status != TenantDumpCapture.Status.CAPTURING:
        raise TenantDumpBuildError("The Lane D capture changed state during capture.")
    capture.status = TenantDumpCapture.Status.CAPTURED
    capture.gate_owner_id = lease.owner_id
    capture.gate_fencing_token = lease.fencing_token
    capture.database_snapshot_at = snapshot_at
    capture.source_postgres_major = source_postgres_major
    capture.database_image_sha256 = database_sha256
    capture.object_ledger = list(objects)
    capture.object_ledger_sha256 = object_ledger_sha256
    capture.capture_completed_at = timezone.now()
    capture.save()
    audit.record(
        capture.requested_by,
        "tenant_migration.tenant_dump_captured",
        makerspace=capture.makerspace,
        target=capture,
        meta={
            "gate_owner_id": str(lease.owner_id),
            "gate_fencing_token": lease.fencing_token,
            "database_image_sha256": database_sha256,
            "object_ledger_sha256": object_ledger_sha256,
        },
    )


def _fail_capture(capture_id, exc):
    detail = str(exc).strip()[:500] or type(exc).__name__
    changed = TenantDumpCapture.objects.filter(pk=capture_id).exclude(
        status=TenantDumpCapture.Status.CAPTURED
    ).update(
        status=TenantDumpCapture.Status.FAILED,
        refusal_code="capture_failed",
        refusal_detail=detail,
        updated_at=timezone.now(),
    )
    if changed:
        capture = TenantDumpCapture.objects.get(pk=capture_id)
        audit.record(
            capture.requested_by,
            "tenant_migration.tenant_dump_capture_failed",
            makerspace=capture.makerspace,
            target=capture,
            meta={"failure_detail": detail},
        )


def _storage_modes():
    return {
        "private": storage.ensure_versioning_or_quiescence(
            settings.AWS_STORAGE_BUCKET_NAME
        ),
        "public_image": storage.ensure_versioning_or_quiescence(
            settings.PUBLIC_IMAGE_BUCKET
        ),
    }
