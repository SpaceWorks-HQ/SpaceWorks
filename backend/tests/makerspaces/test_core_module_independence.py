"""The core loan spine must survive any single optional module being uninstalled.

**What this proves, precisely.** For every optional module `M`, a makerspace built from
`core + (every other optional module)` can still run the loan spine end to end: browse the
public catalogue, submit a borrow request, see it in the staff queue, accept it, read its
public status, scan and assign a box, attach issue evidence, issue it, then attach return
evidence and a remark and complete the return. Plus the strongest single case — `core`
and nothing else.

**What it does NOT prove.** It is not a general proof that "no core module hard-depends on
an optional module's data". A true static proof is not available in this codebase: an app
label is not the unit of module ownership (`hardware_requests` owns core `request_workflow`
AND optional `guest_handover`; `admin_api` owns core `staff_admin` and many optional
surfaces), so no per-file rule can separate a legitimate optional-module gate from a core
module reaching for optional data. The declared half of the property is checked at import
time instead, by `module_registry._validate_registry` (a core module may not name an
optional one in `requires_modules`).

This is the regression that `9e496997` shipped and nothing caught: core `request_workflow`
called `require_active_member_presence` unconditionally, that guard hard-requires a
`MakerspaceMembership` row, and the default `recommended` profile installs no `membership`
module — so a fresh self-host install returned 403 `membership_required` to every public
borrow request. The `no_membership` case below fails without that fix.

**The identity is built to match each configuration, and that is load-bearing.** With
`membership` installed the spine legitimately requires an active member with an open
presence session; a test that always used a plain account would be rejected by the
membership guard in 25 of 26 cases and would prove nothing about the module under test.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.evidence.storage import EvidenceValidationResult
from apps.hardware_requests.models import HardwareRequest
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.makerspaces.module_registry import BY_KEY, MODULES, core_module_keys
from apps.presence.models import PresenceSession
from tests.return_helpers import (
    make_box,
    make_issue_evidence,
    make_return_evidence,
    return_payload,
)

pytestmark = pytest.mark.django_db

CORE = frozenset(core_module_keys())
OPTIONAL = tuple(sorted(key for key in BY_KEY if key not in CORE))


def transitive_dependents(key):
    """Every module that would break if `key` were removed, at any depth.

    `module_registry_helpers.dependents_of` answers one level only. Removing `machines`
    while leaving `printing` installed would produce a capability set
    `validate_capabilities` rejects, so the closure is what makes each configuration in
    this matrix a legal one.
    """
    removed = {key}
    changed = True
    while changed:
        changed = False
        for definition in MODULES:
            if definition.key in removed:
                continue
            if removed & set(definition.requires_modules):
                removed.add(definition.key)
                changed = True
    return removed - {key}


def configuration_without(key):
    dropped = {key, *transitive_dependents(key)}
    return sorted(CORE | ({*OPTIONAL} - dropped))


def _space(slug, modules):
    return Makerspace.objects.create(
        name=slug,
        slug=slug,
        enabled_modules=list(modules),
        public_inventory_enabled=True,
    )


def _requester(slug, space):
    """An account that is legitimately allowed to submit under THIS configuration."""
    user = User.objects.create_user(
        username=f"cmi-{slug}",
        email=f"cmi-{slug}@example.test",
        display_name="Spine Requester",
        access_status=User.AccessStatus.ACTIVE,
    )
    if "membership" in (space.enabled_modules or []):
        # Membership installed => the spine legitimately demands an active member with an
        # open presence session. No MakerspaceWaiver row is created, so the waiver branch
        # of `require_active_member` is not exercised here; that rule has its own tests.
        membership = MakerspaceMembership.objects.create(
            makerspace=space, user=user, status="active",
        )
        now = timezone.now()
        PresenceSession.objects.create(
            member=user,
            makerspace=space,
            membership=membership,
            started_at=now,
            expires_at=now + timedelta(hours=2),
        )
    return user


def _staff(slug):
    return User.objects.create_user(
        username=f"cmi-staff-{slug}",
        email=f"cmi-staff-{slug}@example.test",
        role=User.Role.SUPERADMIN,
        is_staff=True,
        is_superuser=True,
        access_status=User.AccessStatus.ACTIVE,
    )


def _client(user=None):
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


def run_loan_spine(slug, modules, monkeypatch):
    """Browse -> submit -> queue -> accept -> public status -> box -> issue -> return.

    Returns nothing; every step asserts, so the failing endpoint names itself. The
    post-acceptance steps satisfy the production handover rules with a real box scan,
    distinct issue/return evidence, and a complete return remark + resolution.
    """
    space = _space(slug, modules)
    product = InventoryProduct.objects.create(
        makerspace=space,
        name="Torque wrench",
        total_quantity=3,
        available_quantity=3,
        is_public=True,
    )

    catalog = _client().get(reverse("inventory:public-inventory", args=[space.slug]))
    assert catalog.status_code == 200, f"catalog: {catalog.status_code} {catalog.data}"

    submit = _client(_requester(slug, space)).post(
        reverse("hardware_requests:request-submit", args=[space.slug]),
        {"requested_for": "Spine check", "items": [{"product_id": product.pk, "quantity": 1}]},
        format="json",
    )
    assert submit.status_code == 201, f"submit: {submit.status_code} {submit.data}"
    public_token = submit.data["public_token"]

    staff_user = _staff(slug)
    staff = _client(staff_user)
    pending = staff.get(reverse("hardware_requests:pending-requests", args=[space.id]))
    assert pending.status_code == 200, f"queue: {pending.status_code} {pending.data}"
    assert pending.data["count"] == 1, pending.data

    request_id = pending.data["results"][0]["id"]
    accepted = staff.post(reverse("hardware_requests:request-accept", args=[request_id]), {}, format="json")
    assert accepted.status_code == 200, f"accept: {accepted.status_code} {accepted.data}"
    assert accepted.data["status"] == "accepted"

    status_response = _client().get(
        reverse("hardware_requests:request-status", args=[public_token])
    )
    assert status_response.status_code == 200, f"status: {status_response.status_code}"

    monkeypatch.setattr(
        "apps.evidence.storage.finalize_upload",
        lambda *_args: EvidenceValidationResult(size=123, content_type="image/jpeg"),
    )
    box = make_box(space, label=f"{slug} loan box")
    assigned = staff.post(
        reverse("hardware_requests:request-assign-box", args=[request_id]),
        {"box_code": box.code},
        format="json",
    )
    assert assigned.status_code == 200, f"assign-box: {assigned.status_code} {assigned.data}"

    issued = staff.post(
        reverse("hardware_requests:request-issue", args=[request_id]),
        {
            "evidence_id": make_issue_evidence(space, staff_user).pk,
            "remark": "Issued after box and evidence verification.",
        },
        format="json",
    )
    assert issued.status_code == 200, f"issue: {issued.status_code} {issued.data}"
    assert issued.data["status"] == HardwareRequest.Status.ISSUED

    hardware_request = HardwareRequest.objects.get(pk=request_id)
    returned = staff.post(
        reverse("hardware_requests:request-return", args=[request_id]),
        return_payload(
            hardware_request,
            make_return_evidence(space, staff_user),
            remark="Returned complete and inspected.",
        ),
        format="json",
    )
    assert returned.status_code == 200, f"return: {returned.status_code} {returned.data}"
    hardware_request.refresh_from_db()
    assert hardware_request.status in {
        HardwareRequest.Status.RETURNED,
        HardwareRequest.Status.CLOSED_WITH_ISSUE,
    }
    assert returned.data["status"] == hardware_request.status


def test_the_loan_spine_runs_on_a_core_only_makerspace(monkeypatch):
    """The strongest single case: every optional module uninstalled at once."""
    run_loan_spine("core-only", sorted(CORE), monkeypatch)


@pytest.mark.parametrize("missing", OPTIONAL)
def test_the_loan_spine_survives_each_optional_module_being_uninstalled(missing, monkeypatch):
    run_loan_spine(
        f"no-{missing.replace('_', '-')}", configuration_without(missing), monkeypatch
    )


def test_every_optional_module_is_actually_covered_by_the_matrix():
    """Guards the guard: a module added to the registry joins the matrix automatically,
    and this fails loudly if the core/optional split ever computes to nothing."""
    assert OPTIONAL, "no optional modules found — the matrix would be vacuous"
    assert CORE.isdisjoint(OPTIONAL)
    assert len(CORE) + len(OPTIONAL) == len(BY_KEY)


def test_a_core_module_may_not_declare_a_dependency_on_an_optional_one():
    """The declared half, pinned here so the registry rule cannot be quietly removed."""
    for definition in MODULES:
        if not definition.is_core:
            continue
        optional_requirements = [
            key for key in definition.requires_modules if not BY_KEY[key].is_core
        ]
        assert not optional_requirements, (
            f"{definition.key} is core but requires {optional_requirements}"
        )
