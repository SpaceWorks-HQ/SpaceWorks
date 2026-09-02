from datetime import timedelta

import pytest
from django.utils import timezone

from apps.events.models import Event
from tests.data_export.portable_helpers import (
    archive_files,
    csv_rows,
    make_job,
    make_space,
    make_user,
)


pytestmark = pytest.mark.django_db(transaction=True)


def test_event_registration_policy_survives_portable_export():
    actor = make_user("event-policy-exporter")
    makerspace = make_space("event-policy-export")
    start = timezone.now() + timedelta(days=1)
    cutoff = start - timedelta(minutes=45)
    event = Event.objects.create(
        makerspace=makerspace,
        title="Approval workshop",
        starts_at=start,
        ends_at=start + timedelta(hours=2),
        registration_requires_approval=True,
        registration_cutoff_at=cutoff,
    )

    files, _archive_bytes, _manifest = archive_files(make_job(makerspace, actor))
    row = csv_rows(files, "events/events.csv")[0]

    assert row["id"] == str(event.pk)
    assert row["registration_requires_approval"] == "true"
    assert row["registration_cutoff_at"] == cutoff.isoformat()
    assert row["registration_cutoff_lead_minutes"] == ""
