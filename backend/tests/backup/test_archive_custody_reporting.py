from io import StringIO

import pytest
from django.contrib import admin
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.backup.custody import with_makerspace_custody_lock
from apps.backup.models import (
    MakerspaceArchiveCustodyState,
    MakerspaceArchiveRecipient,
)
from apps.makerspaces.models import Makerspace


pytestmark = pytest.mark.django_db


def test_custody_state_is_read_only_and_visible_in_django_admin():
    model_admin = admin.site._registry[MakerspaceArchiveCustodyState]

    assert model_admin.resolve_hidden_lookup() is None
    assert model_admin.has_add_permission(None) is False
    assert model_admin.has_change_permission(None) is False
    assert model_admin.has_delete_permission(None) is False


def test_report_is_empty_on_a_fresh_deployment():
    makerspace = Makerspace.objects.create(
        name="Fresh deployment", slug="fresh-deployment"
    )
    with with_makerspace_custody_lock(makerspace.pk):
        pass
    output = StringIO()

    call_command("archive_custody_report", stdout=output)

    assert "No self-governed makerspaces" in output.getvalue()


def test_report_lists_one_verified_recipient_and_current_custody_state():
    makerspace = Makerspace.objects.create(
        name="One custodian",
        slug="one-custodian",
        superadmin_access_enabled=False,
    )
    MakerspaceArchiveRecipient.objects.create(
        makerspace=makerspace,
        public_recipient="age1reportone",
        fingerprint="a" * 64,
        label="Only custodian",
        verified_at=timezone.now(),
    )
    with with_makerspace_custody_lock(makerspace.pk):
        pass
    output = StringIO()

    call_command("archive_custody_report", stdout=output)

    report = output.getvalue()
    assert "slug=one-custodian" in report
    assert "verified_recipients=1" in report
    assert "custody_state=degraded_one_recipient" in report


def test_readiness_counts_below_floor_custody_rows(monkeypatch):
    healthy = Makerspace.objects.create(
        name="Healthy",
        slug="readiness-healthy",
        superadmin_access_enabled=False,
    )
    degraded = Makerspace.objects.create(
        name="Degraded",
        slug="readiness-degraded",
        superadmin_access_enabled=False,
    )
    for makerspace, count in ((healthy, 2), (degraded, 1)):
        for index in range(count):
            MakerspaceArchiveRecipient.objects.create(
                makerspace=makerspace,
                public_recipient=f"age1ready{makerspace.pk}{index}",
                fingerprint=f"{makerspace.pk:032x}{index:032x}",
                label=f"Custodian {index}",
                verified_at=timezone.now(),
            )
        with with_makerspace_custody_lock(makerspace.pk):
            pass
    monkeypatch.setattr("apps.encryption.readiness.assert_ready", lambda: None)

    response = APIClient().get(reverse("readiness"))

    assert response.status_code == 200
    assert response.data["archive_custody"]["below_floor_makerspaces"] == 1
    assert response.data["archive_custody"]["zero_recipient_makerspaces"] == 0
