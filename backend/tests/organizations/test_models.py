import pytest
from django.db import IntegrityError, transaction

from apps.accounts.models import User
from apps.makerspaces.models import Makerspace
from apps.organizations.models import Organization, OrganizationMakerspace


pytestmark = pytest.mark.django_db


def make_organization(slug):
    return Organization.objects.create(name=slug.title(), slug=slug)


def make_makerspace(slug):
    return Makerspace.objects.create(name=slug.title(), slug=slug)


def link(organization, makerspace, relationship):
    return OrganizationMakerspace.objects.create(
        organization=organization,
        makerspace=makerspace,
        relationship=relationship,
    )


def test_organization_is_creatable_before_any_makerspace_exists():
    assert Makerspace.objects.count() == 0

    organization = make_organization("platform-org")

    assert organization.pk is not None
    assert organization.makerspaces.count() == 0


def test_ownership_is_optional_and_multiple_managers_are_allowed():
    makerspace = make_makerspace("manager-only-space")
    first = make_organization("first-manager")
    second = make_organization("second-manager")

    link(first, makerspace, OrganizationMakerspace.Relationship.MANAGER)
    link(second, makerspace, OrganizationMakerspace.Relationship.MANAGER)

    assert makerspace.organization_links.filter(
        relationship=OrganizationMakerspace.Relationship.OWNER
    ).count() == 0
    assert makerspace.organization_links.filter(
        relationship=OrganizationMakerspace.Relationship.MANAGER
    ).count() == 2


def test_at_most_one_owner_per_makerspace():
    makerspace = make_makerspace("single-owner-space")
    first = make_organization("first-owner")
    second = make_organization("second-owner")
    link(first, makerspace, OrganizationMakerspace.Relationship.OWNER)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            link(second, makerspace, OrganizationMakerspace.Relationship.OWNER)

    assert makerspace.organization_links.filter(
        relationship=OrganizationMakerspace.Relationship.OWNER
    ).count() == 1


def test_many_to_many_relationship_works_in_both_directions():
    organization = make_organization("multi-space-manager")
    first_space = make_makerspace("first-managed-space")
    second_space = make_makerspace("second-managed-space")
    second_organization = make_organization("co-manager")

    link(organization, first_space, OrganizationMakerspace.Relationship.MANAGER)
    link(organization, second_space, OrganizationMakerspace.Relationship.MANAGER)
    link(second_organization, first_space, OrganizationMakerspace.Relationship.AFFILIATE)

    # Forward accessor is kept for convenience; the makerspace side is reached through
    # the link model, so Makerspace gains no extra tenant-export surface.
    assert set(organization.makerspaces.all()) == {first_space, second_space}
    assert {
        row.organization for row in first_space.organization_links.all()
    } == {organization, second_organization}


def test_one_relationship_per_organization_makerspace_pair():
    organization = make_organization("unique-pair-org")
    makerspace = make_makerspace("unique-pair-space")
    link(organization, makerspace, OrganizationMakerspace.Relationship.MANAGER)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            link(organization, makerspace, OrganizationMakerspace.Relationship.AFFILIATE)

    assert OrganizationMakerspace.objects.filter(
        organization=organization,
        makerspace=makerspace,
    ).count() == 1


def test_created_by_history_survives_user_deletion():
    creator = User.objects.create_user(username="organization-creator")
    makerspace = make_makerspace("creator-history-space")
    organization = Organization.objects.create(
        name="Creator History",
        slug="creator-history",
        created_by=creator,
    )
    organization_link = OrganizationMakerspace.objects.create(
        organization=organization,
        makerspace=makerspace,
        relationship=OrganizationMakerspace.Relationship.MANAGER,
        created_by=creator,
    )

    creator.delete()

    organization.refresh_from_db()
    organization_link.refresh_from_db()
    assert organization.created_by is None
    assert organization_link.created_by is None

