from datetime import timedelta
import uuid

import pytest
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.backup import recipient_selection, recipients, services
from apps.backup.models import BackupArchive, MakerspaceArchiveRecipient
from apps.makerspaces.models import Makerspace


pytestmark = pytest.mark.django_db(transaction=True)

TENANT_RECIPIENT = (
    "age1qqqsyqcyq5rqwzqfpg9scrgwpugpzysnzs23v9ccrydpk8qarc0savhh7m"
)
PLATFORM_RECIPIENT = "age1platform-recipient"


def _archive_without_snapshot(makerspace, *, legacy=False):
    return BackupArchive.objects.create(
        scope=BackupArchive.Scope.MAKERSPACE,
        makerspace=makerspace,
        superadmin_access_at_decision=None,
        legacy_pre_decision_snapshot=legacy,
        object_key=f"backup-archives/makerspace/{uuid.uuid4()}.tar.age",
        expires_at=timezone.now() + timedelta(days=1),
    )


def _verified_recipient(makerspace):
    return MakerspaceArchiveRecipient.objects.create(
        makerspace=makerspace,
        public_recipient=TENANT_RECIPIENT,
        fingerprint=uuid.uuid4().hex * 2,
        label="Tenant custody",
        verified_at=timezone.now(),
    )


def test_create_archive_snapshots_fresh_locked_makerspace_value():
    makerspace = Makerspace.objects.create(
        name="Fresh snapshot",
        slug="archive-fresh-snapshot",
        superadmin_access_enabled=True,
    )
    Makerspace.objects.filter(pk=makerspace.pk).update(
        superadmin_access_enabled=False
    )

    with CaptureQueriesContext(connection) as queries:
        archive = services.create_archive(
            None,
            scope=BackupArchive.Scope.MAKERSPACE,
            makerspace=makerspace,
        )

    assert makerspace.superadmin_access_enabled is True
    assert archive.superadmin_access_at_decision is False
    statements = [query["sql"] for query in queries]
    makerspace_lock = next(
        index
        for index, sql in enumerate(statements)
        if 'FROM "makerspaces_makerspace"' in sql and "FOR UPDATE" in sql
    )
    archive_insert = next(
        index
        for index, sql in enumerate(statements)
        if 'INSERT INTO "backup_backuparchive"' in sql
    )
    assert makerspace_lock < archive_insert


def test_switch_flipped_after_create_does_not_change_selected_recipients(settings):
    settings.BACKUP_AGE_RECIPIENT = PLATFORM_RECIPIENT
    makerspace = Makerspace.objects.create(
        name="Frozen switch",
        slug="archive-frozen-request-decision",
        superadmin_access_enabled=False,
    )
    _verified_recipient(makerspace)
    archive = services.create_archive(
        None,
        scope=BackupArchive.Scope.MAKERSPACE,
        makerspace=makerspace,
    )

    Makerspace.objects.filter(pk=makerspace.pk).update(
        superadmin_access_enabled=True
    )

    assert archive.superadmin_access_at_decision is False
    assert recipients.selection_for(archive) == [
        {"label": "Tenant custody", "public_recipient": TENANT_RECIPIENT}
    ]


def test_null_makerspace_decision_snapshot_fails_closed():
    makerspace = Makerspace.objects.create(
        name="Legacy missing snapshot",
        slug="archive-legacy-missing-snapshot",
    )
    _verified_recipient(makerspace)
    archive = _archive_without_snapshot(makerspace, legacy=True)

    with pytest.raises(
        recipient_selection.BackupBuildError,
        match="request-time superadmin access decision snapshot",
    ):
        recipients.selection_for(archive)


def test_deployment_archive_works_with_null_snapshot(settings):
    settings.BACKUP_AGE_RECIPIENT = PLATFORM_RECIPIENT
    archive = services.create_archive(None, scope=BackupArchive.Scope.DEPLOYMENT)

    assert archive.superadmin_access_at_decision is None
    assert recipients.selection_for(archive) == [
        {
            "label": "Platform backup recipient",
            "public_recipient": PLATFORM_RECIPIENT,
        }
    ]


def test_makerspace_snapshot_constraint_allows_only_legacy_null_rows():
    makerspace = Makerspace.objects.create(
        name="Snapshot constraint",
        slug="archive-snapshot-constraint",
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        _archive_without_snapshot(makerspace)

    legacy = _archive_without_snapshot(makerspace, legacy=True)
    assert legacy.superadmin_access_at_decision is None
