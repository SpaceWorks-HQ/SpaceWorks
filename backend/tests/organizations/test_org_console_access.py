import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import rbac
from apps.accounts.models import User
from apps.accounts.serializers import user_payload
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.organizations.models import OrganizationMakerspace, OrganizationMembership
from tests.organizations.test_org_authority import (
    grant,
    link,
    make_makerspace,
    make_organization,
    make_user,
)


pytestmark = pytest.mark.django_db
PASSWORD = "password"
LOGIN = "/api/v1/auth/login"


def org_actor(slug, action):
    user = make_user(f"{slug}-user")
    makerspace = make_makerspace(slug)
    makerspace.frontend_domain = f"{slug}.example.test"
    makerspace.frontend_domain_status = Makerspace.DomainStatus.VERIFIED
    makerspace.save(update_fields=["frontend_domain", "frontend_domain_status"])
    organization = make_organization(f"{slug}-org")
    link(organization, makerspace, "manager")
    membership = grant(organization, user, [action])
    return user, makerspace, organization, membership


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def login(user, makerspace=None):
    kwargs = {}
    if makerspace is not None:
        kwargs["HTTP_ORIGIN"] = f"https://{makerspace.frontend_domain}"
    return APIClient().post(
        LOGIN,
        {"username": user.username, "password": PASSWORD, "surface": "staff"},
        format="json",
        **kwargs,
    )


def test_org_only_actor_can_obtain_scoped_and_originless_staff_sessions():
    user, makerspace, _organization, _grant = org_actor(
        "org-console-login", rbac.Action.MANAGE_EVENTS
    )

    scoped = login(user, makerspace)
    originless = login(user)

    assert scoped.status_code == 200
    assert scoped.data["surface"] == "staff"
    assert originless.status_code == 200
    assert originless.data["surface"] == "staff_api"


@pytest.mark.parametrize("blocked_by", ["grant", "organization", "makerspace"])
def test_org_staff_login_rejects_inactive_authority(blocked_by):
    user, makerspace, organization, membership = org_actor(
        f"org-console-{blocked_by}", rbac.Action.MANAGE_EVENTS
    )
    if blocked_by == "grant":
        membership.status = OrganizationMembership.Status.SUSPENDED
        membership.save(update_fields=["status"])
    elif blocked_by == "organization":
        organization.is_active = False
        organization.save(update_fields=["is_active"])
    else:
        makerspace.archived_at = timezone.now()
        makerspace.save(update_fields=["archived_at"])

    assert login(user, makerspace).status_code == 403


def test_org_only_space_is_projected_into_user_payload():
    user, makerspace, organization, _grant = org_actor(
        "org-console-payload", rbac.Action.MANAGE_EVENTS
    )

    assert user_payload(user)["makerspaces"] == [
        {
            "id": makerspace.id,
            "slug": makerspace.slug,
            "role": None,
            "role_id": None,
            "role_name": organization.name,
            "role_slug": None,
            "actions": [rbac.Action.MANAGE_EVENTS],
            "can_configure_machine_types": False,
            "is_machine_only": False,
            "can_refer": False,
            "can_verify": False,
            "verified_at": None,
            "referrals_enabled": makerspace.referrals_enabled,
            "source": "organization",
        }
    ]


def test_membership_entry_unions_org_actions_without_duplication():
    user, makerspace, _organization, _grant = org_actor(
        "org-console-union", rbac.Action.MANAGE_EVENTS
    )
    role = MakerspaceRole.objects.create(
        makerspace=makerspace,
        name="Local Viewer",
        slug="local-viewer",
        granted_actions=[rbac.Action.VIEW_INVENTORY],
    )
    MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=user,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
    )

    rows = user_payload(user)["makerspaces"]

    assert len(rows) == 1
    assert rows[0]["source"] == "membership"
    assert rows[0]["actions"] == sorted(
        [rbac.Action.MANAGE_EVENTS, rbac.Action.VIEW_INVENTORY]
    )


def test_hard_hidden_org_space_neither_projects_nor_grants_a_session():
    user, makerspace, _organization, _grant = org_actor(
        "org-console-hidden", rbac.Action.MANAGE_EVENTS
    )
    makerspace.superadmin_access_enabled = False
    makerspace.save(update_fields=["superadmin_access_enabled"])

    assert user_payload(user)["makerspaces"] == []
    assert login(user, makerspace).status_code == 403


def test_events_admin_endpoint_accepts_org_action_and_hides_from_outsider():
    user, makerspace, _organization, _grant = org_actor(
        "org-console-events", rbac.Action.MANAGE_EVENTS
    )
    url = reverse(
        "admin-event-list-create", kwargs={"makerspace_id": makerspace.pk}
    )

    assert client_for(user).get(url).status_code == 200
    assert client_for(make_user("org-console-events-outsider")).get(url).status_code == 404


def test_bookings_admin_endpoint_accepts_org_action_and_hides_from_outsider():
    user, makerspace, _organization, _grant = org_actor(
        "org-console-bookings", rbac.Action.MANAGE_BOOKINGS
    )
    url = reverse(
        "admin-bookable-space-list-create",
        kwargs={"makerspace_id": makerspace.pk},
    )

    assert client_for(user).get(url).status_code == 200
    assert client_for(make_user("org-console-bookings-outsider")).get(url).status_code == 404


def test_org_payload_query_count_does_not_scale_with_linked_spaces(
    django_assert_num_queries,
):
    one_user, _one_space, _organization, _grant = org_actor(
        "org-console-query-one", rbac.Action.MANAGE_EVENTS
    )
    many_user = make_user("org-console-query-many-user")
    many_org = make_organization("org-console-query-many-org")
    grant(many_org, many_user, [rbac.Action.MANAGE_EVENTS])
    for index in range(4):
        link(
            many_org,
            make_makerspace(f"org-console-query-many-{index}"),
            "affiliate",
        )

    with CaptureQueriesContext(connection) as queries:
        assert len(user_payload(one_user)["makerspaces"]) == 1
    with django_assert_num_queries(len(queries)):
        assert len(user_payload(many_user)["makerspaces"]) == 4


def test_staff_roster_does_not_project_org_only_actor():
    org_user, makerspace, _organization, _grant = org_actor(
        "org-console-roster", rbac.Action.MANAGE_EVENTS
    )
    superadmin = make_user(
        "org-console-roster-root",
        role=User.Role.SUPERADMIN,
        is_superuser=True,
        is_staff=True,
    )

    response = client_for(superadmin).get(
        reverse("admin-memberships-roster"),
        {"makerspace_id": makerspace.pk},
    )

    assert response.status_code == 200
    assert org_user.username not in {
        row["user"]["username"] for row in response.data["results"]
    }


def test_a_native_device_payload_omits_organization_only_spaces():
    """Native scoping resolves X-Makerspace-Id from local memberships only.

    So an organization-only space in a device payload would be advertised to the app and
    then rejected on every selected request. Omitting it is honest; advertising it is not.
    """
    from apps.accounts.serializers import user_payload

    user = make_user("device-payload-org-user")
    makerspace = make_makerspace("device-payload-org-space")
    organization = make_organization("device-payload-org")
    link(organization, makerspace, OrganizationMakerspace.Relationship.MANAGER)
    grant(organization, user, [rbac.Action.MANAGE_EVENTS])

    from django.test import RequestFactory

    device_request = RequestFactory().get("/")
    device_request.device_grant = object()

    payload = user_payload(user, device_request)

    assert payload["makerspaces"] == []

    # Without a device grant the same user does see it, so the exclusion is specific to
    # the native payload rather than a general regression.
    browser_payload = user_payload(user, RequestFactory().get("/"))
    assert [entry["id"] for entry in browser_payload["makerspaces"]] == [makerspace.id]
