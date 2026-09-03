"""Retention removes evidence bytes, never historical report facts."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.evidence import storage
from apps.evidence.models import EvidencePhoto
from apps.evidence.services_retention import sweep_evidence_retention
from apps.makerspaces import lifecycle
from apps.makerspaces.models import Makerspace
from apps.operations.models import ReportMetricRollup


pytestmark = pytest.mark.django_db(transaction=True)


def _rollup(space):
    now = timezone.now()
    return ReportMetricRollup.objects.create(
        makerspace=space,
        source_module="events",
        report_key="attendance",
        metric_key="attended",
        bucket_start=now.replace(hour=0, minute=0, second=0, microsecond=0),
        grain=ReportMetricRollup.Grain.DAY,
        dimension_key="status=attended",
        dimensions={"status": "attended"},
        value="9.000000",
        sample_count=9,
        source_cutoff=now,
        checksum="b" * 64,
    )


def test_automatic_evidence_retention_does_not_rewrite_rollups(settings, monkeypatch):
    settings.EVIDENCE_OBJECT_EXPIRY_ENABLED = True
    settings.EVIDENCE_OBJECT_RETENTION_DAYS = 30
    space = Makerspace.objects.create(name="Retention reports", slug="retention-reports")
    user = get_user_model().objects.create_user(username="retention-reports")
    photo = EvidencePhoto.objects.create(
        makerspace=space,
        evidence_type=EvidencePhoto.EvidenceType.ISSUE,
        object_key=f"evidence/{space.pk}/old.jpg",
        size_bytes=12,
        uploaded_by=user,
    )
    rollup = _rollup(space)
    before = ReportMetricRollup.objects.values().get(pk=rollup.pk)
    monkeypatch.setattr(storage, "object_size", lambda _key: 12)
    monkeypatch.setattr(storage, "delete_object_strict", lambda _key: "deleted")

    summary = sweep_evidence_retention(
        now=photo.created_at + timedelta(days=31), batch_size=1
    )

    assert summary["photos_expired"] == 1
    assert ReportMetricRollup.objects.values().get(pk=rollup.pk) == before


def test_explicit_legal_tenant_purge_deletes_rollups(settings, monkeypatch):
    settings.MANAGED_POSTGRES = True
    actor = get_user_model().objects.create_superuser(
        username="legal-purge", email="legal-purge@example.test", password="pw"
    )
    space = Makerspace.objects.create(
        name="Legal purge reports",
        slug="legal-purge-reports",
        archived_at=timezone.now(),
        archived_by=actor,
        superadmin_access_enabled=True,
    )
    rollup = _rollup(space)
    monkeypatch.setattr(lifecycle, "_delete_storage_keys", lambda _keys: None)
    monkeypatch.setattr(lifecycle, "_delete_public_image_keys", lambda _keys: None)

    lifecycle.purge(space, actor)

    assert not Makerspace.objects.filter(pk=space.pk).exists()
    assert not ReportMetricRollup.objects.filter(pk=rollup.pk).exists()
