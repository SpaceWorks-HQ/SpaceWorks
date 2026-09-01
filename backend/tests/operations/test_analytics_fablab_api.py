import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.makerspaces.models import MakerspaceMembership
from tests.return_helpers import authenticated_client, make_member, make_space, make_user
from tests.handout_roles import make_handout_member


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("name", [
    "analytics-machine-usage", "analytics-event-attendance",
    "analytics-booking-utilization", "analytics-maintenance-activity",
    "analytics-fablab-health",
])
def test_fixed_fablab_urls_reverse_and_space_manager_can_read(name):
    space = make_space(f"url-{name}")
    manager = make_member(f"manager-{name}", space)
    response = authenticated_client(manager).get(reverse(name, args=[space.id]))
    assert response.status_code == 200


def test_report_rbac_status_codes_match_inventory_first_resolution():
    space = make_space("analytics-rbac")
    guest = make_handout_member("analytics-guest", space)
    printer = make_member(
        "analytics-printer", space,
        membership_role=MakerspaceMembership.Role.PRINT_MANAGER,
        role=User.Role.REQUESTER,
    )
    outsider = make_user("analytics-outsider", access_status=User.AccessStatus.ACTIVE)
    url = reverse("analytics-fablab-health", args=[space.id])
    assert authenticated_client(guest).get(url).status_code == 403
    assert authenticated_client(printer).get(url).status_code == 404
    assert authenticated_client(outsider).get(url).status_code == 404


def test_selected_hidden_space_allows_explicit_authorized_superadmin_membership():
    space = make_space("analytics-hidden-member")
    space.superadmin_access_enabled = False
    space.save(update_fields=["superadmin_access_enabled"])
    user = make_user(
        "analytics-hidden-super", role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=user, makerspace=space, role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    response = authenticated_client(user).get(reverse("analytics-fablab-health", args=[space.id]))
    assert response.status_code == 200


def test_required_source_module_is_a_typed_400_gate():
    space = make_space("analytics-module-gate")
    space.enabled_modules = [module for module in space.enabled_modules if module != "events"]
    space.save(update_fields=["enabled_modules"])
    manager = make_member("analytics-module-manager", space)
    response = authenticated_client(manager).get(reverse("analytics-event-attendance", args=[space.id]))
    assert response.status_code == 400
    assert "events is disabled" in str(response.data)


def test_unknown_and_non_exportable_keys_fail_before_builder(monkeypatch):
    superadmin = make_user(
        "analytics-key-super", role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )
    called = False

    def forbidden(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("builder must not run")

    monkeypatch.setattr("apps.operations.report_registry.ReportDefinition.builder", forbidden)
    client = authenticated_client(superadmin)
    unknown = client.get("/api/v1/admin/analytics/not-a-report")
    assert unknown.status_code == 404
    assert unknown.data == {"detail": "Unknown report key.", "code": "report_not_found"}
    not_exportable = client.get("/api/v1/admin/reports/summary/export")
    assert not_exportable.status_code == 400
    assert not_exportable.data == {"detail": "Report is not exportable.", "code": "report_not_exportable"}
    assert "Content-Disposition" not in not_exportable
    assert called is False


def test_aggregate_is_superadmin_only():
    space = make_space("analytics-aggregate-role")
    manager = make_member("analytics-aggregate-manager", space)
    response = authenticated_client(manager).get("/api/v1/admin/analytics/fablab-health")
    assert response.status_code == 403
