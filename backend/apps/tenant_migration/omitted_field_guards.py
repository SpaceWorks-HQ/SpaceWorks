"""Totality and column-legality guards for omitted-field reconstruction."""

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import models

from apps.data_export.datasets import DATASETS
from apps.data_export.fields import ALWAYS_OMITTED
from apps.data_export.types import Fidelity

from .omitted_fields import (
    OMITTED_FIELD_RECONSTRUCTIONS,
    OmittedFieldDisposition,
)


class OmittedFieldRegistryError(AssertionError):
    pass


def portable_omitted_fields():
    """Return ALWAYS_OMITTED entries belonging to an actual PORTABLE dataset."""
    portable_models = {
        dataset.model
        for (fidelity, _path), dataset in DATASETS.items()
        if fidelity is Fidelity.PORTABLE
    }
    return {
        pair for pair in ALWAYS_OMITTED if pair[0] in portable_models
    }


def field_is_globally_unique(field):
    """Whether one field has an unconditional database uniqueness guarantee."""
    if field.unique:
        return True
    return any(
        isinstance(constraint, models.UniqueConstraint)
        and not constraint.condition
        and not constraint.expressions
        and tuple(constraint.fields) == (field.name,)
        for constraint in field.model._meta.constraints
    )


def validate_omitted_field_reconstructions(
    declarations=OMITTED_FIELD_RECONSTRUCTIONS,
):
    expected = portable_omitted_fields()
    declared = set(declarations)
    if declared != expected:
        raise OmittedFieldRegistryError(
            "portable omitted-field reconstruction registry drifted; "
            f"missing={sorted(expected - declared)}, "
            f"extra={sorted(declared - expected)}"
        )

    for (model_label, field_name), disposition in declarations.items():
        if not isinstance(disposition, OmittedFieldDisposition):
            raise OmittedFieldRegistryError(
                f"{model_label}.{field_name} has an unknown reconstruction disposition"
            )
        field = apps.get_model(model_label)._meta.get_field(field_name)
        _validate_column_rule(field, disposition)


def _validate_column_rule(field, disposition):
    label = f"{field.model._meta.label}.{field.name}"
    unique = field_is_globally_unique(field)

    if (
        field.null
        and unique
        and disposition
        not in {
            OmittedFieldDisposition.NULL,
            OmittedFieldDisposition.DROP_ROW,
            OmittedFieldDisposition.EMPTY_STRING,
            OmittedFieldDisposition.QUARANTINE,
        }
    ):
        raise OmittedFieldRegistryError(
            f"{label} is nullable and globally unique, so it must reconstruct to NULL"
        )

    if disposition is OmittedFieldDisposition.NULL:
        if not field.null:
            raise OmittedFieldRegistryError(f"{label} is NOT NULL")
        return

    if disposition is OmittedFieldDisposition.EMPTY_STRING:
        if not isinstance(field, (models.CharField, models.TextField)):
            raise OmittedFieldRegistryError(f"{label} is not a string column")
        if field.null:
            qualifier = "nullable and globally unique" if unique else "nullable"
            raise OmittedFieldRegistryError(
                f"{label} is {qualifier} and must reconstruct to NULL"
            )
        if unique:
            raise OmittedFieldRegistryError(
                f"{label} is unique and cannot share an empty-string sentinel"
            )
        return

    if disposition is OmittedFieldDisposition.FRESH:
        if not unique:
            raise OmittedFieldRegistryError(
                f"{label} has no unconditional uniqueness guarantee"
            )
        if not field.has_default() or not callable(field.default):
            raise OmittedFieldRegistryError(
                f"{label} has no callable source for a fresh value"
            )
        try:
            field.clean(field.get_default(), field.model())
        except (TypeError, ValueError, ValidationError) as exc:
            raise OmittedFieldRegistryError(
                f"{label} callable default does not produce a legal column value"
            ) from exc
        return

    # DROP_ROW and QUARANTINE do not write the omitted column. DERIVED values are
    # supplied by their target-owned derivation, whose implementation belongs to the
    # importer rather than this declaration-only step.
