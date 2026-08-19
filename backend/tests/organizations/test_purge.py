import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.makerspaces import lifecycle
from apps.makerspaces.models import Makerspace
from apps.organizations.models import Organization, OrganizationMakerspace


@pytest.mark.django_db(transaction=True)
def test_purge_removes_only_the_purged_makerspace_links(monkeypatch):
    actor = User.objects.create_user(
        username="organization-purge-superadmin",
        is_staff=True,
        is_superuser=True,
    )
    organization = Organization.objects.create(
        name="Shared Organization",
        slug="shared-organization",
        created_by=actor,
    )
    purged_space = Makerspace.objects.create(
        name="Purged Space",
        slug="organization-purged-space",
        archived_at=timezone.now(),
    )
    surviving_space = Makerspace.objects.create(
        name="Surviving Space",
        slug="organization-surviving-space",
    )
    purged_link = OrganizationMakerspace.objects.create(
        organization=organization,
        makerspace=purged_space,
        relationship=OrganizationMakerspace.Relationship.OWNER,
        created_by=actor,
    )
    surviving_link = OrganizationMakerspace.objects.create(
        organization=organization,
        makerspace=surviving_space,
        relationship=OrganizationMakerspace.Relationship.MANAGER,
        created_by=actor,
    )
    monkeypatch.setattr(lifecycle, "_delete_storage_keys", lambda _keys: None)
    monkeypatch.setattr(lifecycle, "_delete_public_image_keys", lambda _keys: None)

    lifecycle.purge(purged_space, actor)

    assert not Makerspace.objects.filter(pk=purged_space.pk).exists()
    assert not OrganizationMakerspace.objects.filter(pk=purged_link.pk).exists()
    assert Organization.objects.filter(pk=organization.pk).exists()
    assert OrganizationMakerspace.objects.filter(pk=surviving_link.pk).exists()
    assert organization.makerspaces.get() == surviving_space

