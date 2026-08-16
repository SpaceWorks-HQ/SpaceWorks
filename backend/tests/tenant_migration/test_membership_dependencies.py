import pytest
from django.apps import apps

from apps.tenant_migration.membership_dependencies import (
    MEMBERSHIP_DEPENDENT_MODELS,
)


def _scan_non_null_membership_dependents():
    membership = apps.get_model("makerspaces.MakerspaceMembership")
    return {
        model._meta.label
        for model in apps.get_models()
        for field in model._meta.get_fields()
        if field.concrete
        and field.is_relation
        and field.related_model is membership
        and not field.null
    }


def _assert_complete_registry(declared):
    scanned = _scan_non_null_membership_dependents()
    assert set(declared) == scanned, (
        f"membership-dependent model registry drifted; "
        f"missing={sorted(scanned - set(declared))}, "
        f"extra={sorted(set(declared) - scanned)}"
    )


def test_every_non_null_membership_dependent_is_classified():
    _assert_complete_registry(MEMBERSHIP_DEPENDENT_MODELS)


def test_membership_dependency_guard_detects_a_removed_declaration():
    incomplete = dict(MEMBERSHIP_DEPENDENT_MODELS)
    incomplete.pop("presence.PresenceSession")

    with pytest.raises(AssertionError, match="presence.PresenceSession"):
        _assert_complete_registry(incomplete)
