"""Offline derivation of D2 output from one immutable Phase S capture."""

import json
import shutil

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.backup.digests import sha256_file

from .models import TenantDumpCapture
from .tenant_dump_builder import build_tenant_dump
from .tenant_dump_catalog import CATALOG_SCHEMA_SHA256
from .tenant_dump_database import (
    empty_verification_database,
    restore_scratch_dump,
)
from .tenant_dump_deks import seal_tenant_deks
from .tenant_dump_envelope import (
    TENANT_DEKS_MEMBER,
    build_tenant_content_ledger,
    seal_outer_bundle,
)
from .tenant_dump_errors import TenantDumpBuildError, TenantDumpVerificationError
from .tenant_dump_key_inventory import (
    enumerate_immutable_source_keys,
    manifest_key_inventory,
    retained_key_rows,
)
from .tenant_dump_lineage import (
    FORMAT,
    canonical_digest,
    derivation_policy_digest,
)
from .tenant_dump_objects import package_staged_objects
from .tenant_dump_pii import ENCRYPTED, scan_mapped_pii, source_pii_mode
from .tenant_dump_publication import revalidate_before_encryption
from .tenant_dump_recipients import recipient_sets
from .tenant_dump_source_projection import project_makerspace_source
from .tenant_dump_staging import require_owned_root


def derive_tenant_dump(capture_id, *, database=None):
    capture = _claim_derivation(capture_id)
    root = require_owned_root(capture.pk)
    source_image = root / "database.source.dump"
    bundle = root / "derived"
    artifact = root / "tenant-dump.tar.age"
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
                capture_id=capture.pk,
            )
            pii_mode = source_pii_mode(capture.source_encryption_mode)
            pii_findings = scan_mapped_pii(projection.rows, pii_mode)
            source_key_rows = enumerate_immutable_source_keys(
                capture.source_makerspace_id,
                using=using,
            )
            retained_keys = retained_key_rows(source_key_rows, mode=pii_mode)
        build = build_tenant_dump(
            projection,
            bundle / "database.dump",
            run_id=capture.pk,
            source_pii_mode=pii_mode,
            database=database,
        )
        object_entries = tuple(
            item
            for item in capture.object_ledger
            if item.get("source_key") not in projection.excluded_object_keys
        )
        objects = package_staged_objects(root, bundle, object_entries)
        key_envelope = None
        if pii_mode == ENCRYPTED:
            frozen = revalidate_before_encryption(capture.pk, stage="inner")
            recipients = recipient_sets(capture, frozen)
            key_envelope = seal_tenant_deks(
                source_key_rows,
                retained_keys,
                recipients.tenant_dek_recipients,
                bundle / TENANT_DEKS_MEMBER,
            )
        policy_digest = derivation_policy_digest(
            source_encryption_mode=capture.source_encryption_mode
        )
        manifest = _manifest(
            capture,
            build,
            objects,
            projection,
            policy_digest,
            pii_mode=pii_mode,
            pii_findings=pii_findings,
            retained_keys=retained_keys,
            key_envelope=key_envelope,
        )
        manifest["contents"] = build_tenant_content_ledger(
            bundle, source_pii_mode=pii_mode
        )
        manifest_path = bundle / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        manifest_path.chmod(0o600)
        frozen = revalidate_before_encryption(capture.pk, stage="outer")
        recipients = recipient_sets(capture, frozen)
        seal_outer_bundle(bundle, artifact, recipients.outer_recipients)
        shutil.rmtree(bundle)
        _complete_derivation(capture.pk, manifest, policy_digest)
        return artifact, manifest
    except Exception as exc:
        if bundle.exists():
            shutil.rmtree(bundle)
        artifact.unlink(missing_ok=True)
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


def _manifest(
    capture,
    build,
    objects,
    projection,
    policy_digest,
    *,
    pii_mode,
    pii_findings,
    retained_keys,
    key_envelope,
):
    return {
        "format": FORMAT,
        "capture_id": str(capture.pk),
        "source_pii_mode": pii_mode,
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
            "source_pii_mode": pii_mode,
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
        "encryption": {
            "source_pii_mode": pii_mode,
            "mapped_column_findings": pii_findings.as_manifest(),
            "retained_key_inventory": manifest_key_inventory(retained_keys),
            "tenant_dek_envelope": key_envelope or {
                "path": TENANT_DEKS_MEMBER,
                "present": False,
            },
        },
        "machine_operator_manifest": list(projection.machine_operator_manifest),
        "user_closure": projection.user_closure.manifest(),
        "cross_tenant_lost_edges": list(projection.cross_tenant_lost_edges),
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
            "artifact_id": str(capture.pk),
            "capture_id": str(capture.pk),
            "database_image_sha256": capture.parent_database_sha256,
            "object_ledger_sha256": capture.parent_object_ledger_sha256,
            "derivation_policy_sha256": policy_digest,
            "user_closure_digest": manifest["user_closure"]["sha256"],
            "user_closure_included_count": len(
                manifest["user_closure"]["included"]
            ),
            "user_closure_stubbed_count": len(
                manifest["user_closure"]["stubbed"]
            ),
            "user_closure_refused_count": len(
                manifest["user_closure"]["refused"]
            ),
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
