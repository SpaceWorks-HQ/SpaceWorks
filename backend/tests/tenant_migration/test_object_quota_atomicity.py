import hashlib

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.makerspaces.models import Makerspace
from apps.tenant_migration.models import TenantImportJob, TenantImportObject
from apps.tenant_migration.object_import import _mark_promoted_and_charge


pytestmark = pytest.mark.django_db(transaction=True)


@override_settings(PLATFORM_DOMAIN_SUFFIX=".space-works.test")
def test_quota_charge_rolls_back_when_promoted_journal_transition_fails(monkeypatch):
    target = Makerspace.objects.create(name="Atomic Quota", slug="atomic-quota")
    target.resource_limit_overrides = {"storage": 100}
    target.save(update_fields=("resource_limit_overrides",))
    job = TenantImportJob.objects.create(
        source_archive_digest="f" * 64, target_makerspace=target,
        expires_at=timezone.now(),
    )
    row = TenantImportObject.objects.create(
        job=job, bucket_kind="private", source_key="source",
        staging_key="staged", target_key="target", size=10,
        sha256=hashlib.sha256(b"0123456789").hexdigest(),
        claimed_at=timezone.now(),
    )
    real_filter = TenantImportObject.objects.filter

    class FailedJournalUpdate:
        def update(self, **_kwargs):
            raise RuntimeError("injected journal failure")

    monkeypatch.setattr(
        TenantImportObject.objects, "filter", lambda **_kwargs: FailedJournalUpdate()
    )
    with pytest.raises(RuntimeError, match="journal failure"):
        _mark_promoted_and_charge(row.pk, target)
    monkeypatch.setattr(TenantImportObject.objects, "filter", real_filter)

    target.refresh_from_db()
    row.refresh_from_db()
    assert target.storage_bytes_used == 0
    assert row.state == TenantImportObject.State.STAGED
    assert row.quota_charged_at is None
