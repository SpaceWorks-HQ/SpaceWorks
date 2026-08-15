"""Typed policy values used by the account-less claim route matrix."""

from dataclasses import dataclass
from enum import Enum


class TenantResolver(str, Enum):
    SLUG = "slug"
    ID = "id"
    PUBLIC_TOKEN = "public_token"
    BODY_OBJECT = "body_object"


SLUG = TenantResolver.SLUG
ID = TenantResolver.ID
PUBLIC_TOKEN = TenantResolver.PUBLIC_TOKEN
BODY_OBJECT = TenantResolver.BODY_OBJECT


class RowOwnership(str, Enum):
    SINGLE_OWNER = "single_owner"
    LOCALLY_FILTERED = "locally_filtered"
    LOCAL_OWNER_ENFORCED = "local_owner_enforced"
    MIXED_REFUSED = "mixed_refused"


@dataclass(frozen=True, slots=True)
class Allowed:
    tenant: TenantResolver
    audited: bool
    ownership: RowOwnership = RowOwnership.SINGLE_OWNER


@dataclass(frozen=True, slots=True)
class ReadOnly:
    tenant: TenantResolver
    ownership: RowOwnership = RowOwnership.SINGLE_OWNER


@dataclass(frozen=True, slots=True)
class LocallyFiltered:
    """A read whose ordinary-user queryset can contain foreign-owned rows.

    D3 records the ownership disposition. The claim-aware filter itself arrives with
    claim authentication in D5; keeping the marker distinct prevents that work from
    being mistaken for an already-enforced filter.
    """

    tenant: TenantResolver
    ownership: RowOwnership = RowOwnership.LOCALLY_FILTERED


@dataclass(frozen=True, slots=True)
class Refused:
    reason: str
    ownership: RowOwnership = RowOwnership.SINGLE_OWNER


@dataclass(frozen=True, slots=True)
class ControlRoute:
    """A session-control route with no business tenant."""


@dataclass(frozen=True, slots=True)
class AnonymousRead:
    """A public metadata/read route on which a presented claim token is ignored."""


ClaimRoutePolicy = Allowed | ReadOnly | LocallyFiltered | Refused | ControlRoute | AnonymousRead

