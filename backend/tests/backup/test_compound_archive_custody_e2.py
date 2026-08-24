import pytest

from apps.backup import archive_builder
from apps.backup.models import MakerspaceArchiveCustodyState
from apps.backup.recipients import fingerprint_for
from apps.makerspaces.models import Makerspace
from tests.backup import test_compound_archive_e2 as e2


pytestmark = pytest.mark.django_db(transaction=True)


def test_one_recipient_succeeds_with_degraded_custody_recorded(
    monkeypatch, settings
):
    sovereign = Makerspace.objects.create(
        name="Degraded custody",
        slug="degraded-custody",
        superadmin_access_enabled=False,
    )
    e2._recipient(sovereign, e2.TENANT_RECIPIENT_ONE, "Only tenant key")
    MakerspaceArchiveCustodyState.objects.create(
        makerspace=sovereign,
        state=MakerspaceArchiveCustodyState.State.DEGRADED_ONE_RECIPIENT,
    )
    commands = e2._prepare_build(
        monkeypatch,
        settings,
        {sovereign.pk: "degraded tenant content"},
    )

    _encrypted, manifest, tempdir, _digest = archive_builder.build_archive(
        e2._archive()
    )
    try:
        assert manifest["slices"][0]["custody_state"] == (
            MakerspaceArchiveCustodyState.State.DEGRADED_ONE_RECIPIENT
        )
        assert manifest["slices"][0]["recipient_fingerprints"] == [
            fingerprint_for(e2.TENANT_RECIPIENT_ONE)
        ]
        assert e2._command_recipients(commands[0]) == [e2.TENANT_RECIPIENT_ONE]
    finally:
        tempdir.cleanup()
