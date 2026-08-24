from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.backup.models import (
    MakerspaceTenantExitCustodyState as CustodyState,
    TenantExitCustodyAlarmDelivery as Delivery,
)
from apps.backup.raw_projection import raw_records
from apps.backup.tenant_exit_custody_alarms import ensure_delivery_intents
from apps.bookings.models import BookableSpace, Booking
from apps.bookings.services_bookings import create_booking
from apps.boxes.api_views import (
    _asset_checkout_eligible,
    _product_checkout_eligible,
)
from apps.events.models import Event, EventRegistration
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from apps.machines.models import Machine, MachineType
from apps.makerspaces import profile_services
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceMembership,
    MemberProfile,
)
from apps.tenant_migration.tenant_dump_raw import sanitize_record
from tests.tenant_migration.tenant_dump_d3_helpers import manager, operator


pytestmark = pytest.mark.django_db


def _projected(model, instance):
    source = raw_records(model.objects.filter(pk=instance.pk), model)[0]
    return sanitize_record(model, source).values


def test_public_machine_visibility_uses_post_projection_module_and_visibility_values():
    space = Makerspace.objects.create(
        name="D8 public machine",
        slug="d8-public-machine",
        public_inventory_enabled=True,
        enabled_modules=["machines"],
    )
    machine_type = MachineType.objects.create(
        makerspace=space, slug="d8-public-type", name="D8 public type"
    )
    machine = Machine.objects.create(
        makerspace=space,
        machine_type=machine_type,
        name="Projected public machine",
        is_public=True,
        is_active=True,
    )

    projected_space = _projected(Makerspace, space)
    projected_machine = _projected(Machine, machine)
    Makerspace.objects.filter(pk=space.pk).update(
        enabled_modules=projected_space["enabled_modules"],
        public_inventory_enabled=projected_space["public_inventory_enabled"],
    )
    Machine.objects.filter(pk=machine.pk).update(
        is_public=projected_machine["is_public"],
        is_active=projected_machine["is_active"],
    )

    response = APIClient().get(
        reverse("public-machines", kwargs={"makerspace_slug": space.slug})
    )

    assert "machines" not in projected_space["enabled_modules"]
    assert projected_machine["is_public"] is True
    assert projected_machine["is_active"] is True
    assert response.status_code == 404


def test_public_checkout_eligibility_uses_both_post_projection_reset_flags():
    space = Makerspace.objects.create(name="D8 checkout", slug="d8-checkout")
    product = InventoryProduct.objects.create(
        makerspace=space,
        name="Projected checkout product",
        total_quantity=1,
        available_quantity=1,
        is_public=True,
        public_self_checkout_enabled=True,
    )
    individual_product = InventoryProduct.objects.create(
        makerspace=space,
        name="Projected checkout asset parent",
        tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=1,
        available_quantity=1,
        is_public=True,
        public_self_checkout_enabled=True,
    )
    asset = InventoryAsset.objects.create(
        makerspace=space,
        product=individual_product,
        asset_tag="D8-ASSET",
        status=InventoryAsset.Status.AVAILABLE,
        public_self_checkout_enabled=True,
    )

    projected_product = _projected(InventoryProduct, product)
    projected_asset = _projected(InventoryAsset, asset)
    InventoryProduct.objects.filter(pk=product.pk).update(
        public_self_checkout_enabled=projected_product[
            "public_self_checkout_enabled"
        ]
    )
    InventoryAsset.objects.filter(pk=asset.pk).update(
        public_self_checkout_enabled=projected_asset[
            "public_self_checkout_enabled"
        ]
    )
    product.refresh_from_db()
    asset.refresh_from_db()

    assert product.public_self_checkout_enabled is False
    assert asset.public_self_checkout_enabled is False
    assert _product_checkout_eligible(product, require_public=True) is False
    assert _asset_checkout_eligible(asset, require_public=True) is False


def test_booking_initial_status_uses_post_projection_approval_mode(monkeypatch):
    space = Makerspace.objects.create(
        name="D8 booking",
        slug="d8-booking",
        enabled_modules=["bookings"],
    )
    member = User.objects.create_user(
        username="d8-booking-member",
        email="d8-booking-member@example.test",
        phone="+15550001111",
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(makerspace=space, user=member)
    bookable = BookableSpace.objects.create(
        makerspace=space,
        name="Projected approval room",
        approval_mode=BookableSpace.ApprovalMode.INSTANT,
    )
    projected = _projected(BookableSpace, bookable)
    BookableSpace.objects.filter(pk=bookable.pk).update(
        approval_mode=projected["approval_mode"]
    )
    bookable.refresh_from_db()
    monkeypatch.setattr(
        "apps.bookings.notifications.notify_booking_status",
        lambda *_args, **_kwargs: None,
    )
    starts = timezone.now() + timedelta(hours=2)

    booking = create_booking(
        bookable,
        starts_at=starts,
        ends_at=starts + timedelta(hours=1),
        member=member,
        actor=member,
    )

    assert projected["approval_mode"] == BookableSpace.ApprovalMode.APPROVE
    assert booking.status == Booking.Status.PENDING


def test_profile_and_attendance_publication_use_post_projection_consents():
    space = Makerspace.objects.create(
        name="D8 profile",
        slug="d8-profile",
        enabled_modules=["events", "membership"],
    )
    user = User.objects.create_user(
        username="d8-profile-member", access_status=User.AccessStatus.ACTIVE
    )
    membership = MakerspaceMembership.objects.create(makerspace=space, user=user)
    profile = MemberProfile.objects.create(
        membership=membership,
        is_visible=True,
        show_attended_events=True,
        headline="Projected maker",
    )
    starts = timezone.now() - timedelta(days=1)
    event = Event.objects.create(
        makerspace=space,
        title="Projected attended event",
        starts_at=starts,
        ends_at=starts + timedelta(hours=1),
    )
    EventRegistration.objects.create(
        event=event,
        member=user,
        name=user.username,
        email="d8-profile-member@example.test",
        status=EventRegistration.Status.ATTENDED,
    )
    projected = _projected(MemberProfile, profile)
    MemberProfile.objects.filter(pk=profile.pk).update(
        is_visible=projected["is_visible"],
        show_attended_events=projected["show_attended_events"],
    )

    directory = profile_services.directory(space)
    activity = profile_services.profile_activity(membership)

    assert projected["is_visible"] is True
    assert projected["show_attended_events"] is True
    assert [row["membership_id"] for row in directory["members"]] == [membership.pk]
    assert [row["title"] for row in activity["recent_attended_events"]] == [
        "Projected attended event"
    ]


def test_decision_19b_uses_post_projection_notification_reset_values():
    space = Makerspace.objects.create(
        name="D8 projected routing",
        slug="d8-projected-routing",
        enabled_modules=["notifications"],
        staff_notifications_enabled=False,
    )
    tenant = manager(space, suffix="projected", opted_in=False)
    operator("d8-projected-routing-operator")
    membership = MakerspaceMembership.objects.get(makerspace=space, user=tenant)
    projected_space = _projected(Makerspace, space)
    projected_membership = _projected(MakerspaceMembership, membership)
    Makerspace.objects.filter(pk=space.pk).update(
        staff_notifications_enabled=projected_space[
            "staff_notifications_enabled"
        ]
    )
    MakerspaceMembership.objects.filter(pk=membership.pk).update(
        receives_notifications=projected_membership["receives_notifications"]
    )
    state = CustodyState.objects.create(
        makerspace=space,
        state=CustodyState.State.DEGRADED_ONE_RECIPIENT,
        alarm_episode=1,
        alarm_revision=1,
    )

    ensure_delivery_intents(state.pk)

    assert projected_space["staff_notifications_enabled"] is True
    assert projected_membership["receives_notifications"] is True
    assert set(
        Delivery.objects.filter(makerspace=space).values_list("channel", flat=True)
    ) == {Delivery.Channel.TENANT_INAPP, Delivery.Channel.TENANT_EMAIL}
