import pytest
from django.db import connection
from django.http import Http404
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts import rbac
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.boxes.models import QrCode, QrScanEvent
from apps.evidence.models import EvidencePhoto
from apps.hardware_requests.models import HardwareRequest, PublicToolLoan
from apps.inventory.models import InventoryProduct
from apps.makerspaces import import_lifecycle
from apps.makerspaces.lookup import get_public_makerspace
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.makerspaces.servability import is_servable, servable_queryset
from apps.presence import services as presence
from apps.presence.guard import MemberPresenceRequired, require_active_member


pytestmark = pytest.mark.django_db


def _space(slug, state=Makerspace.LifecycleState.ACTIVE):
    return Makerspace.objects.create(
        name=slug,
        slug=slug,
        lifecycle_state=state,
        public_inventory_enabled=True,
    )


def _member(space, username):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        phone="+15550101010",
    )
    MakerspaceMembership.objects.create(
        makerspace=space,
        user=user,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=MakerspaceRole.objects.get(makerspace=space, slug="member"),
    )
    presence.start_session(user, space, 60)
    return user


def _staff(space):
    user = User.objects.create_user(username=f"staff-{space.slug}")
    MakerspaceMembership.objects.create(
        makerspace=space,
        user=user,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=MakerspaceRole.objects.get(
            makerspace=space, slug="inventory_manager"
        ),
    )
    return user


def _checkout_fixture(space, user):
    product = InventoryProduct.objects.create(
        makerspace=space,
        name=f"Tool {space.slug}",
        total_quantity=1,
        available_quantity=1,
        is_public=True,
        public_self_checkout_enabled=True,
    )
    qr = QrCode.objects.create(
        makerspace=space,
        target_type=QrCode.TargetType.PRODUCT,
        target_id=product.pk,
    )
    evidence = EvidencePhoto.objects.create(
        makerspace=space,
        evidence_type=EvidencePhoto.EvidenceType.ISSUE,
        object_key=f"evidence/{space.pk}/issue.jpg",
        uploaded_by=user,
    )
    return qr, evidence


def _checkout(space, user, qr, evidence):
    client = APIClient(REMOTE_ADDR="10.20.30.40")
    client.force_authenticate(user)
    return client.post(
        f"/api/v1/public/{space.slug}/tools/checkout",
        {"payload": qr.payload, "evidence_id": evidence.pk},
        format="json",
    )


def test_ordinary_makerspace_creation_defaults_to_active():
    space = Makerspace.objects.create(name="Default active", slug="default-active")

    assert space.lifecycle_state == Makerspace.LifecycleState.ACTIVE
    assert is_servable(space)


@pytest.mark.parametrize(
    "state",
    [Makerspace.LifecycleState.IMPORTING, Makerspace.LifecycleState.ABORTED],
)
def test_non_active_lifecycle_states_fail_the_canonical_policy_closed(state):
    space = _space(f"closed-{state}", state)

    assert not is_servable(space)
    assert not servable_queryset().filter(pk=space.pk).exists()


def test_importing_tenant_is_invisible_to_public_resolution_and_inventory():
    space = _space("importing-public", Makerspace.LifecycleState.IMPORTING)
    InventoryProduct.objects.create(
        makerspace=space,
        name="Hidden tool",
        total_quantity=1,
        available_quantity=1,
        is_public=True,
    )

    with pytest.raises(Http404):
        get_public_makerspace(space.slug)
    response = APIClient().get(
        reverse("public-inventory", kwargs={"makerspace_slug": space.slug})
    )
    assert response.status_code == 404
    listed = APIClient().get(reverse("public-makerspaces"))
    assert all(row["slug"] != space.slug for row in listed.data)


def test_importing_tenant_refuses_staff_and_member_authorization():
    space = _space("importing-auth")
    member = _member(space, "blocked-member")
    staff = _staff(space)
    space.lifecycle_state = Makerspace.LifecycleState.IMPORTING
    space.save(update_fields=["lifecycle_state"])

    assert not rbac.can(staff, rbac.Action.VIEW_INVENTORY, space.pk)
    assert rbac.resolve_scope(member) == set()
    with pytest.raises(MemberPresenceRequired):
        require_active_member(member, space)


def test_importing_tenant_cannot_complete_self_checkout_or_write_evidence_rows():
    space = _space("importing-checkout")
    member = _member(space, "checkout-blocked")
    qr, evidence = _checkout_fixture(space, member)
    space.lifecycle_state = Makerspace.LifecycleState.IMPORTING
    space.save(update_fields=["lifecycle_state"])
    before = {
        "requests": HardwareRequest.objects.count(),
        "loans": PublicToolLoan.objects.count(),
        "scans": QrScanEvent.objects.count(),
        "audits": AuditLog.objects.count(),
    }

    response = _checkout(space, member, qr, evidence)

    assert response.status_code == 404
    assert HardwareRequest.objects.count() == before["requests"]
    assert PublicToolLoan.objects.count() == before["loans"]
    assert QrScanEvent.objects.count() == before["scans"]
    assert AuditLog.objects.count() == before["audits"]


def test_active_tenant_public_authorization_and_checkout_are_unchanged():
    space = _space("active-checkout")
    member = _member(space, "checkout-active")
    staff = _staff(space)
    qr, evidence = _checkout_fixture(space, member)

    assert get_public_makerspace(space.slug) == space
    assert rbac.can(staff, rbac.Action.VIEW_INVENTORY, space.pk)
    assert require_active_member(member, space).membership.user_id == member.pk
    response = _checkout(space, member, qr, evidence)

    assert response.status_code == 201
    assert HardwareRequest.objects.filter(makerspace=space).count() == 1
    assert PublicToolLoan.objects.filter(makerspace=space).count() == 1
    assert QrScanEvent.objects.filter(makerspace=space).count() == 1
    assert AuditLog.objects.filter(
        makerspace=space, action="public_tool.checked_out"
    ).count() == 1


@pytest.mark.django_db(transaction=True)
def test_importing_to_active_transition_is_atomic(monkeypatch):
    space = _space("activate-import", Makerspace.LifecycleState.IMPORTING)
    original_save = Makerspace.save
    observed_atomic_state = []

    def fail_after_save(instance, *args, **kwargs):
        observed_atomic_state.append(connection.in_atomic_block)
        original_save(instance, *args, **kwargs)
        raise RuntimeError("fail after lifecycle update")

    monkeypatch.setattr(Makerspace, "save", fail_after_save)
    with pytest.raises(RuntimeError, match="fail after lifecycle update"):
        import_lifecycle.activate_imported_makerspace(space.pk)

    assert observed_atomic_state == [True]
    space.refresh_from_db()
    assert space.lifecycle_state == Makerspace.LifecycleState.IMPORTING

    monkeypatch.setattr(Makerspace, "save", original_save)
    activated = import_lifecycle.activate_imported_makerspace(space.pk)
    assert activated.lifecycle_state == Makerspace.LifecycleState.ACTIVE
    space.refresh_from_db()
    assert space.lifecycle_state == Makerspace.LifecycleState.ACTIVE
