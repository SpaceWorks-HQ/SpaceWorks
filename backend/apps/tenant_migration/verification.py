"""Pre-commit, database-only verification for tenant materialization."""

from django.apps import apps
from django.db.models import Count

from apps.accounts.models import User
from apps.encryption import services
from apps.encryption.blind_index import active_generation
from apps.encryption.crypto import decrypt_with_key_loader
from apps.encryption.models import PiiBlindIndex
from apps.encryption.registry import all_fields
from apps.makerspaces.models import MakerspaceMembership

from .blind_indexes import verify_event_hashes
from .insertion_errors import ImportVerificationError, PrimaryKeyMapUnavailable
from .identity_resolution import linked_authority_fingerprint
from .references import (
    AUDIT_TARGET_DISPOSITIONS,
    DISCRIMINATOR_REFERENCES,
    PAYMENT_SUBJECT_REFERENCES,
    normalize_audit_target_type,
)
from .audit_references import AuditReferenceDisposition
from .semantic_remap import _remap_notification_url


def verify_materialization(
    *, archive, models, target, job, pk_map, references, accounting,
    identity_report, regenerated_fields,
):
    _verify_counts(archive, models, references, accounting, pk_map)
    _verify_reference_remaps(archive, models, pk_map)
    _verify_mapped_round_trips(target)
    _verify_blind_index_generation(target)
    verify_event_hashes(target)
    _verify_external_references(archive, target, job)
    _verify_regenerated_unique(regenerated_fields)
    _verify_authority(target, job, pk_map, identity_report)


def _verify_counts(archive, models, references, accounting, pk_map):
    for model in models:
        label = model._meta.label
        if label == "accounts.User":
            continue
        archived = sum(1 for _row in archive.rows(label))
        expected = (
            accounting.imported.get(label, 0)
            + accounting.resolved.get(label, 0)
            + accounting.dropped.get(label, 0)
        )
        if archived != expected:
            raise ImportVerificationError(
                f"Disposition count mismatch for {label}: archive={archived}, expected={expected}."
            )
        mapped = accounting.imported.get(label, 0) + accounting.resolved.get(label, 0)
        if pk_map.count(model) != mapped or pk_map.existing_target_count(model) != mapped:
            raise ImportVerificationError(
                f"Materialized row count mismatch for {label}."
            )


def _verify_mapped_round_trips(target):
    for mapped in all_fields():
        model = apps.get_model(mapped.model_label)
        tenant_lookup = mapped.makerspace_path.replace(".", "__")
        field = model._meta.get_field(mapped.field_name)
        rows = model.objects.filter(**{tenant_lookup: target.pk}).only(
            model._meta.pk.name, mapped.field_name
        )
        for instance in rows.iterator(chunk_size=500):
            envelope = instance.__dict__.get(field.attname)
            if not envelope:
                continue
            try:
                decrypt_with_key_loader(
                    envelope,
                    makerspace_id=target.pk,
                    table=model._meta.db_table,
                    pk=instance.pk,
                    field=mapped.field_name,
                    load_dek=lambda version: services.get_dek(target.pk, version),
                )
            except Exception as exc:
                raise ImportVerificationError(
                    f"Mapped value is unreadable for {mapped.model_label}.{mapped.field_name}."
                ) from exc


def _verify_blind_index_generation(target):
    generation = active_generation()
    invalid = PiiBlindIndex.objects.filter(makerspace=target).exclude(
        search_generation=generation
    )
    if invalid.exists():
        raise ImportVerificationError(
            "An imported blind-index row does not use the active generation."
        )
    expected = 0
    for mapped in all_fields():
        if mapped.index_kind not in {"bloom", "bloom_exact"}:
            continue
        model = apps.get_model(mapped.model_label)
        lookup = mapped.makerspace_path.replace(".", "__")
        expected += model.objects.filter(
            **{lookup: target.pk}, **{f"{mapped.field_name}__isnull": False}
        ).exclude(**{mapped.field_name: ""}).count()
    if PiiBlindIndex.objects.filter(makerspace=target).count() != expected:
        raise ImportVerificationError("Imported blind-index row count is invalid.")


def _verify_external_references(archive, target, job):
    expected = sum(
        1 for _row in archive.json_lines("migration/external_references.jsonl")
    )
    actual = target.external_tenant_references.filter(
        source_archive_digest=job.source_archive_digest
    ).count()
    if actual != expected:
        raise ImportVerificationError("External reference materialization is incomplete.")


def _verify_regenerated_unique(regenerated_fields):
    for model, field_name in regenerated_fields:
        duplicate = (
            model._base_manager.values(field_name)
            .order_by()
            .annotate(total=Count("pk"))
            .filter(total__gt=1)
            .exists()
        )
        if duplicate:
            raise ImportVerificationError(
                f"Regenerated value is not unique for {model._meta.label}.{field_name}."
            )


def _verify_authority(target, job, pk_map, identity_report):
    member_role = target.roles.get(slug="member")
    memberships = MakerspaceMembership.objects.filter(makerspace=target)
    if memberships.exclude(
        assigned_role=member_role,
        role=MakerspaceMembership.Role.CUSTOM,
    ).exists():
        raise ImportVerificationError("The import conferred authority beyond Member.")
    for decision in job.identity_decisions.iterator(chunk_size=500):
        try:
            target_id = pk_map.lookup(User, decision.source_user_id)
        except PrimaryKeyMapUnavailable:
            continue
        user = User.objects.get(pk=target_id)
        if decision.identity_resolution == decision.IdentityResolution.CREATE_WALK_IN:
            if user.is_superuser or user.is_staff or user.role != User.Role.REQUESTER:
                raise ImportVerificationError("An imported walk-in has global authority.")
    if (
        linked_authority_fingerprint(job, pk_map)
        != identity_report.linked_global_state_fingerprint
    ):
        raise ImportVerificationError(
            "The import mutated a linked identity's target-global authority."
        )


def _verify_reference_remaps(archive, models, pk_map):
    for model in models:
        label = model._meta.label
        user_fields = [
            field
            for field in model._meta.local_concrete_fields
            if field.is_relation
            and field.related_model is not None
            and field.related_model._meta.label == "accounts.User"
        ]
        semantic_fields = _semantic_field_names(label)
        if not user_fields and not semantic_fields:
            continue
        for source in archive.rows(label):
            try:
                target_pk = pk_map.lookup(model, source[model._meta.pk.attname])
            except PrimaryKeyMapUnavailable:
                continue
            names = [field.attname for field in user_fields] + semantic_fields
            actual = model._base_manager.values(*names).get(pk=target_pk)
            for field in user_fields:
                source_id = source[field.attname]
                expected = None
                if source_id and label not in {
                    "audit.AuditLog",
                    "makerspaces.Makerspace",
                }:
                    expected = pk_map.lookup(User, source_id)
                if actual[field.attname] != expected:
                    raise ImportVerificationError(
                        f"User reference was not remapped for {label}.{field.name}."
                    )
            _verify_semantic_row(label, source, actual, pk_map)


def _semantic_field_names(label):
    names = []
    if any(edge[0] == label for edge in DISCRIMINATOR_REFERENCES):
        names.extend(("target_type", "target_id"))
    if label == "payments.Payment":
        names.extend(("subject_type", "subject_id"))
    elif label == "machines.ServiceRequestFile":
        names.append("owner_user_id")
    elif label == "audit.AuditLog":
        names.extend(("target_type", "target_id"))
    elif label == "notifications.Notification":
        names.append("url_path")
    return list(dict.fromkeys(names))


def _verify_semantic_row(label, source, actual, pk_map):
    edge = (label, "target_type", "target_id")
    if edge in DISCRIMINATOR_REFERENCES:
        target_label = DISCRIMINATOR_REFERENCES[edge][source["target_type"]]
        expected = pk_map.lookup(apps.get_model(target_label), source["target_id"])
        if str(actual["target_id"]) != str(expected):
            raise ImportVerificationError(f"Discriminator reference is invalid for {label}.")
    if label == "payments.Payment":
        target_label = PAYMENT_SUBJECT_REFERENCES[source["subject_type"]]
        expected = pk_map.lookup(apps.get_model(target_label), source["subject_id"])
        if actual["subject_id"] != expected:
            raise ImportVerificationError("A payment subject reference is invalid.")
    elif label == "machines.ServiceRequestFile" and source["owner_user_id"]:
        expected = pk_map.lookup(User, source["owner_user_id"])
        if actual["owner_user_id"] != expected:
            raise ImportVerificationError("A raw user reference is unresolved.")
    elif label == "audit.AuditLog" and source["target_id"]:
        disposition = AUDIT_TARGET_DISPOSITIONS.get(
            normalize_audit_target_type(source["target_type"])
        )
        if disposition and disposition.disposition is AuditReferenceDisposition.REMAP:
            expected = pk_map.lookup(
                apps.get_model(disposition.target_model_label), source["target_id"]
            )
            if str(actual["target_id"]) != str(expected):
                raise ImportVerificationError("An audit target reference is invalid.")
    elif label == "notifications.Notification":
        expected = _remap_notification_url(source["url_path"], pk_map)
        if actual["url_path"] != expected:
            raise ImportVerificationError("A notification URL reference is invalid.")
