import pytest
from django.urls import reverse

from apps.machines.models import Machine, MachineType
from tests.modules.family_helpers import assert_family_bootstrap, client, family_space

pytestmark = pytest.mark.django_db


def test_machines_only_public_list_works_without_catalogue_or_membership():
    space = family_space("family-machines", "machines")
    space.public_inventory_enabled = False
    space.save(update_fields=["public_inventory_enabled"])
    kind = MachineType.objects.create(makerspace=space, name="Laser", slug="laser")
    machine = Machine.objects.create(makerspace=space, machine_type=kind, name="Laser A", is_public=True)
    result = client().get(reverse("public-machines", args=[space.slug]))
    assert result.status_code == 200, result.data
    assert [row["id"] for row in result.data["results"]] == [machine.pk]
    assert_family_bootstrap(space, "machines")
    assert client().get(reverse("public-inventory", args=[space.slug])).status_code == 400
