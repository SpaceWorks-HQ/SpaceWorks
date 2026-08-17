"""Model-graph and uniqueness drift guards for the target projection."""

from dataclasses import dataclass

from django.apps import apps
from django.db import models

from apps.data_export.datasets import DATASET_SPECS
from apps.data_export.models import EXPORTED_MODELS

from .target_projection import (
    DROPPED_NOTIFICATION_RECIPIENT_KINDS,
    FK_POLICIES,
    ROW_POLICIES,
    SEEDED_RESOLUTIONS,
    ReferenceDisposition,
    RowDisposition,
)
from .unique_values import (
    DEPLOYMENT_GLOBAL_UNIQUE_RULES,
    UniqueValueDisposition,
    UniqueValuePolicy,
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


def discover_unique_constraint_risks(
    exported_models=EXPORTED_MODELS, ownership_paths=None
):
    """Return every exported uniqueness rule that is not tenant-scoped."""
    risks = set()
    for item in exported_models:
        model = item if isinstance(item, type) else apps.get_model(item)
        label = model._meta.label
        tenant_roots = _tenant_path_roots(label, ownership_paths)
        for field in model._meta.local_concrete_fields:
            if field.unique and not field.primary_key and field.name not in tenant_roots:
                risks.add(UniqueConstraintRisk(label, f"field:{field.name}"))
        for constraint in model._meta.constraints:
            if (
                isinstance(constraint, models.UniqueConstraint)
                and not (_constraint_fields(constraint) & tenant_roots)
            ):
                risks.add(UniqueConstraintRisk(label, constraint.name))
        for fields in model._meta.unique_together:
            if not (set(fields) & tenant_roots):
                risks.add(
                    UniqueConstraintRisk(
                        label, "unique_together:" + ",".join(fields)
                    )
                )
    return frozenset(risks)


def _tenant_path_roots(label, ownership_paths):
    if ownership_paths is None:
        predicate = DATASET_SPECS[label][1]
        paths = predicate.any_paths + predicate.local_or_global_paths
    else:
        paths = ownership_paths[label]
    # Makerspace itself is deployment-global; its ``pk`` export predicate is only the
    # selector for the one source row, not a tenant column that scopes uniqueness.
    return {
        path.split("__", 1)[0]
        for path in paths
        if path not in {"pk", "id", "closure"}
    }


def _constraint_fields(constraint):
    names = set(constraint.fields)
    pending = list(constraint.expressions)
    while pending:
        expression = pending.pop()
        if isinstance(expression, models.F):
            names.add(expression.name.split("__", 1)[0])
            continue
        getter = getattr(expression, "get_source_expressions", None)
        if getter is not None:
            pending.extend(item for item in getter() if item is not None)
    return names


DECLARED_UNIQUE_CONSTRAINT_RISKS = frozenset(
    UniqueConstraintRisk(*key) for key in DEPLOYMENT_GLOBAL_UNIQUE_RULES
)


def validate_unique_constraint_risks(
    declarations=DEPLOYMENT_GLOBAL_UNIQUE_RULES,
    *,
    exported_models=EXPORTED_MODELS,
    ownership_paths=None,
):
    actual = discover_unique_constraint_risks(exported_models, ownership_paths)
    if isinstance(declarations, dict):
        declared = {UniqueConstraintRisk(*key) for key in declarations}
        for key, policy in declarations.items():
            if not isinstance(policy, UniqueValuePolicy) or not policy.reason:
                raise ProjectionRegistryError(
                    f"deployment-global uniqueness rule {key} has no disposition"
                )
            if policy.disposition is UniqueValueDisposition.PRESERVE_OR_REGENERATE:
                field = apps.get_model(key[0])._meta.get_field(policy.collision_field)
                if policy.generator is None and not (
                    field.has_default() and callable(field.default)
                ):
                    raise ProjectionRegistryError(
                        f"{key} has no callable source for collision regeneration"
                    )
    else:
        declared = set(declarations)
    if declared != set(actual):
        raise ProjectionRegistryError(
            "deployment-global uniqueness registry drifted; "
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
