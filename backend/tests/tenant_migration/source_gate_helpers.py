import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.makerspaces.models import Makerspace
from apps.tenant_migration.models import SourceMigrationGate


def make_space(label):
    return Makerspace.objects.create(
        name=label, slug=f"{label}-{uuid.uuid4().hex[:8]}"
    )


def make_actor(label="source-gate"):
    return get_user_model().objects.create_superuser(
        username=f"{label}-{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@example.test",
        password="gate-test-password",
    )


def close_gate(
    space, actor, *, state=SourceMigrationGate.State.QUIESCED, expired=False
):
    now = timezone.now()
    return SourceMigrationGate.objects.create(
        makerspace=space,
        state=state,
        owner_id=uuid.uuid4(),
        fencing_token=1,
        actor=actor,
        heartbeat_at=now - timedelta(minutes=10),
        lease_expires_at=now
        + (-timedelta(seconds=1) if expired else timedelta(hours=1)),
        presign_drain_until=now,
        quiesced_at=(
            now if state == SourceMigrationGate.State.QUIESCED else None
        ),
    )
