"""All-or-nothing database materialization of one decrypted tenant archive."""

from dataclasses import dataclass

from django.apps import apps
from django.db import connection, transaction
from django.utils import timezone

from apps.encryption.cache import dek_cache
from apps.encryption.models import PiiMakerspaceWriteFence
from apps.encryption.write_fence import fence_operation

from .archive_stream import PortableArchive
from .blind_indexes import rebuild_blind_indexes
from .dependency_order import exported_models_in_dependency_order
from .external_materialization import materialize_external_references
from .identity_resolution import (
    RequiredIdentitySet,
    preallocate_walk_in_ids,
    resolve_identities,
)
from .import_keys import install_carried_deks
from .import_finalization import finalize_import_job
from .insertion_errors import (
    ImportCompletionAuditError,
    ImportPromotionClaimLost,
    ImportPromotionInProgress,
    MaterializationAlreadyCommitted,
)
from .models_import_job import TenantImportJob
from .object_import import (
    prepare_import_objects,
    promote_import_objects,
    rollback_import_objects,
)
from .pk_maps import TransactionPkMap
from .raw_repository import RawImportRepository
from .reference_state import ReferenceState
from .row_dispositions import ImportAccounting, preallocate_model
from .row_planning import (
    final_row,
    protect_carried_unique_values,
    update_resolved_row,
)
from .target_creation import create_target_makerspace
from .verification import verify_materialization


@dataclass(frozen=True)
class MaterializationResult:
    target_makerspace_id: int
    imported: dict[str, int]
    resolved: dict[str, int]
    dropped: dict[str, int]
    preserved: dict[tuple[str, str], int]
    regenerated: dict[tuple[str, str], int]
    identities_linked: int
    identities_created: int
    preexisting_global_authority: tuple[dict[str, object], ...]
    installed_dek_versions: tuple[int, ...]
    blind_indexes_created: int
    external_references_created: int
    objects_staged: int
    object_keys_regenerated: int
    object_key_regenerations: dict[str, str]
    objects_promoted: int


def materialize_tenant(
    archive_directory,
    job,
    carried_deks,
    *,
    target_identity=None,
    batch_size=500,
):
    """Commit database state atomically, then promote its staged objects."""
    archive = PortableArchive(archive_directory)
    target = None
    locked_job = None
    object_plan = None
    carried = tuple(carried_deks)
    if batch_size < 1:
        raise ValueError("batch_size must be positive.")
    try:
        object_plan = prepare_import_objects(archive, job)
        with transaction.atomic():
            locked_job = TenantImportJob.objects.select_for_update().get(pk=job.pk)
            if locked_job.target_makerspace_id is not None:
                raise MaterializationAlreadyCommitted(
                    "The import database materialization is already committed."
                )
            target = create_target_makerspace(
                archive,
                locked_job,
                target_identity=target_identity,
                object_key_map=object_plan.target_keys,
            )
            locked_job.target_makerspace = target
            locked_job.status = TenantImportJob.Status.MATERIALIZING
            locked_job.save(
                update_fields=("target_makerspace", "status", "updated_at")
            )
            _close_target_import_fence(target, locked_job.pk)

            with fence_operation(locked_job.pk):
                # Django's PostgreSQL FKs are transaction-deferred. This permits a
                # self-FK such as Box.parent to point at a preallocated row inserted
                # later in the same model stream without buffering the hierarchy.
                with connection.cursor() as cursor:
                    cursor.execute("SET CONSTRAINTS ALL DEFERRED")
                references = ReferenceState(archive)
                pk_map = TransactionPkMap()
                accounting = ImportAccounting()
                required_identities = RequiredIdentitySet()
                ordered = exported_models_in_dependency_order(apps)

                for model in ordered:
                    preallocate_model(
                        model,
                        archive,
                        pk_map,
                        references,
                        target,
                        accounting,
                        locked_job,
                        required_identities,
                    )
                preallocate_walk_in_ids(locked_job, pk_map, required_identities)
                identities = resolve_identities(
                    archive, locked_job, pk_map, required_identities
                )
                installed_versions = install_carried_deks(target, carried)
                deks = {
                    int(record["version"]): record["dek"]
                    for record in carried
                    if record.get("insert_at_target", True) is not False
                }
                regenerated = _insert_models(
                    ordered,
                    archive,
                    locked_job,
                    pk_map,
                    references,
                    target,
                    deks,
                    accounting,
                    batch_size,
                    object_plan.target_keys,
                )
                external_count = materialize_external_references(
                    archive, locked_job, target, pk_map, batch_size=batch_size
                )
                blind_count = rebuild_blind_indexes(target, batch_size=batch_size)
                verify_materialization(
                    archive=archive,
                    models=ordered,
                    target=target,
                    job=locked_job,
                    pk_map=pk_map,
                    references=references,
                    accounting=accounting,
                    identity_report=identities,
                    regenerated_fields=regenerated,
                )
            result = MaterializationResult(
                target_makerspace_id=target.pk,
                imported=dict(accounting.imported),
                resolved=dict(accounting.resolved),
                dropped=dict(accounting.dropped),
                preserved=dict(accounting.preserved),
                regenerated=dict(accounting.regenerated),
                identities_linked=identities.linked,
                identities_created=identities.created,
                preexisting_global_authority=identities.preexisting_global_authority,
                installed_dek_versions=installed_versions,
                blind_indexes_created=blind_count,
                external_references_created=external_count,
                objects_staged=object_plan.staged,
                object_keys_regenerated=object_plan.regenerated,
                object_key_regenerations=dict(object_plan.regenerated_keys),
                objects_promoted=0,
            )
            locked_job.status = TenantImportJob.Status.FINALIZING
            locked_job.materialization_report = _report_for(result)
            locked_job.save(
                update_fields=("status", "materialization_report", "updated_at")
            )
        promoted = promote_import_objects(locked_job)
        finalize_import_job(locked_job, actor=locked_job.actor)
        return MaterializationResult(
            **{
                **result.__dict__,
                "objects_promoted": promoted,
            }
        )
    except ImportPromotionClaimLost:
        # The replacement owns finalization; this worker must not mutate its work.
        raise
    except (ImportCompletionAuditError, ImportPromotionInProgress):
        raise
    except MaterializationAlreadyCommitted:
        raise
    except Exception as exc:
        failed_active = TenantImportJob.objects.filter(
            pk=job.pk,
            status__in=(
                TenantImportJob.Status.MATERIALIZING,
                TenantImportJob.Status.FINALIZING,
            ),
        ).update(
            status=TenantImportJob.Status.FAILED,
            terminal_at=timezone.now(),
            updated_at=timezone.now(),
        )
        if not failed_active:
            # Matching no row means this worker did not own an in-flight job -- but that
            # covers two very different situations, and only ONE of them is a lost race.
            # A replacement that carried the import to COMPLETED must not have its work
            # rolled back. Anything else (a failure before materialization even began, or
            # a job already marked FAILED) is an ordinary failure, and reporting it as
            # "superseded" would mask the real error from the operator -- which is exactly
            # what it did to every materialization-failure test.
            if TenantImportJob.objects.filter(
                pk=job.pk, status=TenantImportJob.Status.COMPLETED
            ).exists():
                raise ImportPromotionClaimLost(
                    "The import execution was superseded before failure cleanup."
                ) from exc
            raise
        if target is not None:
            dek_cache.invalidate(target.pk)
        rollback_job = TenantImportJob.objects.select_related(
            "target_makerspace", "actor"
        ).get(pk=job.pk)
        rollback_import_objects(rollback_job)
        raise


def _report_for(result):
    return {
        "format_version": 1,
        "target_makerspace_id": result.target_makerspace_id,
        "imported": result.imported,
        "resolved": result.resolved,
        "dropped": result.dropped,
        "identities_linked": result.identities_linked,
        "identities_created": result.identities_created,
        "external_references_created": result.external_references_created,
    }


def _insert_models(
    ordered, archive, job, pk_map, references, target, deks,
    accounting, batch_size, object_key_map,
):
    repository = RawImportRepository()
    regenerated = set()
    for model in ordered:
        label = model._meta.label
        if label == "makerspaces.Makerspace":
            continue
        pending = []
        fresh_values = {}
        for source in archive.rows(label):
            if update_resolved_row(model, source, target):
                continue
            row = final_row(
                model,
                source,
                job=job,
                pk_map=pk_map,
                references=references,
                target=target,
                deks=deks,
                fresh_values=fresh_values,
                object_key_map=object_key_map,
            )
            if row is None:
                continue
            for field_name, outcome in protect_carried_unique_values(
                model, row, target, fresh_values
            ):
                accounting.increment_field(outcome, label, field_name)
            pending.append(row)
            if len(pending) == batch_size:
                accounting.increment(
                    "imported", label, repository.insert_rows(model, pending)
                )
                regenerated.update((model, name) for _label, name in fresh_values)
                pending.clear()
                fresh_values.clear()
        if pending:
            accounting.increment(
                "imported", label, repository.insert_rows(model, pending)
            )
            regenerated.update((model, name) for _label, name in fresh_values)
    return regenerated


def _close_target_import_fence(target, operation_id):
    updated = PiiMakerspaceWriteFence.objects.filter(
        makerspace=target,
        state=PiiMakerspaceWriteFence.State.OPEN,
    ).update(
        state=PiiMakerspaceWriteFence.State.CLOSED,
        operation_id=operation_id,
        operation_kind=PiiMakerspaceWriteFence.OperationKind.TENANT_IMPORT,
    )
    if updated != 1:
        raise RuntimeError("The target tenant import fence could not be closed.")
