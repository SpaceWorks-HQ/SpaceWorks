"""Resolve which machines a role's ``MANAGE_MACHINES`` grant reaches.

This stable import surface explicitly re-exports the split resolution, direct-grant,
and queryset-filter layers. ``EXEMPT`` and ``NOTHING`` are defined only in
``role_scope_resolution`` and retain identity through these bindings.
"""

from .role_scope_grants import (
    grant_builtin_type_scope,
    grants_directly,
    is_machine_only,
    makerspaces_granting_directly,
    organization_grants_directly,
    role_grants_directly,
)
from .role_scope_queries import (
    SERVICE_REQUEST_MACHINE_PATHS,
    SERVICE_REQUEST_TYPE_PATHS,
    covers_service_request,
    scope_q_for,
    scoped_q,
    scoped_related_q,
    scoped_service_requests,
)
from .role_scope_resolution import (
    EXEMPT,
    NOTHING,
    _scope_for_membership,
    covers_machine,
    covers_type,
    manage_scope_for,
    manage_scopes_for,
    manage_scopes_for_memberships,
    scope_covers_machine,
    scope_covers_type,
)
