import pytest
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import rbac
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceMembership,
    MakerspaceRole,
    MakerspaceWaiver,
)
from apps.makerspaces.waiver_state import (
    acceptance_on_file,
    active_waiver_for,
    current_acceptance,
)

pytestmark = pytest.mark.django_db(transaction=True)


def make_user(name, **values):
    return User.objects.create_user(
        username=name,
        email=f"{name}@example.test",
        password="password",
        **values,
    )


def make_space(slug="witness-space"):
    return Makerspace.objects.create(name=slug, slug=slug)


def add_member(space, user, role_slug="member", *, status="active"):
    role = MakerspaceRole.objects.get(makerspace=space, slug=role_slug)
    return MakerspaceMembership.objects.create(
        makerspace=space,
        user=user,
        assigned_role=role,
        role=role.legacy_role or MakerspaceMembership.Role.CUSTOM,
        status=status,
    )


def front_desk(space, name="front-desk"):
    actor = make_user(name)
    role = MakerspaceRole.objects.create(
        makerspace=space,
        name="Waiver Desk",
        slug=f"waiver-desk-{name}",
        granted_actions=[rbac.Action.ISSUE_DIRECT_LOAN],
    )
    add_member(space, actor)
    membership = MakerspaceMembership.objects.get(makerspace=space, user=actor)
    membership.assigned_role = role
    membership.save(update_fields=["assigned_role"])
    return actor


def authed(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def witness_url(membership):
    return reverse("admin-membership-waiver-witness", kwargs={"pk": membership.pk})


def test_witness_endpoint_derives_current_waiver_time_actor_and_safe_audit():
    space = make_space()
    actor = front_desk(space)
    target = add_member(space, make_user("target"))
    old = MakerspaceWaiver.objects.create(
        makerspace=space, version="old", body="Old body", is_active=False,
    )
    current = MakerspaceWaiver.objects.create(
        makerspace=space, version="current", body="SECRET WAIVER BODY", is_active=True,
    )
    before = timezone.now()

    response = authed(actor).post(witness_url(target), {}, format="json")

    after = timezone.now()
    assert response.status_code == 200, response.data
    target.refresh_from_db()
    assert target.witnessed_waiver_id == current.id != old.id
    assert target.witnessed_waiver_version == current.version
    assert target.witnessed_by_id == actor.id
    assert target.witnessed_actor_snapshot is None
    assert before <= target.witnessed_at <= after
    entry = AuditLog.objects.get(action="membership.waiver_witnessed")
    assert entry.actor_id == actor.id
    assert entry.meta == {
        "membership_id": target.id,
        "waiver_id": current.id,
        "version": current.version,
    }
    assert current.body not in str(entry.meta)


@pytest.mark.parametrize(
    "payload",
    [
        {"waiver_id": 999},
        {"witnessed_at": "2000-01-01T00:00:00Z"},
    ],
)
def test_witness_endpoint_rejects_every_caller_supplied_evidence_field(payload):
    space = make_space(f"reject-{next(iter(payload))}")
    actor = front_desk(space, f"desk-{next(iter(payload))}")
    target = add_member(space, make_user(f"target-{next(iter(payload))}"))
    MakerspaceWaiver.objects.create(
        makerspace=space, version="v1", body="Terms", is_active=True,
    )

    response = authed(actor).post(witness_url(target), payload, format="json")

    assert response.status_code == 400
    target.refresh_from_db()
    assert target.witnessed_waiver_id is None


def test_witness_endpoint_refuses_actor_without_either_allowed_action():
    space = make_space("no-authority")
    actor = make_user("ordinary-member")
    add_member(space, actor)
    target = add_member(space, make_user("ordinary-target"))
    MakerspaceWaiver.objects.create(
        makerspace=space, version="v1", body="Terms", is_active=True,
    )

    response = authed(actor).post(witness_url(target), {}, format="json")

    assert response.status_code == 403


def test_witness_endpoint_requires_an_active_target_in_the_actors_space():
    own = make_space("target-scope-own")
    other = make_space("target-scope-other")
    actor = front_desk(own, "target-scope-actor")
    foreign_target = add_member(other, make_user("foreign-target"))
    revoked_target = add_member(
        own, make_user("revoked-target"), status="revoked"
    )
    for space in (own, other):
        MakerspaceWaiver.objects.create(
            makerspace=space, version="v1", body="Terms", is_active=True,
        )
    client = authed(actor)

    foreign = client.post(witness_url(foreign_target), {}, format="json")
    revoked = client.post(witness_url(revoked_target), {}, format="json")

    assert foreign.status_code == 403
    assert revoked.status_code == 400


@pytest.mark.parametrize(
    "locked_change",
    [
        {"access_status": User.AccessStatus.SUSPENDED},
        {"must_change_password": True},
    ],
)
def test_witness_reloads_actor_state_under_the_lock(locked_change):
    space = make_space(f"locked-{next(iter(locked_change))}")
    actor = front_desk(space, f"actor-{next(iter(locked_change))}")
    target = add_member(space, make_user(f"target-{next(iter(locked_change))}"))
    MakerspaceWaiver.objects.create(
        makerspace=space, version="v1", body="Terms", is_active=True,
    )
    client = authed(actor)
    User.objects.filter(pk=actor.pk).update(**locked_change)

    response = client.post(witness_url(target), {}, format="json")

    assert response.status_code == 403
    target.refresh_from_db()
    assert target.witnessed_waiver_id is None


def test_witness_evidence_protects_waiver_and_staff_actor_deletion():
    space = make_space("protect")
    actor = front_desk(space, "protect-actor")
    target = add_member(space, make_user("protect-target"))
    waiver = MakerspaceWaiver.objects.create(
        makerspace=space, version="v1", body="Terms", is_active=True,
    )
    MakerspaceMembership.objects.filter(pk=target.pk).update(
        witnessed_waiver=waiver,
        witnessed_waiver_version=waiver.version,
        witnessed_by=actor,
        witnessed_at=timezone.now(),
    )

    with pytest.raises(ProtectedError):
        waiver.delete()
    with pytest.raises(ProtectedError):
        actor.delete()


def test_witness_constraint_rejects_partial_and_accepts_snapshot_actor():
    space = make_space("constraint")
    waiver = MakerspaceWaiver.objects.create(
        makerspace=space, version="v1", body="Terms", is_active=True,
    )
    partial_user = make_user("partial-target")
    with pytest.raises(IntegrityError), transaction.atomic():
        MakerspaceMembership.objects.create(
            makerspace=space,
            user=partial_user,
            witnessed_waiver=waiver,
        )

    snapshot = {
        "actor_username": "source-staff",
        "actor_display": "Source Staff",
        "source_user_id": 42,
        "recorded_at": "2026-08-16T10:00:00Z",
    }
    complete = MakerspaceMembership.objects.create(
        makerspace=space,
        user=make_user("snapshot-target"),
        witnessed_waiver=waiver,
        witnessed_waiver_version=waiver.version,
        witnessed_actor_snapshot=snapshot,
        witnessed_at=timezone.now(),
    )
    assert complete.witnessed_by_id is None
    assert acceptance_on_file(complete) is True


def test_current_and_historical_predicates_cover_both_evidence_types():
    space = make_space("predicates")
    waiver = MakerspaceWaiver.objects.create(
        makerspace=space, version="v1", body="Terms", is_active=True,
    )
    actor = make_user("predicate-actor")
    neither = add_member(space, make_user("neither"))
    self_only = add_member(space, make_user("self-only"))
    witnessed_only = add_member(space, make_user("witness-only"))
    both = add_member(space, make_user("both"))
    now = timezone.now()
    MakerspaceMembership.objects.filter(pk=self_only.pk).update(
        accepted_waiver=waiver, waiver_version_accepted="v1", waiver_accepted_at=now,
    )
    MakerspaceMembership.objects.filter(pk=witnessed_only.pk).update(
        witnessed_waiver=waiver, witnessed_waiver_version="v1",
        witnessed_by=actor, witnessed_at=now,
    )
    MakerspaceMembership.objects.filter(pk=both.pk).update(
        accepted_waiver=waiver, waiver_version_accepted="v1", waiver_accepted_at=now,
        witnessed_waiver=waiver, witnessed_waiver_version="v1",
        witnessed_by=actor, witnessed_at=now,
    )
    rows = {
        row.user.username: row
        for row in MakerspaceMembership.objects.filter(
            pk__in=[neither.pk, self_only.pk, witnessed_only.pk, both.pk]
        )
    }

    active = active_waiver_for(space.id)
    assert acceptance_on_file(rows["neither"]) is False
    assert current_acceptance(rows["neither"], active_waiver=active) is False
    for name in ("self-only", "witness-only", "both"):
        assert acceptance_on_file(rows[name]) is True
        assert current_acceptance(rows[name], active_waiver=active) is True

    waiver.is_active = False
    waiver.superseded_at = now
    waiver.save(update_fields=["is_active", "superseded_at"])
    MakerspaceWaiver.objects.create(
        makerspace=space, version="v2", body="New terms", is_active=True,
    )
    # Deliberately re-resolved rather than reused: an earlier version memoised the
    # active waiver on the membership instance, so these same rows kept reporting the
    # superseded v1 as current.
    active = active_waiver_for(space.id)
    for name in ("self-only", "witness-only", "both"):
        assert acceptance_on_file(rows[name]) is True
        assert current_acceptance(rows[name], active_waiver=active) is False
