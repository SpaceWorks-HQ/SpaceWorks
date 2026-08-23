"""Offline derivation of D2 output from one immutable Phase S capture."""

import json
import shutil

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.backup.digests import build_content_ledger, sha256_file

from .models import TenantDumpCapture
from .tenant_dump_builder import build_tenant_dump
from .tenant_dump_catalog import CATALOG_SCHEMA_SHA256
from .tenant_dump_database import (
    empty_verification_database,
    restore_scratch_dump,
)
from .tenant_dump_errors import TenantDumpBuildError, TenantDumpVerificationError
from .tenant_dump_lineage import (
    FORMAT,
    canonical_digest,
    derivation_policy_digest,
)
from .tenant_dump_objects import package_staged_objects
from .tenant_dump_source_projection import project_makerspace_source
from .tenant_dump_staging import require_owned_root


def derive_tenant_dump(capture_id, *, database=None):
    capture = _claim_derivation(capture_id)
    root = require_owned_root(capture.pk)
    source_image = root / "database.source.dump"
    bundle = root / "derived"
    try:
        _verify_capture_bytes(capture, source_image)
        if bundle.exists():
            raise TenantDumpBuildError("The Lane D derivation output already exists.")
        bundle.mkdir(mode=0o700)
        with empty_verification_database(
            capture.makerspace_id,
            f"{capture.pk}source",
            database=database,
        ) as (using, database_name):
            restore_scratch_dump(source_image, database_name, database=database)
            projection = project_makerspace_source(
                capture.source_makerspace_id,
                using=using,
            )
        build = build_tenant_dump(
            projection,
            bundle / "database.dump",
            run_id=capture.pk,
            database=database,
        )
        objects = package_staged_objects(root, bundle, capture.object_ledger)
        policy_digest = derivation_policy_digest(
            source_encryption_mode=capture.source_encryption_mode
        )
        manifest = _manifest(capture, build, objects, projection, policy_digest)
        manifest["contents"] = build_content_ledger(bundle)
        manifest_path = bundle / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        manifest_path.chmod(0o600)
        _complete_derivation(capture.pk, manifest, policy_digest)
        return bundle, manifest
    except Exception as exc:
        if bundle.exists():
            shutil.rmtree(bundle)
        _fail_derivation(capture.pk, exc)
        raise


def _verify_capture_bytes(capture, source_image):
    if capture.catalog_digest != CATALOG_SCHEMA_SHA256:
        raise TenantDumpVerificationError(
            "The Lane D source catalog changed after the capture request."
        )
    try:
        database_digest = sha256_file(source_image)
    except OSError as exc:
        raise TenantDumpVerificationError(
            "The immutable Lane D database image is unavailable."
        ) from exc
    if database_digest != capture.database_image_sha256:
        raise TenantDumpVerificationError(
            "The immutable Lane D database image digest changed."
        )
    if canonical_digest(capture.object_ledger) != capture.object_ledger_sha256:
        raise TenantDumpVerificationError("The immutable object ledger digest changed.")


def _manifest(capture, build, objects, projection, policy_digest):
    return {
        "format": FORMAT,
        "capture_id": str(capture.pk),
        "source": {
            "deployment_identity": capture.source_deployment_identity,
            "makerspace_id": capture.source_makerspace_id,
            "makerspace_slug": capture.source_makerspace_slug,
            "request_actor_id": capture.requested_by_id,
            "gate_owner_id": str(capture.gate_owner_id),
            "gate_fencing_token": capture.gate_fencing_token,
            "superadmin_access_at_decision": (
                capture.superadmin_access_at_decision
            ),
            "tenant_recipients": capture.frozen_tenant_recipients,
            "database_snapshot_at": capture.database_snapshot_at.isoformat(),
            "postgres_major": capture.source_postgres_major,
            "encryption_mode": capture.source_encryption_mode,
            "catalog_digest": capture.catalog_digest,
            "capture_completed_at": capture.capture_completed_at.isoformat(),
        },
        "lineage": {
            "database_image_sha256": capture.database_image_sha256,
            "object_ledger_sha256": capture.object_ledger_sha256,
            "derivation_policy_sha256": policy_digest,
        },
        "database": {
            "member_path": "database.dump",
            "mapped_raw_sha256": build.mapped_raw_sha256,
            "sequence_state": build.sequence_state,
        },
        "objects": list(objects),
        "machine_operator_manifest": list(projection.machine_operator_manifest),
    }


@transaction.atomic
def _claim_derivation(capture_id):
    capture = TenantDumpCapture.objects.select_for_update().get(pk=capture_id)
    if capture.status != TenantDumpCapture.Status.CAPTURED:
        raise TenantDumpBuildError("The Lane D capture is not ready for derivation.")
    capture.status = TenantDumpCapture.Status.DERIVING
    capture.save(update_fields=("status", "updated_at"))
    return capture


@transaction.atomic
def _complete_derivation(capture_id, manifest, policy_digest):
    capture = TenantDumpCapture.objects.select_for_update().get(pk=capture_id)
    if capture.status != TenantDumpCapture.Status.DERIVING:
        raise TenantDumpBuildError("The Lane D derivation changed state.")
    capture.status = TenantDumpCapture.Status.PENDING_PUBLICATION
    capture.parent_database_sha256 = capture.database_image_sha256
    capture.parent_object_ledger_sha256 = capture.object_ledger_sha256
    capture.derivation_policy_sha256 = policy_digest
    capture.content_ledger = manifest["contents"]
    capture.manifest = manifest
    capture.save()
    audit.record(
        capture.requested_by,
        "tenant_migration.tenant_dump_derived",
        makerspace=capture.makerspace,
        target=capture,
        meta={
            "database_image_sha256": capture.parent_database_sha256,
            "object_ledger_sha256": capture.parent_object_ledger_sha256,
            "derivation_policy_sha256": policy_digest,
        },
    )


def _fail_derivation(capture_id, exc):
    detail = str(exc).strip()[:500] or type(exc).__name__
    changed = TenantDumpCapture.objects.filter(
        pk=capture_id,
        status=TenantDumpCapture.Status.DERIVING,
    ).update(
        status=TenantDumpCapture.Status.FAILED,
        refusal_code="derivation_failed",
        refusal_detail=detail,
        updated_at=timezone.now(),
    )
    if changed:
        capture = TenantDumpCapture.objects.get(pk=capture_id)
        audit.record(
            capture.requested_by,
            "tenant_migration.tenant_dump_derivation_failed",
            makerspace=capture.makerspace,
            target=capture,
            meta={"failure_detail": detail},
        )
