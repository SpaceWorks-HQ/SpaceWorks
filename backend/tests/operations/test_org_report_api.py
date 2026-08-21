import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts import rbac
from apps.accounts.models import User
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace
from apps.operations.report_registry import REPORT_REGISTRY, ReportDefinition
from apps.organizations.models import (
    Organization,
    OrganizationMakerspace,
    OrganizationMembership,
)


pytestmark = pytest.mark.django_db


def _user(slug):
    return User.objects.create_user(
        username=slug,
        access_status=User.AccessStatus.ACTIVE,
    )


def _space(slug):
    return Makerspace.objects.create(name=slug.title(), slug=slug)


def _organization(slug):
    return Organization.objects.create(name=slug.title(), slug=slug)


def _own(organization, *spaces):
    for space in spaces:
        OrganizationMakerspace.objects.create(
            organization=organization,
            makerspace=space,
            relationship=OrganizationMakerspace.Relationship.OWNER,
        )


def _grant(organization, actor, action=rbac.Action.VIEW_AUDIT):
    return OrganizationMembership.objects.create(
        organization=organization,
        user=actor,
        granted_actions=[action],
    )


def _client(actor=None):
    client = APIClient()
    if actor is not None:
        client.force_authenticate(actor)
    return client


def _url(organization, report_key="summary"):
    return reverse("organization-analytics", args=[organization.pk, report_key])


def test_organization_report_requires_authentication():
    organization = _organization("api-unauthorized")

    response = _client().get(_url(organization))

    assert response.status_code == 401


def test_other_organization_grant_is_indistinguishable_from_a_missing_organization():
    """A grant in another organization must 404, not 200-with-empty-rows.

    An empty 200 would make "you may not read this organization" look identical to
    "this organization owns nothing", and comparing it against the 404 for a
    non-existent id would make organization ids enumerable. Both must be 404.
    """
    actor = _user("api-other-actor")
    granted = _organization("api-granted")
    requested = _organization("api-requested")
    hidden = _space("api-requested-space")
    _grant(granted, actor)
    _own(requested, hidden)

    response = _client(actor).get(_url(requested))

    assert response.status_code == 404


def test_missing_organization_matches_the_unauthorized_status_exactly():
    """The oracle check: a non-existent id and an unreachable one must not differ."""
    actor = _user("api-oracle-actor")
    granted = _organization("api-oracle-granted")
    requested = _organization("api-oracle-requested")
    _grant(granted, actor)
    unreachable = _client(actor).get(_url(requested))

    missing = _client(actor).get(
        reverse("organization-analytics", args=[requested.pk + 10_000, "summary"])
    )

    assert unreachable.status_code == missing.status_code == 404


def test_member_of_the_requested_organization_owning_nothing_gets_an_empty_200():
    """Contrast: a genuinely qualifying actor whose organization owns nothing sees 200."""
    actor = _user("api-empty-actor")
    organization = _organization("api-empty-org")
    _grant(organization, actor)

    response = _client(actor).get(_url(organization))

    assert response.status_code == 200
    assert response.data["breakdown"] == []
    assert response.data["total"] == {"rows": []}


@pytest.mark.parametrize("report_key", ["machine-service", "printer-service"])
def test_excluded_organization_report_key_is_typed_400(report_key):
    actor = _user(f"api-excluded-{report_key}")
    organization = _organization(f"api-excluded-org-{report_key}")
    _grant(organization, actor)

    response = _client(actor).get(_url(organization, report_key))

    assert response.status_code == 400
    assert response.data["code"] == "invalid_organization_report"


def test_unsupported_report_action_is_typed_400(monkeypatch):
    actor = _user("api-action-actor")
    organization = _organization("api-action-org")
    _grant(organization, actor, rbac.Action.EDIT_INVENTORY)
    monkeypatch.setitem(
        REPORT_REGISTRY,
        "summary",
        ReportDefinition(
            "summary",
            "apps.operations.reports_inventory.build_summary",
            (),
            exportable=False,
            summary=True,
            required_action=rbac.Action.EDIT_INVENTORY,
        ),
    )

    response = _client(actor).get(_url(organization))

    assert response.status_code == 400
    assert response.data["code"] == "invalid_organization_report"


def test_happy_path_returns_two_owned_spaces_and_their_combined_total():
    actor = _user("api-happy-actor")
    organization = _organization("api-happy-org")
    first, second = _space("api-happy-first"), _space("api-happy-second")
    _own(organization, first, second)
    _grant(organization, actor)
    for space, quantity in ((first, 3), (second, 7)):
        InventoryProduct.objects.create(
            makerspace=space,
            name=f"Product {space.pk}",
            total_quantity=quantity,
            available_quantity=quantity,
        )

    response = _client(actor).get(_url(organization))

    assert response.status_code == 200
    assert [row["makerspace_id"] for row in response.data["breakdown"]] == [
        first.id, second.id,
    ]
    assert response.data["total"]["rows"][0]["products"] == 2
    assert response.data["total"]["rows"][0]["available_quantity"] == 10


@pytest.mark.parametrize(
    "field,value",
    [
        ("access_status", "restricted"),
        ("access_status", "suspended"),
        ("must_change_password", True),
    ],
)
def test_inactive_account_is_refused_even_with_a_valid_token(field, value):
    """A valid token is not enough: IsAuthenticated admitted these, IsActiveStaff must not.

    Stage 4 [P1]: a restricted or suspended organization member, or one carrying
    must_change_password, could still read organization analytics while their access
    token remained valid.
    """
    actor = _user(f"api-inactive-{field}-{value}")
    organization = _organization(f"api-inactive-org-{field}-{value}")
    space = _space(f"api-inactive-space-{field}-{value}")
    _own(organization, space)
    _grant(organization, actor)
    setattr(actor, field, value)
    actor.save(update_fields=[field])

    response = _client(actor).get(_url(organization))

    assert response.status_code == 403
