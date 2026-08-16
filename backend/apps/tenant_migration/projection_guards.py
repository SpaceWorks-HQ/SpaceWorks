"""Model-graph and uniqueness drift guards for the target projection."""

from dataclasses import dataclass

from django.apps import apps
from django.db import models

from apps.data_export.models import EXPORTED_MODELS

from .target_projection import (
    DROPPED_NOTIFICATION_RECIPIENT_KINDS,
    FK_POLICIES,
    ROW_POLICIES,
    SEEDED_RESOLUTIONS,
    UNIQUE_COLLISION_MODEL_REASONS,
    ReferenceDisposition,
    RowDisposition,
)


class ProjectionRegistryError(AssertionError):
    pass


REFERENCE_TARGET_MODELS = frozenset(
    set(SEEDED_RESOLUTIONS)
    | {
        label
        for label, policy in ROW_POLICIES.items()
        if policy.disposition in {RowDisposition.DROP, RowDisposition.KEEP_TARGET}
    }
)


UNIQUE_COLLISION_MODELS = frozenset(UNIQUE_COLLISION_MODEL_REASONS)


@dataclass(frozen=True, order=True)
class UniqueConstraintRisk:
    model_label: str
    constraint_name: str


def discover_projection_fk_edges():
    """Return exported concrete FKs into every resolved/dropped model."""
    edges = set()
    for source_label in EXPORTED_MODELS:
        model = apps.get_model(source_label)
        for field in model._meta.get_fields():
            if not (
                field.concrete
                and field.is_relation
                and field.related_model is not None
                and not field.many_to_many
            ):
                continue
            if field.related_model._meta.label in REFERENCE_TARGET_MODELS:
                edges.add((source_label, field.name))
    return frozenset(edges)


def validate_projection_fk_registry(declarations=FK_POLICIES):
    actual = discover_projection_fk_edges()
    declared = set(declarations)
    if declared != set(actual):
        raise ProjectionRegistryError(
            "projection FK registry drifted; "
            f"missing={sorted(actual - declared)}, extra={sorted(declared - actual)}"
        )
    for edge, policy in declarations.items():
        field = apps.get_model(edge[0])._meta.get_field(edge[1])
        target = field.related_model._meta.label
        if target not in REFERENCE_TARGET_MODELS:
            raise ProjectionRegistryError(f"{edge} no longer targets a governed model")
        if not field.null and target == "makerspaces.MakerspaceRole":
            if policy.disposition not in {
                ReferenceDisposition.DROP_ROW,
                ReferenceDisposition.REMAP_TARGET_MEMBER,
            }:
                raise ProjectionRegistryError(
                    f"non-null dropped-role dependent {edge} has no safe disposition"
                )


def non_null_role_dependents():
    role = apps.get_model("makerspaces.MakerspaceRole")
    return frozenset(
        (label, field.name)
        for label in EXPORTED_MODELS
        for field in apps.get_model(label)._meta.get_fields()
        if field.concrete
        and field.is_relation
        and field.related_model is role
        and not field.null
    )


def discover_unique_constraint_risks():
    """Introspect every named uniqueness rule on rows that resolve or can collide.

    The model list is the reviewed semantic boundary; constraint names are deliberately
    obtained from Django metadata so conditional/expression constraints are not
    reimplemented incorrectly here.
    """
    risks = set()
    for label in UNIQUE_COLLISION_MODELS:
        model = apps.get_model(label)
        for constraint in model._meta.constraints:
            if isinstance(constraint, models.UniqueConstraint):
                risks.add(UniqueConstraintRisk(label, constraint.name))
        for fields in model._meta.unique_together:
            risks.add(UniqueConstraintRisk(label, "unique_together:" + ",".join(fields)))
    return frozenset(risks)


DECLARED_UNIQUE_CONSTRAINT_RISKS = discover_unique_constraint_risks()


def validate_unique_constraint_risks(declarations=DECLARED_UNIQUE_CONSTRAINT_RISKS):
    actual = discover_unique_constraint_risks()
    declared = set(declarations)
    if declared != set(actual):
        raise ProjectionRegistryError(
            "resolved-row uniqueness registry drifted; "
            f"missing={sorted(actual - declared)}, extra={sorted(declared - actual)}"
        )


def validate_notification_recipient_kinds(declarations=DROPPED_NOTIFICATION_RECIPIENT_KINDS):
    recipient = apps.get_model("integrations.NotificationRecipient")
    actual = {value for value, _label in recipient._meta.get_field("kind").choices}
    if set(declarations) != actual:
        raise ProjectionRegistryError(
            "notification recipient kind registry drifted; "
            f"missing={sorted(actual - set(declarations))}, "
            f"extra={sorted(set(declarations) - actual)}"
        )


def validate_projection_registry():
    validate_projection_fk_registry()
    validate_unique_constraint_risks()
    validate_notification_recipient_kinds()
