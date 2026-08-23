import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.backup.models import (
    MakerspaceArchiveCustodyState,
    MakerspaceTenantExitCustodyState,
    TenantExitCustodyAlarmDelivery,
)
from apps.backup.recipient_states import compromise_recipient, revoke_recipient
from apps.tenant_migration.models import TenantDumpCapture
from apps.tenant_migration.tenant_dump_capture import request_tenant_dump_capture
from apps.tenant_migration.tenant_dump_errors import TenantDumpCustodyError
from tests.tenant_migration.tenant_dump_d3_helpers import (
    makerspace,
    manager,
    operator,
    recipient,
)


pytestmark = pytest.mark.django_db


def test_request_locks_makerspace_then_recipient_rows_before_capture():
    space = makerspace("d3-lock-order")
    actor = manager(space)
    recipient(space, 1)

    with CaptureQueriesContext(connection) as queries:
        capture = request_tenant_dump_capture(actor, space)

    statements = [query["sql"] for query in queries]
    makerspace_lock = next(
        index
        for index, sql in enumerate(statements)
        if 'FROM "makerspaces_makerspace"' in sql and "FOR UPDATE" in sql
    )
    recipient_lock, recipient_sql = next(
        (index, sql)
        for index, sql in enumerate(statements)
        if 'FROM "backup_makerspacearchiverecipient"' in sql
        and "FOR UPDATE" in sql
    )
    capture_insert = next(
        index
        for index, sql in enumerate(statements)
        if 'INSERT INTO "tenant_migration_tenantdumpcapture"' in sql
    )
    assert makerspace_lock < recipient_lock < capture_insert
    # Deterministic primary-key order is the property that matters; the exact SQL
    # rendering is Django's business. `.values_list("pk")` selects `"id" AS "pk"`
    # and Django then orders by the ordinal of that first column, so PK-ascending
    # locking appears as `ORDER BY 1 ASC` rather than `ORDER BY "id" ASC`. Accept
    # either spelling, but pin that the ordered column really is the primary key.
    assert '"id"' in recipient_sql
    assert (
        'ORDER BY "backup_makerspacearchiverecipient"."id" ASC' in recipient_sql
        or 'ORDER BY "id" ASC' in recipient_sql
        or "ORDER BY 1 ASC" in recipient_sql
    )
    assert capture.frozen_tenant_recipients[0]["fingerprint"]


def test_zero_recipients_refuses_request_but_persists_floor_episode():
    space = makerspace("d3-zero")
    actor = manager(space)
    operator("d3-zero-operator")

    with pytest.raises(TenantDumpCustodyError, match="at least one"):
        request_tenant_dump_capture(actor, space)

    state = MakerspaceTenantExitCustodyState.objects.get(makerspace=space)
    assert state.state == state.State.FLOOR_BREACHED_ZERO
    assert state.alarm_episode == 1
    assert TenantExitCustodyAlarmDelivery.objects.filter(
        makerspace=space,
        alarm_revision=state.alarm_revision,
        channel=TenantExitCustodyAlarmDelivery.Channel.OPERATOR_EMAIL,
    ).exists()
    assert not TenantDumpCapture.objects.filter(makerspace=space).exists()


def test_one_recipient_continues_with_durable_degraded_episode():
    space = makerspace("d3-one")
    actor = manager(space)
    recipient(space, 2)

    capture = request_tenant_dump_capture(actor, space)

    state = MakerspaceTenantExitCustodyState.objects.get(makerspace=space)
    assert capture.status == TenantDumpCapture.Status.REQUESTED
    assert state.state == state.State.DEGRADED_ONE_RECIPIENT
    assert TenantExitCustodyAlarmDelivery.objects.filter(
        makerspace=space,
        alarm_revision=state.alarm_revision,
    ).exists()


def test_part_a_not_applicable_and_lane_d_degraded_coexist():
    space = makerspace("d3-independent", superadmin_access=True)
    actor = manager(space)
    recipient(space, 3)

    request_tenant_dump_capture(actor, space)

    assert MakerspaceArchiveCustodyState.objects.get(
        makerspace=space
    ).state == MakerspaceArchiveCustodyState.State.NOT_APPLICABLE
    assert MakerspaceTenantExitCustodyState.objects.get(
        makerspace=space
    ).state == MakerspaceTenantExitCustodyState.State.DEGRADED_ONE_RECIPIENT


def test_ordinary_revocation_cannot_cross_floor_but_compromise_is_immediate():
    space = makerspace("d3-floor")
    first = recipient(space, 4)
    recipient(space, 5)

    with pytest.raises(ValidationError) as caught:
        revoke_recipient(recipient=first)
    assert caught.value.code == "recipient_floor"

    compromise_recipient(recipient=first)
    state = MakerspaceTenantExitCustodyState.objects.get(makerspace=space)
    assert state.state == state.State.DEGRADED_ONE_RECIPIENT
    first.refresh_from_db()
    assert first.compromised_at is not None
