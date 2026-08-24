import uuid

import pytest
from django.db import connection

from apps.backup.models import B1FenceContinuity
from tests.backup.e7_reservation_test_helpers import (
    assert_database_rejects,
    digest,
    persist_restore_state,
)


pytestmark = pytest.mark.django_db(transaction=True)


def _continuity():
    operation_id, _component_id = persist_restore_state({
        "component_ids": [str(uuid.uuid4())]
    })
    return B1FenceContinuity.objects.create(
        operation_id=operation_id,
        registry_identity=digest("continuity-rule"),
        definition_sha256=digest("continuity-definition"),
        trigger_oids=[7001],
    )


@pytest.mark.parametrize("writer", ("queryset", "raw-sql"))
def test_database_refuses_fence_continuity_deletion(writer):
    continuity = _continuity()

    if writer == "queryset":
        write = lambda: B1FenceContinuity.objects.filter(pk=continuity.pk).delete()
    else:
        def write():
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM backup_b1fencecontinuity WHERE id = %s",
                    [continuity.pk],
                )

    assert_database_rejects(write)
    assert B1FenceContinuity.objects.filter(pk=continuity.pk).exists()
