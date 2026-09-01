import uuid

import pytest
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace

pytestmark = pytest.mark.django_db


def make_user(username, **kwargs):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@e.com",
        access_status=User.AccessStatus.ACTIVE,
        **kwargs,
    )


def make_superadmin(username="hardware-action-superadmin"):
    return make_user(
        username,
        role=User.Role.SUPERADMIN,
        is_staff=True,
        is_superuser=True,
    )


def make_hardware_request(status=HardwareRequest.Status.PENDING_APPROVAL):
    makerspace = Makerspace.objects.create(
        name=f"Admin Hardware {uuid.uuid4().hex[:8]}",
        slug=f"admin-hardware-{uuid.uuid4().hex[:8]}",
    )
    requester = make_user(
        f"admin-hardware-requester-{uuid.uuid4().hex[:8]}",
    )
    product = InventoryProduct.objects.create(
        makerspace=makerspace,
        name=f"Logic Analyzer {uuid.uuid4().hex[:8]}",
        description="Bench diagnostics",
        total_quantity=5,
        available_quantity=5,
        reserved_quantity=0,
        is_public=True,
        is_archived=False,
    )
    hardware_request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=requester.username,
        status=status,
    )
    HardwareRequestItem.objects.create(
        request=hardware_request,
        product=product,
        requested_quantity=1,
    )
    return hardware_request


def admin_client(user):
    client = Client()
    client.force_login(user)
    return client


def changelist_url():
    return reverse("admin:hardware_requests_hardwarerequest_changelist")


def action_payload(action, hardware_request, **extra):
    return {
        "action": action,
        ACTION_CHECKBOX_NAME: [str(hardware_request.pk)],
        **extra,
    }


def review_url(hardware_request):
    return reverse(
        "admin:hardware_requests_hardwarerequest_review", args=[hardware_request.pk]
    )


def test_the_bulk_accept_and_reject_actions_no_longer_exist():
    """Accepting reserves stock and rejecting closes a person's ask. Neither is a
    checkbox-column decision any more -- both moved to the one-by-one review page."""
    superadmin = make_superadmin("hardware-no-bulk-superadmin")
    hardware_request = make_hardware_request()

    for action in ("accept_selected", "reject_selected"):
        response = admin_client(superadmin).post(
            changelist_url(), action_payload(action, hardware_request), follow=True
        )
        hardware_request.refresh_from_db()
        assert hardware_request.status == HardwareRequest.Status.PENDING_APPROVAL, action
        messages = [str(message) for message in get_messages(response.wsgi_request)]
        assert "No action selected." in messages, action


def test_the_review_page_accepts_one_request():
    superadmin = make_superadmin()
    hardware_request = make_hardware_request()

    response = admin_client(superadmin).post(review_url(hardware_request), {"accept": "1"})

    assert response.status_code == 302
    hardware_request.refresh_from_db()
    assert hardware_request.status == HardwareRequest.Status.ACCEPTED


def test_the_review_page_honours_a_lowered_accepted_quantity():
    superadmin = make_superadmin("hardware-partial-superadmin")
    hardware_request = make_hardware_request()
    item = hardware_request.items.get()
    item.requested_quantity = 3
    item.save(update_fields=["requested_quantity"])

    response = admin_client(superadmin).post(
        review_url(hardware_request),
        {"accept": "1", f"accepted_quantity_{item.pk}": "2"},
    )

    assert response.status_code == 302
    item.refresh_from_db()
    assert item.accepted_quantity == 2


def test_the_review_page_refuses_a_quantity_above_what_was_requested():
    superadmin = make_superadmin("hardware-overrequest-superadmin")
    hardware_request = make_hardware_request()
    item = hardware_request.items.get()

    response = admin_client(superadmin).post(
        review_url(hardware_request),
        {"accept": "1", f"accepted_quantity_{item.pk}": "99"},
        follow=True,
    )

    hardware_request.refresh_from_db()
    assert hardware_request.status == HardwareRequest.Status.PENDING_APPROVAL
    messages = [str(message) for message in get_messages(response.wsgi_request)]
    assert any("must be between 0 and" in message for message in messages)


def test_the_review_page_refuses_a_non_numeric_quantity():
    """Parsed here rather than handed to the workflow, so a malformed field is an error
    on the page instead of a 500 inside the service."""
    superadmin = make_superadmin("hardware-nan-superadmin")
    hardware_request = make_hardware_request()
    item = hardware_request.items.get()

    response = admin_client(superadmin).post(
        review_url(hardware_request),
        {"accept": "1", f"accepted_quantity_{item.pk}": "two"},
        follow=True,
    )

    hardware_request.refresh_from_db()
    assert hardware_request.status == HardwareRequest.Status.PENDING_APPROVAL
    messages = [str(message) for message in get_messages(response.wsgi_request)]
    assert any("whole number" in message for message in messages)


def test_the_review_page_rejects_with_a_reason():
    superadmin = make_superadmin("hardware-reject-superadmin")
    hardware_request = make_hardware_request()

    response = admin_client(superadmin).post(
        review_url(hardware_request),
        {"reject": "1", "reason": "Unavailable this week."},
    )

    assert response.status_code == 302
    hardware_request.refresh_from_db()
    assert hardware_request.status == HardwareRequest.Status.REJECTED
    assert hardware_request.rejection_reason == "Unavailable this week."


def test_the_review_page_refuses_to_reject_without_a_reason():
    superadmin = make_superadmin("hardware-empty-reject-superadmin")
    hardware_request = make_hardware_request()

    response = admin_client(superadmin).post(
        review_url(hardware_request),
        {"reject": "1", "reason": "   "},
        follow=True,
    )

    hardware_request.refresh_from_db()
    assert hardware_request.status == HardwareRequest.Status.PENDING_APPROVAL
    messages = [str(message) for message in get_messages(response.wsgi_request)]
    assert "Rejection reason is required." in messages


def test_the_review_page_is_closed_to_a_non_superadmin():
    """`admin_site.admin_view` plus the model's superuser gate. Without both, this URL
    would be the one state-changing surface that skipped them."""
    staffer = make_user("hardware-review-staffer", is_staff=True)
    hardware_request = make_hardware_request()

    response = admin_client(staffer).get(review_url(hardware_request))

    assert response.status_code in (302, 403, 404)
    hardware_request.refresh_from_db()
    assert hardware_request.status == HardwareRequest.Status.PENDING_APPROVAL
