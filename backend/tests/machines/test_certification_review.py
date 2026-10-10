"""Regression coverage from the Wave 2 review; run in the isolated DB runner."""

from datetime import datetime, timedelta, timezone as utc

import pytest
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.admin_api.serializers_certifications import CertificationTypeSerializer
from apps.machines.models import CertificationGrant, CertificationType
from apps.machines import reminders_certifications, reminders_certification_digest
from apps.operations.reminder_sweeper import run_reminder_sweep
from tests.machines.test_certification_ui_api import setup, client
from tests.machines.test_certification_reminders import world
from tests.machines.certification_helpers import _certification, _machine_type

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("database_collision", [False, True])
@pytest.mark.parametrize("method", ["post", "patch"])
def test_duplicate_type_name_is_400_without_partial_audit(database_collision, method, monkeypatch):
    space, kind, manager, _, _, cert = setup("review-duplicate")
    if database_collision:
        # Simulate another request winning after preflight. Exercise the actual
        # PostgreSQL unique constraint and the endpoint's nested savepoint.
        monkeypatch.setattr(CertificationTypeSerializer, "validate", lambda self, attrs: attrs)
    api = client(manager)
    if method == "post":
        url = reverse("admin-certification-types", args=[space.pk])
        data = {"machine_type": kind.pk, "name": cert.name}
    else:
        other = _certification(space, kind, name="Other training")
        url = reverse("admin-certification-type-detail", args=[other.pk])
        data = {"name": cert.name}
    response = getattr(api, method)(url, data, format="json")
    assert response.status_code == 400 and "name" in response.data
    assert CertificationType.objects.filter(makerspace=space, name=cert.name).count() == 1
    assert not AuditLog.objects.filter(action__in=["certification_type.created", "certification_type.updated"]).exists()
    if method == "patch":
        other.refresh_from_db()
        assert other.name == "Other training"


@pytest.mark.parametrize("validity", [0, -1, 2147483648])
def test_validity_range_refused_before_database_write(validity):
    space, kind, manager, _, _, cert = setup("review-validity")
    api = client(manager)
    created = api.post(reverse("admin-certification-types", args=[space.pk]),
                       {"machine_type": kind.pk, "name": "New", "validity_days": validity}, format="json")
    updated = api.patch(reverse("admin-certification-type-detail", args=[cert.pk]),
                        {"validity_days": validity}, format="json")
    assert created.status_code == updated.status_code == 400
    cert.refresh_from_db()
    assert cert.validity_days == 30
    assert not CertificationType.objects.filter(name="New").exists()


def test_type_and_grant_lists_are_paginated_after_machine_scope_filtering():
    space, kind, manager, _, membership, cert = setup("review-pagination")
    for index in range(25):
        _certification(space, kind, name=f"Training {index:02d}")
        CertificationGrant.objects.create(certification_type=cert, membership=membership)
    foreign_kind = _machine_type(space, "Out of scope")
    _certification(space, foreign_kind, name="Hidden training")
    api = client(manager)
    for name, pk, count in [("admin-certification-types", space.pk, 26),
                             ("admin-certification-type-grants", cert.pk, 25)]:
        url = reverse(name, args=[pk])
        first = api.get(url)
        second = api.get(url, {"page": 2})
        assert first.status_code == second.status_code == 200
        assert first.data["count"] == count and len(first.data["results"]) == 24
        assert first.data["next"] and second.data["previous"] and second.data["next"] is None
        assert len(second.data["results"]) == count - 24
        assert {row["id"] for row in first.data["results"]}.isdisjoint(row["id"] for row in second.data["results"])
        assert all(row.get("name") != "Hidden training" for row in first.data["results"] + second.data["results"])


def test_inactive_type_grants_are_not_presented_as_live():
    _, _, manager, _, membership, cert = setup("review-inactive")
    CertificationGrant.objects.create(certification_type=cert, membership=membership)
    cert.is_active = False
    cert.save(update_fields=["is_active"])
    result = client(manager).get(reverse("admin-certification-type-grants", args=[cert.pk]))
    assert result.status_code == 200 and result.data["results"][0]["is_live"] is False


def test_expired_notices_take_priority_in_small_discovery_batches(monkeypatch):
    space, _, membership, cert = world("review-expired-priority")
    now = datetime(2026, 10, 11, 10, tzinfo=utc.utc)
    advance_cert = _certification(space, cert.machine_type, name="Advance")
    advance = CertificationGrant.objects.create(certification_type=advance_cert, membership=membership,
                                               expires_at=now + timedelta(days=7))
    expired = CertificationGrant.objects.create(certification_type=cert, membership=membership,
                                               expires_at=now - timedelta(days=1))
    seen = []
    monkeypatch.setattr(reminders_certifications, "notify_certification", lambda row, event, **kw: seen.append((row.pk, event)))
    monkeypatch.setattr(reminders_certification_digest, "notify_family", lambda *a, **kw: None)
    run_reminder_sweep(now=now, limit=1)
    assert seen == [(expired.pk, "expired")]
    run_reminder_sweep(now=now, limit=1)
    assert seen == [(expired.pk, "expired"), (advance.pk, "expiring")]


def test_member_expiry_payload_has_only_owner_email_and_disables_staff_channels(monkeypatch):
    from apps.integrations import notify
    from apps.machines.notifications_certifications import notify_certification

    space, _, membership, cert = world("review-member-delivery")
    grant = CertificationGrant.objects.create(
        certification_type=cert, membership=membership,
        expires_at=datetime(2026, 10, 20, tzinfo=utc.utc), notes="Private assessment",
    )
    payloads = []
    monkeypatch.setattr(notify, "_run_guarded", lambda ms, feature, event, build, *args: payloads.append(build()))
    result = notify_certification(grant, "expiring", include_staff=False)
    assert result.scheduled and len(payloads) == 1
    payload = payloads[0]
    assert payload.staff_channels_enabled is False
    assert [(email.to_email, email.audience) for email in payload.emails] == [(membership.user.email, "requester")]
    assert "Private assessment" not in payload.text
    assert all("Private assessment" not in email.text_body for email in payload.emails)


def test_member_expiry_does_not_send_after_membership_disappears(monkeypatch):
    from apps.integrations import notify
    from apps.machines.notifications_certifications import notify_certification

    _, _, membership, cert = world("review-member-disappeared")
    grant = CertificationGrant.objects.create(certification_type=cert, membership=membership)
    builds = []
    monkeypatch.setattr(notify, "_run_guarded", lambda ms, feature, event, build, *args: builds.append(build))
    notify_certification(grant, "expired", include_staff=False)
    membership.delete()
    assert len(builds) == 1 and builds[0]().emails == ()
