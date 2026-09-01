import pytest
from django.apps import apps
from django.db import models

from apps.tenant_migration.omitted_field_guards import (
    OmittedFieldRegistryError,
    field_is_globally_unique,
    portable_omitted_fields,
    validate_omitted_field_reconstructions,
)
from apps.tenant_migration.omitted_fields import (
    EMPTY_STRING,
    FRESH,
    NULL,
    OMITTED_FIELD_RECONSTRUCTIONS,
)


def _changed(pair, disposition):
    declarations = dict(OMITTED_FIELD_RECONSTRUCTIONS)
    declarations[pair] = disposition
    return declarations


def test_registry_exactly_covers_portable_omissions():
    assert set(OMITTED_FIELD_RECONSTRUCTIONS) == portable_omitted_fields()
    validate_omitted_field_reconstructions()


def test_registry_guard_rejects_a_removed_declaration():
    declarations = dict(OMITTED_FIELD_RECONSTRUCTIONS)
    declarations.pop(("machines.Machine", "camera_feed_url"))

    with pytest.raises(OmittedFieldRegistryError, match="missing=.*camera_feed_url"):
        validate_omitted_field_reconstructions(declarations)


def test_registry_guard_rejects_a_non_omitted_declaration():
    declarations = _changed(("machines.Machine", "name"), EMPTY_STRING)

    with pytest.raises(OmittedFieldRegistryError, match="extra=.*Machine.*name"):
        validate_omitted_field_reconstructions(declarations)


def test_guard_rejects_empty_string_for_nullable_unique_column():
    declarations = _changed(
        ("payments.MakerspacePaymentSettings", "connect_account_id"),
        EMPTY_STRING,
    )

    with pytest.raises(OmittedFieldRegistryError, match="nullable.*NULL"):
        validate_omitted_field_reconstructions(declarations)


def test_guard_rejects_empty_string_for_integer_column():
    declarations = _changed(
        ("machines.Machine", "legacy_print_printer_id"),
        EMPTY_STRING,
    )

    with pytest.raises(OmittedFieldRegistryError, match="not a string column"):
        validate_omitted_field_reconstructions(declarations)


def test_guard_rejects_null_for_not_null_column():
    declarations = _changed(("machines.Machine", "camera_feed_url"), NULL)

    with pytest.raises(OmittedFieldRegistryError, match="NOT NULL"):
        validate_omitted_field_reconstructions(declarations)


def test_every_fresh_column_is_actually_unique():
    for pair, disposition in OMITTED_FIELD_RECONSTRUCTIONS.items():
        if disposition is FRESH:
            field = apps.get_model(pair[0])._meta.get_field(pair[1])
            assert field_is_globally_unique(field), ".".join(pair)


def test_every_empty_string_column_is_not_null_text():
    for pair, disposition in OMITTED_FIELD_RECONSTRUCTIONS.items():
        if disposition is EMPTY_STRING:
            field = apps.get_model(pair[0])._meta.get_field(pair[1])
            assert not field.null, ".".join(pair)
            assert isinstance(
                field, (models.CharField, models.TextField)
            ), ".".join(pair)
