"""Organization-owned makerspace scope for the reports dashboard.

COMBINED mode flattens rows across makerspaces, which the report-grouping invariant
otherwise forbids ("aggregate output groups by makerspace_id and never flattens
cross-tenant data"). A Stage-4 review flagged that correctly, and the invariant was
amended on 2026-08-20 with a bounded exception -- see docs/INVARIANTS.md under
"Reports/analytics extend one registry". This module is condition (1) of that exception:
the id set is resolved HERE, server-side, and never accepted from a client. Condition (2)
is the OWNER-only link filter below. Conditions (3) and (4) -- that a combined total only
ever ACCOMPANIES the per-makerspace breakdown, and that COMBINED is the only flattening
mode -- must be enforced by the aggregation layer that consumes this scope.
"""

from django.db.models import Exists, OuterRef

from apps.accounts import rbac
from apps.makerspaces.models import Makerspace
from apps.makerspaces.servability import servable_queryset
from apps.operations.report_registry import ReportDefinition
from apps.operations.report_scope import ReportScope, combined_report_scope
from apps.organizations.models import (
    Organization,
    OrganizationMakerspace,
    OrganizationMembership,
)


ORGANIZATION_REPORT_ACTIONS = frozenset({
    rbac.Action.VIEW_AUDIT,
    rbac.Action.MANAGE_MAKERSPACE,
})
EXCLUDED_ORGANIZATION_REPORT_KEYS = frozenset({
    "machine-service",
    "printer-service",
})


class OrganizationReportScopeError(ValueError):
    """Base error for a report definition the organization dashboard cannot use."""


class UnsupportedOrganizationReport(OrganizationReportScopeError):
    """The report key is deliberately unavailable to organization dashboards."""


class UnsupportedOrganizationReportAction(OrganizationReportScopeError):
    """The report requires authority outside the dashboard's safe vocabulary."""


def _validate_inputs(
    organization: Organization,
    definition: ReportDefinition,
) -> None:
    if not isinstance(organization, Organization):
        raise TypeError("organization must be a server-resolved Organization instance.")
    if organization.pk is None:
        raise ValueError("organization must be saved before resolving report scope.")
    if not isinstance(definition, ReportDefinition):
        raise TypeError("definition must be a ReportDefinition.")
    if definition.key in EXCLUDED_ORGANIZATION_REPORT_KEYS:
        raise UnsupportedOrganizationReport(
            f"Report {definition.key!r} is unavailable to organization dashboards."
        )
    if definition.required_action not in ORGANIZATION_REPORT_ACTIONS:
        raise UnsupportedOrganizationReportAction(
            f"Action {definition.required_action!r} is not supported by organization reports."
        )
    if any(
        not isinstance(module, str) or not module
        for module in definition.required_modules
    ):
        raise OrganizationReportScopeError(
            "Report source modules must be non-empty strings."
        )


def resolve_organization_report_scope(
    actor,
    organization: Organization,
    definition: ReportDefinition,
) -> ReportScope:
    """Resolve a combined scope using only the requested organization's OWNER grant."""
    _validate_inputs(organization, definition)

    if (
        actor is None
        or not getattr(actor, "is_authenticated", False)
        or getattr(actor, "pk", None) is None
    ):
        return combined_report_scope(Makerspace.objects.none())

    # Terms 1-3 deliberately share one membership query so the action cannot come
    # from a different organization or from a local makerspace role.
    active_grant = OrganizationMembership.objects.filter(
        organization=organization,
        organization__is_active=True,
        user=actor,
        status=OrganizationMembership.Status.ACTIVE,
        granted_actions__contains=[definition.required_action],
    )
    requested_owner_link = OrganizationMakerspace.objects.filter(
        organization=organization,
        relationship=OrganizationMakerspace.Relationship.OWNER,
        makerspace_id=OuterRef("pk"),
    )
    # Terms 1 and 4 share one link predicate: the requested organization itself
    # must be the OWNER, even if some other organization owns the same makerspace.
    makerspaces = Makerspace.objects.filter(
        Exists(active_grant),
        Exists(requested_owner_link),
    )
    # Term 5: importing, aborted, and archived spaces cannot serve reports.
    makerspaces = servable_queryset(makerspaces)
    # Term 6 is platform-reach consent, NOT hide -- named precisely because an earlier
    # draft called this "hard-hide" and that was wrong. It matches eligible_makerspaces()
    # and the rbac organization branch, so a tenant that has withdrawn platform reach is
    # absent from organization-level aggregates too.
    # Two deliberate non-filters, recorded so nobody "fixes" them later:
    #   - hidden_from_central_directory is DIRECTORY visibility, not authorization; an
    #     owning organization still sees a space it owns that is off the central list.
    #   - there is no hidden LifecycleState (only ACTIVE/IMPORTING/ABORTED), so
    #     servable_queryset above already covers importing, aborted and archived.
    makerspaces = makerspaces.filter(superadmin_access_enabled=True)
    # Term 7: the reports module and every declared source module are required.
    makerspaces = makerspaces.filter(enabled_modules__contains=["reports"])
    for module in definition.required_modules:
        makerspaces = makerspaces.filter(enabled_modules__contains=[module])

    return combined_report_scope(makerspaces)
