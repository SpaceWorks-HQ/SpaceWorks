"""Waiver supersession, immutable versions and the audit's current-version default."""
import pytest
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.makerspaces.models import MakerspaceMembership, MakerspaceWaiver
from tests.makerspaces.test_membership_j1 import manager, member_role, space, user
from tests.return_helpers import authenticated_client

pytestmark = pytest.mark.django_db


def state():
    makerspace = space("waiver-remaining")
    boss = manager(makerspace, "waiver-remaining-boss")
    person = user("waiver-remaining-person")
    row = MakerspaceMembership.objects.create(makerspace=makerspace, user=person, assigned_role=member_role(makerspace), role="custom")
    return makerspace, boss, row


def test_publish_supersedes_once_duplicate_version_refuses_and_acceptance_audits_current_version():
    makerspace, boss, row = state()
    client = authenticated_client(boss)
    url = reverse("admin-makerspace-waiver", args=[makerspace.pk])
    assert client.put(url, {"version": "v1", "body": "First terms"}, format="json").status_code == 200
    first = MakerspaceWaiver.objects.get(makerspace=makerspace, version="v1")
    assert client.put(url, {"version": "v2", "body": "New terms"}, format="json").status_code == 200
    first.refresh_from_db()
    assert not first.is_active and first.superseded_at is not None
    second = MakerspaceWaiver.objects.get(makerspace=makerspace, version="v2")
    assert MakerspaceWaiver.objects.filter(makerspace=makerspace, is_active=True).count() == 1
    assert client.put(url, {"version": "v2", "body": "Altered terms"}, format="json").status_code == 400
    second.refresh_from_db()
    assert second.is_active and second.body == "New terms"
    assert AuditLog.objects.filter(action="makerspace.waiver_published", makerspace=makerspace, actor=boss).count() == 2
    # D9: acceptance binds the current version even if the browser previously read v1.
    member_client = authenticated_client(row.user)
    assert member_client.post(reverse("member-waiver-accept", args=[makerspace.pk])).status_code == 200
    row.refresh_from_db()
    assert row.accepted_waiver_id == second.pk
    entry = AuditLog.objects.get(action="membership.waiver_accepted", actor=row.user)
    assert entry.meta == {"waiver_id": second.pk, "version": "v2"}
    assert client.put(url, {"clear": True}, format="json").status_code == 200
    second.refresh_from_db()
    assert not second.is_active and second.superseded_at is not None
    assert AuditLog.objects.filter(action="makerspace.waiver_deactivated", actor=boss).count() == 1


def test_witness_without_active_waiver_is_400_and_records_no_acceptance():
    _, boss, row = state()
    response = authenticated_client(boss).post(reverse("admin-membership-waiver-witness", args=[row.pk]))
    assert response.status_code == 400
    row.refresh_from_db()
    assert row.witnessed_waiver_id is None and row.witnessed_at is None
    assert not AuditLog.objects.filter(action="membership.waiver_witnessed").exists()
