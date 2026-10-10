from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory

import pytest

from apps.machines.admin import MachineTypeAdmin
from apps.machines.metering import validate_type_config
from apps.machines.models import MachineType


def test_control_plane_capability_field_discloses_booking_flag_is_not_enforced():
    model_admin = MachineTypeAdmin(MachineType, AdminSite())
    request = RequestFactory().get("/control/machines/machinetype/add/")

    field = model_admin.formfield_for_dbfield(
        MachineType._meta.get_field("capability_config"), request,
    )

    assert "requires_booking is not yet enforced" in field.help_text
    assert "Machine time bookings are not available" in field.help_text
    assert "does not block service requests or job starts" in field.help_text


@pytest.mark.parametrize("requires_booking", [True, False])
def test_booking_metadata_remains_valid_for_custom_types(requires_booking):
    validate_type_config(
        {"metering_unit": "minutes", "requires_booking": requires_booking},
        is_custom=True,
    )
