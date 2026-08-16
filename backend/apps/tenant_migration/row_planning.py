"""Construct complete final database rows before their one allowed INSERT."""

from django.apps import apps

from apps.encryption.registry import fields_for

from .archive_stream import database_value
from .event_hashes import event_registration_hash_columns
from .identity_resolution import decision_for_source_user
from .omitted_fields import OMITTED_FIELD_RECONSTRUCTIONS, OmittedFieldDisposition
from .pii_reencryption import reencrypt_mapped_value_with_plaintext
from .insertion_errors import PrimaryKeyMapUnavailable
from .row_dispositions import row_disposition, _seeded_target_pk
from .semantic_remap import remap_semantic_references
from .target_projection import (
    FK_POLICIES,
    SEEDED_RESOLUTIONS,
    TARGET_FIELD_PROJECTION,
    ReferenceDisposition,
)


def final_row(
    model,
    source,
    *,
    job,
    pk_map,
    references,
    target,
    deks,
    fresh_values,
):
    label = model._meta.label
    disposition = row_disposition(label, source, references)
    if disposition in {"drop", "resolve"}:
        return None
    if _seeded_target_pk(label, source, target) is not None:
        return None
    if label == "makerspaces.MakerspaceMembership":
        decision = decision_for_source_user(job, source["user_id"])
        if decision.membership_disposition == decision.MembershipDisposition.NO_MEMBERSHIP:
            return None

    row = {}
    plaintext = {}
    for field in model._meta.local_concrete_fields:
        if field.primary_key:
            value = pk_map.lookup(model, source[field.attname])
        elif field.attname in source:
            value = database_value(field, source[field.attname])
        else:
            value = _reconstructed_value(label, field, fresh_values)
        row[field.column] = value

    _apply_target_fields(label, source, row)
    if not _remap_foreign_keys(model, source, row, job, pk_map, target):
        return None
    _clear_walk_in_waiver_evidence(label, source, row, job)
    if not remap_semantic_references(label, source, row, pk_map, references):
        return None

    for mapped in fields_for(model):
        column = model._meta.get_field(mapped.field_name).column
        source_aad = {
            "makerspace_id": int(job.source_makerspace_id),
            "table": model._meta.db_table,
            "pk": source[model._meta.pk.attname],
            "field": mapped.field_name,
        }
        row[column], raw_plaintext = reencrypt_mapped_value_with_plaintext(
            row[column],
            source_aad=source_aad,
            target_makerspace_id=target.pk,
            target_table=model._meta.db_table,
            target_pk=row[model._meta.pk.column],
            target_field=mapped.field_name,
            deks=deks,
        )
        plaintext[mapped.field_name] = (
            raw_plaintext.decode("utf-8")
            if isinstance(raw_plaintext, bytes)
            else raw_plaintext
        )
    if label == "events.EventRegistration":
        row.update(
            event_registration_hash_columns(
                plaintext.get("email", ""),
                target_makerspace_id=target.pk,
                target_event_id=row[model._meta.get_field("event").column],
            )
        )
    return row


def update_resolved_row(model, source, target):
    resolution = SEEDED_RESOLUTIONS.get(model._meta.label)
    target_pk = _seeded_target_pk(model._meta.label, source, target)
    if resolution is None or target_pk is None or not resolution.archive_update_fields:
        return False
    values = {
        model._meta.get_field(name).attname: database_value(
            model._meta.get_field(name), source[model._meta.get_field(name).attname]
        )
        for name in resolution.archive_update_fields
    }
    model.objects.filter(pk=target_pk).update(**values)
    return True


def _reconstructed_value(label, field, fresh_values):
    disposition = OMITTED_FIELD_RECONSTRUCTIONS[(label, field.name)]
    if disposition is OmittedFieldDisposition.FRESH:
        value = _fresh_unique(field, fresh_values)
    elif disposition is OmittedFieldDisposition.EMPTY_STRING:
        value = ""
    elif disposition is OmittedFieldDisposition.NULL:
        value = None
    elif disposition is OmittedFieldDisposition.DERIVED:
        value = field.get_default() if field.has_default() else None
    elif disposition is OmittedFieldDisposition.DROP_ROW:
        value = ""
    else:
        raise ValueError(f"Unsupported omitted-field disposition for {label}.{field.name}.")
    return value


def _fresh_unique(field, fresh_values):
    key = (field.model._meta.label, field.name)
    current_batch = fresh_values.setdefault(key, set())
    for _attempt in range(16):
        value = field.get_default()
        if value in current_batch:
            continue
        if field.model._base_manager.filter(**{field.name: value}).exists():
            continue
        current_batch.add(value)
        return value
    raise RuntimeError(f"Could not generate a unique value for {key[0]}.{key[1]}.")


def _apply_target_fields(label, source, row):
    for (model_label, name), policy in TARGET_FIELD_PROJECTION.items():
        if model_label != label:
            continue
        if policy.condition and source.get(policy.condition[0]) != str(policy.condition[1]).lower():
            continue
        field = apps.get_model(label)._meta.get_field(name)
        row[field.column] = policy.resolved_value(label, name)


def _remap_foreign_keys(model, source, row, job, pk_map, target):
    for field in model._meta.local_concrete_fields:
        if not field.is_relation or field.related_model is None:
            continue
        source_value = row[field.column]
        if source_value is None:
            continue
        edge_policy = FK_POLICIES.get((model._meta.label, field.name))
        if edge_policy and edge_policy.disposition is ReferenceDisposition.DROP_ROW:
            return False
        if edge_policy and edge_policy.disposition is ReferenceDisposition.REMAP_TARGET_MEMBER:
            row[field.column] = target.roles.get(slug="member").pk
            continue
        if field.related_model._meta.label == "accounts.User":
            row[field.column] = pk_map.lookup(field.related_model, source_value)
        elif field.related_model._meta.label == "encryption.SearchKeyGeneration":
            continue
        elif field.related_model._meta.label == "accounts.MemberClaimCode":
            row[field.column] = None
        else:
            try:
                row[field.column] = pk_map.lookup(field.related_model, source_value)
            except PrimaryKeyMapUnavailable:
                if field.null and model._meta.label == "operations.InventoryAdjustment":
                    row[field.column] = None
                else:
                    raise
    return True


def _clear_walk_in_waiver_evidence(label, source, row, job):
    if label != "makerspaces.MakerspaceMembership":
        return
    decision = decision_for_source_user(job, source["user_id"])
    if decision.identity_resolution != decision.IdentityResolution.CREATE_WALK_IN:
        return
    for name in (
        "waiver_accepted_at", "waiver_version_accepted", "accepted_waiver",
        "witnessed_waiver", "witnessed_waiver_version", "witnessed_by",
        "witnessed_actor_snapshot", "witnessed_at",
    ):
        field = apps.get_model(label)._meta.get_field(name)
        row[field.column] = None
