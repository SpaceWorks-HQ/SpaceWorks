"""OFF-state contracts for the platform-facing optional modules.

These modules share infrastructure with core or ungated surfaces. Their switches must
remove only their own capability, never the lending workflow or the neighbouring API.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_profiles import RECOMMENDED, profile_modules
from apps.operations.models import QrPrintBatch


pytestmark = pytest.mark.django_db

PLATFORM_MODULES = ("reports", "qr_print_batches", "updates")


def _space(slug, *, without=None):
    modules = set(profile_modules(RECOMMENDED))
    if without is not None:
        modules.remove(without)
    return Makerspace.objects.create(
        name=slug,
        slug=slug,
        enabled_modules=sorted(modules),
        public_inventory_enabled=True,
    )


def _product(space, name="Torque wrench"):
    return InventoryProduct.objects.create(
        makerspace=space,
        name=name,
        total_quantity=3,
        available_quantity=3,
        is_public=True,
    )


def _user(slug, *, superadmin=False):
    return User.objects.create_user(
        username=slug,
        email=f"{slug}@example.test",
        display_name="Module Contract User",
        role=User.Role.SUPERADMIN if superadmin else User.Role.REQUESTER,
        is_staff=superadmin,
        is_superuser=superadmin,
        access_status=User.AccessStatus.ACTIVE,
    )


def _client(user=None):
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


def _enable(space, module_key):
    space.enabled_modules = sorted({*(space.enabled_modules or []), module_key})
    space.save(update_fields=["enabled_modules"])


def _run_loan_spine(module_key):
    """Browse -> submit -> staff queue -> accept -> public status with one key OFF."""
    label = module_key.replace("_", "-")
    space = _space(f"platform-off-{label}", without=module_key)
    assert module_key not in space.enabled_modules
    product = _product(space)

    catalog = _client().get(
        reverse("inventory:public-inventory", args=[space.slug])
    )
    assert catalog.status_code == 200, catalog.data

    requester = _user(f"platform-off-{label}-requester")
    submitted = _client(requester).post(
        reverse("hardware_requests:request-submit", args=[space.slug]),
        {
            "requested_for": "Module independence check",
            "items": [{"product_id": product.pk, "quantity": 1}],
        },
        format="json",
    )
    assert submitted.status_code == 201, submitted.data

    staff = _client(_user(f"platform-off-{label}-staff", superadmin=True))
    pending = staff.get(
        reverse("hardware_requests:pending-requests", args=[space.pk])
    )
    assert pending.status_code == 200, pending.data
    assert pending.data["count"] == 1

    accepted = staff.post(
        reverse(
            "hardware_requests:request-accept",
            args=[pending.data["results"][0]["id"]],
        ),
        {},
        format="json",
    )
    assert accepted.status_code == 200, accepted.data
    assert accepted.data["status"] == "accepted"

    public_status = _client().get(
        reverse(
            "hardware_requests:request-status",
            args=[submitted.data["public_token"]],
        )
    )
    assert public_status.status_code == 200, public_status.data


@pytest.mark.parametrize("module_key", PLATFORM_MODULES)
def test_each_platform_optional_module_off_leaves_the_complete_loan_spine_working(
    module_key,
):
    """An optional platform tool must not become an undeclared loan dependency."""
    _run_loan_spine(module_key)


def test_reports_off_refuses_analytics_but_leaves_operations_queries_working_and_on_restores_it():
    """The dashboard is an operations surface, not a substitute reports endpoint.

    It deliberately remains useful on lean installs even though analytics and exports
    disappear with the reports module.
    """
    space = _space("platform-reports-gate", without="reports")
    client = _client(_user("platform-reports-manager", superadmin=True))
    analytics_url = reverse("analytics-summary", args=[space.pk])
    export_url = reverse("report-export", args=[space.pk, "damaged-missing"])

    refused_analytics = client.get(analytics_url)
    refused_export = client.get(export_url)
    dashboard = client.get(reverse("operations-dashboard", args=[space.pk]))

    assert refused_analytics.status_code == 400
    assert refused_export.status_code == 400
    assert "reports is disabled" in str(refused_analytics.data)
    assert "reports is disabled" in str(refused_export.data)
    assert dashboard.status_code == 200, dashboard.data
    assert dashboard.data["scope_mode"] == "full"

    _enable(space, "reports")
    enabled_analytics = client.get(analytics_url)
    enabled_export = client.get(export_url)

    assert enabled_analytics.status_code == 200, enabled_analytics.data
    assert enabled_export.status_code == 200
    assert enabled_export["Content-Type"].startswith("text/csv")


def test_qr_print_batches_off_refuses_batches_but_core_qr_management_works_and_on_restores_batches():
    """Batch ZIP generation is optional; creating a core tool QR can never require it."""
    space = _space("platform-qr-batches-gate", without="qr_print_batches")
    product = _product(space, "Multimeter")
    client = _client(_user("platform-qr-batches-manager", superadmin=True))
    batch_url = reverse("qr-print-batches", args=[space.pk])

    refused = client.post(batch_url, {"title": "Bench labels"}, format="json")
    core_qr = client.post(
        reverse("qr-tools"),
        {"makerspace_id": space.pk, "product_id": product.pk},
        format="json",
    )

    assert refused.status_code == 400
    assert "qr_print_batches is disabled" in str(refused.data)
    assert not QrPrintBatch.objects.filter(makerspace=space).exists()
    assert core_qr.status_code == 201, core_qr.data

    _enable(space, "qr_print_batches")
    enabled = client.post(batch_url, {"title": "Bench labels"}, format="json")

    assert enabled.status_code == 201, enabled.data
    assert QrPrintBatch.objects.filter(makerspace=space).count() == 1


def test_updates_off_hides_the_updater_but_platform_settings_work_and_on_restores_it():
    """Updates is deployment-wide because its singleton has no tenant foreign key.

    With at least one live space and none enabling updates, only the updater should be
    absent; the independent email and login-provider settings must remain reachable.
    """
    space = _space("platform-updates-gate", without="updates")
    client = _client(_user("platform-updates-superadmin", superadmin=True))
    updater_url = reverse("admin-platform-update-settings")
    update_now_url = reverse("admin-platform-update-now")

    refused_settings = client.get(updater_url)
    refused_update = client.post(update_now_url)
    email_settings = client.get(reverse("admin-platform-email-settings"))
    social_settings = client.get(reverse("admin-platform-social-auth-settings"))

    assert refused_settings.status_code == 404
    assert refused_update.status_code == 404
    assert email_settings.status_code == 200, email_settings.data
    assert social_settings.status_code == 200, social_settings.data

    _enable(space, "updates")
    enabled_settings = client.get(updater_url)
    enabled_update = client.post(update_now_url)

    assert enabled_settings.status_code == 200, enabled_settings.data
    assert enabled_update.status_code == 202, enabled_update.data
