"""Orchestrate the Phase D2 scratch projection and verified custom dump."""

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
from uuid import UUID

from django.apps import apps
from django.db import connections, transaction

from apps.backup.raw_projection import no_decrypt_guard
from apps.data_export.datasets import DATASET_SPECS

from .tenant_dump_bootstrap import seed_default_roles
from .tenant_dump_catalog import validate_catalog, validate_unowned_tables
from .tenant_dump_cross_tenant import project_cross_tenant_values
from .tenant_dump_database import (
    dump_scratch_database,
    empty_verification_database,
    migrated_scratch_database,
    restore_scratch_dump,
)
from .tenant_dump_errors import TenantDumpVerificationError
from .tenant_dump_graph import plan_row_load
from .tenant_dump_machine_types import resolve_machine_types
from .tenant_dump_model_catalog import FIRST_PARTY_MODEL_RULES
from .tenant_dump_pii import verify_ciphertext_aad_identities
from .tenant_dump_raw import (
    SanitizedRow,
    mapped_raw_digest,
    projected_raw_digest,
    sanitize_record,
    validate_raw_column_allowlists,
)
from .tenant_dump_sql import (
    apply_deferred_foreign_keys,
    delete_portable_rows,
    empty_source_disposition_tables,
    insert_closed_tenant_fence,
    insert_rows,
    serialize_open_tenant_fence,
    verify_source_disposition_tables_empty,
    verify_tables_empty,
)
from .tenant_dump_sequences import normalize_sequences
from .tenant_dump_types import ModelDisposition
from .tenant_dump_verification import verify_projection_database


@dataclass(frozen=True)
class TenantDumpBuildResult:
    database_dump: Path
    mapped_raw_sha256: str
    sequence_state: dict
    used_two_pass: bool


def build_tenant_dump(
    projection, destination, *, run_id, source_pii_mode, database=None
):
    """Build one target-compatible dump exclusively from a frozen D1 projection."""
    makerspace_id = int(projection.makerspace_id)
    operation_id = UUID(str(run_id))
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    validate_catalog()
    validate_raw_column_allowlists()
    if projection.user_closure is None:
        raise TenantDumpVerificationError(
            "The Lane D projection lacks its immutable-image user closure."
        )
    expected_digest = mapped_raw_digest(projection.rows)
    mapped_identities = _mapped_identities(projection.rows)
    models = _portable_models()
    used_two_pass = False

    with tempfile.TemporaryDirectory(
        prefix=".spaceworks-tenant-dump-", dir=destination.parent
    ) as temporary:
        candidate = Path(temporary, "database.dump")
        with migrated_scratch_database(
            makerspace_id, run_id, database=database
        ) as (using, database_name):
            validate_unowned_tables(connections[using].introspection.table_names())
            with transaction.atomic(using=using), no_decrypt_guard():
                with connections[using].cursor() as cursor:
                    cursor.execute("SET LOCAL app.allow_immutable_delete = 'on'")
                delete_portable_rows(using, makerspace_id, models)
                verify_tables_empty(using, {"spaceworks_cache"})
                source_rows = {
                    label: tuple(rows) for label, rows in projection.rows.items()
                }
                machine_type_model = apps.get_model("machines.MachineType")
                resolved_pks, custom_types = resolve_machine_types(
                    using,
                    source_rows.get("machines.MachineType", ()),
                    machine_type_model,
                )
                source_rows["machines.MachineType"] = custom_types
                sanitized = _sanitize_rows(source_rows, makerspace_id)
                roots, remainder = _split_bootstrap_roots(sanitized)
                root_plan = plan_row_load(roots, resolved_pks=resolved_pks)
                if root_plan.used_two_pass:
                    raise TenantDumpVerificationError(
                        "User/makerspace bootstrap unexpectedly requires a nullable cycle."
                    )
                insert_rows(using, root_plan.rows)
                insert_closed_tenant_fence(using, makerspace_id, operation_id)
                role_ids = seed_default_roles(using, makerspace_id)
                remainder = _remap_member_roles(remainder, role_ids["member"])
                plan = plan_row_load(remainder, resolved_pks=resolved_pks)
                insert_rows(using, plan.rows)
                apply_deferred_foreign_keys(
                    using,
                    plan.deferred_foreign_keys,
                    {row.identity: row for row in plan.rows},
                )
                used_two_pass = plan.used_two_pass
                empty_source_disposition_tables(using)
                serialize_open_tenant_fence(using, makerspace_id, operation_id)
                sequence_state = normalize_sequences(using)
                final_rows = _final_rows(
                    (*root_plan.rows, *plan.rows), plan.deferred_foreign_keys
                )
                verify_ciphertext_aad_identities(
                    projection.rows,
                    final_rows,
                    makerspace_id,
                    mode=source_pii_mode,
                )
                projected_digest = projected_raw_digest(final_rows)
                projected_identities = {
                    label: tuple(row[apps.get_model(label)._meta.pk.attname] for row in rows)
                    for label, rows in final_rows.items()
                }
            verify_projection_database(
                using,
                makerspace_id,
                expected_mapped_digest=expected_digest,
                mapped_identities=mapped_identities,
                expected_projected_digest=projected_digest,
                projected_identities=projected_identities,
                expected_sequence_state=sequence_state,
                capture_id=run_id,
                expected_user_closure_digest=projection.user_closure.digest,
            )
            # Keep this adjacent to pg_dump: future verification code cannot make
            # runtime cache state accidentally portable.
            verify_tables_empty(using, {"spaceworks_cache"})
            verify_source_disposition_tables_empty(using)
            dump_scratch_database(database_name, candidate, database=database)

        with empty_verification_database(
            makerspace_id, run_id, database=database
        ) as (using, database_name):
            restore_scratch_dump(candidate, database_name, database=database)
            restored_digest = verify_projection_database(
                using,
                makerspace_id,
                expected_mapped_digest=expected_digest,
                mapped_identities=mapped_identities,
                expected_projected_digest=projected_digest,
                projected_identities=projected_identities,
                expected_sequence_state=sequence_state,
                capture_id=run_id,
                expected_user_closure_digest=projection.user_closure.digest,
            )
            if restored_digest != expected_digest:
                raise TenantDumpVerificationError(
                    "The custom dump changed a mapped raw value."
                )
        if not candidate.is_file() or candidate.stat().st_size <= 0:
            raise TenantDumpVerificationError("The verified Lane D database dump is empty.")
        candidate.chmod(0o600)
        os.replace(candidate, destination)
    return TenantDumpBuildResult(
        database_dump=destination,
        mapped_raw_sha256=expected_digest,
        sequence_state=sequence_state,
        used_two_pass=used_two_pass,
    )


def _portable_models():
    return tuple(
        apps.get_model(label)
        for label in DATASET_SPECS
        if FIRST_PARTY_MODEL_RULES[label].disposition
        in {ModelDisposition.PROJECT, ModelDisposition.PRESERVE_LIVE}
    )


def _sanitize_rows(rows_by_label, makerspace_id):
    result = []
    for label, rows in sorted(rows_by_label.items()):
        rule = FIRST_PARTY_MODEL_RULES[label]
        if rule.disposition not in {
            ModelDisposition.PROJECT,
            ModelDisposition.PRESERVE_LIVE,
        }:
            continue
        model = apps.get_model(label)
        result.extend(
            _apply_contextual_dispositions(
                sanitize_record(model, row), row, makerspace_id
            )
            for row in rows
        )
    return result


def _apply_contextual_dispositions(row, source, makerspace_id):
    """Apply row-context rules whose result cannot be a table-wide field label."""
    values = dict(row.values)
    label = row.model._meta.label
    values = project_cross_tenant_values(
        row.model, values, source, makerspace_id
    )
    if label == "events.EventRegistration":
        # Search generations and their blind-index rows are target-derived and empty
        # in the scratch bootstrap; ciphertext itself remains byte-identical.
        values[row.model._meta.get_field("email_exact_hash").column] = None
        values[row.model._meta.get_field("email_hash_generation").column] = None
    return SanitizedRow(row.model, row.source_pk, values)


def _split_bootstrap_roots(rows):
    root_labels = {"accounts.User", "makerspaces.Makerspace"}
    return (
        [row for row in rows if row.model._meta.label in root_labels],
        [row for row in rows if row.model._meta.label not in root_labels],
    )


def _remap_member_roles(rows, member_role_id):
    result = []
    labels = {"makerspaces.MakerspaceMembership", "makerspaces.MembershipRequest"}
    for row in rows:
        if row.model._meta.label not in labels:
            result.append(row)
            continue
        field = row.model._meta.get_field("assigned_role")
        values = dict(row.values)
        values[field.column] = member_role_id
        result.append(SanitizedRow(row.model, row.source_pk, values))
    return result


def _mapped_identities(rows_by_label):
    result = {}
    for label, rows in rows_by_label.items():
        model = apps.get_model(label)
        from apps.encryption.registry import fields_for

        if fields_for(model):
            result[label] = tuple(row[model._meta.pk.attname] for row in rows)
    return result


def _final_rows(rows, deferred):
    by_identity = {row.identity: row for row in rows}
    final_values = {identity: dict(row.values) for identity, row in by_identity.items()}
    for update in deferred:
        final_values[update.identity][update.column] = update.value
    result = {}
    for identity, row in by_identity.items():
        record = {
            field.attname: final_values[identity][field.column]
            for field in row.model._meta.concrete_fields
        }
        result.setdefault(row.model._meta.label, []).append(record)
    return {label: tuple(values) for label, values in result.items()}
