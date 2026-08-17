"""Apply the declared row, omission, and seeded-resolution dispositions."""

from dataclasses import dataclass, field

from django.apps import apps

from .omitted_fields import OMITTED_FIELD_RECONSTRUCTIONS, OmittedFieldDisposition
from .closure_references import (
    CROSS_TENANT_DEPENDENT_REFERENCES,
    MOVABLE_DISCRIMINATOR_REFERENCES,
    MOVABLE_ROW_REFERENCES,
    MissingReferenceDisposition,
)
from .row_conditions import condition_matches
from .target_projection import ROW_POLICIES, RowDisposition, SEEDED_RESOLUTIONS


@dataclass
class ImportAccounting:
    imported: dict[str, int] = field(default_factory=dict)
    resolved: dict[str, int] = field(default_factory=dict)
    dropped: dict[str, int] = field(default_factory=dict)
    preserved: dict[tuple[str, str], int] = field(default_factory=dict)
    regenerated: dict[tuple[str, str], int] = field(default_factory=dict)

    def increment(self, bucket, label, amount=1):
        values = getattr(self, bucket)
        values[label] = values.get(label, 0) + amount

    def increment_field(self, bucket, label, field_name, amount=1):
        values = getattr(self, bucket)
        key = (label, field_name)
        values[key] = values.get(key, 0) + amount
        other = self.regenerated if bucket == "preserved" else self.preserved
        other.setdefault(key, 0)


def row_disposition(model_label, row, references):
    policy = ROW_POLICIES.get(model_label)
    if policy is not None and condition_matches(policy.condition, row):
        if policy.disposition is RowDisposition.KEEP_TARGET:
            return "resolve"
        if policy.disposition is RowDisposition.DROP:
            return "drop"

    # This omitted credential applies only to webhook destinations. Other channel
    # rows legally reconstruct the irrelevant column as an empty string.
    if model_label == "integrations.NotificationDestination":
        if row.get("channel") == "webhook":
            return "drop"
    elif any(
        label == model_label and disposition is OmittedFieldDisposition.DROP_ROW
        for (label, _field), disposition in OMITTED_FIELD_RECONSTRUCTIONS.items()
    ):
        return "drop"

    for (label, field_name), rule in MOVABLE_ROW_REFERENCES.items():
        if (
            label == model_label
            and rule.disposition is MissingReferenceDisposition.DROP_WITH_PROVENANCE
            and references.get(model_label, row["id"], field_name)
        ):
            return "drop"
    for edge, typed_rules in MOVABLE_DISCRIMINATOR_REFERENCES.items():
        if edge[0] != model_label:
            continue
        target_type = row.get("target_type", "")
        if target_type.startswith("external_"):
            target_type = target_type.removeprefix("external_")
        rule = typed_rules.get(target_type)
        if (
            rule is not None
            and rule.disposition is MissingReferenceDisposition.DROP_WITH_PROVENANCE
            and references.get(model_label, row["id"], "target_type+target_id")
        ):
            return "drop"
    for (label, field_name), disposition in CROSS_TENANT_DEPENDENT_REFERENCES.items():
        if (
            label == model_label
            and disposition is MissingReferenceDisposition.DROP_WITH_PROVENANCE
            and references.get(model_label, row["id"], field_name)
        ):
            return "drop"

    # Both foreign-collaboration shapes have a non-null FK to a row that is not
    # imported. Their typed snapshot survives separately, anchored where possible.
    if model_label == "events.EventCollaborator" and (
        references.get(model_label, row["id"], "event")
        or references.get(model_label, row["id"], "makerspace")
    ):
        return "drop"
    # An inbound transfer is foreign-owned. It is provenance, not a live transfer.
    if model_label == "operations.StockTransfer" and references.get(
        model_label, row["id"], "source_makerspace"
    ):
        return "drop"
    if model_label == "payments.Payment" and references.get(
        model_label, row["id"], "subject_id"
    ):
        return "drop"
    return "insert"


def preallocate_model(
    model, archive, pk_map, references, target, accounting, job, required_identities
):
    label = model._meta.label
    if label == "makerspaces.Makerspace":
        source = next(archive.rows(label))
        pk_map.add_many(model, [(source["id"], target.pk)])
        accounting.increment("resolved", label)
        return
    if label == "accounts.User":
        return

    source_ids = []
    for row in archive.rows(label):
        if label == "makerspaces.MakerspaceMembership":
            from .identity_resolution import decision_for_source_user

            decision = decision_for_source_user(job, row["user_id"])
            if decision.membership_disposition == decision.MembershipDisposition.NO_MEMBERSHIP:
                accounting.increment("dropped", label)
                continue
        disposition = row_disposition(label, row, references)
        if disposition == "drop":
            accounting.increment("dropped", label)
            continue
        required_identities.add_row(model, row)
        resolved_pk = _seeded_target_pk(label, row, target)
        if resolved_pk is not None:
            pk_map.add_many(model, [(row["id"], resolved_pk)])
            accounting.increment("resolved", label)
        elif disposition == "resolve":
            accounting.increment("dropped", label)
        else:
            source_ids.append(row["id"])
            if len(source_ids) == 1_000:
                pk_map.reserve(model, source_ids)
                source_ids.clear()
    if source_ids:
        pk_map.reserve(model, source_ids)
    required_identities.flush()


def _seeded_target_pk(label, row, target):
    if label == "makerspaces.MakerspaceRole":
        match = target.roles.filter(slug=row["slug"]).first()
        return match.pk if match else None
    resolution = SEEDED_RESOLUTIONS.get(label)
    if resolution is None:
        return None
    model = apps.get_model(label)
    lookup = {name: row[name] for name in resolution.lookup_fields}
    if label == "inventory.Category":
        lookup["makerspace_id"] = target.pk
    elif label == "machines.MachineType":
        # Only source-global built-ins resolve to target-global definitions.
        if row.get("makerspace") or row.get("makerspace_id"):
            return None
        lookup["makerspace_id"] = None
    match = model.objects.filter(**lookup).first()
    if match is None:
        return None
    for name in resolution.definition_fingerprint_fields:
        field = model._meta.get_field(name)
        from .archive_stream import database_value

        if getattr(match, field.attname) != database_value(field, row[field.attname]):
            from .insertion_errors import ArchiveFormatError

            raise ArchiveFormatError(
                f"Seeded definition mismatch for {label} source row {row['id']}."
            )
    return match.pk
