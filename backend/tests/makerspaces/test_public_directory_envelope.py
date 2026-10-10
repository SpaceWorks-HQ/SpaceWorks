"""The central public directory lists only live, opted-in, directory-visible spaces.

`PublicMakerspaceListView` filters on servability, `public_inventory_enabled` and
`hidden_from_central_directory`; only the second had a test. A space that left the
directory (its own domain), was archived, or is mid-import must not be advertised.
"""

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.makerspaces.models import Makerspace

pytestmark = pytest.mark.django_db


def listed_slugs():
    response = APIClient().get(reverse("public-makerspaces"))
    assert response.status_code == 200
    return {row["slug"] for row in response.data}


def test_directory_excludes_hidden_archived_and_importing_spaces():
    Makerspace.objects.create(name="Listed", slug="dir-listed")
    Makerspace.objects.create(
        name="Own Domain",
        slug="dir-own-domain",
        frontend_domain="own.example.org",
        hidden_from_central_directory=True,
    )
    Makerspace.objects.create(name="Archived", slug="dir-archived", archived_at=timezone.now())
    Makerspace.objects.create(
        name="Importing",
        slug="dir-importing",
        lifecycle_state=Makerspace.LifecycleState.IMPORTING,
    )
    Makerspace.objects.create(
        name="Aborted",
        slug="dir-aborted",
        lifecycle_state=Makerspace.LifecycleState.ABORTED,
    )

    assert listed_slugs() == {"dir-listed"}


def test_directory_hidden_space_still_serves_its_own_catalogue():
    # Leaving the directory is not going private: the space keeps its public catalogue
    # on its own domain, so only the central listing omits it.
    Makerspace.objects.create(
        name="Own Domain",
        slug="dir-own-catalogue",
        frontend_domain="catalogue.example.org",
        hidden_from_central_directory=True,
    )

    assert "dir-own-catalogue" not in listed_slugs()
    response = APIClient().get(reverse("public-inventory", args=["dir-own-catalogue"]))
    assert response.status_code == 200
