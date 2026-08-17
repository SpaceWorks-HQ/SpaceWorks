from django.db.models import Q

from .external_refs import select_related_paths as external_paths
from .pii_raw import select_related_paths as pii_paths
from .types import Fidelity


def select_declared_relations(queryset, dataset):
    paths = {
        source.rsplit("__", 1)[0]
        for column in dataset.columns
        for source in column.sources
        if "__" in source
    }
    if dataset.fidelity is Fidelity.PORTABLE:
        paths.update(pii_paths(dataset.model))
        paths.update(external_paths(dataset.model))
    return queryset.select_related(*paths) if paths else queryset


def after_keyset(names, values):
    result = Q()
    for index, name in enumerate(names):
        prefix = {names[i]: values[i] for i in range(index)}
        result |= Q(**prefix, **{f"{name}__gt": values[index]})
    return result


def key_value(row, name):
    field = next(
        field
        for field in row._meta.get_fields()
        if field.name == name or getattr(field, "attname", None) == name
    )
    return getattr(row, field.attname)


def is_statement_timeout(exc):
    cause = getattr(exc, "__cause__", None)
    return (
        getattr(cause, "sqlstate", None) == "57014"
        or "statement timeout" in str(exc).lower()
    )
