from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.bookings.models import BookableSpace, Booking
from apps.events.models import Event, EventRegistration
from apps.hardware_requests.models import HardwareRequest, PublicProblemReport, PublicToolLoan
from apps.integrations.models import EmailLog
from apps.makerspaces.models import MakerspaceMembership
from apps.machines.models import Machine, MachineServiceRequest, MachineType, ServiceQueue
from apps.maintenance.models import MaintenanceSchedule
from apps.operations import views_dashboard
from apps.operations.models import StocktakeSession
from apps.payments.models import Payment
from tests.return_helpers import authenticated_client, make_member, make_product, make_space, make_user
from tests.handout_roles import make_handout_member

pytestmark = pytest.mark.django_db


def dashboard_url(makerspace):
    return f"/api/v1/admin/makerspace/{makerspace.id}/dashboard"


def test_space_manager_gets_dashboard_with_all_count_keys():
    makerspace = make_space("ops-dashboard-access")
    manager = make_member("ops-dashboard-manager", makerspace)

    response = authenticated_client(manager).get(dashboard_url(makerspace))

    assert response.status_code == 200
    assert set(response.data) == set(views_dashboard.DashboardSerializer().fields)
    assert all(isinstance(value, int) for value in response.data.values())


def test_pending_payments_are_manager_only_and_ignore_dates_or_modules():
    makerspace = make_space("ops-dashboard-payments")
    manager = make_member("ops-dashboard-payments-manager", makerspace)
    machine_manager = make_member(
        "ops-dashboard-payments-machine-manager",
        makerspace,
        membership_role=MakerspaceMembership.Role.MACHINE_MANAGER,
        role=User.Role.REQUESTER,
    )
    now = timezone.now()
    bookable = BookableSpace.objects.create(
        makerspace=makerspace, name="Dashboard paid space", created_by=manager
    )
    booking = Booking.objects.create(
        space=bookable, member=manager, name=manager.username,
        email=manager.email or "dashboard-booking@example.test", phone="1",
        starts_at=now + timedelta(days=1), ends_at=now + timedelta(days=1, hours=1),
    )
    event = Event.objects.create(
        makerspace=makerspace, title="Dashboard paid event",
        starts_at=now + timedelta(days=1), ends_at=now + timedelta(days=1, hours=1),
        created_by=manager,
    )
    registration = EventRegistration.objects.create(
        event=event, member=manager, name=manager.username,
        email=manager.email or "dashboard-event@example.test", phone="1",
    )
    Payment.objects.create(
        makerspace=makerspace,
        subject_type=Payment.SubjectType.BOOKING,
        subject_id=booking.pk,
        member=manager,
        amount="8.00",
        currency="usd",
        created_by=manager,
    )
    Payment.objects.create(
        makerspace=makerspace,
        subject_type=Payment.SubjectType.EVENT_REGISTRATION,
        subject_id=registration.pk,
        member=manager,
        amount="9.00",
        currency="usd",
        status=Payment.Status.PAID_ONLINE,
        created_by=manager,
    )

    manager_response = authenticated_client(manager).get(dashboard_url(makerspace))
    machine_response = authenticated_client(machine_manager).get(dashboard_url(makerspace))

    assert manager_response.data["pending_payments"] == 1
    assert "pending_payments" not in machine_response.data


def test_dashboard_rejects_guest_non_member_and_archived_makerspace():
    makerspace = make_space("ops-dashboard-rbac")
    other = make_space("ops-dashboard-other")
    archived = make_space("ops-dashboard-archived")
    archived.archived_at = timezone.now()
    archived.save(update_fields=["archived_at"])
    guest = make_handout_member("ops-dashboard-guest", makerspace)
    non_member = make_user("ops-dashboard-non-member", access_status=User.AccessStatus.ACTIVE)
    archived_manager = make_member("ops-dashboard-archived-manager", archived)

    assert authenticated_client(guest).get(dashboard_url(makerspace)).status_code == 403
    assert authenticated_client(non_member).get(dashboard_url(makerspace)).status_code == 404
    assert authenticated_client(archived_manager).get(dashboard_url(archived)).status_code == 404
    assert authenticated_client(make_member("ops-dashboard-other-manager", other)).get(
        dashboard_url(makerspace)
    ).status_code == 404


def test_dashboard_counts_are_tenant_scoped_and_count_only_categories():
    makerspace = make_space("ops-dashboard-counts")
    other = make_space("ops-dashboard-counts-other")
    manager = make_member("ops-dashboard-counts-manager", makerspace)
    requester = make_user("ops-dashboard-counts-requester", access_status=User.AccessStatus.ACTIVE)
    other_requester = make_user("ops-dashboard-counts-other-requester", access_status=User.AccessStatus.ACTIVE)
    now = timezone.now()

    HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=requester.username,
        status=HardwareRequest.Status.PENDING_APPROVAL,
    )
    HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=requester.username,
        status=HardwareRequest.Status.ACCEPTED,
    )
    HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=requester.username,
        status=HardwareRequest.Status.ISSUED,
        return_due_at=now - timedelta(days=1),
    )
    make_product(makerspace, name="Out of stock", available_quantity=0)
    problem_product = make_product(makerspace, name="Problem tool")
    problem_request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=requester.username,
        status=HardwareRequest.Status.RETURNED,
    )
    problem_loan = PublicToolLoan.objects.create(
        makerspace=makerspace,
        request=problem_request,
        requester=requester,
        target_type="product",
        target_id=problem_product.id,
        target_label=problem_product.name,
        status=PublicToolLoan.Status.RETURNED,
        returned_at=now,
    )
    PublicProblemReport.objects.create(
        makerspace=makerspace,
        loan=problem_loan,
        request=problem_request,
        requester=requester,
        note="It was not working.",
    )
    direct_request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=requester.username,
        status=HardwareRequest.Status.ISSUED,
    )
    PublicToolLoan.objects.create(
        makerspace=makerspace,
        request=direct_request,
        requester=requester,
        target_type="product",
        target_id=problem_product.id,
        target_label=problem_product.name,
        due_at=now - timedelta(days=1),
        returned_at=None,
    )
    StocktakeSession.objects.create(
        makerspace=makerspace,
        status=StocktakeSession.Status.COMPLETED,
        started_by=manager,
    )
    EmailLog.objects.create(
        makerspace=makerspace,
        to_email="borrower@example.com",
        subject="Failed",
        status=EmailLog.Status.FAILED,
    )
    printer_type = MachineType.objects.get(makerspace__isnull=True, slug="3d_printer")
    queue = ServiceQueue.objects.create(
        makerspace=makerspace,
        machine_type=printer_type,
        name="General print queue",
    )
    for status, title in (
        (MachineServiceRequest.Status.PENDING, "Queued print"),
        (MachineServiceRequest.Status.IN_PROGRESS, "Running print"),
        (MachineServiceRequest.Status.COMPLETED, "Finished print"),
    ):
        MachineServiceRequest.objects.create(
            makerspace=makerspace,
            queue=queue,
            requester=requester,
            requester_name=requester.username,
            title=title,
            status=status,
        )
    HardwareRequest.objects.create(
        makerspace=other,
        requester=other_requester,
        requester_username=other_requester.username,
        status=HardwareRequest.Status.PENDING_APPROVAL,
    )
    make_product(other, name="Other out of stock", available_quantity=0)
    StocktakeSession.objects.create(
        makerspace=other,
        status=StocktakeSession.Status.COMPLETED,
    )
    EmailLog.objects.create(
        makerspace=other,
        to_email="other@example.com",
        subject="Failed",
        status=EmailLog.Status.FAILED,
    )

    response = authenticated_client(manager).get(dashboard_url(makerspace))

    assert response.status_code == 200
    assert response.data["pending_requests"] == 1
    assert response.data["awaiting_issue"] == 1
    assert response.data["overdue_loans"] == 2
    assert response.data["open_problem_reports"] == 1
    assert response.data["low_stock"] == 1
    assert response.data["stocktakes_awaiting_approval"] == 1
    assert response.data["failed_emails"] == 1
    assert response.data["pending_prints"] == 1
    assert response.data["active_prints"] == 1
    assert response.data["prints_awaiting_collection"] == 1


def test_build_dashboard_is_fail_safe(monkeypatch):
    makerspace = make_space("ops-dashboard-fail-safe")

    class BrokenManager:
        def filter(self, *args, **kwargs):
            raise RuntimeError("database unavailable")

    class BrokenHardwareRequest:
        objects = BrokenManager()

        class Status:
            ISSUED = "issued"
            PARTIALLY_RETURNED = "partially_returned"
            PENDING_APPROVAL = "pending_approval"
            ACCEPTED = "accepted"

    monkeypatch.setattr(views_dashboard, "HardwareRequest", BrokenHardwareRequest)

    counts = views_dashboard.build_dashboard(makerspace)

    assert set(counts) == set(views_dashboard.DashboardSerializer().fields)
    assert counts["overdue_loans"] == 0
    assert counts["pending_requests"] == 0
    assert counts["awaiting_issue"] == 0


def test_dashboard_counts_only_tenant_active_strictly_overdue_maintenance():
    makerspace = make_space("ops-dashboard-maintenance")
    other = make_space("ops-dashboard-maintenance-other")
    today = timezone.localdate()
    machine_type = MachineType.objects.create(
        makerspace=makerspace, slug="dashboard-maintenance", name="Maintenance",
    )
    other_type = MachineType.objects.create(
        makerspace=other, slug="dashboard-maintenance-other", name="Maintenance",
    )
    machine = Machine.objects.create(
        makerspace=makerspace, machine_type=machine_type, name="Machine",
    )
    other_machine = Machine.objects.create(
        makerspace=other, machine_type=other_type, name="Other Machine",
    )
    for due, active in (
        (today - timedelta(days=1), True),
        (today, True),
        (today + timedelta(days=1), True),
        (today - timedelta(days=1), False),
    ):
        MaintenanceSchedule.objects.create(
            machine=machine, description="Schedule", interval_days=1,
            next_due=due, is_active=active,
        )
    MaintenanceSchedule.objects.create(
        machine=other_machine, description="Foreign", interval_days=1,
        next_due=today - timedelta(days=1),
    )
    assert views_dashboard.build_dashboard(makerspace)["maintenance_overdue"] == 1


def test_disabled_maintenance_dashboard_does_not_query(monkeypatch):
    makerspace = make_space("ops-dashboard-maintenance-disabled")
    makerspace.enabled_modules = [
        name for name in makerspace.enabled_modules if name != "maintenance"
    ]
    makerspace.save(update_fields=["enabled_modules"])

    class BrokenSchedule:
        class BrokenManager:
            def filter(self, *args, **kwargs):
                raise AssertionError("maintenance query must stay gated")

        objects = BrokenManager()

    import apps.maintenance.models as maintenance_models

    monkeypatch.setattr(maintenance_models, "MaintenanceSchedule", BrokenSchedule)
    assert views_dashboard.build_dashboard(makerspace)["maintenance_overdue"] == 0


def test_enabled_maintenance_query_failure_is_isolated(monkeypatch):
    makerspace = make_space("ops-dashboard-maintenance-failure")

    class BrokenSchedule:
        class BrokenManager:
            def filter(self, *args, **kwargs):
                raise RuntimeError("maintenance table unavailable")

        objects = BrokenManager()

    import apps.maintenance.models as maintenance_models

    monkeypatch.setattr(maintenance_models, "MaintenanceSchedule", BrokenSchedule)
    counts = views_dashboard.build_dashboard(makerspace)
    assert counts["maintenance_overdue"] == 0
    assert set(counts) == set(views_dashboard.DashboardSerializer().fields)
