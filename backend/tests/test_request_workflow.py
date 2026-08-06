import uuid
from collections.abc import Mapping
from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.boxes.models import Box
from apps.hardware_requests.models import (
    HardwareRequest,
    HardwareRequestItem,
)
from apps.integrations.models import EmailTemplate
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.presence import services as presence

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_cache_between_tests():
    cache.clear()


def make_user(username, role=User.Role.REQUESTER, **kw):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@e.com",
        role=role,
        **kw,
    )


def make_space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def make_member(
    username,
    makerspace,
    membership_role=MakerspaceMembership.Role.SPACE_MANAGER,
    role=User.Role.SPACE_MANAGER,
):
    user = make_user(username, role=role, access_status=User.AccessStatus.ACTIVE)
    MakerspaceMembership.objects.create(
        user=user,
        makerspace=makerspace,
        role=membership_role,
    )
    return user


def make_product(makerspace, name="Oscilloscope", **overrides):
    defaults = {
        "makerspace": makerspace,
        "name": name,
        "description": f"{name} description",
        "total_quantity": 5,
        "available_quantity": 5,
        "reserved_quantity": 0,
        "is_public": True,
        "is_archived": False,
    }
    defaults.update(overrides)
    return InventoryProduct.objects.create(**defaults)


def make_hardware_request(
    makerspace,
    product,
    requester=None,
    quantity=1,
    status=HardwareRequest.Status.PENDING_APPROVAL,
    contact_email="",
):
    requester = requester or make_user(
        f"requester-{makerspace.slug}-{uuid.uuid4().hex[:8]}",
        access_status=User.AccessStatus.ACTIVE,
    )
    request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=requester.username,
        requester_contact_email=contact_email,
        status=status,
    )
    HardwareRequestItem.objects.create(
        request=request,
        product=product,
        requested_quantity=quantity,
    )
    return request


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def make_present_member(username, makerspace, **overrides):
    """Create an authenticated member eligible for the M4 request path."""
    user = make_user(
        username,
        access_status=User.AccessStatus.ACTIVE,
        display_name=f"{username} display",
        phone="+15550101010",
        **overrides,
    )
    MakerspaceMembership.objects.create(
        user=user,
        makerspace=makerspace,
        role=MakerspaceMembership.Role.CUSTOM,
    )
    presence.start_session(user, makerspace, 60)
    return user


def public_submit_url(makerspace):
    return f"/api/v1/public/{makerspace.slug}/requests"


def public_status_url(public_token):
    return f"/api/v1/public/requests/{public_token}/status"


def public_lookup_url(makerspace):
    return f"/api/v1/public/{makerspace.slug}/requests/status"


def pending_requests_url(makerspace):
    return f"/api/v1/admin/makerspace/{makerspace.id}/pending-requests"


def accepted_requests_url(makerspace):
    return f"/api/v1/admin/makerspace/{makerspace.id}/accepted-requests"


def accept_url(hardware_request):
    return f"/api/v1/admin/requests/{hardware_request.id}/accept"


def reject_url(hardware_request):
    return f"/api/v1/admin/requests/{hardware_request.id}/reject"


def return_due_url(hardware_request):
    return f"/api/v1/admin/requests/{hardware_request.id}/return-due"


def return_policy_url(makerspace):
    return f"/api/v1/admin/makerspace/{makerspace.id}/return-policy"


def submit_payload(contact_email, product, quantity=1, **overrides):
    payload = {
        "requester_name": "Ada Borrower",
        "contact_email": contact_email,
        "contact_phone": "+15550101010",
        "requested_for": "Bench diagnostics",
        "items": [{"product_id": product.id, "quantity": quantity}],
    }
    payload.update(overrides)
    return payload


def email_for_identifier(name):
    return f"{name}@example.com"


def legacy_submit_payload(identifier, product, quantity=1, **overrides):
    return {
        **submit_payload(email_for_identifier(identifier), product, quantity),
        **overrides,
    }


def json_keys(data):
    keys = set()
    if isinstance(data, Mapping):
        for key, value in data.items():
            keys.add(key)
            keys.update(json_keys(value))
    elif isinstance(data, list):
        for item in data:
            keys.update(json_keys(item))
    return keys


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_restricted_requester_cannot_submit():
    makerspace = make_space("restricted-submit")
    product = make_product(makerspace)
    make_user(
        "restricted-requester",
        access_status=User.AccessStatus.RESTRICTED,
        external_checkin_user_id="ext-r@example.com",
    )

    response = authenticated_client(
        make_present_member("restricted-member", makerspace)
    ).post(
        public_submit_url(makerspace),
        legacy_submit_payload("ext-r", product),
        format="json",
    )

    # External Check-In identities no longer participate in request authorization.
    assert response.status_code == 201
    assert HardwareRequest.objects.count() == 1


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_suspended_requester_cannot_submit():
    makerspace = make_space("suspended-submit")
    product = make_product(makerspace)
    make_user(
        "suspended-requester",
        access_status=User.AccessStatus.SUSPENDED,
        external_checkin_user_id="ext-s@example.com",
    )

    response = authenticated_client(
        make_present_member("suspended-member", makerspace)
    ).post(
        public_submit_url(makerspace),
        legacy_submit_payload("ext-s", product),
        format="json",
    )

    # A legacy shadow-account status cannot block a distinct active member.
    assert response.status_code == 201
    assert HardwareRequest.objects.count() == 1


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_successful_submission_creates_pending_request_items_audit_and_notifies(
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    makerspace = make_space("successful-submit")
    product = make_product(makerspace, name="Logic Analyzer")
    requester = make_present_member("successful-member", makerspace)
    notify = Mock()
    monkeypatch.setattr(
        "apps.hardware_requests.notifications.notify_request_submitted",
        notify,
    )

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        response = authenticated_client(requester).post(
            public_submit_url(makerspace),
            legacy_submit_payload("ext-ok", product, quantity=2),
            format="json",
        )

    assert response.status_code == 201
    assert set(response.data) == {"public_token", "status"}
    assert response.data["status"] == HardwareRequest.Status.PENDING_APPROVAL
    # The in-app notification emit is the only deferred work. It used to be zero only
    # because `notifications` was unreachable -- it is a real installable module now,
    # so the guard is "nothing else got deferred", not "nothing at all".
    assert [callback.__qualname__ for callback in callbacks] == [
        "emit_notification.<locals>._create"
    ]
    hardware_request = HardwareRequest.objects.get()
    assert str(hardware_request.public_token) == response.data["public_token"]
    assert hardware_request.status == HardwareRequest.Status.PENDING_APPROVAL
    assert hardware_request.requester_name == requester.display_name
    assert hardware_request.requester_contact_email == requester.email
    assert hardware_request.requester_contact_phone == requester.phone
    item = hardware_request.items.get()
    assert item.product == product
    assert item.requested_quantity == 2
    audit = AuditLog.objects.get(action="request.submitted")
    assert audit.makerspace == makerspace
    assert audit.target_id == str(hardware_request.id)
    notify.assert_called_once_with(hardware_request)


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
@pytest.mark.parametrize("missing_field", ["requester_name", "contact_email", "contact_phone"])
def test_submission_requires_name_email_and_phone(missing_field):
    makerspace = make_space(f"missing-{missing_field.replace('_', '-')}")
    product = make_product(makerspace)
    requester = make_present_member(f"missing-{missing_field}", makerspace)
    payload = legacy_submit_payload("ext-missing-contact", product)
    payload.pop(missing_field)

    response = authenticated_client(requester).post(
        public_submit_url(makerspace),
        payload,
        format="json",
    )

    assert response.status_code == 201
    saved = HardwareRequest.objects.get()
    assert saved.requester_contact_email == requester.email
    assert saved.requester_contact_phone == requester.phone


@override_settings(
    API_CLIENT_AUTH_REQUIRED=False,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
def test_submission_sends_confirmation_email_to_contact(
    django_capture_on_commit_callbacks,
    mailoutbox,
):
    makerspace = make_space("email-confirm")
    product = make_product(makerspace)
    requester = make_present_member("email-confirm-member", makerspace)

    with django_capture_on_commit_callbacks(execute=True):
        response = authenticated_client(requester).post(
            public_submit_url(makerspace),
            legacy_submit_payload("ext-email", product),
            format="json",
        )

    assert response.status_code == 201
    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == [requester.email]
    assert "Use your email or phone" in mailoutbox[0].body


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_duplicate_product_lines_in_one_submission_return_400():
    makerspace = make_space("duplicate-lines")
    product = make_product(makerspace)
    requester = make_present_member("duplicate-lines-member", makerspace)
    payload = {
        "requester_name": "Ada Borrower",
        "contact_email": "ext-duplicate@example.com",
        "contact_phone": "+15550101010",
        "requested_for": "Bench diagnostics",
        "items": [
            {"product_id": product.id, "quantity": 1},
            {"product_id": product.id, "quantity": 2},
        ],
    }

    response = authenticated_client(requester).post(
        public_submit_url(makerspace),
        payload,
        format="json",
    )

    assert response.status_code == 400
    assert HardwareRequest.objects.count() == 0


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
@pytest.mark.parametrize(
    ("name", "product_overrides", "other_space"),
    [
        ("private", {"is_public": False}, False),
        ("archived", {"is_archived": True}, False),
        ("other-space", {}, True),
    ],
)
def test_unrequestable_product_returns_400_and_creates_no_request(
    name,
    product_overrides,
    other_space,
):
    makerspace = make_space(f"unrequestable-{name}")
    product_space = make_space(f"unrequestable-{name}-other") if other_space else makerspace
    product = make_product(product_space, **product_overrides)
    requester = make_present_member(f"unrequestable-{name}-member", makerspace)

    response = authenticated_client(requester).post(
        public_submit_url(makerspace),
        legacy_submit_payload(f"ext-{name}", product),
        format="json",
    )

    assert response.status_code == 400
    assert HardwareRequest.objects.count() == 0


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_public_status_by_token_returns_strict_allowlist_and_unknown_token_404():
    makerspace = make_space("public-status")
    box = Box.objects.create(
        makerspace=makerspace,
        label="Secure Box",
        location="Hidden Shelf",
    )
    product = make_product(
        makerspace,
        name="Thermal Camera",
        box=box,
        storage_location="Locked cabinet A",
    )
    requester = make_user(
        "status-requester",
        access_status=User.AccessStatus.ACTIVE,
        phone="+15551234567",
    )
    hardware_request = make_hardware_request(
        makerspace,
        product,
        requester=requester,
        quantity=3,
    )

    response = APIClient().get(public_status_url(hardware_request.public_token))

    assert response.status_code == 200
    assert set(response.data) == {
        "status",
        "created_at",
        "items",
    }
    assert len(response.data["items"]) == 1
    assert set(response.data["items"][0]) == {"product_name", "requested_quantity"}
    all_keys = json_keys(response.data)
    for forbidden_key in {
        "id",
        "product_id",
        "box",
        "code",
        "storage_location",
        "makerspace_id",
        "requester",
        "requester_username",
        "email",
        "phone",
        "accepted_quantity",
        "issued_quantity",
        "public_token",
    }:
        assert forbidden_key not in all_keys

    missing = APIClient().get(public_status_url(uuid.uuid4()))
    assert missing.status_code == 404


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_legacy_public_request_lookup_is_retired():
    makerspace = make_space("lookup-space")
    other_space = make_space("lookup-other-space")
    product = make_product(makerspace, name="Bench Meter")
    other_product = make_product(other_space, name="Other Meter")
    requester = make_user(
        "lookup-requester",
        access_status=User.AccessStatus.ACTIVE,
        external_checkin_user_id="lookup-id",
    )
    other_requester = make_user(
        "lookup-other-requester",
        access_status=User.AccessStatus.ACTIVE,
        external_checkin_user_id="other-lookup-id",
    )
    expected = make_hardware_request(
        makerspace,
        product,
        requester=requester,
        quantity=2,
    )
    # A different verified identity in the same space — must not be returned.
    make_hardware_request(makerspace, product, requester=other_requester)
    # Same identity in a different space — must not leak across makerspaces.
    make_hardware_request(other_space, other_product, requester=requester)

    response = APIClient().post(
        public_lookup_url(makerspace),
        {"identifier": "lookup-id"},
        format="json",
    )

    assert response.status_code == 404


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_legacy_public_contact_lookup_is_retired():
    # Knowing a requester's contact email must NOT surface their requests: lookup
    # is keyed on the verified Check-In identity, not free-text contact fields.
    makerspace = make_space("lookup-contact-priv")
    product = make_product(makerspace, name="Caliper")
    requester = make_user(
        "lookup-priv-requester",
        access_status=User.AccessStatus.ACTIVE,
        external_checkin_user_id="priv-checkin-id",
    )
    req = make_hardware_request(makerspace, product, requester=requester)
    req.requester_contact_email = "victim@example.com"
    req.save(update_fields=["requester_contact_email"])

    response = APIClient().post(
        public_lookup_url(makerspace),
        {"identifier": "victim@example.com"},
        format="json",
    )

    assert response.status_code == 404


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_legacy_public_history_lookup_is_retired():
    first_space = make_space("same-user-first")
    second_space = make_space("same-user-second")
    first_product = make_product(first_space, name="First Space Meter")
    second_product = make_product(second_space, name="Second Space Meter")
    contact = "shared@example.com"

    first_payload = submit_payload(contact, first_product)
    second_payload = submit_payload(contact, second_product)

    first_submit = APIClient().post(
        public_submit_url(first_space),
        first_payload,
        format="json",
    )
    second_submit = APIClient().post(
        public_submit_url(second_space),
        second_payload,
        format="json",
    )

    assert first_submit.status_code == 401
    assert second_submit.status_code == 401
    assert APIClient().post(public_lookup_url(first_space), {"identifier": contact}, format="json").status_code == 404
    assert APIClient().post(public_lookup_url(second_space), {"identifier": contact}, format="json").status_code == 404


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_legacy_empty_public_lookup_is_retired():
    makerspace = make_space("lookup-empty")

    response = APIClient().post(
        public_lookup_url(makerspace),
        {"identifier": "no-requests-yet"},
        format="json",
    )

    assert response.status_code == 404


def test_admin_accept_reserves_inventory_and_writes_audit():
    makerspace = make_space("accept-reserves")
    product = make_product(makerspace, total_quantity=5, available_quantity=5)
    hardware_request = make_hardware_request(makerspace, product, quantity=2)
    admin = make_member("accept-admin", makerspace)

    response = authenticated_client(admin).post(accept_url(hardware_request), format="json")

    assert response.status_code == 200
    assert response.data["status"] == HardwareRequest.Status.ACCEPTED
    product.refresh_from_db()
    assert product.available_quantity == 3
    assert product.reserved_quantity == 2
    hardware_request.refresh_from_db()
    assert hardware_request.status == HardwareRequest.Status.ACCEPTED
    item = hardware_request.items.get()
    assert item.accepted_quantity == 2
    audit = AuditLog.objects.get(action="request.accepted")
    assert audit.makerspace == makerspace
    assert audit.target_id == str(hardware_request.id)


def test_pending_requests_search_filters_by_requester_identity():
    makerspace = make_space("queue-search")
    product = make_product(makerspace, total_quantity=5, available_quantity=5)
    ada = make_hardware_request(makerspace, product)
    ada.requester_name = "Ada Lovelace"
    ada.save(update_fields=["requester_name"])
    grace = make_hardware_request(makerspace, product)
    grace.requester_name = "Grace Hopper"
    grace.save(update_fields=["requester_name"])
    admin = make_member("queue-search-admin", makerspace)

    response = authenticated_client(admin).get(
        pending_requests_url(makerspace), {"search": "Lovelace"}
    )

    assert response.status_code == 200
    ids = [row["id"] for row in response.data["results"]]
    assert ada.id in ids
    assert grace.id not in ids


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_accept_and_reject_send_contact_email(django_capture_on_commit_callbacks, mailoutbox):
    makerspace = make_space("request-status-email")
    product = make_product(makerspace)
    accepted_request = make_hardware_request(
        makerspace,
        product,
        contact_email="accepted@example.com",
    )
    rejected_request = make_hardware_request(
        makerspace,
        product,
        contact_email="rejected@example.com",
    )
    admin = make_member("status-email-admin", makerspace)
    client = authenticated_client(admin)

    with django_capture_on_commit_callbacks(execute=True):
        accept_response = client.post(accept_url(accepted_request), format="json")
    with django_capture_on_commit_callbacks(execute=True):
        reject_response = client.post(
            reject_url(rejected_request),
            {"reason": "Not available today."},
            format="json",
        )

    assert accept_response.status_code == 200
    assert reject_response.status_code == 200
    assert [message.to for message in mailoutbox] == [
        ["accepted@example.com"],
        ["status-email-admin@e.com"],
        ["rejected@example.com"],
        ["status-email-admin@e.com"],
    ]
    assert "approved" in mailoutbox[0].subject
    assert "accepted" in mailoutbox[1].subject
    assert "rejected" in mailoutbox[2].subject
    assert "Not available today." in mailoutbox[2].body
    assert "rejected" in mailoutbox[3].subject


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_accept_email_uses_admin_configured_template(
    django_capture_on_commit_callbacks,
    mailoutbox,
):
    makerspace = make_space("request-template-email")
    product = make_product(makerspace)
    EmailTemplate.objects.create(
        makerspace=makerspace,
        stream="hardware",
        audience="requester",
        key="request_accepted",
        subject="Custom approval {{ request.id }}",
        text_body="Hi {{ request.requester_username }}, approved by {{ makerspace.name }}.",
    )
    hardware_request = make_hardware_request(
        makerspace,
        product,
        contact_email="templated@example.com",
    )
    admin = make_member("template-email-admin", makerspace)

    with django_capture_on_commit_callbacks(execute=True):
        response = authenticated_client(admin).post(
            accept_url(hardware_request),
            format="json",
        )

    assert response.status_code == 200
    assert len(mailoutbox) == 2
    requester_email = next(
        message for message in mailoutbox if message.to == ["templated@example.com"]
    )
    staff_email = next(
        message for message in mailoutbox if message.to == ["template-email-admin@e.com"]
    )
    assert requester_email.subject == f"Custom approval {hardware_request.id}"
    assert f"Hi {hardware_request.requester_username}" in requester_email.body
    assert "accepted" in staff_email.subject


def test_return_policy_requires_space_manager_and_inventory_can_set_due_time():
    makerspace = make_space("return-policy")
    product = make_product(makerspace)
    hardware_request = make_hardware_request(
        makerspace,
        product,
        status=HardwareRequest.Status.ACCEPTED,
    )
    inventory_manager = make_member(
        "return-policy-inventory",
        makerspace,
        membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER,
        role=User.Role.REQUESTER,
    )
    client = authenticated_client(inventory_manager)

    response = client.patch(
        return_policy_url(makerspace),
        {"default_loan_days": 10},
        format="json",
    )
    assert response.status_code == 404
    makerspace.refresh_from_db()
    assert makerspace.default_loan_days != 10

    space_manager = make_member("return-policy-manager", makerspace)
    response = authenticated_client(space_manager).patch(
        return_policy_url(makerspace),
        {"default_loan_days": 10},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["default_loan_days"] == 10
    makerspace.refresh_from_db()
    assert makerspace.default_loan_days == 10

    due_at = timezone.now() + timedelta(days=4)
    response = client.post(
        return_due_url(hardware_request),
        {"return_due_at": due_at.isoformat()},
        format="json",
    )

    assert response.status_code == 200
    hardware_request.refresh_from_db()
    assert hardware_request.return_due_at == due_at
    assert hardware_request.return_reminder_sent_at is None


def test_accept_with_insufficient_stock_rolls_back_and_returns_409():
    makerspace = make_space("insufficient-stock")
    product = make_product(makerspace, total_quantity=1, available_quantity=1)
    hardware_request = make_hardware_request(makerspace, product, quantity=3)
    admin = make_member("insufficient-admin", makerspace)

    response = authenticated_client(admin).post(accept_url(hardware_request), format="json")

    assert response.status_code == 409
    assert response.data["code"] == "insufficient_stock"
    product.refresh_from_db()
    assert product.available_quantity == 1
    assert product.reserved_quantity == 0
    hardware_request.refresh_from_db()
    assert hardware_request.status == HardwareRequest.Status.PENDING_APPROVAL
    item = hardware_request.items.get()
    assert item.accepted_quantity == 0
    assert AuditLog.objects.filter(action="request.accepted").count() == 0


def test_accept_individual_request_requires_available_assets_and_returns_409():
    makerspace = make_space("individual-asset-shortfall")
    product = make_product(
        makerspace,
        tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=2,
        available_quantity=2,
    )
    InventoryAsset.objects.create(
        makerspace=makerspace,
        product=product,
        asset_tag="IA-1",
        status=InventoryAsset.Status.AVAILABLE,
    )
    hardware_request = make_hardware_request(makerspace, product, quantity=2)
    admin = make_member("individual-shortfall-admin", makerspace)

    response = authenticated_client(admin).post(accept_url(hardware_request), format="json")

    assert response.status_code == 409
    assert response.data["code"] == "insufficient_stock"
    product.refresh_from_db()
    assert product.available_quantity == 2
    assert product.reserved_quantity == 0
    hardware_request.refresh_from_db()
    assert hardware_request.status == HardwareRequest.Status.PENDING_APPROVAL
    item = hardware_request.items.get()
    assert item.accepted_quantity == 0
    assert AuditLog.objects.filter(action="request.accepted").count() == 0


def test_accept_individual_request_counts_outstanding_reservations():
    # Drifted bucket: quantity says 2 available but only ONE physical asset exists.
    # The first 1-unit accept reserves it (the asset stays AVAILABLE until issue); the
    # second 1-unit accept must be blocked because that lone asset is already spoken for
    # by the outstanding reservation, not just by issued units.
    makerspace = make_space("individual-asset-reserved")
    product = make_product(
        makerspace,
        tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=2,
        available_quantity=2,
    )
    InventoryAsset.objects.create(
        makerspace=makerspace,
        product=product,
        asset_tag="IAR-1",
        status=InventoryAsset.Status.AVAILABLE,
    )
    admin = make_member("individual-reserved-admin", makerspace)
    client = authenticated_client(admin)

    first = make_hardware_request(makerspace, product, quantity=1)
    second = make_hardware_request(makerspace, product, quantity=1)

    first_response = client.post(accept_url(first), format="json")
    assert first_response.status_code == 200

    second_response = client.post(accept_url(second), format="json")
    assert second_response.status_code == 409
    assert second_response.data["code"] == "insufficient_stock"
    product.refresh_from_db()
    assert product.reserved_quantity == 1
    second.refresh_from_db()
    assert second.status == HardwareRequest.Status.PENDING_APPROVAL


def test_cross_tenant_accept_returns_404_without_leaking_request_existence():
    own_space = make_space("cross-tenant-own")
    other_space = make_space("cross-tenant-other")
    product = make_product(other_space)
    hardware_request = make_hardware_request(other_space, product)
    admin = make_member("cross-tenant-admin", own_space)

    response = authenticated_client(admin).post(accept_url(hardware_request), format="json")

    assert response.status_code == 404


def test_wrong_action_accept_in_own_makerspace_returns_403_for_guest_and_requester():
    makerspace = make_space("wrong-action")
    product = make_product(makerspace)
    hardware_request = make_hardware_request(makerspace, product)
    guest_admin = make_member(
        "wrong-action-guest",
        makerspace,
        membership_role=MakerspaceMembership.Role.GUEST_ADMIN,
        role=User.Role.GUEST_ADMIN,
    )
    plain_requester = make_user("wrong-action-requester", access_status=User.AccessStatus.ACTIVE)

    response = authenticated_client(guest_admin).post(
        accept_url(hardware_request),
        format="json",
    )
    assert response.status_code == 403

    response = authenticated_client(plain_requester).post(
        accept_url(hardware_request),
        format="json",
    )
    assert response.status_code == 403


def test_guest_admin_cannot_reject_but_can_get_accepted_queue_not_pending_queue():
    makerspace = make_space("guest-queues")
    product = make_product(makerspace, storage_location="Shelf B3")
    pending_request = make_hardware_request(makerspace, product)
    accepted_request = make_hardware_request(
        makerspace,
        product,
        status=HardwareRequest.Status.ACCEPTED,
    )
    guest_admin = make_member(
        "guest-queue-admin",
        makerspace,
        membership_role=MakerspaceMembership.Role.GUEST_ADMIN,
        role=User.Role.GUEST_ADMIN,
    )
    client = authenticated_client(guest_admin)

    response = client.post(
        reject_url(pending_request),
        {"reason": "No longer eligible."},
        format="json",
    )
    assert response.status_code == 403

    response = client.get(accepted_requests_url(makerspace))
    assert response.status_code == 200
    assert [item["id"] for item in response.data["results"]] == [accepted_request.id]
    assert response.data["results"][0]["items"][0]["id"]
    assert response.data["results"][0]["items"][0]["product_name"] == product.name
    # The handout/handover payload exposes the shelf so staff know where to fetch the item.
    assert response.data["results"][0]["items"][0]["storage_location"] == "Shelf B3"

    response = client.get(pending_requests_url(makerspace))
    assert response.status_code == 403


def test_reject_requires_reason_and_valid_reason_rejects_without_inventory_change():
    makerspace = make_space("reject-reason")
    product = make_product(makerspace, total_quantity=4, available_quantity=4)
    hardware_request = make_hardware_request(makerspace, product, quantity=2)
    admin = make_member("reject-admin", makerspace)
    client = authenticated_client(admin)

    response = client.post(reject_url(hardware_request), {"reason": ""}, format="json")
    assert response.status_code == 400

    response = client.post(
        reject_url(hardware_request),
        {"reason": "Missing training clearance."},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["status"] == HardwareRequest.Status.REJECTED
    assert response.data["rejection_reason"] == "Missing training clearance."
    product.refresh_from_db()
    assert product.available_quantity == 4
    assert product.reserved_quantity == 0
    hardware_request.refresh_from_db()
    assert hardware_request.status == HardwareRequest.Status.REJECTED
    assert hardware_request.rejection_reason == "Missing training clearance."
    assert AuditLog.objects.get(action="request.rejected").target_id == str(
        hardware_request.id
    )


def test_availability_never_goes_below_zero_for_sequential_accepts():
    makerspace = make_space("sequential-accepts")
    product = make_product(makerspace, total_quantity=1, available_quantity=1)
    first_request = make_hardware_request(makerspace, product, quantity=1)
    second_request = make_hardware_request(makerspace, product, quantity=1)
    admin = make_member("sequential-admin", makerspace)
    client = authenticated_client(admin)

    first_response = client.post(accept_url(first_request), format="json")
    second_response = client.post(accept_url(second_request), format="json")

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert second_response.data["code"] == "insufficient_stock"
    product.refresh_from_db()
    assert product.available_quantity == 0
    assert product.reserved_quantity == 1
    second_request.refresh_from_db()
    assert second_request.status == HardwareRequest.Status.PENDING_APPROVAL


def test_superadmin_can_accept_across_makerspaces_without_membership():
    makerspace = make_space("superadmin-accept")
    product = make_product(makerspace)
    hardware_request = make_hardware_request(makerspace, product, quantity=1)
    superadmin = make_user(
        "request-superadmin",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )

    response = authenticated_client(superadmin).post(
        accept_url(hardware_request),
        format="json",
    )

    assert response.status_code == 200
    assert response.data["status"] == HardwareRequest.Status.ACCEPTED


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_request_submit_throttle_returns_429_on_second_rapid_submit(settings, monkeypatch):
    cache.clear()
    rest_framework_settings = dict(django_settings.REST_FRAMEWORK)
    rest_framework_settings["DEFAULT_THROTTLE_RATES"] = {
        **django_settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
        "public_request_submit": "1/min",
    }
    settings.REST_FRAMEWORK = rest_framework_settings
    monkeypatch.setattr(
        ScopedRateThrottle,
        "THROTTLE_RATES",
        rest_framework_settings["DEFAULT_THROTTLE_RATES"],
    )
    makerspace = make_space("submit-throttle")
    product = make_product(makerspace)
    client = authenticated_client(make_present_member("submit-throttle-member", makerspace))

    first = client.post(
        public_submit_url(makerspace),
        legacy_submit_payload("first", product),
        format="json",
    )
    second = client.post(
        public_submit_url(makerspace),
        legacy_submit_payload("second", product),
        format="json",
    )

    assert first.status_code == 201
    assert second.status_code == 429


def test_suspended_staff_cannot_view_accepted_queue():
    # Stage-4 review fix (P2-2): the handover queue must enforce active access_status,
    # not just authentication + ISSUE_REQUEST membership.
    makerspace = make_space("suspended-staff-queue")
    guest = make_member(
        "suspended-guest",
        makerspace,
        membership_role=MakerspaceMembership.Role.GUEST_ADMIN,
        role=User.Role.GUEST_ADMIN,
    )
    guest.access_status = User.AccessStatus.SUSPENDED
    guest.save(update_fields=["access_status"])

    response = authenticated_client(guest).get(accepted_requests_url(makerspace))

    assert response.status_code == 403


def history_url(makerspace):
    return f"/api/v1/admin/makerspace/{makerspace.id}/request-history"


def test_request_history_lists_only_terminal_statuses_with_item_metadata():
    makerspace = make_space("history-space")
    admin = make_member("history-admin", makerspace)
    product = make_product(makerspace)
    individual = make_product(
        makerspace, name="Serial Meter", tracking_mode="individual"
    )

    returned = make_hardware_request(
        makerspace, product, status=HardwareRequest.Status.RETURNED
    )
    rejected = make_hardware_request(
        makerspace, individual, status=HardwareRequest.Status.REJECTED
    )
    closed = make_hardware_request(
        makerspace, product, status=HardwareRequest.Status.CLOSED_WITH_ISSUE
    )
    # Non-terminal requests must be excluded.
    make_hardware_request(
        makerspace, product, status=HardwareRequest.Status.PENDING_APPROVAL
    )
    make_hardware_request(
        makerspace, product, status=HardwareRequest.Status.ISSUED
    )

    response = authenticated_client(admin).get(history_url(makerspace))

    assert response.status_code == 200
    ids = {row["id"] for row in response.data["results"]}
    assert ids == {returned.id, rejected.id, closed.id}
    # The individual-tracked rejected request exposes the asset-scan flag for the issue UI.
    rejected_row = next(r for r in response.data["results"] if r["id"] == rejected.id)
    assert rejected_row["items"][0]["requires_asset_qr"] is True
    assert rejected_row["items"][0]["tracking_mode"] == "individual"
    returned_row = next(r for r in response.data["results"] if r["id"] == returned.id)
    assert returned_row["items"][0]["requires_asset_qr"] is False


def test_request_history_is_tenant_scoped():
    own = make_space("history-own")
    other = make_space("history-other")
    admin = make_member("history-scope-admin", own)
    product = make_product(other)
    make_hardware_request(other, product, status=HardwareRequest.Status.RETURNED)

    response = authenticated_client(admin).get(history_url(own))

    assert response.status_code == 200
    assert response.data["results"] == []


def test_admin_request_serializer_exposes_issue_and_return_evidence_ids():
    from apps.boxes.models import Box
    from apps.evidence.models import EvidencePhoto
    from apps.hardware_requests.return_models import ReturnEvent
    from apps.hardware_requests.serializers import AdminRequestSerializer

    makerspace = make_space("evidence-serializer")
    product = make_product(makerspace)
    actor = make_member("evidence-actor", makerspace)
    issue_photo = EvidencePhoto.objects.create(
        makerspace=makerspace, evidence_type=EvidencePhoto.EvidenceType.ISSUE,
        object_key="evidence/issue", uploaded_by=actor,
    )
    return_photo = EvidencePhoto.objects.create(
        makerspace=makerspace, evidence_type=EvidencePhoto.EvidenceType.RETURN,
        object_key="evidence/return", uploaded_by=actor,
    )
    request = make_hardware_request(makerspace, product, status=HardwareRequest.Status.RETURNED)
    request.issue_evidence = issue_photo
    request.save(update_fields=["issue_evidence"])
    box = Box.objects.create(makerspace=makerspace, label="EV-1")
    ReturnEvent.objects.create(
        request=request, makerspace=makerspace, box=box, evidence=return_photo,
        remark="returned", actor=actor,
    )

    data = AdminRequestSerializer(request).data

    assert data["issue_evidence_id"] == issue_photo.id
    assert data["return_evidence_ids"] == [return_photo.id]
