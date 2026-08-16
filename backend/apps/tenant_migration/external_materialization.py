"""Persist typed cross-tenant snapshots after their local anchors exist."""

from django.apps import apps

from .models import ExternalTenantReference
from .schemas import validate_snapshot
from .insertion_errors import PrimaryKeyMapUnavailable


def materialize_external_references(archive, job, target, pk_map, *, batch_size=500):
    pending = []
    inserted = 0
    for record in archive.json_lines("migration/external_references.jsonl"):
        validate_snapshot(
            record["source_model_label"], record["field_name"], record["snapshot"]
        )
        target_label = record["target_model_label"]
        try:
            target_id = str(
                pk_map.lookup(apps.get_model(target_label), record["target_object_id"])
            )
        except PrimaryKeyMapUnavailable:
            target_label, target_id = "", ""
        pending.append(
            ExternalTenantReference(
                makerspace=target,
                source_archive_digest=job.source_archive_digest,
                source_model_label=record["source_model_label"],
                source_object_id=str(record["source_object_id"]),
                field_name=record["field_name"],
                target_model_label=target_label,
                target_object_id=target_id,
                snapshot=record["snapshot"],
            )
        )
        if len(pending) == batch_size:
            ExternalTenantReference.objects.bulk_create(pending)
            inserted += len(pending)
            pending.clear()
    if pending:
        ExternalTenantReference.objects.bulk_create(pending)
        inserted += len(pending)
    return inserted
