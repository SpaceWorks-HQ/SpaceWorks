import pytest
from django.core.management import call_command

from apps.accounts.models import User
from apps.inventory.models import InventoryAsset, InventoryProduct
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.machines.models import Machine, MachineConsumablePool, MachineServiceRequest

pytestmark = pytest.mark.django_db


def test_seed_demo_creates_three_spaces_staff_and_inventory():
    call_command("seed_demo", password="same-pass-123")

    spaces = {space.slug: space for space in Makerspace.objects.all()}
    assert set(spaces) == {"alpha-lab", "beta-workshop", "gamma-fab"}
    assert spaces["beta-workshop"].superadmin_access_enabled is True
    assert spaces["beta-workshop"].location == "North Wing - Woodshop"

    for username in ("superadmin", "alpha_manager", "beta_manager", "gamma_manager"):
        assert User.objects.get(username=username).check_password("same-pass-123")

    assert MakerspaceMembership.objects.filter(
        makerspace=spaces["beta-workshop"],
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    ).exists()
    assert InventoryProduct.objects.count() == 15
    assert InventoryAsset.objects.count() == 9
    assert Machine.objects.filter(machine_type__slug="3d_printer").count() == 3
    assert MachineConsumablePool.objects.filter(material="PLA", remaining_grams="1000.00").count() == 3
    assert MachineServiceRequest.objects.filter(title="Demo 3D print request", status="pending").count() == 3
