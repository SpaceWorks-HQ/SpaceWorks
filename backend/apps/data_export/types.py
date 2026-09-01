"""Small immutable value types used by the export registries."""

from dataclasses import dataclass, field
from enum import StrEnum

from django.db.models import Q


class Fidelity(StrEnum):
    REDACTED = "REDACTED"
    PORTABLE = "PORTABLE"


@dataclass(frozen=True)
class Emitted:
    pass


@dataclass(frozen=True)
class Transformed:
    reason: str


@dataclass(frozen=True)
class Redacted:
    marker: str


@dataclass(frozen=True)
class Remapped:
    pass


@dataclass(frozen=True)
class Omitted:
    reason: str


OUTPUT_DISPOSITIONS = (Emitted, Transformed, Remapped)
PERMITTED_SOURCE_DISPOSITIONS = (Emitted, Transformed, Remapped)


@dataclass(frozen=True)
class Exported:
    reason: str = "Tenant-owned operational data."


@dataclass(frozen=True)
class GlobalReference:
    reason: str


@dataclass(frozen=True)
class OmittedModel:
    reason: str


@dataclass(frozen=True)
class NotTenantData:
    reason: str


@dataclass(frozen=True)
class TenantPredicate:
    """One ownership contract compiled to both queryset and fixture semantics."""

    any_paths: tuple[str, ...]
    local_or_global_paths: tuple[str, ...] = ()
    include_global_if_unowned: bool = False

    def as_q(self, tenant_id: int) -> Q:
        ownership = Q()
        for path in self.any_paths:
            lookup = path if path in {"pk", "id"} else f"{path}_id"
            ownership |= Q(**{lookup: tenant_id})
        if self.include_global_if_unowned:
            for path in self.any_paths:
                ownership |= Q(**{f"{path}__isnull": True})
        for path in self.local_or_global_paths:
            ownership &= Q(
                Q(**{f"{path}_id": tenant_id}) | Q(**{f"{path}__isnull": True})
            )
        return ownership

    def includes(self, values: dict[str, int | None], tenant_id: int) -> bool:
        owned = any(values.get(path) == tenant_id for path in self.any_paths)
        if self.include_global_if_unowned:
            owned = owned or all(values.get(path) is None for path in self.any_paths)
        local = all(values.get(path) in (None, tenant_id) for path in self.local_or_global_paths)
        return owned and local


@dataclass(frozen=True)
class Column:
    name: str
    sources: tuple[str, ...]
    disposition: object


@dataclass(frozen=True)
class Dataset:
    fidelity: Fidelity
    path: str
    model: str
    predicate: TenantPredicate
    keyset: tuple[str, ...]
    columns: tuple[Column, ...]
    explicit_omissions: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class UserEdge:
    included: bool
    reason: str
    raw: bool = False


@dataclass(frozen=True)
class SemanticUserRef:
    model: str
    location: str
    reason: str
    included: bool = True


@dataclass(frozen=True)
class SourceLocalProvenance:
    model: str
    location: str
    reason: str
