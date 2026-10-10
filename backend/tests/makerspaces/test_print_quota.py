"""The makerspace print allowance counts this month's built-in printer jobs only."""

from datetime import UTC, datetime, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.machines.models import MachineServiceRequest, MachineType, ServiceQueue
from apps.makerspaces import limits
from tests.module_helpers import disable_module
from tests.return_helpers import authenticated_client, make_space, make_user

pytestmark = pytest.mark.django_db


def setup_prints(slug):
    space = make_space(slug)
    # A print proposal is available to active accounts on the membership-off profile.
    disable_module(space, "membership")
    space.resource_limit_overrides = {"print": 1}
    space.save(update_fields=["resource_limit_overrides"])
    requester = make_user(f"{slug}-requester", access_status="active")
    printer_type = MachineType.objects.get(makerspace__isnull=True, slug="3d_printer")
    queue = ServiceQueue.objects.create(
        makerspace=space, machine_type=printer_type, name="Public print queue"
    )
    return space, requester, queue


def seed_request(space, queue, requester, **values):
    return MachineServiceRequest.objects.create(
        makerspace=space, queue=queue, requester=requester,
        requester_name="Requester", title="Existing job", **values,
    )


def submit_print(space, requester, queue):
    return authenticated_client(requester).post(
        reverse("public-printer-service-request", args=[space.slug]),
        {"queue_id": queue.pk, "title": "New print"}, format="json",
        HTTP_HOST="localhost",
    )


def test_managed_print_cap_refuses_a_second_request_without_an_audit(settings):
    settings.PLATFORM_DOMAIN_SUFFIX = ".space-works.tech"
    space, requester, queue = setup_prints("print-quota-managed")

    first = submit_print(space, requester, queue)
    second = submit_print(space, requester, queue)

    assert first.status_code == 201, first.data
    assert second.status_code == 400, second.data
    assert "limit" in second.data
    assert second.data["limit"].code == "limit_reached"
    assert MachineServiceRequest.objects.filter(makerspace=space).count() == 1
    entry = AuditLog.objects.get(action="machine_service.submitted", makerspace=space)
    assert entry.actor_id == requester.pk


def test_self_host_print_submissions_ignore_managed_caps(settings):
    settings.PLATFORM_DOMAIN_SUFFIX = ""
    space, requester, queue = setup_prints("print-quota-self")

    responses = [submit_print(space, requester, queue) for _ in range(2)]

    assert [response.status_code for response in responses] == [201, 201]
    assert MachineServiceRequest.objects.filter(makerspace=space).count() == 2


def test_tenant_type_slug_collision_does_not_spend_the_print_allowance(settings):
    settings.PLATFORM_DOMAIN_SUFFIX = ".space-works.tech"
    space, requester, queue = setup_prints("print-quota-collision")
    local_type = MachineType.objects.create(
        makerspace=space, slug="3d_printer", name="Custom service type"
    )
    local_queue = ServiceQueue.objects.create(
        makerspace=space, machine_type=local_type, name="Custom queue"
    )
    seed_request(space, local_queue, requester)

    assert limits._print_requests(space) == 0
    response = submit_print(space, requester, queue)

    assert response.status_code == 201, response.data
    assert limits._print_requests(space) == 1


def test_print_usage_is_tenant_scoped_and_resets_at_the_utc_month_boundary():
    space, requester, queue = setup_prints("print-quota-month")
    now = timezone.now()
    start = datetime(now.year, now.month, 1, tzinfo=UTC)
    next_month = (
        datetime(now.year + 1, 1, 1, tzinfo=UTC)
        if now.month == 12 else datetime(now.year, now.month + 1, 1, tzinfo=UTC)
    )
    for created_at in (start - timedelta(microseconds=1), next_month):
        row = seed_request(space, queue, requester)
        MachineServiceRequest.objects.filter(pk=row.pk).update(created_at=created_at)
    other = make_space("print-quota-other")
    other_queue = ServiceQueue.objects.create(
        makerspace=other, machine_type=queue.machine_type, name="Other queue"
    )
    seed_request(other, other_queue, requester)
    assert limits._print_requests(space) == 0

    # Rejected jobs still used the monthly submission allowance.
    row = seed_request(space, queue, requester, status=MachineServiceRequest.Status.REJECTED)
    MachineServiceRequest.objects.filter(pk=row.pk).update(created_at=start)
    assert limits._print_requests(space) == 1


def test_missing_global_printer_type_leaves_no_print_usage():
    space = make_space("print-quota-no-global")
    requester = make_user("print-quota-no-global-requester")
    MachineType.objects.get(makerspace__isnull=True, slug="3d_printer").delete()
    local_type = MachineType.objects.create(
        makerspace=space, slug="3d_printer", name="Custom service type"
    )
    local_queue = ServiceQueue.objects.create(
        makerspace=space, machine_type=local_type, name="Custom queue"
    )
    seed_request(space, local_queue, requester)

    assert limits._print_requests(space) == 0
