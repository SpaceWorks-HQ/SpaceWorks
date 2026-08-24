"""Lane E section 11 row 6: data-export model and user-edge totality."""

from types import SimpleNamespace

import pytest
from django.apps import apps

from apps.data_export import guards
from apps.data_export.fields import FIELDS
from apps.data_export.guards import RegistryError
from apps.data_export.references import RELATIONAL_USER_FIELDS, USER_EDGES


def test_new_internal_model_fails_until_model_classification_exists(monkeypatch):
    existing = guards.internal_models()
    unclassified = SimpleNamespace(
        _meta=SimpleNamespace(label="e10.UnclassifiedModel")
    )
    monkeypatch.setattr(
        guards, "internal_models", lambda: (*existing, unclassified)
    )

    with pytest.raises(RegistryError, match="model dispositions"):
        guards.validate_model_and_field_coverage(FIELDS)


@pytest.mark.parametrize(
    ("model_label", "field_name"), sorted(RELATIONAL_USER_FIELDS)
)
def test_each_current_user_fk_or_o2o_edge_fails_independently_when_unclassified(
    model_label, field_name
):
    changed = {
        key: value
        for key, value in USER_EDGES.items()
        if key[1:] != (model_label, field_name)
    }

    with pytest.raises(RegistryError, match="user-edge decisions"):
        guards.validate_user_edges(changed)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "SPEC BUG: data_export.validate_user_edges ignores concrete=False "
        "ManyToManyField edges to accounts.User"
    ),
)
def test_new_many_to_many_user_edge_fails_until_classified(monkeypatch):
    user = apps.get_model("accounts.User")
    m2m = SimpleNamespace(
        name="watchers",
        concrete=False,
        many_to_many=True,
        is_relation=True,
        related_model=user,
    )
    synthetic = SimpleNamespace(
        _meta=SimpleNamespace(
            label="e10.UnclassifiedM2M",
            get_fields=lambda: (m2m,),
        )
    )
    existing = guards.internal_models()
    monkeypatch.setattr(
        guards, "internal_models", lambda: (*existing, synthetic)
    )

    with pytest.raises(RegistryError, match="user-edge decisions"):
        guards.validate_user_edges(USER_EDGES)
