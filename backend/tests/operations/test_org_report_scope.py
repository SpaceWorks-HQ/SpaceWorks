import pytest

from apps.accounts import rbac
from apps.accounts.models import User
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceMembership,
)
from apps.operations import report_scope
from apps.operations.org_report_scope import (
    UnsupportedOrganizationReport,
    UnsupportedOrganizationReportAction,
    resolve_organization_report_scope,
)
from apps.operations.report_registry import ReportDefinition, report_definition
from apps.operations.report_scope import (
    ReportScopeMode,
    scope_queryset,
)
from apps.organizations.models import (
    Organization,
    OrganizationMakerspace,
    OrganizationMembership,
)


pytestmark = pytest.mark.django_db
DEFAULT_REPORT = report_definition("summary")


def make_user(slug, **kwargs):
    return User.objects.create_user(username=slug, **kwargs)


def make_space(slug, **kwargs):
    return Makerspace.objects.create(name=slug.title(), slug=slug, **kwargs)


def make_organization(slug, **kwargs):
    return Organization.objects.create(name=slug.title(), slug=slug, **kwargs)


def link(organization, makerspace, relationship=OrganizationMakerspace.Relationship.OWNER):
    return OrganizationMakerspace.objects.create(
        organization=organization,
        makerspace=makerspace,
        relationship=relationship,
    )


def grant(organization, actor, action=rbac.Action.VIEW_AUDIT, **kwargs):
    return OrganizationMembership.objects.create(
        organization=organization,
        user=actor,
        granted_actions=[action],
        **kwargs,
    )


def resolved_ids(actor, organization, definition=DEFAULT_REPORT):
    return resolve_organization_report_scope(
        actor,
        organization,
        definition,
    ).makerspace_ids


def test_organization_grantable_vocabulary_excludes_only_manage_machines():
    assert rbac.ORGANIZATION_GRANTABLE_ACTIONS == (
        rbac.ROLE_GRANTABLE_ACTIONS - {rbac.Action.MANAGE_MACHINES}
    )


def test_local_makerspace_action_without_organization_grant_is_denied():
    actor = make_user("local-report-action")
    makerspace = make_space("local-report-space")
    organization = make_organization("local-report-org")
    link(organization, makerspace)
    MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=actor,
        role=MakerspaceMembership.Role.INVENTORY_MANAGER,
    )

    assert rbac.can(actor, rbac.Action.VIEW_AUDIT, makerspace.id)
    assert resolved_ids(actor, organization) == ()


def test_grant_from_a_different_organization_is_denied():
    actor = make_user("other-org-report-action")
    makerspace = make_space("other-org-report-space")
    requested = make_organization("requested-report-org")
    other = make_organization("granting-report-org")
    link(requested, makerspace)
    link(other, makerspace, OrganizationMakerspace.Relationship.MANAGER)
    grant(other, actor)

    assert resolved_ids(actor, requested) == ()


def test_suspended_organization_membership_is_denied():
    actor = make_user("suspended-report-member")
    makerspace = make_space("suspended-report-space")
    organization = make_organization("suspended-report-org")
    link(organization, makerspace)
    grant(
        organization,
        actor,
        status=OrganizationMembership.Status.SUSPENDED,
    )

    assert resolved_ids(actor, organization) == ()


def test_inactive_organization_is_denied():
    actor = make_user("inactive-report-member")
    makerspace = make_space("inactive-report-space")
    organization = make_organization("inactive-report-org", is_active=False)
    link(organization, makerspace)
    grant(organization, actor)

    assert resolved_ids(actor, organization) == ()


def test_superadmin_without_organization_grant_is_denied():
    actor = make_user(
        "organization-report-superadmin",
        role=User.Role.SUPERADMIN,
        is_staff=True,
        is_superuser=True,
    )
    makerspace = make_space("superadmin-report-space")
    organization = make_organization("superadmin-report-org")
    link(organization, makerspace)

    assert resolved_ids(actor, organization) == ()


def test_manager_and_affiliate_links_are_excluded():
    actor = make_user("non-owner-report-member")
    organization = make_organization("non-owner-report-org")
    actual_owner = make_organization("actual-owner-report-org")
    manager_space = make_space("manager-report-space")
    affiliate_space = make_space("affiliate-report-space")
    link(organization, manager_space, OrganizationMakerspace.Relationship.MANAGER)
    link(organization, affiliate_space, OrganizationMakerspace.Relationship.AFFILIATE)
    link(actual_owner, manager_space)
    link(actual_owner, affiliate_space)
    grant(organization, actor)

    assert resolved_ids(actor, organization) == ()


def test_makerspace_that_withdrew_platform_reach_is_excluded():
    actor = make_user("hidden-report-member")
    organization = make_organization("hidden-report-org")
    makerspace = make_space(
        "hidden-report-space",
        superadmin_access_enabled=False,
    )
    link(organization, makerspace)
    grant(organization, actor)

    assert resolved_ids(actor, organization) == ()


def test_non_servable_makerspace_is_excluded():
    actor = make_user("unservable-report-member")
    organization = make_organization("unservable-report-org")
    makerspace = make_space(
        "unservable-report-space",
        lifecycle_state=Makerspace.LifecycleState.IMPORTING,
    )
    link(organization, makerspace)
    grant(organization, actor)

    assert resolved_ids(actor, organization) == ()


def test_reports_disabled_makerspace_is_excluded():
    actor = make_user("reports-disabled-member")
    organization = make_organization("reports-disabled-org")
    makerspace = make_space("reports-disabled-space")
    makerspace.enabled_modules.remove("reports")
    makerspace.save(update_fields=["enabled_modules"])
    link(organization, makerspace)
    grant(organization, actor)

    assert resolved_ids(actor, organization) == ()


def test_makerspace_missing_a_report_source_module_is_excluded():
    actor = make_user("source-disabled-member")
    organization = make_organization("source-disabled-org")
    makerspace = make_space("source-disabled-space")
    makerspace.enabled_modules.remove("events")
    makerspace.save(update_fields=["enabled_modules"])
    link(organization, makerspace)
    grant(organization, actor)

    assert resolved_ids(actor, organization, report_definition("event-attendance")) == ()


def test_empty_scope_filters_to_none_without_falling_back_to_deployment(monkeypatch):
    actor = make_user("empty-report-member")
    organization = make_organization("empty-report-org")
    eligible = make_space("empty-report-eligible-space")
    link(organization, eligible)
    scope = resolve_organization_report_scope(actor, organization, DEFAULT_REPORT)
    assert eligible.id in report_scope.eligible_makerspace_ids()

    monkeypatch.setattr(
        report_scope,
        "scoped_ids",
        lambda *_args: pytest.fail("empty typed scope reached legacy scoped_ids"),
    )

    assert scope.makerspace_ids == ()
    assert list(scope_queryset(Makerspace.objects.all(), scope, makerspace_field="id")) == []


def test_definition_with_unsupported_action_raises():
    actor = make_user("unsupported-action-member")
    organization = make_organization("unsupported-action-org")
    definition = ReportDefinition(
        "unsupported-action",
        "unused.builder",
        (),
        required_action=rbac.Action.EDIT_INVENTORY,
    )

    with pytest.raises(UnsupportedOrganizationReportAction):
        resolve_organization_report_scope(actor, organization, definition)


def test_machine_service_report_keys_are_excluded_entirely():
    actor = make_user("machine-report-member")
    organization = make_organization("machine-report-org")

    for key in ("machine-service", "printer-service"):
        with pytest.raises(UnsupportedOrganizationReport):
            resolve_organization_report_scope(
                actor,
                organization,
                report_definition(key),
            )


def test_two_eligible_owner_makerspaces_are_combined():
    actor = make_user("owner-report-member")
    organization = make_organization("owner-report-org")
    first = make_space("first-owner-report-space")
    second = make_space("second-owner-report-space")
    link(organization, first)
    link(organization, second)
    grant(organization, actor)

    scope = resolve_organization_report_scope(actor, organization, DEFAULT_REPORT)

    assert scope.mode is ReportScopeMode.COMBINED
    assert scope.makerspace_ids == (first.id, second.id)
