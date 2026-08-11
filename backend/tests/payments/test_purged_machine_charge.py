"""Machine-service charges: what they must never snapshot, and who may settle an orphan.

Machine service is the one payment subject that behaves differently from the other three, in
both directions, which is why it gets its own module:

* It snapshots **no** `subject_label`. The other three snapshot staff-authored or literal
  text; `MachineServiceRequest.title` is free text a public member types, so it can hold
  their name, email or phone -- and a snapshot would outlive the `machine_service` purge
  whose entire job is destroying that.
* It is the only subject whose *authorization* dereferences the subject row, because
  `MANAGE_MACHINES` is scoped per role. That is what made a purged charge unsettleable.
"""

from decimal import Decimal

import pytest

from apps.machines.models import (
    Machine,
    MachineServiceRequest,
    MachineType,
    MakerspaceMachineTypePricing,
)
from apps.machines.service_workflow import accept, complete, start, submit
from apps.payments.models import Payment
from tests.payments.test_models import configured_settings
from tests.return_helpers import make_member, make_space

pytestmark = pytest.mark.django_db


# --- the label must never carry member-typed text ------------------------------------


def test_a_machine_service_charge_snapshots_no_member_typed_text():
    """`title` is free text a public member types, so it must never be snapshotted.

    Payments now survive a `machine_service` purge, and that purge exists to destroy the
    requester's name, email and phone. A snapshotted title would smuggle the same data past
    it whenever a member typed contact details into the title field -- which the public
    submit form invites them to do. The label stays blank: resolvable live while the request
    exists, generic once it is gone.

    This drives the REAL path -- `submit` -> `accept` -> `start` -> `complete`, which calls
    `service_payments.create_for_completed_request`. Fabricating a `Payment`, or calling
    `create_payment` directly with some other subject type, would prove nothing: that
    function wraps everything in `except Exception: return None`, so a future edit adding
    `subject_label=service_request.title` would leave a hand-rolled test perfectly green
    while the PII contract was broken. Same trap `CLAUDE.md` records for event charging.
    """
    space = make_space("machine-label-pii")
    space.enabled_features = ["payments.enabled", "payments.machines"]
    space.save(update_fields=["enabled_features", "updated_at"])
    configured_settings(space)
    actor = make_member("machine-label-pii-user", space)
    machine_type = MachineType.objects.create(
        makerspace=space, slug="pii-lathe", name="Lathe",
        capability_config={"metering_unit": "minutes", "requires_booking": False},
    )
    machine = Machine.objects.create(
        makerspace=space, machine_type=machine_type, name="Lathe 1"
    )
    # The requester types their own phone number into the title -- the whole hazard.
    row = submit(
        machine, actor, member=actor, actor=actor,
        requester_name=actor.username, contact_email=actor.email, contact_phone="",
        title="Bracket -- call me on 555-0100",
    )
    MakerspaceMachineTypePricing.objects.create(
        makerspace=space, machine_type=machine_type,
        rate_per_unit="1.00", flat_fee="2.00", payment_enabled=True,
    )

    accept(row, actor)
    start(row, actor, machine_id=row.assigned_machine_id)
    assert complete(row, actor, actual_minutes=1, consumptions=[]).status == (
        MachineServiceRequest.Status.COMPLETED
    )

    payment = Payment.objects.get(subject_id=row.pk)
    assert payment.amount == Decimal("3.00"), "the real charge path must have run"
    assert payment.subject_label == "", "member-typed text must never be snapshotted"
    assert "555-0100" not in payment.subject_label


# --- the orphaned charge must stay actionable ----------------------------------------


def machine_charge(space, actor):
    """A pending machine-service charge on a real request the caller can then purge."""
    from apps.machines.models import ServiceBucket

    kind = MachineType.objects.create(
        makerspace=space, slug=f"orphan-{space.id}", name="Service type"
    )
    machine = Machine.objects.create(makerspace=space, machine_type=kind, name="Laser")
    bucket, _ = ServiceBucket.objects.get_or_create(machine=machine, name="Service")
    request = MachineServiceRequest.objects.create(
        bucket=bucket, requester=actor, title="Cut me a bracket",
        requester_name="Ada", contact_email="ada@example.test",
        contact_phone="555-0100", reason="",
    )
    payment = Payment.objects.create(
        makerspace=space, member=actor, created_by=actor,
        subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST,
        subject_id=request.pk,
        amount=Decimal("10.00"), currency="usd",
        status=Payment.Status.PENDING,
    )
    return payment, request


def test_a_purged_machine_charge_can_still_be_waived_by_a_space_manager():
    """The charge outlives its request, so someone must still be able to settle it.

    `_require_machine_scope` compared the scoped request ids against every subject id, so a
    purged request made the sets unequal for EVERY actor -- 403 on both mark-offline and
    waive. The pending charge was then stranded forever: unwaivable, and unrecordable if the
    member paid cash at the desk. Preserving the payment to keep it payable while making it
    impossible to settle is the same failure wearing the opposite mask.
    """
    from apps.payments.reconciliation import waive

    space = make_space("orphan-charge-manager")
    manager = make_member("orphan-charge-manager-user", space)
    payment, request = machine_charge(space, manager)
    request.delete()

    settled = waive(payment, manager)

    assert settled.status == Payment.Status.WAIVED


def test_a_purged_machine_charge_is_still_refused_to_a_scoped_role():
    """The fix must not become a hole: scoping still fails closed for a scoped role.

    Falling open to every `MANAGE_MACHINES` holder would silently widen a role that was
    deliberately narrowed to one team. Only the actors machine scoping already exempts may
    settle an orphan, so a role holding `MANAGE_MACHINES` with no scope links stays refused.
    """
    from rest_framework.exceptions import PermissionDenied

    from apps.accounts import rbac
    from apps.payments.reconciliation import waive
    from tests.payments.test_reconciliation import custom_actor

    space = make_space("orphan-charge-scoped")
    owner = make_member("orphan-charge-scoped-owner", space)
    payment, request = machine_charge(space, owner)
    request.delete()
    scoped = custom_actor(
        "orphan-charge-scoped-role", space, [rbac.Action.MANAGE_MACHINES]
    )

    with pytest.raises(PermissionDenied):
        waive(payment, scoped)

    payment.refresh_from_db()
    assert payment.status == Payment.Status.PENDING
