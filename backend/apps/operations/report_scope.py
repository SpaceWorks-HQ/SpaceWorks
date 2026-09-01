from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from django.db.models import QuerySet

from apps.makerspaces.models import Makerspace
from apps.makerspaces.servability import servable_queryset


class ReportScopeMode(str, Enum):
    SINGLE = "single"
    BY_MAKERSPACE = "by_makerspace"
    COMBINED = "combined"


_REPORT_SCOPE_FACTORY_TOKEN = object()


@dataclass(frozen=True, init=False)
class ReportScope:
    makerspace_ids: tuple[int, ...]
    mode: ReportScopeMode

    def __init__(
        self,
        makerspace_ids: tuple[int, ...],
        mode: ReportScopeMode,
        *,
        _factory_token=None,
    ):
        if _factory_token is not _REPORT_SCOPE_FACTORY_TOKEN:
            raise TypeError("ReportScope must be created by a server-side scope factory.")
        object.__setattr__(self, "makerspace_ids", makerspace_ids)
        object.__setattr__(self, "mode", mode)


def _resolved_scope(
    makerspace_ids: Iterable[int],
    mode: ReportScopeMode,
) -> ReportScope:
    if not isinstance(mode, ReportScopeMode):
        raise TypeError("mode must be a ReportScopeMode.")
    resolved_ids = tuple(dict.fromkeys(makerspace_ids))
    if any(
        isinstance(makerspace_id, bool)
        or not isinstance(makerspace_id, int)
        or makerspace_id <= 0
        for makerspace_id in resolved_ids
    ):
        raise ValueError("Resolved makerspace ids must be positive integers.")
    return ReportScope(
        resolved_ids,
        mode,
        _factory_token=_REPORT_SCOPE_FACTORY_TOKEN,
    )


def single_report_scope(makerspace: Makerspace) -> ReportScope:
    """Build a single-tenant scope from a server-resolved Makerspace row."""
    if not isinstance(makerspace, Makerspace):
        raise TypeError("makerspace must be a server-resolved Makerspace instance.")
    if makerspace.pk is None:
        raise ValueError("makerspace must be saved before it can define a report scope.")
    return _resolved_scope((makerspace.pk,), ReportScopeMode.SINGLE)


def deployment_report_scope(*source_modules: str) -> ReportScope:
    """Build the existing deployment aggregate scope with explicit row grouping."""
    return _resolved_scope(
        eligible_makerspace_ids(*source_modules),
        ReportScopeMode.BY_MAKERSPACE,
    )


def combined_report_scope(makerspaces: QuerySet) -> ReportScope:
    """Build one combined scope from a server-resolved Makerspace queryset."""
    if not isinstance(makerspaces, QuerySet) or makerspaces.model is not Makerspace:
        raise TypeError("makerspaces must be a Makerspace QuerySet.")
    ids = makerspaces.order_by("pk").values_list("pk", flat=True).distinct()
    return _resolved_scope(ids, ReportScopeMode.COMBINED)


def scope_queryset(
    queryset: QuerySet,
    scope: ReportScope,
    *,
    makerspace_field: str = "makerspace_id",
) -> QuerySet:
    """Apply a typed scope without allowing an empty scope to widen."""
    if not isinstance(queryset, QuerySet):
        raise TypeError("queryset must be a Django QuerySet.")
    if not isinstance(scope, ReportScope):
        raise TypeError("scope must be a ReportScope.")
    if not isinstance(makerspace_field, str) or not makerspace_field:
        raise ValueError("makerspace_field must be a non-empty string.")
    if not scope.makerspace_ids:
        return queryset.none()
    return queryset.filter(
        **{f"{makerspace_field}__in": scope.makerspace_ids}
    )


def eligible_makerspaces(*source_modules):
    queryset = servable_queryset(Makerspace.objects.filter(
        superadmin_access_enabled=True,
        enabled_modules__contains=["reports"],
    ))
    for module in source_modules:
        queryset = queryset.filter(enabled_modules__contains=[module])
    return queryset


def eligible_makerspace_ids(*source_modules):
    return list(eligible_makerspaces(*source_modules).values_list("id", flat=True))


def scoped_ids(makerspace_id, *source_modules):
    return [makerspace_id] if makerspace_id is not None else eligible_makerspace_ids(*source_modules)
