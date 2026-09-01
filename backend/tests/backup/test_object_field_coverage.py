"""The object-capture drift guard.

`archive_payload.OBJECT_FIELD_NAMES` is a hand-written set of six field names and is
the ONLY thing deciding which object-storage bytes a backup captures. Nothing
regenerates it, and it has already drifted once: `logo_key` was missing, so backups
captured the database value but not the image, and a restore left
`Makerspace.logo_key` pointing at an object that had never been captured. The row
comes back, the file does not, and nothing fails at restore time -- the image is
simply gone.

This guard makes that class of mistake loud. Every concrete `*_key` field in the
schema must be classified as exactly one of:

  * captured   -- its name is in OBJECT_FIELD_NAMES, so the capture loop collects it;
  * not an object pointer -- its (label, field) pair is in NON_OBJECT_KEY_FIELDS.

A newly added `*_key` field is in neither, so this test fails and the author has to
decide which it is. That is the same deny-by-default shape the export registry uses
in `apps/data_export/guards.py`.
"""

import pytest
from django.apps import apps

from apps.backup.archive_payload import NON_OBJECT_KEY_FIELDS, OBJECT_FIELD_NAMES


def _key_fields():
    """Every concrete field whose name ends in `_key`, as (label, field name)."""
    for model in apps.get_models(include_auto_created=True):
        for field in model._meta.concrete_fields:
            if field.name.endswith("_key"):
                yield model._meta.label, field.name


def test_every_key_field_is_classified():
    unclassified = sorted(
        (label, name)
        for label, name in _key_fields()
        if name not in OBJECT_FIELD_NAMES and (label, name) not in NON_OBJECT_KEY_FIELDS
    )
    assert not unclassified, (
        "These `*_key` fields are classified neither as captured object pointers "
        "(add the field name to archive_payload.OBJECT_FIELD_NAMES) nor as "
        "non-object keys (add the (label, field) pair to "
        f"archive_payload.NON_OBJECT_KEY_FIELDS, with a reason): {unclassified}. "
        "An object pointer left out of OBJECT_FIELD_NAMES restores as a database "
        "row whose file was never captured."
    )


def test_classification_sets_do_not_overlap():
    # A pair in both sets is ambiguous: the capture loop keys on the bare field name,
    # so the NON_OBJECT entry would be silently ineffective and read as a decision
    # that was never actually applied.
    overlap = sorted(
        (label, name)
        for label, name in NON_OBJECT_KEY_FIELDS
        if name in OBJECT_FIELD_NAMES
    )
    assert not overlap, (
        "These pairs are in NON_OBJECT_KEY_FIELDS while their field name is also in "
        f"OBJECT_FIELD_NAMES, so the exemption has no effect: {overlap}."
    )


def test_non_object_entries_still_exist_in_the_schema():
    # A stale exemption hides a real field: if the model is renamed and the exemption
    # is not, the replacement field arrives unclassified but the reader sees an entry
    # that looks like it covers it.
    live = set(_key_fields())
    stale = sorted(pair for pair in NON_OBJECT_KEY_FIELDS if pair not in live)
    assert not stale, (
        f"These NON_OBJECT_KEY_FIELDS entries no longer exist in the schema: {stale}. "
        "Remove them so the set keeps describing the real model graph."
    )


@pytest.mark.parametrize("field_name", sorted(OBJECT_FIELD_NAMES))
def test_every_captured_field_name_is_used_by_some_model(field_name):
    # The reverse direction: a captured name nothing declares is dead configuration,
    # and dead entries make the set harder to audit for the missing ones that matter.
    labels = [label for label, name in _key_fields() if name == field_name]
    assert labels, (
        f"OBJECT_FIELD_NAMES contains {field_name!r} but no model declares it."
    )
