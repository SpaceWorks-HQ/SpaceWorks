"""Derive raw insertion order from the live exported model graph."""

from collections import defaultdict

from apps.data_export.models import EXPORTED_MODELS

from .insertion_errors import DependencyCycleError


def concrete_fk_dependencies(models):
    """Return model -> exported concrete FK targets, excluding legitimate self-FKs."""
    by_label = {model._meta.label: model for model in models}
    dependencies = {label: set() for label in by_label}
    for label, model in by_label.items():
        for field in model._meta.local_concrete_fields:
            if not field.is_relation or field.related_model is None:
                continue
            target = field.related_model._meta.label
            if target in by_label and target != label:
                dependencies[label].add(target)
    return dependencies


def topologically_sort_models(models):
    """Place each referenced model before its referrers and name any cycle."""
    by_label = {model._meta.label: model for model in models}
    dependencies = concrete_fk_dependencies(models)
    referrers = defaultdict(set)
    indegree = {}
    for label, targets in dependencies.items():
        indegree[label] = len(targets)
        for target in targets:
            referrers[target].add(label)

    ready = sorted(label for label, count in indegree.items() if count == 0)
    ordered = []
    while ready:
        label = ready.pop(0)
        ordered.append(by_label[label])
        for referrer in sorted(referrers[label]):
            indegree[referrer] -= 1
            if indegree[referrer] == 0:
                ready.append(referrer)
                ready.sort()

    if len(ordered) != len(by_label):
        cycle_members = sorted(label for label, count in indegree.items() if count)
        raise DependencyCycleError(
            "Concrete-FK dependency cycle: " + ", ".join(cycle_members)
        )
    return ordered


def exported_models_in_dependency_order(apps_registry):
    return topologically_sort_models(
        [apps_registry.get_model(label) for label in EXPORTED_MODELS]
    )
