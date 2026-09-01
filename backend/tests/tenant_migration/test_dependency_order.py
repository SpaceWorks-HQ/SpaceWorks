from types import SimpleNamespace

import pytest
from django.apps import apps

from apps.events.models import Event, EventRegistration
from apps.tenant_migration.dependency_order import (
    exported_models_in_dependency_order,
    topologically_sort_models,
)
from apps.tenant_migration.insertion_errors import DependencyCycleError


def test_derived_order_places_referenced_model_before_referrer():
    labels = [model._meta.label for model in exported_models_in_dependency_order(apps)]
    assert labels.index(Event._meta.label) < labels.index(EventRegistration._meta.label)


def test_synthetic_dependency_cycle_names_every_member():
    first = SimpleNamespace()
    second = SimpleNamespace()
    first._meta = SimpleNamespace(
        label="synthetic.First",
        local_concrete_fields=[
            SimpleNamespace(is_relation=True, related_model=second)
        ],
    )
    second._meta = SimpleNamespace(
        label="synthetic.Second",
        local_concrete_fields=[
            SimpleNamespace(is_relation=True, related_model=first)
        ],
    )

    with pytest.raises(DependencyCycleError) as exc_info:
        topologically_sort_models([first, second])

    assert "synthetic.First" in str(exc_info.value)
    assert "synthetic.Second" in str(exc_info.value)
